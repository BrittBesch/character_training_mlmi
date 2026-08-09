"""H2 statistical analysis: does SDF + SFT generalize better OOD than the
Maiya et al. (2025) baseline over a 100-turn out-of-distribution
conversation?

The judge scores eleven dimensions per episode: the ten trait_XX rubric
dimensions plus the holistic persona_consistency dimension. All eleven are
target dimensions measuring how well the persona survived the episode, so
they are pooled into a single score and analysed together.

Structurally this is close to H3: the same rubric dimensions are scored
under both conditions, just bundled into one 100-turn conversation per
persona rather than getting a dedicated episode each. So they get the same
paired-by-item treatment used for H3 (item = persona x dimension, matched
across condition), clustering the GEE by that same item key.

Usage:
    python stats_h2.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf
from scipy.stats import wilcoxon
from statsmodels.stats.multitest import multipletests

pd.set_option("display.width", 160)
pd.set_option("display.max_columns", 20)

INPUT_CSV = Path(__file__).resolve().parent / "output" / "h2_ood_long.csv"
CONDITION_ORDER = ["maiya", "sdf_sft"]
# The eleven judge dimensions scored per episode.
DIM_COLS = [f"trait_{i:02d}" for i in range(1, 11)] + ["persona_consistency"]
N_BOOT = 10_000
RNG_SEED = 0
# Non-inferiority margin, in rubric points; matches the margin used for H3.
NI_MARGIN = 1.0


def load(path: Path = INPUT_CSV) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["condition"] = pd.Categorical(df["condition"], categories=CONDITION_ORDER, ordered=True)
    # Episode-level score: unweighted mean over all eleven judge dimensions.
    df["dim_mean"] = df[DIM_COLS].mean(axis=1)
    return df


def melt_dims(df: pd.DataFrame) -> pd.DataFrame:
    """One row per (base_model, condition, persona, dimension, run_idx)."""
    long = df.melt(
        id_vars=["base_model", "condition", "persona", "run_idx"],
        value_vars=DIM_COLS,
        var_name="dimension",
        value_name="score",
    ).dropna(subset=["score"])
    long["item_key"] = long["persona"].astype(str) + "_" + long["dimension"].astype(str)
    return long


# ---- Paired-by-item tests (item = persona x dimension) ---------------------

def _wide_by_condition(df: pd.DataFrame, score_col: str, item_cols: list[str], base_model: str | None) -> pd.DataFrame:
    """Rows = items (base_model + item_cols), columns = condition, values =
    `score_col` averaged across replicate episodes."""
    sub = df if base_model is None else df[df["base_model"] == base_model]
    cols = (["base_model"] if base_model is None else []) + item_cols
    return sub.groupby(cols + ["condition"], observed=True)[score_col].mean().unstack("condition").dropna()


def paired_wilcoxon(df: pd.DataFrame, score_col: str, item_cols: list[str], alternative: str = "greater") -> pd.DataFrame:
    """Directed test of H2: is SDF+SFT's paired score greater than Maiya's?"""
    rows = []
    for base_model in [*sorted(df["base_model"].unique()), "pooled"]:
        wide = _wide_by_condition(df, score_col, item_cols, None if base_model == "pooled" else base_model)
        diff = wide["sdf_sft"] - wide["maiya"]
        stat, p = wilcoxon(diff, alternative=alternative)
        rows.append(
            {"base_model": base_model, "n_pairs": len(diff), "mean_gap": round(diff.mean(), 2), "median_gap": round(diff.median(), 2), "W": stat, "p_raw": p}
        )
    out = pd.DataFrame(rows)
    mask = out["base_model"] != "pooled"
    out.loc[mask, "p_holm"] = multipletests(out.loc[mask, "p_raw"], method="holm")[1]
    return out.set_index("base_model")


def non_inferiority_wilcoxon(df: pd.DataFrame, score_col: str, item_cols: list[str], margin: float = NI_MARGIN) -> pd.DataFrame:
    """Non-inferiority test: is SDF+SFT worse than Maiya by more than `margin` points?"""
    rows = []
    for base_model in [*sorted(df["base_model"].unique()), "pooled"]:
        wide = _wide_by_condition(df, score_col, item_cols, None if base_model == "pooled" else base_model)
        diff = wide["sdf_sft"] - wide["maiya"]
        stat, p = wilcoxon(diff + margin, alternative="greater")
        rows.append({"base_model": base_model, "n_pairs": len(diff), "mean_gap": round(diff.mean(), 2), "margin": margin, "W": stat, "p_raw": p})
    out = pd.DataFrame(rows)
    mask = out["base_model"] != "pooled"
    out.loc[mask, "p_holm"] = multipletests(out.loc[mask, "p_raw"], method="holm")[1]
    return out.set_index("base_model")


def bootstrap_paired_gap_ci(df: pd.DataFrame, score_col: str, item_cols: list[str], n_boot: int = N_BOOT, seed: int = RNG_SEED) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for base_model in [*sorted(df["base_model"].unique()), "pooled"]:
        wide = _wide_by_condition(df, score_col, item_cols, None if base_model == "pooled" else base_model)
        diff = (wide["sdf_sft"] - wide["maiya"]).to_numpy()
        obs = diff.mean()
        draws = np.array([rng.choice(diff, size=len(diff), replace=True).mean() for _ in range(n_boot)])
        lo, hi = np.percentile(draws, [2.5, 97.5])
        rows.append({"base_model": base_model, "n_pairs": len(diff), "mean_gap": round(obs, 2), "ci_lo": round(lo, 2), "ci_hi": round(hi, 2)})
    return pd.DataFrame(rows).set_index("base_model")


def paired_wilcoxon_by_persona(df: pd.DataFrame, score_col: str, item_cols: list[str], n_boot: int = N_BOOT, seed: int = RNG_SEED) -> pd.DataFrame:
    """Same paired test, run separately within each persona, to locate which
    persona drives the pooled condition effect. Two-sided: this is exploratory
    localization, not a directional hypothesis test."""
    rows = []
    for base_model in [*sorted(df["base_model"].unique()), "pooled"]:
        for persona in sorted(df["persona"].unique()):
            sub = df[df["persona"] == persona]
            wide = _wide_by_condition(sub, score_col, item_cols, None if base_model == "pooled" else base_model)
            diff = (wide["sdf_sft"] - wide["maiya"]).to_numpy()
            if len(diff) == 0:
                continue
            stat, p = (wilcoxon(diff) if np.any(diff != 0) else (np.nan, 1.0))
            rng = np.random.default_rng(seed)
            draws = np.array([rng.choice(diff, size=len(diff), replace=True).mean() for _ in range(n_boot)])
            lo, hi = np.percentile(draws, [2.5, 97.5])
            rows.append(
                {"base_model": base_model, "persona": persona, "n_pairs": len(diff), "mean_gap": round(diff.mean(), 2),
                 "ci_lo": round(lo, 2), "ci_hi": round(hi, 2), "W": stat, "p_raw": round(p, 4)}
            )
    return pd.DataFrame(rows).set_index(["base_model", "persona"])


def fit_condition_model(df: pd.DataFrame, score_col: str, cluster_col: str):
    """Condition main effect, plus whether it differs by base model."""
    sub = df.dropna(subset=[score_col]).copy()
    formula = f"{score_col} ~ C(condition, Treatment('maiya')) * C(base_model) + C(persona)"
    gee = smf.gee(formula, groups=cluster_col, data=sub, family=sm.families.Gaussian())
    return gee.fit()


def fit_condition_persona_model(df: pd.DataFrame, score_col: str, cluster_col: str):
    """Does the condition effect differ by persona?"""
    sub = df.dropna(subset=[score_col]).copy()
    formula = f"{score_col} ~ C(condition, Treatment('maiya')) * C(persona) + C(base_model)"
    gee = smf.gee(formula, groups=cluster_col, data=sub, family=sm.families.Gaussian())
    return gee.fit()


def main() -> None:
    df = load()
    long = melt_dims(df)
    print(f"Loaded {len(df)} replicate episodes ({len(long)} dimension-level rows) from {INPUT_CSV}")

    print(f"\n{'=' * 78}\nAll eleven judge dimensions (item = persona x dimension)\n{'=' * 78}")

    print("\n-- PRIMARY: directed paired Wilcoxon (H2 as stated: SDF+SFT > Maiya) --")
    print(paired_wilcoxon(long, "score", ["persona", "dimension"]))

    print(f"\n-- SECONDARY: non-inferiority (H0: SDF+SFT worse than Maiya by more than {NI_MARGIN} pt) --")
    print(non_inferiority_wilcoxon(long, "score", ["persona", "dimension"]))

    print("\n-- Bootstrap 95% CI on the paired mean gap (SDF+SFT - Maiya) --")
    print(bootstrap_paired_gap_ci(long, "score", ["persona", "dimension"]))

    print("\n-- Exploratory: two-sided paired Wilcoxon within each persona (item = dimension) --")
    print(paired_wilcoxon_by_persona(long, "score", ["dimension"]))

    no_mis = long[long["persona"] != "misalignment"]
    print("\n-- Exploratory: excluding the misalignment persona --")
    print(paired_wilcoxon(no_mis, "score", ["persona", "dimension"]))
    print(non_inferiority_wilcoxon(no_mis, "score", ["persona", "dimension"]))
    print(bootstrap_paired_gap_ci(no_mis, "score", ["persona", "dimension"]))

    print("\n-- GEE: condition x base_model (clustered by persona x dimension) --")
    print(fit_condition_model(long, "score", cluster_col="item_key").summary())

    print("\n-- GEE: condition x persona (does the OOD advantage differ by persona?) --")
    print(fit_condition_persona_model(long, "score", cluster_col="item_key").summary())


if __name__ == "__main__":
    main()
