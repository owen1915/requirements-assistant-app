"""ICAI principle induction, second pass — the three fixes over icai_simple.

  1. EMBEDDING CLUSTERING. Steps 2/3 use OpenAI embeddings + k-means, as the
     paper specifies, instead of frequency dedup on normalised text. Near-
     duplicate principles that differ by a word ("Do not replace a concrete
     numeric value..." vs "...a specific numeric value...") collapsed into one
     cluster instead of occupying two of the five constitution slots — both of
     those appear in the v1 output.

  2. TRAIN/TEST SPLIT. Principles are generated on one half of the decisions and
     scored on the other. v1 generated and tested on the same cases, so its
     net / relevance / accuracy were training-set numbers.

  3. DISCRIMINATING AGREEMENT BASELINE. Eq. 1 is evaluated on the CORRECTIVE
     decisions only. v1 measured agreement over a corpus that is 78% accepts,
     where "accept everything" already scores ~0.56 — so the constitution had no
     room to show lift and reported 0.56 vs 0.56, i.e. nothing.

Across seeds we keep principles by STABILITY rather than averaging: the pipeline
is stochastic (generation sampling, per-cluster subsampling, the split), and the
paper's own spread is +/- 8 points. A principle surviving in most runs is
evidence against the Rashomon problem the paper flags; a principle appearing
once is probably that run's sampling.

    python -m icai_v2.pipeline.icai_v2 --seeds 5
    python -m icai_v2.pipeline.icai_v2 --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import random
from dataclasses import dataclass, field
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from .contract import ExtractedRule, save_rules
from .icai_simple import (Case, build_cases, _generation_prompt, _test_prompt,
                          agreement, MIN_RELEVANCE, WORKERS)
from shared import llm

from shared.paths import output_dir, RULE_SETS_DIR

OUTPUT_DIR = output_dir("icai_v2")

K_CLUSTERS = 100          # paper warns against being restrictive here
N_CONSTITUTION = 5        # paper default n=5
EMBED_MODEL = "text-embedding-3-small"
STABILITY_MIN = 3         # keep a principle seen in >= this many seeds (of 5)


@dataclass
class RunParams:
    """One pipeline configuration.

    These were module constants, which is fine for a CLI and impossible for a
    server that has to run two configurations at once. Defaults are the
    published values, so an unparameterised call behaves as it always did.
    """

    seeds: int = 5
    k_clusters: int = K_CLUSTERS
    n_constitution: int = N_CONSTITUTION
    stability_min: int = STABILITY_MIN
    dry_run: bool = False
    tag: str = "icai_v2"
    data_dir: Optional[Path] = None      # None = the checked-in PM corpus
    model: Optional[str] = None          # None = ANTHROPIC_MODEL, else the pinned default
    # Cap the corpus for cheap exploratory runs. Cost is linear in corpus
    # size, so this is the strongest lever after the model choice.
    max_cases: Optional[int] = None



def subsample(cases, max_cases):
    """Trim the corpus to `max_cases`, keeping the corrective/accept ratio.

    Cost is linear in corpus size, so this is how an exploratory run gets cheap
    without changing the shape of the pipeline. Stratified because the corrective
    decisions are the scarce signal — a uniform sample of a 78%-accept corpus can
    leave almost nothing to learn from.

    Seeded fixed (not per-seed): every seed must see the SAME corpus, or the
    stability measurement conflates corpus sampling with the pipeline's own
    stochasticity, which is the only thing it is supposed to be measuring.
    """
    if not max_cases or len(cases) <= max_cases:
        return cases

    corrective = [c for c in cases if c.is_corrective]
    accepts = [c for c in cases if not c.is_corrective]
    rng = random.Random(0)
    rng.shuffle(corrective); rng.shuffle(accepts)

    share = max_cases / len(cases)
    n_corr = max(2, round(len(corrective) * share))
    kept = corrective[:n_corr] + accepts[:max(2, max_cases - n_corr)]
    rng.shuffle(kept)
    return kept


# --------------------------------------------------------------------------- #
# Step 1 - generation (both prompt variants per case, per the paper)
# --------------------------------------------------------------------------- #

def generate(cases: List[Case], dry_run: bool, model: str = None) -> List[Dict]:
    """Both prompt variants on every case, not one variant chosen by label.

    The paper's ablation (Table 3) makes single-prompt generation the worst
    configuration on unaligned data, and every rule this corpus yields is
    unaligned in that sense — it asks the evaluator to flag less.
    """
    if dry_run:
        return [{"principle": f"[dry-run] principle {i}",
                 "criterion": c.record.criterion_id}
                for i, c in enumerate(cases) for _ in range(2)]

    jobs = [(c, flip) for c in cases for flip in (False, True)]

    def one(job) -> List[Dict]:
        case, flip = job
        # flip: ask the OTHER variant's question of the same case, so accepts
        # also yield "do not flag" candidates and vice versa.
        probe = Case(record=case.record,
                     label=("accept" if case.is_corrective else "reject") if flip
                     else case.label)
        try:
            out = llm.extract_json(llm.call_llm(_generation_prompt(probe),
                                                model=model))
            return [{"principle": p.strip(), "criterion": case.record.criterion_id}
                    for p in out.get("principles", []) if p and p.strip()]
        except Exception as exc:  # noqa: BLE001
            print(f"    ! generation failed ({case.record.record_id}): {exc}")
            return []

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        return [p for group in pool.map(one, jobs) for p in group]


# --------------------------------------------------------------------------- #
# Steps 2 + 3 - embed, cluster, subsample
# --------------------------------------------------------------------------- #

def embed(texts: List[str]) -> np.ndarray:
    """OpenAI embeddings. Anthropic has no embeddings endpoint, and at ~$0.02
    per 1M tokens this is a rounding error next to generation and testing."""
    llm.ensure_env()
    import openai
    client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY", "").strip())
    vecs: List[List[float]] = []
    for i in range(0, len(texts), 256):
        resp = client.embeddings.create(model=EMBED_MODEL, input=texts[i:i + 256])
        vecs.extend(d.embedding for d in resp.data)
    return np.array(vecs, dtype=np.float32)


def cluster_and_subsample(cands: List[Dict], k: int, seed: int,
                          dry_run: bool) -> List[Dict]:
    """k-means over principle embeddings, then one principle per cluster."""
    if not cands:
        return []
    k = min(k, len(cands))
    if dry_run:
        return cands[:k]

    from sklearn.cluster import KMeans
    X = embed([c["principle"] for c in cands])
    labels = KMeans(n_clusters=k, random_state=seed, n_init=4).fit_predict(X)

    by_cluster: Dict[int, List[Dict]] = defaultdict(list)
    for cand, lab in zip(cands, labels):
        by_cluster[int(lab)].append(cand)

    rng = random.Random(seed)
    out = []
    for lab, members in sorted(by_cluster.items()):
        pick = dict(rng.choice(members))
        pick["cluster_size"] = len(members)      # stands in for paper's support
        out.append(pick)
    return out


# --------------------------------------------------------------------------- #
# Step 4/5 - test on held-out cases, then filter
# --------------------------------------------------------------------------- #

def test_principles(principles: List[Dict], cases: List[Case],
                    dry_run: bool, model: str = None) -> List[Dict]:
    n = len(principles)
    tally = [{"correct": 0, "incorrect": 0, "relevant": 0} for _ in range(n)]
    if dry_run:
        # Stub votes that SCALE with the corpus. Fixed counts of 10 meant
        # relevance = 10/len(cases), which drops under MIN_RELEVANCE on any
        # corpus past 100 cases - so a dry run on the real 203-record corpus
        # silently filtered every principle out and returned nothing.
        rel = max(2, len(cases) // 2)
        for i, t in enumerate(tally):
            bad = i % 3
            t.update(correct=rel - bad, incorrect=bad, relevant=rel)
    else:
        def one(case: Case) -> Optional[Dict]:
            for _ in range(2):
                try:
                    out = llm.extract_json(
                        llm.call_llm(_test_prompt(case, principles),
                                     max_tokens=3000, model=model))
                    votes = out.get("votes", {})
                    if isinstance(votes, list):
                        votes = {str(i): v for i, v in enumerate(votes)}
                    return {"case": case, "votes": votes}
                except Exception:  # noqa: BLE001
                    continue
            return None

        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            for res in pool.map(one, cases):
                if not res:
                    continue
                for i in range(n):
                    v = str(res["votes"].get(str(i), "na")).strip().lower()
                    if v not in ("accept", "reject"):
                        continue
                    tally[i]["relevant"] += 1
                    if v == res["case"].label:
                        tally[i]["correct"] += 1
                    else:
                        tally[i]["incorrect"] += 1

    total = max(1, len(cases))
    scored = []
    for p, t in zip(principles, tally):
        rel = t["relevant"] / total
        scored.append({**p, **t, "relevance": round(rel, 3),
                       "accuracy": round(t["correct"] / t["relevant"], 3) if t["relevant"] else 0.0,
                       "net": t["correct"] - t["incorrect"]})
    return scored


def filter_top(scored: List[Dict], n: int) -> List[Dict]:
    keep = [s for s in scored if s["net"] > 0 and s["relevance"] >= MIN_RELEVANCE]
    return sorted(keep, key=lambda s: (-s["net"], -s["accuracy"]))[:n]


# --------------------------------------------------------------------------- #
# One seed
# --------------------------------------------------------------------------- #

def run_once(seed: int, dry_run: bool, params: "RunParams | None" = None,
             progress=print) -> Tuple[List[Dict], float, float]:
    params = params or RunParams(dry_run=dry_run)
    cases = build_cases(params.data_dir)
    cases = subsample(cases, params.max_cases)
    rng = random.Random(seed)

    # Stratified half/half split: corrective decisions are the scarce signal, so
    # they must be represented on both sides.
    corrective = [c for c in cases if c.is_corrective]
    accepts = [c for c in cases if not c.is_corrective]
    rng.shuffle(corrective); rng.shuffle(accepts)
    half_c, half_a = len(corrective) // 2, len(accepts) // 2
    train = corrective[:half_c] + accepts[:half_a]
    test = corrective[half_c:] + accepts[half_a:]
    test_corrective = corrective[half_c:]

    progress(f"  seed {seed}: train {len(train)} / test {len(test)} "
             f"({len(test_corrective)} corrective in test)")

    cands = generate(train, dry_run, params.model)
    progress(f"    generated {len(cands)} candidates")
    survivors = cluster_and_subsample(cands, params.k_clusters, seed, dry_run)
    progress(f"    clustered -> {len(survivors)} principles")
    scored = test_principles(survivors, test, dry_run, params.model)
    const = filter_top(scored, params.n_constitution)
    progress(f"    filtered  -> {len(const)} in constitution")

    base = withc = 0.0
    if const and not dry_run:
        text = "\n".join(f'{i+1}. {c["principle"]}' for i, c in enumerate(const))
        # Eq. 1 on corrective cases only — the discriminating subset.
        base = agreement(test_corrective, None, params.model)
        withc = agreement(test_corrective, text, params.model)
        progress(f"    agreement (corrective only): {base:.2f} -> {withc:.2f} "
                 f"({withc - base:+.2f})")
    return const, base, withc


# --------------------------------------------------------------------------- #
# Stability selection across seeds
# --------------------------------------------------------------------------- #

def stability_select(per_seed: List[List[Dict]], dry_run: bool) -> List[Dict]:
    """Cluster every seed's surviving principles; keep those most seeds found."""
    pooled = [{**p, "seed": s} for s, const in enumerate(per_seed) for p in const]
    if not pooled:
        return []
    if dry_run:
        # Group by identical text instead of embedding, but emit the SAME keys the
        # live branch does. Returning bare candidates here meant every caller that
        # read `seeds_found` blew up the moment a dry run actually produced rules.
        groups: Dict[str, List[Dict]] = defaultdict(list)
        for p in pooled:
            groups[p["principle"]].append(p)
        out = [{**max(g, key=lambda m: (m["net"], m["accuracy"])),
                "seeds_found": len({m["seed"] for m in g}),
                "variants": [g[0]["principle"]]}
               for g in groups.values()]
        out.sort(key=lambda p: (-p["seeds_found"], -p["net"]))
        return out

    from sklearn.cluster import KMeans
    k = min(max(2, len(pooled) // 2), len(pooled))
    X = embed([p["principle"] for p in pooled])
    labels = KMeans(n_clusters=k, random_state=0, n_init=4).fit_predict(X)

    groups: Dict[int, List[Dict]] = defaultdict(list)
    for p, lab in zip(pooled, labels):
        groups[int(lab)].append(p)

    out = []
    for members in groups.values():
        seeds = {m["seed"] for m in members}
        best = max(members, key=lambda m: (m["net"], m["accuracy"]))
        out.append({**best, "seeds_found": len(seeds),
                    "variants": sorted({m["principle"] for m in members})})
    out.sort(key=lambda p: (-p["seeds_found"], -p["net"]))
    return out




# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #

def to_rules(stable: List[Dict]) -> List[ExtractedRule]:
    """The stable constitution in the shape the testbed injects.

    `inject.load_sme_rules` reads exactly this file format, so whatever produces
    it — the CLI or the Studio — yields a drop-in rule set.
    """
    return [ExtractedRule(
        criterion=p["criterion"], criterion_name="", rule_text=p["principle"],
        method="icai_v2", support_count=p.get("cluster_size", 0),
        extra={k: p[k] for k in ("net", "relevance", "accuracy", "correct",
                                 "incorrect", "seeds_found", "variants")
               if k in p}) for p in stable]


def run_pipeline(params: RunParams, progress=print) -> Dict:
    """Every seed, then stability selection across them.

    Split out of main() so the Studio server can run the same code path the CLI
    runs — the alternative, a second orchestration loop in the web layer, is how
    a UI and a paper start reporting different numbers.

    `progress` receives one line per step; the server appends it to a run log the
    browser polls.
    """
    from shared.evaluator import resolve_model
    progress(f"ICAI v2: {params.seeds} seeds, k={params.k_clusters}, "
             f"model={resolve_model(params.model)}"
             f"{f', corpus capped at {params.max_cases}' if params.max_cases else ''}"
             f"{' (dry run - no API calls)' if params.dry_run else ''}")

    per_seed, agreements = [], []
    for s in range(params.seeds):
        const, base, withc = run_once(s, params.dry_run, params, progress)
        per_seed.append(const)
        agreements.append({"seed": s, "base": base, "with_constitution": withc,
                           "lift": round(withc - base, 3)})

    progress("  selecting principles by cross-seed stability...")
    ranked = stability_select(per_seed, params.dry_run)
    stable = [p for p in ranked
              if p["seeds_found"] >= params.stability_min][:params.n_constitution]
    truncated = False
    if not stable:
        progress(f"  !! nothing reached {params.stability_min}/{params.seeds} seeds - "
                 f"reporting the top {params.n_constitution} by seed count instead")
        stable = ranked[:params.n_constitution]
        truncated = True

    lifts = [x["lift"] for x in agreements]
    progress(f"Eq. 1 lift across seeds: mean {np.mean(lifts):+.3f}  "
             f"min {min(lifts):+.3f}  max {max(lifts):+.3f}")
    progress(f"Stable constitution ({len(stable)} rules):")
    for i, p in enumerate(stable, 1):
        progress(f"  {i}. [{p['criterion']}] seeds={p['seeds_found']}/{params.seeds} "
                 f"net={p['net']} rel={p['relevance']} acc={p['accuracy']}")
        progress(f"     {p['principle']}")

    return {
        "params": {"seeds": params.seeds, "k_clusters": params.k_clusters,
                   "n_constitution": params.n_constitution,
                   "stability_min": params.stability_min,
                   "dry_run": params.dry_run, "tag": params.tag},
        "seed_agreements": agreements,
        "lift_mean": round(float(np.mean(lifts)), 3),
        "stable": stable,
        "all_ranked": ranked,
        # True when no principle cleared the stability bar, so the caller can say
        # so rather than presenting a fallback list as if it were stable.
        "below_stability_threshold": truncated,
        "rules": to_rules(stable),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--k-clusters", type=int, default=K_CLUSTERS)
    ap.add_argument("--n-constitution", type=int, default=N_CONSTITUTION)
    ap.add_argument("--stability-min", type=int, default=STABILITY_MIN)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--tag", default="icai_v2")
    a = ap.parse_args()

    params = RunParams(seeds=a.seeds, k_clusters=a.k_clusters,
                       n_constitution=a.n_constitution,
                       stability_min=a.stability_min,
                       dry_run=a.dry_run, tag=a.tag)
    result = run_pipeline(params)

    dest = OUTPUT_DIR if a.dry_run else RULE_SETS_DIR
    dest.mkdir(parents=True, exist_ok=True)
    save_rules(result["rules"], dest / f"rules_group_{a.tag}.json")
    (OUTPUT_DIR / f"{a.tag}_agreement.json").write_text(
        json.dumps({"seeds": result["seed_agreements"],
                    "all_ranked": result["all_ranked"]}, indent=2),
        encoding="utf-8")
    print(f"\nwrote {dest / f'rules_group_{a.tag}.json'}")


if __name__ == "__main__":
    main()
