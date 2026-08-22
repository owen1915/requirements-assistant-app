import pandas as pd
import numpy as np

## Code for calculating the metrics

NUM_PREDICTION_TABS = 100

ISSUE_IDS_TO_KEEP = ["A1", "A2", "A3", "A4", "A5", "A6", "A9", "A10", "A11"]

# Column positions (0-based) in each sheet:
ISSUE_ID_COL = 0          # first column: Issue ID
ISSUE_DESC_COL = 1        # second column: Issue Description


def is_pos_x_df(df: pd.DataFrame) -> pd.DataFrame:
    """Return boolean df where True means cell == 'x' (case-insensitive, trimmed)."""
    arr = df.fillna("").astype(str).map(lambda v: v.strip().lower())
    return (arr == "x")


def read_labeled_matrix(path: str, sheet: str) -> pd.DataFrame:
    """
    Sheet format:
      - col 1: Issue ID
      - col 2: Issue Description
      - remaining cols: FR.* / PR.* / ER.* / RR.* entries (x/blank)

    Keeps only Issue IDs in ISSUE_IDS_TO_KEEP.
    Uses Issue ID (not description) as the row index for reliable alignment.
    Drops summary columns: FR, PR, ER, RR, ALL.
    """
    df = pd.read_excel(path, sheet_name=sheet, engine="openpyxl")

    # Filter strictly by known Issue IDs — also drops nan and junk rows
    mask = df.iloc[:, ISSUE_ID_COL].astype(str).str.strip().isin(ISSUE_IDS_TO_KEEP)
    df = df.loc[mask].copy()

    # Use Issue ID as index (not description — avoids any text mismatch between files)
    df.index = df.iloc[:, ISSUE_ID_COL].astype(str).str.strip()

    # Keep only requirement columns (everything after first two columns)
    mat = df.iloc[:, 2:].copy()

    # Drop summary columns
    cols_to_drop = ["FR", "PR", "ER", "RR", "ALL"]
    mat = mat.drop(columns=[c for c in cols_to_drop if c in mat.columns])

    return mat


def safe_div(numer, denom):
    """Elementwise division with NaN when denom == 0."""
    numer = np.asarray(numer, dtype=float)
    denom = np.asarray(denom, dtype=float)
    return np.where(denom == 0, np.nan, numer / denom)


def confusion_from_bool(P: np.ndarray, G: np.ndarray):
    """Compute TP/TN/FP/FN given boolean prediction and ground truth arrays."""
    tp = int(np.sum(P & G))
    tn = int(np.sum(~P & ~G))
    fp = int(np.sum(P & ~G))
    fn = int(np.sum(~P & G))
    return tp, tn, fp, fn


def metrics_from_counts(tp, tn, fp, fn):
    """
    Return all metrics:
      Accuracy    = (TP + TN) / (TP + TN + FP + FN)
      Precision   = TP / (TP + FP)
      Recall      = TP / (TP + FN)   [same as Sensitivity / TPR]
      Specificity = TN / (TN + FP)   [same as TNR]
      Sensitivity = TP / (TP + FN)   [same as Recall / TPR]
      F1          = 2 * (Precision * Recall) / (Precision + Recall)
      FNR         = FN / (TP + FN)
      FPR         = FP / (FP + TN)
    NaN is returned when the denominator is 0.
    """
    accuracy    = safe_div(tp + tn, tp + tn + fp + fn)
    precision   = safe_div(tp, tp + fp)
    recall      = safe_div(tp, tp + fn)       # = Sensitivity = TPR
    specificity = safe_div(tn, tn + fp)       # = TNR
    sensitivity = recall                       # alias
    f1          = safe_div(2 * precision * recall, precision + recall)
    fnr         = safe_div(fn, tp + fn)
    fpr         = safe_div(fp, fp + tn)
    return accuracy, precision, recall, specificity, sensitivity, f1, fnr, fpr


