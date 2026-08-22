"""
Google Colab Notebook — R1-R14 Requirements Evaluation Analysis
================================================================
USAGE:
  1. Upload your prediction xlsx (contains Execution_* tabs from n8n)
  2. Upload your ground-truth xlsx
  3. Set PRED_PATH and GT_PATH below
  4. Run all cells

The code auto-detects ALL execution sheets (any name like
Execution_10, Execution_30, etc.), aggregates metrics across
all of them, and generates boxplots automatically.
"""

# ═══════════════════════════════════════════════════════════════
#  CELL 0 — Install dependencies (run once in Colab)
# ═══════════════════════════════════════════════════════════════
# !pip install openpyxl pandas matplotlib

# ═══════════════════════════════════════════════════════════════
#  CELL 1 — Configuration
# ═══════════════════════════════════════════════════════════════

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.ticker import FormatStrFormatter
import re

# ---------- EDIT THESE PATHS ----------
PRED_PATH   = "R1_R14_evaluation_matrix.xlsx"    # n8n output (100 Execution_* tabs)
GT_PATH     = "R1_R14_GroundTruth.xlsx"           # ground-truth file
GT_SHEET    = "Sheet1"                             # tab inside GT file
OUT_PATH    = "confusion_detail_R1_R14.xlsx"       # metrics output
SUMMARY_OUT = "summary_stats_R1_R14.xlsx"          # summary statistics
PLOT_OUT    = "boxplot_R1_R14.png"                 # boxplot image

# --- Rule definitions ---
INDIVIDUAL_RULE_IDS = ["R1","R2","R3","R4","R5","R6","R7","R8","R9","R10","R11","R12"]
SET_RULE_IDS        = ["R13","R14"]

RULE_ID_COL  = 0
RULE_DESC_COL = 1


# ═══════════════════════════════════════════════════════════════
#  CELL 2 — Helper functions
# ═══════════════════════════════════════════════════════════════

def _normalize_id(val) -> str:
    s = str(val).strip().upper()
    if s.endswith(".0"):
        s = s[:-2]
    return s

_INDIVIDUAL_SET = {_normalize_id(v) for v in INDIVIDUAL_RULE_IDS}
_SET_LEVEL_SET  = {_normalize_id(v) for v in SET_RULE_IDS}


def is_pos_x_df(df):
    return df.fillna("").astype(str).map(lambda v: v.strip().lower()) == "x"


def _find_rule_id_col(df):
    """Auto-detect which column holds Rule IDs."""
    for col_idx in range(min(3, df.shape[1])):
        vals = df.iloc[:, col_idx].apply(_normalize_id)
        if vals.isin(_INDIVIDUAL_SET | _SET_LEVEL_SET).sum() >= 2:
            return col_idx
    return 0


def read_individual_matrix(path, sheet):
    df = pd.read_excel(path, sheet_name=sheet, engine="openpyxl")
    if df.empty:
        return df
    id_col = _find_rule_id_col(df)
    normed = df.iloc[:, id_col].apply(_normalize_id)
    mask = normed.isin(_INDIVIDUAL_SET)
    df_f = df.loc[mask].copy()
    if df_f.empty:
        return df_f
    df_f.index = normed.loc[mask]
    first_data = id_col + 2
    mat = df_f.iloc[:, first_data:].copy()
    for c in ["FR","PR","ER","RR","ALL"]:
        if c in mat.columns:
            mat = mat.drop(columns=[c])
    return mat


def read_set_matrix(path, sheet):
    df = pd.read_excel(path, sheet_name=sheet, engine="openpyxl")
    if df.empty:
        return df
    id_col = _find_rule_id_col(df)
    normed = df.iloc[:, id_col].apply(_normalize_id)
    mask = normed.isin(_SET_LEVEL_SET)
    df_f = df.loc[mask].copy()
    if df_f.empty:
        return df_f
    df_f.index = normed.loc[mask]
    first_data = id_col + 2
    mat = df_f.iloc[:, first_data:].copy()
    set_cols = [c for c in ["FR","PR","ER","RR","ALL"] if c in mat.columns]
    return mat[set_cols] if set_cols else pd.DataFrame()


def safe_div(n, d):
    n, d = np.asarray(n, float), np.asarray(d, float)
    return np.where(d == 0, np.nan, n / d)


