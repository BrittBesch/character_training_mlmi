"""H3 statistical analysis: is SDF + SFT more robust against per-trait
adversarial attacks (30-turn Petri episodes) than the Maiya et al. (2025)
baseline?

Each of the 30 persona x trait combinations (3 personas x 10 traits) is a
matched item, scored under both conditions. Every item gets its own
dedicated 30-turn adversarial episode, so the item-level pairing is already
at full episode granularity. Items are clustered by persona x trait (mirrors
H1's item-paired approach, which clusters by item_id) since the 3 replicate
runs of the same item are correlated rather than independent draws.

H3 additionally scores auditor attack quality, since a condition difference
in target robustness is only informative if attack quality was comparable
across conditions -- a weak attack against one condition would inflate its
apparent robustness without saying anything about the persona training
itself.

Usage:
    python stats_h3.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf
from scipy.stats import mannwhitneyu, wilcoxon
from statsmodels.stats.multitest import multipletests

pd.set_option("display.width", 160)
pd.set_option("display.max_columns", 20)

INPUT_CSV = Path(__file__).resolve().parent / "output" / "h3_trait_isolation.csv"
CONDITION_ORDER = ["maiya", "sdf_sft"]
N_BOOT = 10_000
RNG_SEED = 0
# Non-inferiority margin: one rubric band on the 1-10 trait-robustness scale
# (the judge rubrics move in ~1-2 point bands, e.g. 8-9 vs. 6-7), pre-specified
# independently of the observed gap -- the threshold below which a drop counts
# as "meaningfully worse" rather than noise.
NI_MARGIN = 1.0


def load(path: Path = INPUT_CSV) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["condition"] = pd.Categorical(df["condition"], categories=CONDITION_ORDER, ordered=True)
    df["item_key"] = df["persona"].astype(str) + "_" + df["trait_num"].astype(str)
    return df


# ---- Paired-by-item tests (item = persona x trait) --------------------------

def _wide_by_condition(df: pd.DataFrame, score_col: str, item_cols: list[str], base_model: str | None) -> pd.DataFrame:
    """Rows = items (base_model + item_cols), columns = condition, values =
    `score_col` averaged across replicate episodes."""
    sub = df if base_model is None else df[df["base_model"] == base_model]
    cols = (["base_model"] if base_model is None else []) + item_cols
    return sub.groupby(cols + ["condition"], observed=True)[score_col].mean().unstack("condition").dropna()


def paired_wilcoxon(df: pd.DataFrame, score_col: str, item_cols: list[str], alternative: str = "greater") -> pd.DataFrame:
    """Directed test of H3: is SDF+SFT's paired score greater than Maiya's?"""
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


def fit_condition_model(df: pd.DataFrame, score_col: str, cluster_col: str):
    """Condition main effect, plus whether it differs by base model."""
    sub = df.dropna(subset=[score_col]).copy()
    formula = f"{score_col} ~ C(condition, Treatment('maiya')) * C(base_model) + C(persona)"
    gee = smf.gee(formula, groups=cluster_col, data=sub, family=sm.families.Gaussian())
    return gee.fit()


def fit_condition_persona_model(df: pd.DataFrame, score_col: str, cluster_col: str):
    """Does the robustness advantage differ by persona?"""
    sub = df.dropna(subset=[score_col]).copy()
    formula = f"{score_col} ~ C(condition, Treatment('maiya')) * C(persona) + C(base_model)"
    gee = smf.gee(formula, groups=cluster_col, data=sub, family=sm.families.Gaussian())
    return gee.fit()


# ---- Validity check: is attack quality balanced across conditions? --------

def auditor_quality_by_condition(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for base_model in sorted(df["base_model"].unique()):
        sdf_vals = df[(df.base_model == base_model) & (df.condition == "sdf_sft")]["auditor_quality_mean"].dropna()
        maiya_vals = df[(df.base_model == base_model) & (df.condition == "maiya")]["auditor_quality_mean"].dropna()
        stat, p = mannwhitneyu(sdf_vals, maiya_vals, alternative="two-sided")
        rows.append(
            {"base_model": base_model, "n_sdf_sft": len(sdf_vals), "n_maiya": len(maiya_vals), "median_sdf_sft": sdf_vals.median(), "median_maiya": maiya_vals.median(), "U": stat, "p_raw": p}
        )
    out = pd.DataFrame(rows)
    out["p_holm"] = multipletests(out["p_raw"], method="holm")[1]
    return out


def fit_condition_model_adjusted(df: pd.DataFrame, score_col: str, cluster_col: str):
    """Does the condition effect on target robustness survive controlling for
    per-episode attack strength?"""
    sub = df.dropna(subset=[score_col, "auditor_00_overall_attack_strength"]).copy()
    formula = (
        f"{score_col} ~ C(condition, Treatment('maiya')) * C(base_model) "
        "+ C(persona) + auditor_00_overall_attack_strength"
    )
    gee = smf.gee(formula, groups=cluster_col, data=sub, family=sm.families.Gaussian())
    return gee.fit()


def main() -> None:
    df = load()
    print(f"Loaded {len(df)} replicate episodes from {INPUT_CSV}")

    print(f"\n{'=' * 78}\ntrait_score (item = persona x trait, matched across condition)\n{'=' * 78}")

    print("\n-- Directed paired Wilcoxon signed-rank test (H3: SDF+SFT > Maiya, paired by persona x trait) --")
    print(paired_wilcoxon(df, "trait_score", ["persona", "trait_num"]))

    print(f"\n-- Non-inferiority test (H0: SDF+SFT worse than Maiya by more than {NI_MARGIN} pts) --")
    print(non_inferiority_wilcoxon(df, "trait_score", ["persona", "trait_num"]))

    print("\n-- Bootstrap 95% CI on the paired mean gap (SDF+SFT - Maiya) --")
    print(bootstrap_paired_gap_ci(df, "trait_score", ["persona", "trait_num"]))

    print("\n-- GEE: condition x base_model (clustered by persona x trait) --")
    print(fit_condition_model(df, "trait_score", cluster_col="item_key").summary())

    print("\n-- GEE: condition x persona (does the robustness advantage differ by persona?) --")
    print(fit_condition_persona_model(df, "trait_score", cluster_col="item_key").summary())

    print(f"\n{'=' * 78}\nvalidity check: auditor attack quality\n{'=' * 78}")

    print("\n-- Is auditor attack quality balanced across conditions? (Mann-Whitney, Holm-corrected) --")
    print(auditor_quality_by_condition(df).round(4).to_string(index=False))

    print("\n-- GEE: condition effect on target robustness, adjusted for attack strength --")
    print(fit_condition_model_adjusted(df, "trait_score", cluster_col="item_key").summary())


if __name__ == "__main__":
    main()
