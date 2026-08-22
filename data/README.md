# Data

Everything the four components read. Before the reorganisation the ground-truth
workbooks lived *outside* the repository — `datasets.py` reached into the parent
directory and `reviewer_rates.py` hardcoded an absolute path under one machine's
Downloads folder — so nothing here ran anywhere else. They are copied in now, and
every loader resolves through `shared/paths.py`.

## ground_truth/

| File | Used by | Notes |
|---|---|---|
| `Point_Mass_v5_GroundTruth.xlsx` | testbed, reviewer reliability | The current reference GT, annotated directly in A-criteria form. The only one carrying A2 and A3 positives. Was also duplicated in the repo root as `Point_Mass_v5_GroundTruth (4).xlsx` — byte-identical, verified by checksum |
| `BookShelf_v5_GroundTruth.xlsx` | testbed | Same form, Bookshelf set |
| `R1_R14_GroundTruth.xlsx` | `eval_colab.py` | R-series, used when driving the original AI4RE notebook logic |
| `Ground Truth - Good Requiremnts.xlsx` | testbed | PM requirements, plus the survey-aggregate GT (the fallback mapping) |
| `Ground Truth - Bad Requiremnts.xlsx` | testbed | Bookshelf equivalent |

These sources **disagree materially**: on PM the v5 GT has A2/A3 positives where the
others have none, and A9 is 9 positives against 1 in the R-series. Which one is in
play is an explicit choice rather than a silent fallback — set `AI4RE_GT_SOURCE` to
`v5` (the default where available), `aseries`, or `survey`.

## specs/

`Project Specifications.xlsx` — the analysis *input*: per system, the Project
Context, the ConOps, and the FR/PR/ER/RR requirements in canonical form with IDs
aligned to the ground truth.

## sme_feedback/

Five Point Mass review sessions exported from the prototype, in the v1 export shape
(`requirement_feedback[].violation_feedback[]`). This is the corpus the ICAIv2
pipeline learns from and the reviewer-reliability component scores.

`_non_pm_backup/` holds a session from a different requirement set, kept out of the
PM corpus so it cannot dilute it.

## schemas/

`feedback-v2.schema.json` — a **proposed** successor export format, which separates
"is this really a violation?" from "is this fix any good?". No exported session uses
it yet; the pipeline and the Studio read the v1 shape above.

## samples/

Requirement and context text files for trying the prototype.