def confusion_from_bool(P, G):
    return int(np.sum(P&G)), int(np.sum(~P&~G)), int(np.sum(P&~G)), int(np.sum(~P&G))


def metrics_from_counts(tp, tn, fp, fn):
    acc  = safe_div(tp+tn, tp+tn+fp+fn)
    prec = safe_div(tp, tp+fp)
    rec  = safe_div(tp, tp+fn)
    spec = safe_div(tn, tn+fp)
    f1   = safe_div(2*prec*rec, prec+rec)
    fnr  = safe_div(fn, tp+fn)
    fpr  = safe_div(fp, fp+tn)
    return acc, prec, rec, spec, rec, f1, fnr, fpr  # sens=rec


def get_execution_sheets(xls):
    """Auto-detect all valid execution sheets by checking for rule IDs."""
    valid = []
    for sh in xls.sheet_names:
        try:
            df = pd.read_excel(xls, sheet_name=sh, engine="openpyxl", nrows=15)
            if df.empty:
                continue
            id_col = _find_rule_id_col(df)
            normed = df.iloc[:, id_col].apply(_normalize_id)
            if normed.isin(_INDIVIDUAL_SET).sum() >= 2:
                valid.append(sh)
        except Exception:
            continue

    def sort_key(name):
        nums = re.findall(r'\d+', name)
        return int(nums[-1]) if nums else 0
    try:
        valid.sort(key=sort_key)
    except TypeError:
        valid.sort()
    return valid


# ═══════════════════════════════════════════════════════════════
#  CELL 3 — Run metrics computation
# ═══════════════════════════════════════════════════════════════

