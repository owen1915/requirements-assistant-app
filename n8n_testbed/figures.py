"""Named recipes for the testbed's published figures.

Every figure in docs/figures was produced by an ad-hoc CLI call whose arguments
lived only in someone's shell history — which configs, in which order, under which
labels. Recovered here from the run metadata in runs/PM_*_raw.json (each dump
records the `rules_config` it was submitted with), so the figures are regenerable
rather than merely archived.

These read the preserved matrices in runs/ and make NO API calls.

    python -m n8n_testbed.figures                 # every recipe
    python -m n8n_testbed.figures stability_tiers # just one
    python -m n8n_testbed.figures --list
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from typing import Dict, List

from shared.paths import DOCS_FIGURE_DIR, TESTBED_RUNS_DIR
from .plots import compare_boxplot


# Config tag -> the rule set that was injected, read back from the raw dumps:
#   n8nbatch    rules_config absent      -> verbatim n8n PART 1, no rules
#   n8nicaiv2   rules_config "icai_v2"   -> 2 rules, each found in 3 of 5 seeds
#   n8nicaiv2s2 rules_config "icai_v2_s2"-> 6 rules, the seeds>=2 tier
# 100 batch runs per config, claude-sonnet-4-6, temperature 0.7.
RECIPES: Dict[str, Dict] = {
    "stability_tiers": {
        "kind": "grouped",
        "dataset": "PM",
        "configs": ["n8nbatch", "n8nicaiv2", "n8nicaiv2s2"],
        "labels": ["Baseline (0 rules)", "seeds>=3 (2 rules)", "seeds>=2 (6 rules)"],
        "out": "PM_stability_tiers_box.png",
        "doc": "How far the ICAIv2 stability threshold moves the evaluator. "
               "Loosening seeds>=3 to seeds>=2 triples the rule count and buys "
               "nothing: precision rises, recall falls further.",
    },
    "stability_tiers_panels": {
        "kind": "panels",
        "dataset": "PM",
        "configs": ["n8nbatch", "n8nicaiv2", "n8nicaiv2s2"],
        "labels": ["Baseline (0 rules)", "seeds>=3 (2 rules)", "seeds>=2 (6 rules)"],
        "out": "PM_stability_tiers_panels.png",
        "doc": "Small-multiples reading of the same three arms, one panel per "
               "metric, so colour stops being the only key.",
    },
    "stable_rule": {
        "kind": "grouped",
        "dataset": "PM",
        "configs": ["n8nbatch", "n8nicaiv2s5"],
        "labels": ["Baseline (0 rules)", "A10 rule, 5/10 seeds"],
        "out": "PM_stable_rule_box.png",
        "doc": "The single principle that survived in 5 of 10 ICAIv2 seeds, "
               "injected alone under A10. Isolates one rule's effect against the "
               "same verbatim n8n baseline the stability-tier figure uses.",
    },
    "baseline_vs_rules": {
        "kind": "grouped",
        "dataset": "PM",
        "configs": ["n8nbatch", "n8nlenient"],
        "labels": ["Baseline", "Baseline + 5 ICAI rules"],
        "out": "PM_baseline_vs_rules_box.png",
        "doc": "The original A/B: verbatim n8n prompt against the same prompt "
               "carrying the five lenient-threshold ICAI rules.",
    },
}


def _missing(recipe: Dict) -> List[str]:
    return [c for c in recipe["configs"]
            if not (TESTBED_RUNS_DIR / f"{recipe['dataset']}_{c}_matrix.xlsx").exists()]


def build(name: str, out_dir: Path = DOCS_FIGURE_DIR) -> Path | None:
    r = RECIPES[name]
    absent = _missing(r)
    if absent:
        print(f"skip {name}: no run matrix for {', '.join(absent)} in {TESTBED_RUNS_DIR}")
        return None

    print(f"\n=== {name} -> {r['out']} ===")
    fn = compare_boxplot.generate if r["kind"] == "grouped" else compare_boxplot.small_multiples
    produced = fn(r["dataset"], r["configs"], r["labels"], r["out"])

    # The plot modules write into the scratch output tree; the published copy
    # lives in docs/figures, so refresh that rather than leaving two versions.
    out_dir.mkdir(parents=True, exist_ok=True)
    final = out_dir / r["out"]
    shutil.copyfile(produced, final)
    print(f"wrote {final}")
    return final


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("recipes", nargs="*", default=[],
                    help=f"which figures to build (default: all). "
                         f"One or more of: {', '.join(RECIPES)}")
    ap.add_argument("--out-dir", type=Path, default=DOCS_FIGURE_DIR)
    ap.add_argument("--list", action="store_true", help="describe the recipes and exit")
    a = ap.parse_args()
    unknown = [r for r in a.recipes if r not in RECIPES]
    if unknown:
        ap.error(f"unknown recipe(s) {', '.join(unknown)}; "
                 f"choose from {', '.join(RECIPES)}")

    if a.list:
        for name, r in RECIPES.items():
            print(f"{name}\n    -> {r['out']}\n    configs: {', '.join(r['configs'])}\n"
                  f"    {r['doc']}\n")
        return

    for name in (a.recipes or list(RECIPES)):
        build(name, a.out_dir)


if __name__ == "__main__":
    main()
