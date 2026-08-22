"""NLP layer — how well does the AI's reasoning align with expert comments?

The GT survey carries free-text expert Comments per requirement, grouped by the
four requirement categories (Function / Performance / Environmental / Resource).
This module measures the semantic similarity between those expert comments and
the AI evaluator's explanations, per requirement and aggregated by category — a
"reasoning-alignment" score to sit alongside the binary detection KPIs.

Embedding backend, best available first:
  1. sentence-transformers (all-MiniLM-L6-v2)  — true semantic similarity
  2. scikit-learn TF-IDF cosine                — lexical similarity
  3. token Jaccard                             — last-resort fallback
The chosen backend is reported so results are interpretable.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

from shared import datasets

from shared.paths import TESTBED_RUNS_DIR as RUNS_DIR, output_dir

# Matrices, raw dumps and ground-truth workbooks are the RUN STORE: each one
# cost 100 whole-set LLM calls, so they are versioned rather than rebuilt.
# Plots and summary workbooks are regenerable and go to outputs/.
RUNS_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR = output_dir("n8n_testbed")
PLOT_DIR = OUTPUT_DIR / "plots"

CATEGORY_NAME = {"FR": "Function", "PR": "Performance",
                 "ER": "Environmental", "RR": "Resource"}


# --------------------------------------------------------------------------- #
# Embedding backends
# --------------------------------------------------------------------------- #

def _get_backend():
    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("all-MiniLM-L6-v2")

        def embed(texts: List[str]) -> np.ndarray:
            return np.asarray(model.encode(texts, normalize_embeddings=True))
        return "sentence-transformers", embed
    except Exception:
        pass

    try:
        from sklearn.feature_extraction.text import TfidfVectorizer

        def embed(texts: List[str]) -> np.ndarray:
            vec = TfidfVectorizer(stop_words="english").fit(texts)
            m = vec.transform(texts).toarray()
            norms = np.linalg.norm(m, axis=1, keepdims=True)
            return m / np.clip(norms, 1e-9, None)
        return "tfidf", embed
    except Exception:
        pass

    def embed(texts: List[str]) -> np.ndarray:  # Jaccard handled specially
        return None
    return "jaccard", embed


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b))


def _jaccard(x: str, y: str) -> float:
    sx, sy = set(x.lower().split()), set(y.lower().split())
    if not sx or not sy:
        return 0.0
    return len(sx & sy) / len(sx | sy)


# --------------------------------------------------------------------------- #
# Text assembly
# --------------------------------------------------------------------------- #

def _gt_comment_text(req) -> str:
    """All expert comments for a requirement, joined."""
    return " ".join(v for v in req.comments.values() if v).strip()


def _ai_explanation_text(raw: Dict, req_id: str) -> str:
    """All AI explanations for a requirement, pooled across runs/criteria."""
    parts = []
    for execution in raw.values():
        for ev in execution.get(req_id, []):
            expl = ev.get("explanation")
            if expl:
                parts.append(expl)
    return " ".join(parts).strip()


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #

def score(dataset: str, config: str) -> pd.DataFrame:
    ds = datasets.load_dataset(dataset)
    raw_path = RUNS_DIR / f"{dataset}_{config}_raw.json"
    if not raw_path.exists():
        raise FileNotFoundError(f"missing {raw_path.name} — run the batch first")
    raw = json.loads(raw_path.read_text(encoding="utf-8"))

    backend, embed = _get_backend()
    rows = []
    for req in ds.requirements:
        gt_text = _gt_comment_text(req)
        ai_text = _ai_explanation_text(raw, req.req_id)
        if not gt_text or not ai_text:
            continue  # only score requirements that have an expert comment
        if backend == "jaccard":
            sim = _jaccard(gt_text, ai_text)
        else:
            vecs = embed([gt_text, ai_text])
            sim = _cosine(vecs[0], vecs[1])
        rows.append({
            "dataset": dataset, "config": config, "req_id": req.req_id,
            "category": req.category, "category_name": CATEGORY_NAME.get(req.category, req.category),
            "similarity": round(sim, 4),
            "gt_comment": gt_text[:200], "ai_explanation": ai_text[:200],
        })
    df = pd.DataFrame(rows)
    df.attrs["backend"] = backend
    return df


def _bar_by_category(df: pd.DataFrame, dataset: str, path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    g = df[df["dataset"] == dataset]
    cats = ["FR", "PR", "ER", "RR"]
    configs = [c for c in ["baseline", "M1", "M2"] if c in g["config"].values]
    x = np.arange(len(cats))
    w = 0.8 / max(len(configs), 1)
    colors = {"baseline": "#6c757d", "M1": "#1f77b4", "M2": "#8a1538"}
    fig, ax = plt.subplots(figsize=(9, 5))
    for i, cfg in enumerate(configs):
        means = [g[(g["config"] == cfg) & (g["category"] == c)]["similarity"].mean()
                 for c in cats]
        means = [0 if (m is None or np.isnan(m)) else m for m in means]
        ax.bar(x + i * w, means, w, label=cfg, color=colors.get(cfg), alpha=0.85)
    ax.set_xticks(x + w * (len(configs) - 1) / 2)
    ax.set_xticklabels([CATEGORY_NAME[c] for c in cats])
    ax.set_ylabel("mean GT-comment vs AI-explanation similarity")
    ax.set_title(f"{dataset}: reasoning alignment by requirement category")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def run(datasets_list: List[str], configs: List[str]) -> pd.DataFrame:
    PLOT_DIR.mkdir(parents=True, exist_ok=True)
    frames = []
    backend = None
    for ds in datasets_list:
        for cfg in configs:
            if not (RUNS_DIR / f"{ds}_{cfg}_raw.json").exists():
                continue
            df = score(ds, cfg)
            backend = df.attrs.get("backend", backend)
            frames.append(df)
    if not frames:
        print("No raw evaluation files found — run the batch first.")
        return pd.DataFrame()
    alldf = pd.concat(frames, ignore_index=True)

    for ds in datasets_list:
        if ds in alldf["dataset"].values:
            _bar_by_category(alldf, ds, PLOT_DIR / f"nlp_alignment_{ds}.png")

    summary = (alldf.groupby(["dataset", "config", "category_name"])["similarity"]
               .agg(["mean", "count"]).reset_index())
    with pd.ExcelWriter(OUTPUT_DIR / "nlp_alignment.xlsx") as xl:
        alldf.to_excel(xl, sheet_name="per_requirement", index=False)
        summary.to_excel(xl, sheet_name="by_category", index=False)

    print(f"NLP backend: {backend}")
    print("\nMean reasoning-alignment by dataset/config/category:")
    print(summary.to_string(index=False))
    return summary


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--datasets", nargs="+", default=["PM", "Bookshelf"])
    ap.add_argument("--configs", nargs="+", default=["baseline", "M1", "M2"])
    args = ap.parse_args()
    run(args.datasets, args.configs)
    print("\nWrote nlp_alignment.xlsx and nlp_alignment_*.png")


if __name__ == "__main__":
    main()