def run_metrics(pred_path, gt_path, gt_sheet, out_path):

    xls_pred = pd.ExcelFile(pred_path, engine="openpyxl")

    gt_indiv = is_pos_x_df(read_individual_matrix(gt_path, gt_sheet)).fillna(False)
    gt_set_raw = read_set_matrix(gt_path, gt_sheet)
    gt_set = is_pos_x_df(gt_set_raw).fillna(False) if not gt_set_raw.empty else pd.DataFrame()

    print(f"GT Individual: {gt_indiv.shape}  rules={gt_indiv.index.tolist()}")
    print(f"GT Set-level:  {gt_set.shape}  rules={gt_set.index.tolist() if not gt_set.empty else '(none)'}")

    sheets = get_execution_sheets(xls_pred)
    print(f"\nFound {len(sheets)} execution sheets")
    if sheets:
        print(f"  e.g. {sheets[:3]} ... {sheets[-3:]}" if len(sheets) > 6 else f"  {sheets}")
    print()

    M = ["Accuracy","Precision","Recall","Specificity","Sensitivity","F1","FNR","FPR"]

    TP_i = pd.DataFrame(index=gt_indiv.index)
    TN_i = pd.DataFrame(index=gt_indiv.index)
    FP_i = pd.DataFrame(index=gt_indiv.index)
    FN_i = pd.DataFrame(index=gt_indiv.index)
    mt_i = {m: pd.DataFrame(index=gt_indiv.index) for m in M}

    has_set = not gt_set.empty
    if has_set:
        TP_s = pd.DataFrame(index=gt_set.index)
        TN_s = pd.DataFrame(index=gt_set.index)
        FP_s = pd.DataFrame(index=gt_set.index)
        FN_s = pd.DataFrame(index=gt_set.index)
        mt_s = {m: pd.DataFrame(index=gt_set.index) for m in M}

    sum_i, sum_s, skipped = [], [], []

    for sh in sheets:
        # --- Individual ---
        raw = read_individual_matrix(pred_path, sh)
        if raw.empty:
            skipped.append(sh); continue

        pred = is_pos_x_df(raw).reindex(index=gt_indiv.index, columns=gt_indiv.columns).fillna(False)
        P, G = pred.to_numpy(bool), gt_indiv.to_numpy(bool)
        tp, tn, fp, fn = confusion_from_bool(P, G)
        a,p,r,sp,sn,f,fnr,fpr = metrics_from_counts(tp,tn,fp,fn)

        sum_i.append({"sheet":sh, "TP":tp,"TN":tn,"FP":fp,"FN":fn,
                       "Accuracy":float(a),"Precision":float(p),"Recall":float(r),
                       "Sensitivity":float(sn),"Specificity":float(sp),
                       "F1":float(f),"FNR":float(fnr),"FPR":float(fpr)})

        tc = {m:[] for m in M}
        tp_c,tn_c,fp_c,fn_c = [],[],[],[]
        for rid in gt_indiv.index:
            pr = pred.loc[rid].to_numpy(bool)
            gr = gt_indiv.loc[rid].to_numpy(bool)
            t,tn2,f2,fn2 = confusion_from_bool(pr,gr)
            tp_c.append(t); tn_c.append(tn2); fp_c.append(f2); fn_c.append(fn2)
            vals = metrics_from_counts(t,tn2,f2,fn2)
            for name,val in zip(M, vals):
                tc[name].append(float(val))
        TP_i[sh]=tp_c; TN_i[sh]=tn_c; FP_i[sh]=fp_c; FN_i[sh]=fn_c
        for m in M: mt_i[m][sh] = tc[m]

        # --- Set-level ---
        if not has_set: continue
        raw_s = read_set_matrix(pred_path, sh)
        if raw_s.empty: continue

        pred_s = is_pos_x_df(raw_s).reindex(index=gt_set.index, columns=gt_set.columns).fillna(False)
        Ps, Gs = pred_s.to_numpy(bool), gt_set.to_numpy(bool)
        tps,tns,fps,fns = confusion_from_bool(Ps,Gs)
        as2,ps2,rs2,sps,sns,fs2,fnrs,fprs = metrics_from_counts(tps,tns,fps,fns)

        sum_s.append({"sheet":sh, "TP":tps,"TN":tns,"FP":fps,"FN":fns,
                       "Accuracy":float(as2),"Precision":float(ps2),"Recall":float(rs2),
                       "Sensitivity":float(sns),"Specificity":float(sps),
                       "F1":float(fs2),"FNR":float(fnrs),"FPR":float(fprs)})

        tc_s = {m:[] for m in M}
        tp_cs,tn_cs,fp_cs,fn_cs = [],[],[],[]
        for rid in gt_set.index:
            pr = pred_s.loc[rid].to_numpy(bool)
            gr = gt_set.loc[rid].to_numpy(bool)
            t,tn2,f2,fn2 = confusion_from_bool(pr,gr)
            tp_cs.append(t); tn_cs.append(tn2); fp_cs.append(f2); fn_cs.append(fn2)
            vals = metrics_from_counts(t,tn2,f2,fn2)
            for name,val in zip(M, vals):
                tc_s[name].append(float(val))
        TP_s[sh]=tp_cs; TN_s[sh]=tn_cs; FP_s[sh]=fp_cs; FN_s[sh]=fn_cs
        for m in M: mt_s[m][sh] = tc_s[m]

    if skipped:
        print(f"Skipped {len(skipped)} empty sheet(s): {skipped}\n")

    si = pd.DataFrame(sum_i).sort_values("sheet")
    ss = pd.DataFrame(sum_s).sort_values("sheet") if sum_s else pd.DataFrame()

    with pd.ExcelWriter(out_path, engine="openpyxl") as w:
        si.to_excel(w, index=False, sheet_name="Summary_Individual")
        if not ss.empty:
            ss.to_excel(w, index=False, sheet_name="Summary_SetLevel")
        TP_i.to_excel(w, sheet_name="TP_by_rule_indiv")
        TN_i.to_excel(w, sheet_name="TN_by_rule_indiv")
        FP_i.to_excel(w, sheet_name="FP_by_rule_indiv")
        FN_i.to_excel(w, sheet_name="FN_by_rule_indiv")
        for m,tbl in mt_i.items():
            tbl.to_excel(w, sheet_name=f"{m}_by_rule_indiv")
        if has_set and not TP_s.columns.empty:
            TP_s.to_excel(w, sheet_name="TP_by_rule_set")
            TN_s.to_excel(w, sheet_name="TN_by_rule_set")
            FP_s.to_excel(w, sheet_name="FP_by_rule_set")
            FN_s.to_excel(w, sheet_name="FN_by_rule_set")
            for m,tbl in mt_s.items():
                tbl.to_excel(w, sheet_name=f"{m}_by_rule_set")

    print(f"Saved -> {out_path}  ({len(sum_i)} sheets processed)")
    return out_path


