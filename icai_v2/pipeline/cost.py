"""What a live ICAIv2 run will cost, before you spend it.

A call count is the wrong unit: the three call types differ by ~7x in prompt
size, and the testing prompt carries every surviving principle, so `k_clusters`
moves the bill as much as the corpus size does. These per-call token figures were
measured with `messages.count_tokens` against the real prompt builders, not
estimated.

Prices are Anthropic list rates per million tokens, current as of 2026-08-22.
Verify against https://platform.claude.com/docs/en/about-claude/pricing before
quoting them to anyone.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List


@dataclass(frozen=True)
class Model:
    id: str
    label: str
    input_per_mtok: float
    output_per_mtok: float
    note: str = ""


# Only models this pipeline can actually drive. `shared.evaluator._call_ai`
# handles the sampling-parameter and adaptive-thinking differences between the
# two generations, so all four are drop-in here.
MODELS: List[Model] = [
    Model("claude-haiku-4-5", "Haiku 4.5", 1.0, 5.0,
          "Cheapest. Best choice for exercising the pipeline."),
    Model("claude-sonnet-5", "Sonnet 5", 2.0, 10.0,
          "Newer and cheaper than Sonnet 4.5 — the sensible default."),
    Model("claude-sonnet-4-5", "Sonnet 4.5", 3.0, 15.0,
          "What every checked-in rule set was induced with."),
    Model("claude-opus-5", "Opus 5", 5.0, 25.0,
          "For a final run where rule quality matters more than spend."),
]

MODELS_BY_ID: Dict[str, Model] = {m.id: m for m in MODELS}
DEFAULT_MODEL = "claude-haiku-4-5"

# Measured per-call token counts (count_tokens on the real prompts, PM corpus).
_GEN_IN, _GEN_OUT = 230, 70          # one case, one prompt variant
_TEST_IN_BASE, _TEST_IN_PER_RULE = 253, 14   # scales with k_clusters
_TEST_OUT_PER_RULE = 9               # one vote per surviving principle
_AGREE_IN, _AGREE_OUT = 1560, 200    # one batch of 25 cases
_AGREE_BATCH = 25


def estimate(n_cases: int, n_corrective: int, seeds: int, k_clusters: int,
             model_id: str, max_cases: int | None = None) -> Dict:
    """Calls, tokens and dollars for one live run."""
    if max_cases and max_cases < n_cases:
        share = max_cases / n_cases
        n_corrective = max(2, round(n_corrective * share))
        n_cases = max_cases

    # run_once splits the corpus in half, stratified.
    half = max(1, n_cases // 2)
    half_corrective = max(1, n_corrective // 2)

    # Steps 2/3 cluster candidates down to at most k, so the testing prompt
    # carries min(k, candidates) principles — not k.
    candidates = 2 * half * 3          # two prompt variants, 3 principles each
    n_rules = min(k_clusters, candidates)

    gen_calls = 2 * half
    test_calls = half
    agree_calls = 2 * math.ceil(half_corrective / _AGREE_BATCH)

    per_seed_in = (gen_calls * _GEN_IN
                   + test_calls * (_TEST_IN_BASE + _TEST_IN_PER_RULE * n_rules)
                   + agree_calls * _AGREE_IN)
    per_seed_out = (gen_calls * _GEN_OUT
                    + test_calls * _TEST_OUT_PER_RULE * n_rules
                    + agree_calls * _AGREE_OUT)

    model = MODELS_BY_ID.get(model_id) or MODELS_BY_ID[DEFAULT_MODEL]
    input_tokens = per_seed_in * seeds
    output_tokens = per_seed_out * seeds
    usd = (input_tokens / 1e6 * model.input_per_mtok
           + output_tokens / 1e6 * model.output_per_mtok)

    return {
        "model": model.id,
        "model_label": model.label,
        "n_cases": n_cases,
        "calls": (gen_calls + test_calls + agree_calls) * seeds,
        "rules_per_test_call": n_rules,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "usd": round(usd, 2),
        # Output length is the estimated part — the prompts are measured, the
        # replies are inferred from their required shape. Treat as +/- 30%.
        "usd_high": round(usd * 1.3, 2),
    }


def compare(n_cases: int, n_corrective: int, seeds: int, k_clusters: int,
            max_cases: int | None = None) -> List[Dict]:
    """The same run priced on every supported model."""
    return [estimate(n_cases, n_corrective, seeds, k_clusters, m.id, max_cases)
            for m in MODELS]