def run(pred_path: str, gt_path: str, gt_sheet: str, out_path: str = "confusion_detail.xlsx"):
    xls_pred = pd.ExcelFile(pred_path, engine="openpyxl")

    # Ground truth (single sheet)
    gt_raw = read_labeled_matrix(gt_path, gt_sheet)
    gt_bool = is_pos_x_df(gt_raw).fillna(False)

    print(f"GT shape: {gt_bool.shape}")
    print(f"GT index (Issue IDs): {gt_bool.index.tolist()}")
    print(f"GT columns: {gt_bool.columns.tolist()}")
    print()

    # Output tables: rows = Issue IDs, cols = prediction sheet names
    TP_tbl  = pd.DataFrame(index=gt_bool.index)
    TN_tbl  = pd.DataFrame(index=gt_bool.index)
    FP_tbl  = pd.DataFrame(index=gt_bool.index)
    FN_tbl  = pd.DataFrame(index=gt_bool.index)

    # Per-issue metric tables
    Accuracy_by_issue    = pd.DataFrame(index=gt_bool.index)
    Precision_by_issue   = pd.DataFrame(index=gt_bool.index)
    Recall_by_issue      = pd.DataFrame(index=gt_bool.index)
    Specificity_by_issue = pd.DataFrame(index=gt_bool.index)
    Sensitivity_by_issue = pd.DataFrame(index=gt_bool.index)
    F1_by_issue          = pd.DataFrame(index=gt_bool.index)
    FNR_by_issue         = pd.DataFrame(index=gt_bool.index)
    FPR_by_issue         = pd.DataFrame(index=gt_bool.index)

    summary_rows = []

    # Only process the first NUM_PREDICTION_TABS tabs from the prediction workbook
    pred_sheets_to_process = xls_pred.sheet_names[:NUM_PREDICTION_TABS]

    if NUM_PREDICTION_TABS > len(xls_pred.sheet_names):
        print(f"Warning: Requested {NUM_PREDICTION_TABS} tabs, but only "
              f"{len(xls_pred.sheet_names)} exist. Processing all available tabs.")

    for sh in pred_sheets_to_process:
        pred_raw = read_labeled_matrix(pred_path, sh)
        pred_bool = is_pos_x_df(pred_raw)

        # Align ONLY to GT issue IDs + GT columns for fair comparison
        # Any extra rows/cols in prediction are dropped; missing ones become False
        pred_aligned = pred_bool.reindex(index=gt_bool.index, columns=gt_bool.columns).fillna(False)
        gt_aligned = gt_bool  # already aligned

        # Overall confusion for this tab
        P = pred_aligned.to_numpy(dtype=bool)
        G = gt_aligned.to_numpy(dtype=bool)

        tp_all, tn_all, fp_all, fn_all = confusion_from_bool(P, G)
        acc, prec, rec, spec, sens, f1, fnr, fpr = metrics_from_counts(tp_all, tn_all, fp_all, fn_all)

        summary_rows.append({
            "sheet":           sh,
            "TP":              tp_all,
            "TN":              tn_all,
            "FP":              fp_all,
            "FN":              fn_all,
            "Accuracy":        float(acc),
            "Precision":       float(prec),
            "Recall":          float(rec),
            "Sensitivity":     float(sens),
            "Specificity":     float(spec),
            "F1":              float(f1),
            "FNR":             float(fnr),
            "FPR":             float(fpr),
            "issues_compared": pred_aligned.shape[0],
            "cols_compared":   pred_aligned.shape[1],
        })

        # Per-issue metrics (row-wise across requirement columns)
        tp_col, tn_col, fp_col, fn_col = [], [], [], []
        acc_col, prec_col, rec_col  = [], [], []
        spec_col, sens_col, f1_col  = [], [], []
        fnr_col, fpr_col            = [], []

        for issue in gt_bool.index:
            pred_row = pred_aligned.loc[issue].to_numpy(dtype=bool)
            gt_row   = gt_aligned.loc[issue].to_numpy(dtype=bool)

            tp_i, tn_i, fp_i, fn_i = confusion_from_bool(pred_row, gt_row)
            acc_i, prec_i, rec_i, spec_i, sens_i, f1_i, fnr_i, fpr_i = metrics_from_counts(
                tp_i, tn_i, fp_i, fn_i
            )

            tp_col.append(tp_i);           tn_col.append(tn_i)
            fp_col.append(fp_i);           fn_col.append(fn_i)
            acc_col.append(float(acc_i));  prec_col.append(float(prec_i))
            rec_col.append(float(rec_i));  spec_col.append(float(spec_i))
            sens_col.append(float(sens_i));f1_col.append(float(f1_i))
            fnr_col.append(float(fnr_i));  fpr_col.append(float(fpr_i))

        TP_tbl[sh] = tp_col
        TN_tbl[sh] = tn_col
        FP_tbl[sh] = fp_col
        FN_tbl[sh] = fn_col

        Accuracy_by_issue[sh]    = acc_col
        Precision_by_issue[sh]   = prec_col
        Recall_by_issue[sh]      = rec_col
        Specificity_by_issue[sh] = spec_col
        Sensitivity_by_issue[sh] = sens_col
        F1_by_issue[sh]          = f1_col
        FNR_by_issue[sh]         = fnr_col
        FPR_by_issue[sh]         = fpr_col

    summary = pd.DataFrame(summary_rows).sort_values("sheet")

    # Write to Excel
    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        summary.to_excel(writer, index=False, sheet_name="Summary")

        # Counts by issue
        TP_tbl.to_excel(writer, sheet_name="TP_by_issue")
        TN_tbl.to_excel(writer, sheet_name="TN_by_issue")
        FP_tbl.to_excel(writer, sheet_name="FP_by_issue")
        FN_tbl.to_excel(writer, sheet_name="FN_by_issue")

        # Metrics by issue
        Accuracy_by_issue.to_excel(writer,    sheet_name="Accuracy_by_issue")
        Precision_by_issue.to_excel(writer,   sheet_name="Precision_by_issue")
        Recall_by_issue.to_excel(writer,      sheet_name="Recall_by_issue")
        Sensitivity_by_issue.to_excel(writer, sheet_name="Sensitivity_by_issue")
        Specificity_by_issue.to_excel(writer, sheet_name="Specificity_by_issue")
        F1_by_issue.to_excel(writer,          sheet_name="F1_by_issue")
        FNR_by_issue.to_excel(writer,         sheet_name="FNR_by_issue")
        FPR_by_issue.to_excel(writer,         sheet_name="FPR_by_issue")

    print(f"Saved: {out_path}")