# ═══════════════════════════════════════════════════════════════
#  CELL 4 — Boxplots & summary stats
# ═══════════════════════════════════════════════════════════════

# Short labels for per-rule breakdown plots (edit as needed)
# GT rule-ID → friendly criterion name for y-axis labels
RULE_LABEL_MAP = {
    "R1":  "Necessary",
    "R2":  "Singular",
    "R3":  "Unambiguous",
    "R4":  "Complete",
    "R5":  "Correct",
    "R6":  "R6",
    "R7":  "R7",
    "R8":  "R8",
    "R9":  "R9",
    "R10": "R10",
    "R11": "Conforming",
    "R12": "Appropriate",
    "R13": "R13",
    "R14": "R14",
}

# Canonical A-series display order (top→bottom): Necessary, Appropriate, …, Conforming
RULE_DISPLAY_ORDER = ["R1", "R12", "R3", "R4", "R2", "R5", "R11"]

# ── Overall distribution boxplot (matches notebook cell 2) ─────────────────
def _make_boxplot(data, labels, title, save_path, color="maroon"):
    fig, ax = plt.subplots(figsize=(8, 6))
    bp = ax.boxplot(data, labels=labels, vert=False, patch_artist=True, showfliers=True)

    for box in bp["boxes"]:
        box.set(color="black")
        box.set(facecolor="none")
    for med in bp["medians"]:
        med.set(color=color, linewidth=1.5)
    for w in bp["whiskers"]:
        w.set(color="black")
    for c in bp["caps"]:
        c.set(color="black")

    medians = [np.nanmedian(d) if len(d) > 0 else np.nan for d in data]
    for i, m in enumerate(medians, start=1):
        if not np.isnan(m):
            ax.text(m, i + 0.2, f"{m:.2f}", va="bottom", ha="center",
                    color=color, fontsize=14)

    ax.set_xlim(0, 1)
    ax.xaxis.set_major_formatter(FormatStrFormatter("%.2f"))
    ax.tick_params(axis="x", labelsize=14)
    ax.tick_params(axis="y", labelsize=14)
    ax.set_xlabel("Rate", fontsize=15)
    ax.set_ylabel("Metric", fontsize=15)
    ax.set_title(title, fontweight="bold", fontsize=15)
    plt.tight_layout()
    plt.savefig(save_path, dpi=300, bbox_inches="tight")
    plt.show()
    print(f"Boxplot saved -> {save_path}")


# ── Per-rule distribution boxplot (matches notebook cell 3) ────────────────
def _make_per_rule_boxplot(df_by_rule, metric_name, title, save_path, color="maroon"):
    """Horizontal boxplot with one box per rule — mirrors notebook cell 3 exactly."""
    X_PADDING = 0.04
    Y_PADDING = 0.3
    Y_OFFSET  = 0.3

    # Sort rows into canonical A-series display order, unknown rules appended last
    ordered = [r for r in RULE_DISPLAY_ORDER if r in df_by_rule.index]
    ordered += [r for r in df_by_rule.index if r not in RULE_DISPLAY_ORDER]
    df_by_rule = df_by_rule.loc[ordered]

    rules = df_by_rule.index.tolist()
    rule_labels = [RULE_LABEL_MAP.get(str(r), str(r)) for r in rules]
    data = [df_by_rule.loc[r].dropna().values for r in rules]

    fig, ax = plt.subplots(figsize=(8, 10))
    bp = ax.boxplot(data, labels=rule_labels, vert=False,
                    patch_artist=True, showfliers=True)

    for box in bp["boxes"]:
        box.set(color="black")
        box.set(facecolor="none")
    for med in bp["medians"]:
        med.set(color=color, linewidth=1)
    for w in bp["whiskers"]:
        w.set(color="black")
    for c in bp["caps"]:
        c.set(color="black")

    medians = [np.nanmedian(d) if len(d) > 0 else np.nan for d in data]
    for i, m in enumerate(medians, start=1):
        if not np.isnan(m):
            ax.text(m, i - Y_OFFSET, f"{m:.2f}", va="bottom", ha="center",
                    color=color, fontsize=14)

    n_rules = len(data)
    ax.set_ylim(0.5 - Y_PADDING, n_rules + 0.5 + Y_PADDING)
    ax.set_xlim(-X_PADDING, 1 + X_PADDING)
    ax.xaxis.set_major_formatter(FormatStrFormatter("%.2f"))
    ax.tick_params(axis="x", labelsize=14)
    ax.tick_params(axis="y", labelsize=14)
    ax.set_xlabel("Rate", fontsize=15)
    ax.set_ylabel("Rule", fontsize=15)
    ax.set_title(title, fontweight="bold", fontsize=15)
    ax.invert_yaxis()
    plt.tight_layout()
    plt.savefig(save_path, dpi=300, bbox_inches="tight")
    plt.show()
    print(f"Per-rule boxplot saved -> {save_path}")


