# n8n testbed — component (b)

Replicates the n8n **AI4RE GR_subrules** assessment process in Python and scores it
against ground truth. This is where the baseline in `docs/figures/PM_stability_tiers_box.png`
comes from.

## Why a replica rather than the workflow itself

Running n8n gives you a number, not a comparison. The replica holds the process
constant — same verbatim PART 1 prompt, same whole-set single call, same
FR→PR→ER→RR ordering, same A1 normalisation — so the *only* thing that varies
between arms is which ICAI rules are appended under the criteria. See the fidelity
list at the top of [`n8n_replica.py`](n8n_replica.py) for what was reproduced and what
was deliberately not (n8n's retry-free parse failures, which score as "found no
issues", are a defect rather than a behaviour worth copying).

## Layout

| Path | Role |
|---|---|
| `n8n_prompt_verbatim.py` | The workflow's PART 1 prompt, transcribed character for character |
| `n8n_replica.py` | Sequential runner — one whole-set call per run |
| `batch_runner.py` | The same call through the Message Batches API: half price, survives a dead poller. **This produced the 100-run configs.** |
| `inject.py` | Appends a rule set under its criterion. `load_sme_rules` reads `icai_v2/rule_sets/` |
| `metrics.py` | KPI engine — scores matrices against ground truth |
| `figures.py` | **Named recipes for the published figures** |
| `plots/` | Every chart and PDF generator |
| `runs/` | Committed prediction matrices, raw dumps and GT workbooks |

## Regenerating the figures (no API calls)

```bash
python -m n8n_testbed.figures --list          # what each recipe is
python -m n8n_testbed.figures stability_tiers # -> docs/figures/
python -m n8n_testbed.metrics --datasets PM --configs n8nbatch n8nicaiv2 n8nicaiv2s2
```

`stability_tiers` is `n8nbatch` (verbatim prompt, 0 rules) against `n8nicaiv2`
(2 rules, each found in 3 of 5 seeds) and `n8nicaiv2s2` (6 rules, the seeds≥2 tier),
100 runs each on `claude-sonnet-4-6`. Those arguments were recovered from the
`rules_config` field the batch runner records in each `runs/PM_*_raw.json`.

## A new run (spends money)

```bash
python -m n8n_testbed.batch_runner submit  --runs 100 --dataset PM --rules icai_v2
python -m n8n_testbed.batch_runner status  --dataset PM
python -m n8n_testbed.batch_runner collect --dataset PM --config n8nmytag
```

`--rules` takes any tag with a `rules_group_<tag>.json` in `icai_v2/rule_sets/`,
including one the ICAIv2 Studio just published. `collect` is idempotent.

Results land in `runs/`, which is versioned — a re-run with an existing `--config`
overwrites a matrix a published figure may depend on. Use a new tag.
