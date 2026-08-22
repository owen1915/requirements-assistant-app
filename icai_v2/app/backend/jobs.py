"""Upload staging and background pipeline runs, both in process memory.

Nothing is persisted, deliberately — the same stance `ui_prototype/backend/
feedback_storage.py` takes. Uploaded SME feedback is reviewer-authored material,
so it lives in a temp directory for the lifetime of the process and goes away on
restart. What the operator wants to keep, they download.

A run is a plain thread rather than a FastAPI BackgroundTask: a live 5-seed
pipeline is minutes of blocking work with hundreds of API calls inside it, and it
needs a cancel flag and an incrementally readable log, neither of which a
fire-and-forget background task gives you.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import threading
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from icai_v2.pipeline import corpus, cost
from icai_v2.pipeline.contract import ExtractedRule
from icai_v2.pipeline.icai_v2 import RunParams, run_pipeline


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #

# The shape `corpus.py` actually consumes. This is the v1 export the prototype's
# /api/download/json endpoint produces — NOT data/schemas/feedback-v2.schema.json,
# which describes a proposed successor format no exported session uses yet.
REQUIRED_VIOLATION_KEYS = ("rule_id", "user_action")


def validate_feedback(raw: bytes, filename: str) -> Dict:
    """Parse one uploaded export, or explain precisely why it cannot be used."""
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {"file": filename, "ok": False, "error": f"not valid JSON: {exc}"}

    if not isinstance(data, dict):
        return {"file": filename, "ok": False,
                "error": "top level must be an object"}
    reqs = data.get("requirement_feedback")
    if not isinstance(reqs, list) or not reqs:
        return {"file": filename, "ok": False,
                "error": "missing a non-empty 'requirement_feedback' array"}

    decisions = 0
    for i, req in enumerate(reqs):
        if not isinstance(req, dict) or "req_id" not in req:
            return {"file": filename, "ok": False,
                    "error": f"requirement_feedback[{i}] has no 'req_id'"}
        viols = req.get("violation_feedback") or []
        if not isinstance(viols, list):
            return {"file": filename, "ok": False,
                    "error": f"requirement_feedback[{i}].violation_feedback "
                             "is not an array"}
        for j, v in enumerate(viols):
            missing = [k for k in REQUIRED_VIOLATION_KEYS
                       if not isinstance(v, dict) or k not in v]
            if missing:
                return {"file": filename, "ok": False,
                        "error": f"requirement_feedback[{i}].violation_feedback[{j}] "
                                 f"missing {', '.join(missing)}"}
            decisions += 1

    if not decisions:
        return {"file": filename, "ok": False,
                "error": "no violation decisions in the file - nothing to learn from"}

    return {"file": filename, "ok": True,
            "session_id": data.get("session_id", Path(filename).stem
                                   .replace("feedback_", "")),
            "requirements": len(reqs), "decisions": decisions}


# --------------------------------------------------------------------------- #
# Uploads
# --------------------------------------------------------------------------- #

@dataclass
class Upload:
    upload_id: str
    directory: Path
    files: List[Dict]
    report: Dict
    created_at: str
    n_cases: int = 0
    n_corrective: int = 0


_UPLOADS: Dict[str, Upload] = {}
_RUNS: Dict[str, "Run"] = {}
_LOCK = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def create_upload(files: List[tuple[str, bytes]]) -> Dict:
    """Stage validated feedback exports and return the corpus report for them."""
    results = [validate_feedback(raw, name) for name, raw in files]
    accepted = [r for r in results if r["ok"]]
    if not accepted:
        return {"ok": False, "files": results,
                "error": "no usable feedback files"}

    directory = Path(tempfile.mkdtemp(prefix="icai_upload_"))
    for (name, raw), result in zip(files, results):
        if not result["ok"]:
            continue
        # corpus.build_corpus globs feedback_*.json, so normalise the name rather
        # than requiring the operator to have kept the original filename.
        stem = result["session_id"]
        (directory / f"feedback_{stem}.json").write_bytes(raw)

    records, report = corpus.build_corpus(directory)
    corrective = corpus.disagreements(records, engaged_only=True)

    upload_id = uuid.uuid4().hex[:12]
    with _LOCK:
        _UPLOADS[upload_id] = Upload(upload_id=upload_id, directory=directory,
                                     files=results, report=report,
                                     created_at=_now(),
                                     n_cases=len(records),
                                     n_corrective=len(corrective))
    return {"ok": True, "upload_id": upload_id, "files": results,
            "report": report,
            "n_cases": len(records), "n_corrective": len(corrective)}


def get_upload(upload_id: str) -> Optional[Upload]:
    return _UPLOADS.get(upload_id)


def estimate(upload: Upload, seeds: int, k_clusters: int,
             max_cases: Optional[int] = None) -> Dict:
    """Priced estimate for this upload, on every supported model.

    Replaces a bare call count: the three call types differ by ~7x in prompt
    size, so a count told you almost nothing about the bill.
    """
    return {
        "n_cases": upload.n_cases,
        "n_corrective": upload.n_corrective,
        "options": cost.compare(upload.n_cases, upload.n_corrective,
                                seeds, k_clusters, max_cases),
    }


# --------------------------------------------------------------------------- #
# Runs
# --------------------------------------------------------------------------- #

@dataclass
class Run:
    run_id: str
    upload_id: str
    params: Dict
    status: str = "queued"          # queued | running | done | error | cancelled
    log: List[str] = field(default_factory=list)
    result: Optional[Dict] = None
    error: Optional[str] = None
    started_at: str = ""
    finished_at: str = ""
    _cancel: threading.Event = field(default_factory=threading.Event)


class Cancelled(RuntimeError):
    pass


def start_run(upload_id: str, seeds: int, k_clusters: int, n_constitution: int,
              stability_min: int, dry_run: bool, tag: str,
              model: Optional[str] = None,
              max_cases: Optional[int] = None) -> Run:
    upload = _UPLOADS[upload_id]
    params = RunParams(seeds=seeds, k_clusters=k_clusters,
                       n_constitution=n_constitution, stability_min=stability_min,
                       dry_run=dry_run, tag=tag, data_dir=upload.directory,
                       model=model, max_cases=max_cases)

    run = Run(run_id=uuid.uuid4().hex[:12], upload_id=upload_id,
              params={"seeds": seeds, "k_clusters": k_clusters,
                      "n_constitution": n_constitution,
                      "stability_min": stability_min, "dry_run": dry_run,
                      "tag": tag, "model": model, "max_cases": max_cases},
              started_at=_now())
    with _LOCK:
        _RUNS[run.run_id] = run

    def progress(line: str) -> None:
        # Cancellation lands between steps rather than mid-call: an in-flight
        # batch of API requests cannot be recalled, only ignored.
        if run._cancel.is_set():
            raise Cancelled()
        run.log.append(str(line))

    def work() -> None:
        run.status = "running"
        try:
            result = run_pipeline(params, progress)
            run.result = _serialise(result)
            run.status = "done"
        except Cancelled:
            run.status = "cancelled"
            run.log.append("cancelled by operator")
        except Exception as exc:                                  # noqa: BLE001
            run.status = "error"
            run.error = f"{type(exc).__name__}: {exc}"
            run.log.append(run.error)
            traceback.print_exc()
        finally:
            run.finished_at = _now()

    threading.Thread(target=work, name=f"icai-run-{run.run_id}",
                     daemon=True).start()
    return run


def _serialise(result: Dict) -> Dict:
    """run_pipeline returns ExtractedRule dataclasses; the wire needs plain dicts."""
    from dataclasses import asdict
    out = dict(result)
    out["rules"] = [asdict(r) for r in result["rules"]]
    return out


def get_run(run_id: str) -> Optional[Run]:
    return _RUNS.get(run_id)


def cancel_run(run_id: str) -> bool:
    run = _RUNS.get(run_id)
    if not run or run.status not in ("queued", "running"):
        return False
    run._cancel.set()
    return True


def run_view(run: Run) -> Dict:
    return {"run_id": run.run_id, "upload_id": run.upload_id,
            "status": run.status, "params": run.params, "log": run.log,
            "result": run.result, "error": run.error,
            "started_at": run.started_at, "finished_at": run.finished_at}


def cleanup(upload_id: str) -> None:
    upload = _UPLOADS.pop(upload_id, None)
    if upload:
        shutil.rmtree(upload.directory, ignore_errors=True)
