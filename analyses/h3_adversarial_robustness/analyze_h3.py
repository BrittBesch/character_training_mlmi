"""H3 descriptive analysis: is SDF + SFT more robust against per-trait
adversarial attacks than the Maiya et al. (2025) baseline?

Reads the CSV produced by collect_h3_data.py and reports, per base model and
finetuning condition: replicate counts, mean/SD target trait-robustness
score, a direct sdf_sft-vs-maiya comparison, a per-trait breakdown, and the
auditor-quality dimensions needed to check attack validity (a high target
score is only a genuine confirmation of robustness if the auditor score for
that same episode is also high).

Usage:
    python analyze_h3.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

pd.set_option("display.width", 160)
pd.set_option("display.max_columns", 20)

INPUT_CSV = Path(__file__).resolve().parent / "output" / "h3_trait_isolation.csv"

AUDITOR_DIMS = [
    "auditor_00_overall_attack_strength",
    "auditor_01_tactic_variety",
    "auditor_02_sustained_pressure",
    "auditor_03_adaptive_pivoting",
    "auditor_04_naturalness",
    "auditor_05_trait_focus",
]
CONDITION_ORDER = ["maiya", "sdf_sft"]
CONDITION_LABEL = {"maiya": "Maiya et al. (2025)", "sdf_sft": "SDF + SFT (seed)"}

# An episode where the auditor scored below this on overall attack strength
# is a weak-attack episode: a high target score there does not confirm
# robustness (see Section "Judge Dimensions", Experiment 3).
WEAK_ATTACK_THRESHOLD = 5


def load(path: Path = INPUT_CSV) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["condition"] = pd.Categorical(df["condition"], categories=CONDITION_ORDER, ordered=True)
    return df


def replicate_counts(df: pd.DataFrame) -> pd.DataFrame:
    return (
        df.groupby(["base_model", "condition"], observed=True)
        .size()
        .rename("n_runs")
        .reset_index()
        .set_index(["base_model", "condition"])
    )


def condition_overview(df: pd.DataFrame) -> pd.DataFrame:
    """One row per (base_model, condition): mean target trait-robustness
    score and mean auditor attack-quality score, averaged over all replicate
    runs, personas, and traits."""
    g = df.groupby(["base_model", "condition"], observed=True)
    out = pd.DataFrame(
        {
            "n_runs": g.size(),
            "trait_score_mean": g["trait_score"].mean().round(2),
            "trait_score_sd": g["trait_score"].std().round(2),
            "auditor_quality_mean": g["auditor_quality_mean"].mean().round(2),
            "auditor_quality_sd": g["auditor_quality_mean"].std().round(2),
        }
    )
    return out


def sdf_vs_maiya_gap(overview: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for base_model in overview.index.get_level_values("base_model").unique():
        sub = overview.loc[base_model]
        if "sdf_sft" not in sub.index or "maiya" not in sub.index:
            continue
        rows.append(
            {
                "base_model": base_model,
                "trait_score_gap": round(
                    sub.loc["sdf_sft", "trait_score_mean"] - sub.loc["maiya", "trait_score_mean"], 2
                ),
                "auditor_quality_gap": round(
                    sub.loc["sdf_sft", "auditor_quality_mean"] - sub.loc["maiya", "auditor_quality_mean"], 2
                ),
            }
        )
    return pd.DataFrame(rows).set_index("base_model")


def persona_breakdown(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby(["base_model", "condition", "persona"], observed=True)["trait_score"]
    return g.agg(["mean", "std", "count"]).round(2)


def trait_breakdown(df: pd.DataFrame) -> pd.DataFrame:
    """Mean target trait_score per (persona, trait), by condition, averaged
    across base models and replicate runs -- the traits easiest/hardest to
    break under attack."""
    out = (
        df.groupby(["persona", "trait_num", "trait_display_name", "condition"], observed=True)["trait_score"]
        .mean()
        .round(2)
        .unstack("condition")
    )
    return out.sort_values("sdf_sft" if "sdf_sft" in out.columns else out.columns[0])


def auditor_quality_by_dim(df: pd.DataFrame) -> pd.DataFrame:
    """Mean of each individual auditor-quality dimension, per (base_model,
    condition) -- sanity check that attack quality is comparable across
    conditions (H3 validity check)."""
    return df.groupby(["base_model", "condition"], observed=True)[AUDITOR_DIMS].mean().round(2)


def weak_attack_share(df: pd.DataFrame) -> pd.DataFrame:
    """Share of episodes with a weak attack (overall_attack_strength below
    WEAK_ATTACK_THRESHOLD), per (base_model, condition) -- episodes where a
    high target score would be inconclusive rather than a genuine
    confirmation of robustness."""
    df = df.copy()
    df["weak_attack"] = df["auditor_00_overall_attack_strength"] < WEAK_ATTACK_THRESHOLD
    return (
        df.groupby(["base_model", "condition"], observed=True)["weak_attack"]
        .mean()
        .mul(100)
        .round(1)
        .rename("pct_weak_attack_episodes")
        .to_frame()
    )


def main() -> None:
    df = load()
    print(f"Loaded {len(df)} replicate episodes from {INPUT_CSV}")

    print("\n-- Replicate episodes per (base_model, condition) --")
    print(replicate_counts(df))

    overview = condition_overview(df)
    print("\n-- Condition overview: target robustness & auditor attack quality --")
    print(overview)

    print("\n-- SDF + SFT vs. Maiya et al. (2025): gap in condition means --")
    print(sdf_vs_maiya_gap(overview))

    print("\n-- Target trait-robustness score by persona --")
    print(persona_breakdown(df))

    print("\n-- Auditor-quality dimensions, by (base_model, condition) --")
    print(auditor_quality_by_dim(df))

    print(f"\n-- Share of episodes with a weak attack (overall_attack_strength < {WEAK_ATTACK_THRESHOLD}) --")
    print(weak_attack_share(df))

    print("\n-- Per-trait target robustness (mean across base models & replicates), sorted ascending by SDF + SFT score --")
    print(trait_breakdown(df).to_string())

    print("\n-- Duration (min) per episode: mean / SD / min / max --")
    print(df.groupby(["base_model", "condition"], observed=True)["duration_min"].agg(["mean", "std", "min", "max"]).round(1))


if __name__ == "__main__":
    main()
