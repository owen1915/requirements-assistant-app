"""Run N identical whole-set evaluations through the Message Batches API.

Same prompt, model, temperature and parsing as n8n_testbed.n8n_replica, but the
N requests are submitted as one batch: half price, and the work happens on
Anthropic's side so a dead poller costs nothing and the job survives any local
timeout.

    python -m n8n_testbed.batch_runner submit  --runs 100 --dataset PM
    python -m n8n_testbed.batch_runner status
    python -m n8n_testbed.batch_runner collect --config n8nbatch

`submit` writes the batch id to outputs/<dataset>_batch.json. `collect` is
idempotent - rerun it until it reports every run written.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Dict, List

import openpyxl

from shared.llm import ensure_env
ensure_env()

from shared import datasets, spec
from . import n8n_prompt_verbatim as VERBATIM
from shared.datasets import CRITERIA, CRITERIA_NAMES
from .inject import EVAL_MODEL, TEMPERATURE, _strip_to_json, load_sme_rules
from .n8n_replica import (_criterion_ids, _normalize_a1, _matrix_sheet,
                          _gt_workbook, _diagnostics)

from shared.paths import TESTBED_RUNS_DIR as RUNS_DIR, output_dir

# Matrices, raw dumps and ground-truth workbooks are the RUN STORE: each one
# cost 100 whole-set LLM calls, so they are versioned rather than rebuilt.
# Plots and summary workbooks are regenerable and go to outputs/.
RUNS_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR = output_dir("n8n_testbed")
MAX_TOKENS = 8000


def _client():
    import anthropic
    return anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", "").strip())


def _prompt(dataset: str, config: str = "baseline"):
    """The verbatim n8n PART 1 prompt for this dataset.

    With config="baseline" this is identical to a `n8n_replica --prompt verbatim`
    run. Any other config appends that group's ICAI-extracted expert rules under
    their criterion, leaving the verbatim criteria text otherwise untouched.
    """
    ds = datasets.load_dataset(dataset)
    sp = spec.load_spec(dataset)
    scored = set(ds.req_ids)
    reqs = [(rid, txt) for rid, txt in sp.requirements.items() if rid in scored]
    missing = [rid for rid in ds.req_ids if not sp.requirements.get(rid)]
    if missing:
        raise ValueError(f"{dataset}: spec missing text for {missing}")
    system = VERBATIM.with_rules(VERBATIM.SYSTEM_PART1, load_sme_rules(config))
    user = VERBATIM.build_user(sp.project_context, sp.conops, reqs, sp.image_url)
    return ds, system, user, [r for r, _ in reqs]


def _build_requests(system: str, user: str, n_runs: int, model: str) -> List[Dict]:
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request
    return [
        Request(
            custom_id=f"run-{i:03d}",
            params=MessageCreateParamsNonStreaming(
                model=model,
                max_tokens=MAX_TOKENS,
                temperature=TEMPERATURE,
                system=[{"type": "text", "text": system,
                         "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user}],
            ),
        )
        for i in range(1, n_runs + 1)
    ]


def _state_path(dataset: str) -> Path:
    return RUNS_DIR / f"{dataset}_batch.json"


def submit(dataset: str, n_runs: int, model: str, dry_run: bool = False,
           rules_config: str = "baseline") -> None:
    ds, system, user, order = _prompt(dataset, rules_config)
    reqs = _build_requests(system, user, n_runs, model)
    n_rules = sum(len(v) for v in load_sme_rules(rules_config).values())
    print(f"dataset={dataset} runs={n_runs} model={model} temp={TEMPERATURE}")
    print(f"rules_config={rules_config} ({n_rules} ICAI rules appended)")
    print(f"requirements ({len(order)}): {', '.join(order)}")
    print(f"system chars={len(system)}  user chars={len(user)}")
    print(f"built {len(reqs)} requests; custom_ids "
          f"{reqs[0]['custom_id']} .. {reqs[-1]['custom_id']}")
    if dry_run:
        print("DRY RUN - nothing submitted")
        return

    OUTPUT_DIR.mkdir(exist_ok=True)
    batch = _client().messages.batches.create(requests=reqs)
    _state_path(dataset).write_text(json.dumps({
        "batch_id": batch.id, "dataset": dataset, "runs": n_runs,
        "model": model, "temperature": TEMPERATURE, "prompt": "verbatim",
        "rules_config": rules_config,
        "req_order": order, "submitted_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }, indent=2), encoding="utf-8")
    print(f"submitted batch {batch.id}  status={batch.processing_status}")


def status(dataset: str) -> str:
    st = json.loads(_state_path(dataset).read_text(encoding="utf-8"))
    b = _client().messages.batches.retrieve(st["batch_id"])
    c = b.request_counts
    print(f"{b.id}  {b.processing_status}  processing={c.processing} "
          f"succeeded={c.succeeded} errored={c.errored} "
          f"canceled={c.canceled} expired={c.expired}")
    return b.processing_status


def collect(dataset: str, config: str) -> None:
    st = json.loads(_state_path(dataset).read_text(encoding="utf-8"))
    client = _client()
    b = client.messages.batches.retrieve(st["batch_id"])
    if b.processing_status != "ended":
        print(f"batch {b.id} is {b.processing_status}, not ready")
        return

    ds = datasets.load_dataset(dataset)
    OUTPUT_DIR.mkdir(exist_ok=True)
    _gt_workbook(ds)

    parsed: Dict[str, Dict] = {}
    failures: List[Dict] = []
    for res in client.messages.batches.results(st["batch_id"]):
        cid = res.custom_id
        if res.result.type != "succeeded":
            failures.append({"custom_id": cid, "type": res.result.type})
            continue
        text = "".join(bl.text for bl in res.result.message.content
                       if bl.type == "text").strip()
        try:
            data = _strip_to_json(text)
            indiv = data.get("individualEvaluations", {})
            objs = {rid: (v if isinstance(v, list) else [])
                    for rid, v in indiv.items()}
            raw = {rid: _criterion_ids(v) for rid, v in objs.items()}
            parsed[cid] = {"raw": raw,
                           "normalized": {r: _normalize_a1(i) for r, i in raw.items()},
                           "evaluations": objs}
        except Exception as exc:  # noqa: BLE001
            failures.append({"custom_id": cid, "type": "parse_error",
                             "error": str(exc)})

    # Sheets go in custom_id order so Execution_NN is stable regardless of the
    # order the API returns results in. A failed run is SKIPPED, never written
    # as a blank sheet - a blank matrix scores as "found no issues".
    wb = openpyxl.Workbook(); wb.remove(wb.active)
    dump, totals = [], {"a1_suppressed_true_flags": 0, "a11_diverted_reqs": 0}
    for n, cid in enumerate(sorted(parsed), start=1):
        p = parsed[cid]
        ws = wb.create_sheet(f"Execution_{n:02d}")
        _matrix_sheet(ws, ds, p["normalized"])
        diag = _diagnostics(ds, p["raw"], p["normalized"])
        for k, v in diag.items():
            totals[k] += v
        dump.append({"run": n, "custom_id": cid, **p, "diagnostics": diag})

    path = RUNS_DIR / f"{dataset}_{config}_matrix.xlsx"
    wb.save(path)
    (RUNS_DIR / f"{dataset}_{config}_raw.json").write_text(
        json.dumps({**st, "config": config, "collected_runs": len(parsed),
                    "failures": failures, "totals": totals,
                    "executions": dump}, indent=2), encoding="utf-8")

    print(f"collected {len(parsed)}/{st['runs']} runs -> {path.name}")
    if failures:
        print(f"  {len(failures)} failed: {failures[:5]}")
    print(f"  totals: {totals}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["submit", "status", "collect"])
    ap.add_argument("--dataset", default="PM")
    ap.add_argument("--runs", type=int, default=100)
    ap.add_argument("--model", default=EVAL_MODEL)
    ap.add_argument("--config", default="n8nbatch")
    ap.add_argument("--dry-run", action="store_true")
    # Discovered from disk rather than a hardcoded table: a rule set the Studio
    # just published has no entry in _RULE_FILE, and a fixed `choices` list
    # rejected it at the CLI even though load_sme_rules resolves it fine.
    from .inject import _RULE_FILE, available_configs
    ap.add_argument("--rules", default="baseline",
                    choices=available_configs(),
                    help="ICAI rule group to append under each criterion")
    a = ap.parse_args()
    if a.action == "submit":
        submit(a.dataset, a.runs, a.model, a.dry_run, a.rules)
    elif a.action == "status":
        status(a.dataset)
    else:
        collect(a.dataset, a.config)


if __name__ == "__main__":
    main()
