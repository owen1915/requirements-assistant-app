"""ICAIv2 Studio — upload SME feedback, run the pipeline, read the induced rules.

The pipeline itself is untouched: this server calls `icai_v2.pipeline.icai_v2.
run_pipeline`, the same function the CLI calls, so the Studio and the paper cannot
drift apart. What it adds is the parts a CLI cannot have — corpus validation
before you spend anything, a cost estimate, a live log, and a downloadable rule
set in the exact shape `n8n_testbed.inject.load_sme_rules` reads.

    python run_icai_studio.py          # this server + the Vite dev server
    uvicorn icai_v2.app.backend.server:app --port 8010
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from icai_v2.pipeline import cost
from shared.llm import ensure_env
from shared.paths import FEEDBACK_DIR, RULE_SETS_DIR

from . import jobs

ensure_env()

app = FastAPI(title="ICAIv2 Studio", version="1.0.0")

# The dev server runs on 3002 and proxies /api; CORS covers the case where the
# UI is opened directly against this port instead.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3002", "http://127.0.0.1:3002"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"

# Embeddings run through OpenAI (Anthropic has no embeddings endpoint), so a live
# run needs BOTH keys: Anthropic for generation/testing, OpenAI for the k-means
# clustering in steps 2/3. A dry run needs neither.
KEY_ENV = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}


class RunRequest(BaseModel):
    upload_id: str
    seeds: int = Field(5, ge=1, le=20)
    k_clusters: int = Field(100, ge=2, le=500)
    n_constitution: int = Field(5, ge=1, le=50)
    stability_min: int = Field(3, ge=1, le=20)
    dry_run: bool = True
    tag: str = "icai_v2_studio"
    model: str = cost.DEFAULT_MODEL
    # None = the whole corpus. Set it to make an exploratory run cheap.
    max_cases: Optional[int] = Field(None, ge=10, le=5000)


@app.get("/api/config")
def get_config():
    """Which keys are configured, and what that permits."""
    keys = {name: bool(os.getenv(env, "").strip()) for name, env in KEY_ENV.items()}
    return {
        "keys": keys,
        "live_runs_available": keys["anthropic"] and keys["openai"],
        "requires": {
            "anthropic": "principle generation and testing",
            "openai": "embeddings for the k-means clustering in steps 2/3",
        },
        "models": [
            {"id": m.id, "label": m.label, "note": m.note,
             "input_per_mtok": m.input_per_mtok,
             "output_per_mtok": m.output_per_mtok}
            for m in cost.MODELS
        ],
        "default_model": cost.DEFAULT_MODEL,
        "sample_corpus": sorted(p.name for p in FEEDBACK_DIR.glob("feedback_*.json")),
    }


@app.post("/api/uploads")
async def create_upload(files: List[UploadFile] = File(...)):
    """Validate and stage feedback exports; returns the corpus report for them."""
    payload = [(f.filename or "upload.json", await f.read()) for f in files]
    result = jobs.create_upload(payload)
    if not result["ok"]:
        return JSONResponse(status_code=422, content=result)
    return result


@app.get("/api/uploads/{upload_id}/estimate")
def estimate(upload_id: str, seeds: int = 5, k_clusters: int = 100,
             max_cases: Optional[int] = None):
    """What a live run would cost, on each supported model."""
    up = jobs.get_upload(upload_id)
    if not up:
        raise HTTPException(404, "unknown upload")
    return jobs.estimate(up, seeds, k_clusters, max_cases)


@app.post("/api/uploads/sample")
def use_sample_corpus():
    """Stage the five checked-in PM sessions, for trying the Studio without files."""
    payload = [(p.name, p.read_bytes())
               for p in sorted(FEEDBACK_DIR.glob("feedback_*.json"))]
    if not payload:
        raise HTTPException(404, f"no sample sessions in {FEEDBACK_DIR}")
    return jobs.create_upload(payload)


@app.post("/api/runs")
def create_run(req: RunRequest):
    if not jobs.get_upload(req.upload_id):
        raise HTTPException(404, "unknown upload")
    if not req.dry_run:
        missing = [n for n, env in KEY_ENV.items() if not os.getenv(env, "").strip()]
        if missing:
            raise HTTPException(
                400, f"a live run needs {', '.join(KEY_ENV[m] for m in missing)} "
                     "in the server environment; use dry run instead")
    run = jobs.start_run(req.upload_id, req.seeds, req.k_clusters,
                         req.n_constitution, req.stability_min, req.dry_run,
                         req.tag, req.model, req.max_cases)
    return jobs.run_view(run)


@app.get("/api/runs/{run_id}")
def read_run(run_id: str):
    run = jobs.get_run(run_id)
    if not run:
        raise HTTPException(404, "unknown run")
    return jobs.run_view(run)


@app.post("/api/runs/{run_id}/cancel")
def cancel(run_id: str):
    if not jobs.cancel_run(run_id):
        raise HTTPException(409, "run is not cancellable")
    return {"ok": True}


@app.get("/api/runs/{run_id}/rules.json")
def download_rules(run_id: str):
    run = jobs.get_run(run_id)
    if not run or not run.result:
        raise HTTPException(404, "no completed run with that id")
    body = json.dumps(run.result["rules"], indent=2, ensure_ascii=False)
    name = f"rules_group_{run.params['tag']}.json"
    return Response(
        content=body, media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.post("/api/runs/{run_id}/publish")
def publish_rules(run_id: str):
    """Write the rule set into icai_v2/rule_sets, where the testbed injects from.

    Refused for dry runs: a stub constitution must never be able to overwrite a
    rule set that a published figure depends on.
    """
    run = jobs.get_run(run_id)
    if not run or not run.result:
        raise HTTPException(404, "no completed run with that id")
    if run.params["dry_run"]:
        raise HTTPException(400, "dry-run results are stubs and cannot be published")
    RULE_SETS_DIR.mkdir(parents=True, exist_ok=True)
    path = RULE_SETS_DIR / f"rules_group_{run.params['tag']}.json"
    path.write_text(json.dumps(run.result["rules"], indent=2, ensure_ascii=False),
                    encoding="utf-8")
    return {"ok": True, "path": str(path),
            "inject_config": run.params["tag"]}


@app.delete("/api/uploads/{upload_id}")
def drop_upload(upload_id: str):
    jobs.cleanup(upload_id)
    return {"ok": True}


# Serve the built SPA when there is one; in development Vite serves it instead.
if FRONTEND_DIST.exists():
    assets = FRONTEND_DIST / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        if full_path.startswith("api"):
            raise HTTPException(status_code=404, detail="Not found")
        candidate = FRONTEND_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(str(candidate))
        return FileResponse(str(FRONTEND_DIST / "index.html"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8010)
