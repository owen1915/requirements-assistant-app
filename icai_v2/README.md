# ICAIv2 — component (d)

Induces a **constitution** — a short list of rules — from reviewer disagreement,
following Findeis et al. (ICAI, ICLR 2025), with cross-seed stability selection added
on top. These are the rules the testbed injects, and the seeds behind
`docs/figures/PM_stability_tiers_box.png`.

## The pipeline

```
data/sme_feedback/*.json
   |  corpus.py       clean, re-derive each action from the text,
   |                  tag rubber-stamp sessions
   v
  cases  (203 decisions, 44 corrective)
   |  icai_v2.py      per seed:  generate (both prompt variants)
   |                             -> embed + k-means cluster
   |                             -> test on the held-out half
   |                             -> filter (net > 0, relevance >= 10%), keep top n
   v
  per-seed constitutions
   |  stability_select  cluster across seeds; keep what most seeds
   |                    independently found
   v
icai_v2/rule_sets/rules_group_<tag>.json
```

Stability selection is the addition, and the paper is the reason for it: multiple
different constitutions explain the same data equally well (the Rashomon effect,
Sec. 6). A principle that survives in most runs is evidence against that; one that
appears once is probably that run's sampling.

## What v2 fixed over v1

1. **Embedding clustering** instead of frequency dedup on normalised text — near
   duplicates were occupying two of the five constitution slots.
2. **Train/test split** — v1 generated and scored on the same cases, so its numbers
   were training-set numbers.
3. **Discriminating agreement baseline** — Eq. 1 is now evaluated on corrective
   decisions only. Over the full corpus (78% accepts) "accept everything" already
   scores ~0.56, leaving no room for a constitution to show lift.

## Running it

```bash
python -m icai_v2.pipeline.corpus                             # corpus report, no API calls
python -m icai_v2.pipeline.icai_v2 --dry-run                  # full shape, no API calls
python -m icai_v2.pipeline.icai_v2 --seeds 5 --tag my_rules   # live
```

A live run writes to `rule_sets/`; a `--dry-run` writes to `outputs/`, so a stub can
never shadow a rule set a published figure depends on.

Live runs need **both** keys: `ANTHROPIC_API_KEY` for generation and testing, and
`OPENAI_API_KEY` for the clustering embeddings (Anthropic has no embeddings endpoint).

## The Studio (`app/`)

A UI over the same `run_pipeline` function the CLI calls — not a reimplementation,
which is how a UI and a paper start reporting different numbers.

```bash
python run_icai_studio.py        # API on 8010, UI on 3002
```

1. **Corpus** — drop in feedback JSON exports, or load the five checked-in PM
   sessions. Each file is validated with a specific reason if it cannot be used, and
   the corpus report appears before anything is spent: decisions, corrective count,
   and which sessions were rubber-stamps.
2. **Run** — seeds, k, keep-n, stability threshold, **model**, and **sample size**.
   The panel prices the run in dollars on every supported model as you tune, so the
   three levers that move the bill sit next to the number they move. Dry run is free;
   a live run is refused outright if the server is missing a key.
3. **Rules** — each rule with its `seeds_found/N` stability, net / relevance /
   accuracy, and the sibling phrasings its cluster absorbed. Principles below the cut
   stay visible — reaching 2 of 5 seeds is a different claim from reaching 0.
   Download, or publish straight into `rule_sets/`.

The downloaded file is the shape `n8n_testbed.inject.load_sme_rules` reads, so it
drops into a testbed run under its tag with no code change.

## What a run costs

Cost is linear in **seeds** and in **corpus size**, and the testing prompt carries
every surviving principle — so **k** moves it too. The model is a flat multiplier:
Haiku 4.5 is $1/$5 per MTok against Sonnet 4.5's $3/$15, and Sonnet 5 is both newer
and cheaper than the pinned Sonnet 4.5 default.

| Configuration | Haiku 4.5 | Sonnet 5 | Sonnet 4.5 |
|---|---|---|---|
| 40 decisions, 2 seeds — smoke test | **$0.20** | $0.40 | $0.60 |
| 60 decisions, 3 seeds — exploratory | $0.67 | $1.35 | $2.02 |
| 238 decisions, 5 seeds, k=100 — comparable to the published figure | $4.40 | $8.80 | **$13.21** |

The 40-decision Haiku run takes ~75 seconds and produces real induced rules — it is
the right way to exercise the pipeline before committing to a full one. Two caveats
on small runs: the Eq. 1 lift is computed over the corrective half of the held-out
split, so at 40 decisions it is ~5 cases and the number is noise; and a corpus cap
means the rules are induced from a subset, so they are not comparable to a full run.

Figures come from `icai_v2/pipeline/cost.py`, whose per-call token counts were
measured with `messages.count_tokens` against the real prompt builders. Prompt sizes
are measured; reply lengths are inferred from their required shape.

## Other methods here

`method_a_icai.py` and `method_b_coding.py` are the earlier M1/M2 arms (ICAI vs
directed coding); `merge.py` combines them; `threshold_sensitivity.py` sweeps the
correlation / accuracy / coverage gates that produced the lenient / default /
moderate / strict rule groups. `icai_explainer.py` renders the process as a PDF.