def run_visualization(excel_path, summary_out_path, plot_out_path):
    mc = ["F1","Precision","Accuracy","FNR","FPR","Specificity","Sensitivity"]
    dl = ["F1","Precision","Accuracy","FNR","FPR","TNR","TPR"]

    df = pd.read_excel(excel_path, sheet_name="Summary_Individual")
    ds = df[mc].apply(pd.to_numeric, errors="coerce")
    stats = ds.agg(["min","max","median","mean","std"]); stats.columns = dl
    print("\n" + "="*60 + "\nIndividual Rules (R1-R12) — Summary\n" + "="*60)
    print(stats)
    stats.to_excel(summary_out_path)
    _make_boxplot([ds[c].dropna().values for c in mc], dl,
                  "Individual Rules (R1-R12): Detection Rate Distribution",
                  plot_out_path, "maroon")

    try:
        df2 = pd.read_excel(excel_path, sheet_name="Summary_SetLevel")
        ds2 = df2[mc].apply(pd.to_numeric, errors="coerce")
        stats2 = ds2.agg(["min","max","median","mean","std"]); stats2.columns = dl
        print("\n" + "="*60 + "\nSet-Level Rules (R13-R14) — Summary\n" + "="*60)
        print(stats2)
        stats2.to_excel(summary_out_path.replace(".xlsx","_set.xlsx"))
        _make_boxplot([ds2[c].dropna().values for c in mc], dl,
                      "Set-Level Rules (R13-R14): Detection Rate Distribution",
                      plot_out_path.replace(".png","_set.png"), "darkblue")
    except: pass


# ═══════════════════════════════════════════════════════════════
#  CELL 5 — Per-rule breakdown
# ═══════════════════════════════════════════════════════════════

PER_RULE_METRICS = [
    ("TPR",       "Recall"),
    ("TNR",       "Specificity"),
    ("FPR",       "FPR"),
    ("FNR",       "FNR"),
    ("Precision", "Precision"),
    ("F1",        "F1"),
    ("Accuracy",  "Accuracy"),
]

def run_per_rule_analysis(excel_path):
    for level, sfx, color in [
        ("Individual (R1-R12)", "_indiv", "maroon"),
        ("Set-Level (R13-R14)", "_set",   "darkblue"),
    ]:
        for display_name, sheet_metric in PER_RULE_METRICS:
            sheet = f"{sheet_metric}_by_rule{sfx}"
            try:
                df = pd.read_excel(excel_path, sheet_name=sheet, index_col=0)
            except Exception:
                continue

            df = df.apply(pd.to_numeric, errors="coerce")
            if df.empty:
                continue

            # Print summary stats (matches notebook cell 3 pattern)
            stats = df.agg(["min", "max", "median", "mean", "std"], axis=1)
            print(f"\n{'='*60}")
            print(f"{level} — {display_name} per rule")
            print(f"{'='*60}")
            print(stats.round(3))

            title = f"Distribution of {display_name} by Rule"
            fn = f"{display_name}_by_rule{sfx}.png"
            _make_per_rule_boxplot(df, display_name, title, fn, color=color)


# ═══════════════════════════════════════════════════════════════
#  CELL 6 — Run everything
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    metrics_file = run_metrics(PRED_PATH, GT_PATH, GT_SHEET, OUT_PATH)
    run_visualization(metrics_file, SUMMARY_OUT, PLOT_OUT)
    run_per_rule_analysis(metrics_file)
