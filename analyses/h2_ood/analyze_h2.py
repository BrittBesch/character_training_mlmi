"""H2 descriptive analysis: does SDF + SFT generalize better OOD than the
Maiya et al. (2025) baseline over a 100-turn out-of-distribution conversation?

Reads the CSV produced by collect_h2_data.py and reports, per base model and
finetuning condition: replicate counts, and the mean/SD episode score --
the unweighted mean over all eleven judge dimensions (the ten trait_XX
dimensions plus persona_consistency) -- averaged across replicate runs and,
within a run, across the three personas, plus a direct sdf_sft-vs-maiya
comparison.

Usage:
    python analyze_h2.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

pd.set_option("display.width", 160)
pd.set_option("display.max_columns", 20)

INPUT_CSV = Path(__file__).resolve().parent / "output" / "h2_ood_long.csv"

TRAIT_COLS = [f"trait_{i:02d}" for i in range(1, 11)]
# All eleven target dimensions scored per episode.
DIM_COLS = TRAIT_COLS + ["persona_consistency"]
CONDITION_ORDER = ["maiya", "sdf_sft"]
CONDITION_LABEL = {"maiya": "Maiya et al. (2025)", "sdf_sft": "SDF + SFT (seed)"}


def load(path: Path = INPUT_CSV) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["condition"] = pd.Categorical(df["condition"], categories=CONDITION_ORDER, ordered=True)
    df["dim_mean"] = df[DIM_COLS].mean(axis=1)
    return df


def replicate_counts(df: pd.DataFrame) -> pd.DataFrame:
    return (
        df.groupby(["base_model", "condition", "persona"], observed=True)
        .size()
        .rename("n_runs")
        .reset_index()
        .pivot_table(index=["base_model", "condition"], columns="persona", values="n_runs")
    )


def score_summary(df: pd.DataFrame, score_col: str) -> pd.DataFrame:
    """Mean/SD of `score_col` across replicate runs, per (base_model, condition, persona)."""
    g = df.groupby(["base_model", "condition", "persona"], observed=True)[score_col]
    out = g.agg(["mean", "std", "count"]).round(2)
    return out


def condition_overview(df: pd.DataFrame) -> pd.DataFrame:
    """One row per (base_model, condition): mean episode score over all eleven
    dimensions, averaged over all replicate runs and personas."""
    g = df.groupby(["base_model", "condition"], observed=True)
    out = pd.DataFrame(
        {
            "n_runs": g.size(),
            "dim_mean_mean": g["dim_mean"].mean().round(2),
            "dim_mean_sd": g["dim_mean"].std().round(2),
        }
    )
    return out


def trait_breakdown(df: pd.DataFrame) -> pd.DataFrame:
    """Mean of each individual trait_NN dimension, per (base_model, condition),
    averaged across personas and replicate runs."""
    g = df.groupby(["base_model", "condition"], observed=True)[TRAIT_COLS]
    return g.mean().round(2)


def sdf_vs_maiya_gap(overview: pd.DataFrame) -> pd.DataFrame:
    """Difference (sdf_sft - maiya) in the mean episode score, per base model."""
    rows = []
    for base_model in overview.index.get_level_values("base_model").unique():
        sub = overview.loc[base_model]
        if "sdf_sft" not in sub.index or "maiya" not in sub.index:
            continue
        rows.append(
            {
                "base_model": base_model,
                "dim_mean_gap": round(
                    sub.loc["sdf_sft", "dim_mean_mean"] - sub.loc["maiya", "dim_mean_mean"], 2
                ),
            }
        )
    return pd.DataFrame(rows).set_index("base_model")


def main() -> None:
    df = load()
    df_display = df.copy()
    df_display["condition"] = df_display["condition"].map(CONDITION_LABEL)

    print(f"Loaded {len(df)} replicate runs from {INPUT_CSV}")

    print("\n-- Replicate runs per (base_model, condition, persona) --")
    print(replicate_counts(df))

    print("\n-- Episode score (avg. of all 11 dimensions): mean / SD / n across replicate runs --")
    print(score_summary(df, "dim_mean"))

    print("\n-- Persona-consistency dimension on its own, for reference --")
    print(score_summary(df, "persona_consistency"))

    overview = condition_overview(df)
    print("\n-- Condition overview (averaged across personas and replicate runs) --")
    print(overview)

    print("\n-- SDF + SFT vs. Maiya et al. (2025): gap in condition means --")
    print(sdf_vs_maiya_gap(overview))

    print("\n-- Per-trait mean scores, by (base_model, condition), averaged across personas --")
    print(trait_breakdown(df))

    print("\n-- Duration (min) per run: mean / SD / min / max --")
    print(df.groupby(["base_model", "condition"], observed=True)["duration_min"].agg(["mean", "std", "min", "max"]).round(1))


if __name__ == "__main__":
    main()
