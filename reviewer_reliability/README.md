# Reviewer reliability — component (c)

Scores the **SME reviewers** against ground truth, rather than the model. Produces
`docs/figures/PM_reviewer_rates_adjudicated.png`.

## What is being measured

Each SME saw only the violations the AI flagged, and said accept / modify / reject on
each. That makes the reviewer a binary classifier over the flagged set:

```
TP  endorsed & GT violation      FP  endorsed & GT clean
FN  rejected & GT violation      TN  rejected & GT clean
```

The universe is the AI's flags, not all 91 (requirement × criterion) cells — a
reviewer is never asked about a defect the AI missed. These rates therefore describe
**reviewing behaviour, not independent detection**, and the chart caption says so.

## The `modify` problem

A `modify` is neither an endorsement nor a rejection on its face, and the policy you
pick moves the numbers materially. Four are implemented:

| Policy | Rule |
|---|---|
| `adjudicated` | **The published one.** Every `modify` labelled by hand, case by case, against the criterion, the AI's suggestion, the SME's final text and their note. The table is `reviewer_rates.ADJUDICATED`, with the reasoning for the two rejects written out |
| `split` | Mechanical: did the reviewer carry the AI's *added tokens* into their final text? Agrees with the hand labels on 7 of 9 |
| `endorse` / `reject` | Count every modify one way. Useful only as bounds |

```bash
python -m reviewer_reliability.figures reviewer_rates    # adjudicated
python -m reviewer_reliability.reviewer_rates --compare  # all four side by side
```

## Everything here

| Command | Output |
|---|---|
| `python -m reviewer_reliability.figures` | All three artefacts below |
| `python -m reviewer_reliability.figures reviewer_rates` | `docs/figures/PM_reviewer_rates_adjudicated.png` |
| `python -m reviewer_reliability.figures reliability` | `outputs/reviewer_reliability/reviewer_reliability_PM.pdf` |
| `python -m reviewer_reliability.figures consistency` | `outputs/reviewer_reliability/ai_flagging_consistency_PM.pdf` — how stably the AI flags the same cell across sessions |

Reads `data/sme_feedback/` and `data/ground_truth/Point_Mass_v5_GroundTruth.xlsx`.
No API calls.
