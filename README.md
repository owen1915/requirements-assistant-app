# INCOSE Requirements Assistant

Four components, each with its own README and entry points. They share one core
(`shared/`) and one data directory (`data/`), so the evaluator the shipped app runs
is provably the evaluator the experiments measure.

```
pip install -e .[app,research]
```

That one command is what makes every `python -m ...` below work from any directory.

| | Component | What it is | Entry point |
|---|---|---|---|
| **a** | [`ui_prototype/`](ui_prototype/README.md) | The shipped prototype: upload requirements, review AI findings, export a corrected document | `python run.py` |
| **b** | [`n8n_testbed/`](n8n_testbed/README.md) | Replicates the n8n *AI4RE GR_subrules* workflow and scores it — the baseline behind `PM_stability_tiers_box.png` | `python -m n8n_testbed.figures` |
| **c** | [`reviewer_reliability/`](reviewer_reliability/README.md) | Scores the SME reviewers themselves against ground truth — `PM_reviewer_rates_adjudicated.png` | `python -m reviewer_reliability.figures` |
| **d** | [`icai_v2/`](icai_v2/README.md) | The ICAIv2 pipeline that induces the rules, and the **Studio** UI for running it on uploaded feedback | `python run_icai_studio.py` |

## How they connect

```
   data/sme_feedback/*.json          reviewer decisions from the prototype
              |
              v
   (d) icai_v2 pipeline              generate -> cluster -> test -> filter
              |                      -> cross-seed stability selection
              v
   icai_v2/rule_sets/*.json          the induced constitutions
              |
              v
   (b) n8n_testbed                   injects them into the verbatim n8n prompt,
              |                      100 batch runs per config
              v
   n8n_testbed/runs/*.xlsx  ------>  docs/figures/PM_stability_tiers_box.png

   (c) reviewer_reliability          scores the same feedback against ground
                                     truth -> PM_reviewer_rates_adjudicated.png
```

The arrow from (d) into (b) is a real file handoff: `icai_v2/rule_sets/rules_group_<tag>.json`
is exactly what `n8n_testbed.inject.load_sme_rules` reads, which is why the Studio's
download button produces something the testbed can run.

## Supporting directories

| Path | Contents |
|---|---|
| `shared/` | The evaluator (`evaluator.py`), LLM plumbing, dataset/spec loaders, the INCOSE rubrics, and `paths.py` — the single source of truth for every location below |
| `data/` | Ground-truth workbooks, the project specification, SME feedback exports, sample inputs, schemas |
| `docs/figures/` | Published figures. Regenerable — see (b) and (c) |
| `docs/reports/` | PDFs, decks and write-ups |
| `outputs/` | Scratch: plots, PDFs, dry-run artefacts. Gitignored, safe to delete |
| `reference/icai_upstream/` | Vendored copy of the ICAI paper repo (Findeis et al., ICLR 2025). Reference only; no code here imports it |

## What is versioned, and why

Two directories look like build output but are committed deliberately:

- **`n8n_testbed/runs/`** — prediction matrices and raw dumps. Each config is 100
  whole-set LLM calls; the published figures cannot be redrawn without them.
- **`icai_v2/rule_sets/`** — extracted constitutions. A pipeline *product* that is
  a testbed *input*.

Everything under `outputs/` is regenerable from those two with no API calls.

## Reproducing the figures

Neither of these spends anything — both read the committed run store:

```bash
python -m n8n_testbed.figures stability_tiers      # -> docs/figures/PM_stability_tiers_box.png
python -m reviewer_reliability.figures reviewer_rates   # -> docs/figures/PM_reviewer_rates_adjudicated.png
```

> ⚠️ **Do not enter sensitive or classified data.** Requirement and context text is
> sent to a third-party AI provider (Anthropic or OpenAI) and is subject to their
> data-handling policies.
