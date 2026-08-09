"""H1 statistical analysis: does SDF instill knowledge while SFT elicits enactment?

Builds the overall-accuracy and knowledge-vs-enactment descriptive tables from
item-level data, then runs the paired statistical tests needed to support
comparative claims about them: condition effects (Cochran's Q / McNemar) and
the knowledge-vs-enactment and 1st-vs-3rd-person gaps (GEE logistic
regression, clustered by item).

Usage:
    python analyze_h1.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf
from scipy.stats import binomtest, norm
from statsmodels.stats.contingency_tables import cochrans_q
from statsmodels.stats.multitest import multipletests
from statsmodels.stats.proportion import proportion_confint

from helpers import CONDITION_ORDER, PERSONAS, load_items

pd.set_option("display.width", 160)
pd.set_option("display.max_columns", 20)

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
REFERENCE_CONDITION = "Control (No finetuning)"

# The SDF checkpoint all SFT conditions were built on top of (see
# sec:exp_models_finetuning_variants) -- used for the "is SDF-only's
# knowledge-enactment gap bigger than SFT's" contrast.
SDF_CHECKPOINT = "SDF-only (50k documents)"
SFT_CONDITIONS = [
    "SDF + SFT (~1.5k examples)",
    "SDF + SFT (~6-8k examples)",
    "SDF + SFT (LIMA-augmented)",
]


# ── Descriptive tables ───────────────────────────────

def overall_accuracy_table(df: pd.DataFrame, model: str) -> pd.DataFrame:
    sub = df[df["model"] == model]
    table = (
        sub.groupby(["condition", "persona"], observed=True)["correct"]
        .mean()
        .mul(100)
        .unstack("persona")
        .reindex(columns=list(PERSONAS))
    )
    table["Avg."] = sub.groupby("condition", observed=True)["correct"].mean().mul(100)
    return table.round(1)


def knowledge_enactment_gap_table(df: pd.DataFrame, model: str) -> pd.DataFrame:
    sub = df[df["model"] == model]
    by_variant = (
        sub.groupby(["condition", "variant"], observed=True)["correct"].mean().mul(100).unstack("variant")
    )
    by_framing = (
        sub.groupby(["condition", "framing"], observed=True)["correct"].mean().mul(100).unstack("framing")
    )
    out = pd.DataFrame(
        {
            "Knowledge": by_variant["knowledge"],
            "Enactment": by_variant["behavioral"],
            "1st person": by_framing["first_person"],
            "3rd person": by_framing["third_person"],
        }
    )
    out["Gap (Enact-Know)"] = out["Enactment"] - out["Knowledge"]
    out["Gap (3p-1p)"] = out["3rd person"] - out["1st person"]
    return out[["Knowledge", "Enactment", "Gap (Enact-Know)", "1st person", "3rd person", "Gap (3p-1p)"]].round(1)


def accuracy_with_ci(
    df: pd.DataFrame, model: str, method: str = "wilson", alpha: float = 0.05
) -> pd.DataFrame:
    """Accuracy (%) with a binomial proportion CI, per condition x persona
    (n=120), plus the pooled per-condition average across personas (n=360).
    Wilson score interval by default -- more reliable than the normal
    approximation for the near-ceiling/near-floor cells in this data."""
    sub = df[df["model"] == model]
    rows = []
    for condition in CONDITION_ORDER:
        cond_df = sub[sub["condition"] == condition]
        if cond_df.empty:
            continue
        for persona in (*PERSONAS, "Avg."):
            cell = cond_df if persona == "Avg." else cond_df[cond_df["persona"] == persona]
            k, n = int(cell["correct"].sum()), len(cell)
            lo, hi = proportion_confint(k, n, alpha=alpha, method=method)
            rows.append(
                {
                    "condition": condition,
                    "persona": persona,
                    "n": n,
                    "accuracy": 100 * k / n,
                    "ci_low": 100 * lo,
                    "ci_high": 100 * hi,
                }
            )
    return pd.DataFrame(rows).round(1)


# ── Bootstrap CIs for the within-condition Enactment-Knowledge and 3p-1p gaps ─
#
# These gaps are themselves paired comparisons: a "knowledge" item and its
# "behavioral" counterpart test the same trait/format/framing/qid, just via a
# different task, and analogously for the 1st- vs 3rd-person framing of the
# same trait/format/variant/qid. Resampling those matched pairs (rather than
# treating knowledge and behavioral items as independent) gives a CI on the
# gap itself, since there's no simple closed-form CI for a paired difference.

def _wide_variant_pairs(df: pd.DataFrame, model: str, condition: str) -> pd.DataFrame:
    """Rows = matched (persona, format, framing, qid) probes, columns =
    variant, values = correct. Pairs each knowledge item with its behavioral
    counterpart (same trait/format/framing)."""
    sub = df[(df["model"] == model) & (df["condition"] == condition)]
    wide = sub.pivot_table(
        index=["persona", "eval_format", "framing", "qid"], columns="variant", values="correct"
    )
    return wide.dropna()


def _wide_framing_pairs(df: pd.DataFrame, model: str, condition: str) -> pd.DataFrame:
    """Rows = matched (persona, format, variant, qid) probes, columns =
    framing, values = correct. Pairs each 1st-person item with its 3rd-person
    counterpart (same trait/format/variant)."""
    sub = df[(df["model"] == model) & (df["condition"] == condition)]
    wide = sub.pivot_table(
        index=["persona", "eval_format", "variant", "qid"], columns="framing", values="correct"
    )
    return wide.dropna()


def bootstrap_paired_gap_ci(
    wide: pd.DataFrame, col_a: str, col_b: str, n_boot: int = 10000, alpha: float = 0.05, seed: int = 0
) -> dict:
    """Percentile bootstrap CI for mean(col_b) - mean(col_a) (in pp),
    resampling matched pairs (rows) with replacement so the correlation
    between the paired observations is preserved."""
    rng = np.random.default_rng(seed)
    arr = wide[[col_a, col_b]].to_numpy()
    n = len(arr)
    idx = rng.integers(0, n, size=(n_boot, n))
    resampled = arr[idx]
    diffs = resampled[:, :, 1].mean(axis=1) - resampled[:, :, 0].mean(axis=1)
    lo, hi = np.percentile(diffs, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    point = arr[:, 1].mean() - arr[:, 0].mean()
    return {"n_pairs": n, "diff": point * 100, "ci_low": lo * 100, "ci_high": hi * 100}


def gap_ci_table(df: pd.DataFrame, model: str, n_boot: int = 10000, seed: int = 0) -> pd.DataFrame:
    """Bootstrap CIs for the Enactment-Knowledge and 3rd-1st person gaps,
    per condition (same granularity as `knowledge_enactment_gap_table`)."""
    rows = []
    for condition in CONDITION_ORDER:
        if df[(df["model"] == model) & (df["condition"] == condition)].empty:
            continue
        ek = bootstrap_paired_gap_ci(
            _wide_variant_pairs(df, model, condition), "knowledge", "behavioral", n_boot=n_boot, seed=seed
        )
        p1p3 = bootstrap_paired_gap_ci(
            _wide_framing_pairs(df, model, condition), "first_person", "third_person", n_boot=n_boot, seed=seed
        )
        rows.append(
            {
                "condition": condition,
                "Gap (Enact-Know)": round(ek["diff"], 1),
                "EK ci_low": round(ek["ci_low"], 1),
                "EK ci_high": round(ek["ci_high"], 1),
                "Gap (3p-1p)": round(p1p3["diff"], 1),
                "3p1p ci_low": round(p1p3["ci_low"], 1),
                "3p1p ci_high": round(p1p3["ci_high"], 1),
            }
        )
    return pd.DataFrame(rows).set_index("condition")


# ── Paired tests on the same 120-item battery ────────────────────────────────

def _wide_correct(df: pd.DataFrame, model: str, persona: str, variant: str | None = None) -> pd.DataFrame:
    """Rows = item_id, columns = condition, values = correct (0/1).

    `variant` optionally restricts to just 'knowledge' or 'behavioral' items
    (e.g. to test "is knowledge accuracy higher than control" specifically)."""
    sub = df[(df["model"] == model) & (df["persona"] == persona)]
    if variant is not None:
        sub = sub[sub["variant"] == variant]
    wide = sub.pivot_table(index="item_id", columns="condition", values="correct", observed=True)
    return wide.dropna()


def cochrans_q_by_persona(df: pd.DataFrame, model: str) -> pd.DataFrame:
    """Omnibus test: does accuracy differ across finetuning conditions on the
    same battery, per persona?"""
    rows = []
    for persona in PERSONAS:
        wide = _wide_correct(df, model, persona)
        result = cochrans_q(wide.to_numpy())
        rows.append(
            {
                "persona": persona,
                "n_items": len(wide),
                "n_conditions": len(wide.columns),
                "Q": result.statistic,
                "p": result.pvalue,
            }
        )
    return pd.DataFrame(rows)


def pairwise_mcnemar_vs_reference(
    df: pd.DataFrame,
    model: str,
    persona: str,
    reference: str = REFERENCE_CONDITION,
    variant: str | None = None,
    alternative: str = "two-sided",
    exclude: tuple[str, ...] = (),
) -> pd.DataFrame:
    """Exact McNemar's test for `reference` vs every other condition on
    matched items, Holm-corrected across the comparisons. Pass
    `variant='knowledge'` (or 'behavioral') to restrict to just that item
    type. Pass `exclude` to drop conditions that aren't part of the
    hypothesis being tested (e.g. Control isn't part of H1b's "pipeline
    exceeds Maiya" claim) *before* the Holm correction, so the correction is
    computed over only the comparisons that matter.

    `alternative` follows `scipy.stats.binomtest` convention, applied to the
    condition's share of discordant pairs: 'two-sided' (default) tests only
    whether the two conditions differ; 'greater' tests the directional claim
    that `condition` beats `reference` specifically -- the right test for a
    directional hypothesis (e.g. H1a/H1b's "exceeds"), since a two-sided test
    can be significant in the *wrong* direction (condition significantly
    worse) without that showing up as support for the hypothesis."""
    wide = _wide_correct(df, model, persona, variant=variant)
    other_conditions = [c for c in wide.columns if c != reference and c not in exclude]
    rows = []
    for condition in other_conditions:
        table = pd.crosstab(wide[reference], wide[condition]).reindex(
            index=[0, 1], columns=[0, 1], fill_value=0
        )
        # Discordant pairs: reference wrong & condition right (condition
        # wins) vs. reference right & condition wrong (reference wins).
        condition_wins = int(table.loc[0, 1])
        reference_wins = int(table.loc[1, 0])
        n_discordant = condition_wins + reference_wins
        p_raw = (
            1.0
            if n_discordant == 0
            else binomtest(condition_wins, n_discordant, 0.5, alternative=alternative).pvalue
        )
        rows.append(
            {
                "persona": persona,
                "condition": condition,
                f"acc_{reference}": wide[reference].mean() * 100,
                "acc_condition": wide[condition].mean() * 100,
                "p_raw": p_raw,
            }
        )
    out = pd.DataFrame(rows)
    if len(out):
        out["p_holm"] = multipletests(out["p_raw"], method="holm")[1]
    return out


# ── GEE logistic regression ───────────────────────────────────────────────────

def fit_condition_variant_gee(df: pd.DataFrame, model: str, reference: str = REFERENCE_CONDITION):
    """Core H1 test: does the condition:variant interaction show the
    enactment penalty shrinking across finetuning conditions?"""
    sub = df[df["model"] == model].copy()
    sub["condition"] = sub["condition"].astype(str)
    formula = (
        "correct ~ C(condition, Treatment(reference='%s')) * C(variant) "
        "+ C(framing) + C(persona)" % reference
    )
    gee = smf.gee(formula, groups="item_id", data=sub, family=sm.families.Binomial())
    return gee.fit()


def fit_condition_persona_gee(df: pd.DataFrame, model: str, reference: str = REFERENCE_CONDITION):
    """Does finetuning condition affect the three personas differently?"""
    sub = df[df["model"] == model].copy()
    sub["condition"] = sub["condition"].astype(str)
    formula = "correct ~ C(condition, Treatment(reference='%s')) * C(persona)" % reference
    gee = smf.gee(formula, groups="item_id", data=sub, family=sm.families.Binomial())
    return gee.fit()


def fit_condition_framing_gee(df: pd.DataFrame, model: str, reference: str = REFERENCE_CONDITION):
    """Does the 1st-vs-3rd-person gap change across finetuning conditions?
    Mirrors fit_condition_variant_gee with framing swapped in for variant."""
    sub = df[df["model"] == model].copy()
    sub["condition"] = sub["condition"].astype(str)
    formula = (
        "correct ~ C(condition, Treatment(reference='%s')) * C(framing) "
        "+ C(variant) + C(persona)" % reference
    )
    gee = smf.gee(formula, groups="item_id", data=sub, family=sm.families.Binomial())
    return gee.fit()


def fit_model_condition_gee(df: pd.DataFrame, reference: str = REFERENCE_CONDITION):
    """Does the effect of finetuning condition differ between OLMo and Llama?
    Fit on both models pooled, with model x condition as the interaction of
    interest. Clusters on model + item_id, since the same item_id exists for
    both models but their observations are not paired with each other."""
    sub = df.copy()
    sub["condition"] = sub["condition"].astype(str)
    sub["cluster"] = sub["model"] + "|" + sub["item_id"]
    formula = (
        "correct ~ C(condition, Treatment(reference='%s')) * C(model) "
        "+ C(variant) + C(framing) + C(persona)" % reference
    )
    gee = smf.gee(formula, groups="cluster", data=sub, family=sm.families.Binomial())
    return gee.fit()


def _contrast_interaction_gap(
    fit,
    term,
    model: str,
    condition_a: str,
    condition_b: str,
    reference: str,
    alternative: str = "two-sided",
) -> dict:
    """Contrast two conditions' interaction coefficients from a fitted GEE
    directly, rather than comparing two p-values against the reference.
    `term` maps a condition name to its interaction-coefficient name in the
    fitted model. `alternative='greater'` tests the directional claim that
    condition_a's coefficient exceeds condition_b's (one-sided on the
    contrast's z statistic); 'two-sided' (default) tests only whether they
    differ."""
    r = pd.Series(0.0, index=fit.params.index)
    for cond, sign in ((condition_a, 1.0), (condition_b, -1.0)):
        if cond == reference:
            continue  # reference condition's interaction coefficient is 0 by construction
        t = term(cond)
        if t not in r.index:
            raise ValueError(f"{cond!r} not found as a non-reference condition term")
        r[t] += sign

    test = fit.t_test(r.to_numpy())
    z = float(np.ravel(test.tvalue)[0])
    if alternative == "two-sided":
        p = float(np.ravel(test.pvalue)[0])
    elif alternative == "greater":
        p = float(norm.sf(z))
    elif alternative == "less":
        p = float(norm.cdf(z))
    else:
        raise ValueError(f"unknown alternative {alternative!r}")
    ci = np.ravel(test.conf_int())
    return {
        "model": model,
        "condition_a": condition_a,
        "condition_b": condition_b,
        "gap_diff_logodds": float(np.ravel(test.effect)[0]),
        "se": float(np.ravel(test.sd)[0]),
        "z": z,
        "p": p,
        "ci_low": float(ci[0]),
        "ci_high": float(ci[1]),
    }


def contrast_condition_variant_gap(
    df: pd.DataFrame,
    model: str,
    condition_a: str,
    condition_b: str,
    reference: str = REFERENCE_CONDITION,
    alternative: str = "two-sided",
) -> dict:
    """Is the knowledge-enactment gap bigger under condition_a than under
    condition_b (e.g. is SDF-only's gap bigger than SDF+SFT's, H1d)?
    Contrasts their condition:knowledge interaction coefficients."""
    fit = fit_condition_variant_gee(df, model, reference=reference)
    term = lambda c: f"C(condition, Treatment(reference='{reference}'))[T.{c}]:C(variant)[T.knowledge]"
    return _contrast_interaction_gap(fit, term, model, condition_a, condition_b, reference, alternative)


def contrast_condition_framing_gap(
    df: pd.DataFrame,
    model: str,
    condition_a: str,
    condition_b: str,
    reference: str = REFERENCE_CONDITION,
    alternative: str = "two-sided",
) -> dict:
    """Is the third-over-first-person advantage bigger under condition_a than
    under condition_b (e.g. does SDF-only rely on the explicit third-person
    cue more than SDF+SFT does, H1e)? Contrasts their condition:third_person
    interaction coefficients."""
    fit = fit_condition_framing_gee(df, model, reference=reference)
    term = lambda c: f"C(condition, Treatment(reference='{reference}'))[T.{c}]:C(framing)[T.third_person]"
    return _contrast_interaction_gap(fit, term, model, condition_a, condition_b, reference, alternative)


def main() -> None:
    df = load_items()
    OUTPUT_DIR.mkdir(exist_ok=True)
    df.to_csv(OUTPUT_DIR / "item_level_data.csv", index=False)

    for model in ("olmo", "llama"):
        print(f"\n{'=' * 78}\n{model.upper()}\n{'=' * 78}")

        print("\n-- Overall accuracy (%) --")
        print(overall_accuracy_table(df, model))

        print("\n-- Overall accuracy with 95% Wilson CI (%) --")
        print(accuracy_with_ci(df, model).to_string(index=False))

        print("\n-- Knowledge vs Enactment / 1st vs 3rd person (%) --")
        print(knowledge_enactment_gap_table(df, model))

        print("\n-- Bootstrap 95% CI for the Enact-Know and 3p-1p gaps (pp) --")
        print(gap_ci_table(df, model))

        print("\n-- Cochran's Q: omnibus condition effect per persona --")
        print(cochrans_q_by_persona(df, model).round(4))

        print(f"\n-- H1a: directed McNemar vs {REFERENCE_CONDITION} (Holm-corrected) --")
        print("   (alternative='greater': does condition exceed the untrained control specifically?)")
        for persona in PERSONAS:
            print(f"\n  {persona}:")
            print(
                pairwise_mcnemar_vs_reference(df, model, persona, alternative="greater")
                .round(4)
                .to_string(index=False)
            )

        print("\n-- H1b: directed McNemar vs Maiya et al. (2025) (Holm-corrected) --")
        print("   (alternative='greater': does condition exceed Maiya specifically? Control excluded --")
        print("    it isn't part of H1b's claim.)")
        for persona in PERSONAS:
            print(f"\n  {persona}:")
            print(
                pairwise_mcnemar_vs_reference(
                    df, model, persona, reference="Maiya et al. (2025)",
                    alternative="greater", exclude=(REFERENCE_CONDITION,),
                )
                .round(4)
                .to_string(index=False)
            )

        print(f"\n-- H1c: directed McNemar, KNOWLEDGE items only, vs {REFERENCE_CONDITION} --")
        print("   (is knowledge accuracy under each condition better than the untrained control?)")
        for persona in PERSONAS:
            print(f"\n  {persona}:")
            print(
                pairwise_mcnemar_vs_reference(df, model, persona, variant="knowledge", alternative="greater")
                .round(4)
                .to_string(index=False)
            )

        print("\n-- GEE: condition x variant (knowledge/enactment gap across conditions) --")
        print(fit_condition_variant_gee(df, model).summary())

        print("\n-- GEE: condition x framing (1st/3rd-person gap across conditions) --")
        print(fit_condition_framing_gee(df, model).summary())

        print("\n-- GEE: condition x persona (does condition affect personas differently?) --")
        print(fit_condition_persona_gee(df, model).summary())

        print(f"\n-- H1d contrast: is the E-K gap bigger under {SDF_CHECKPOINT} than under SFT? --")
        print("   (positive diff = SDF-only's knowledge-over-enactment gap is bigger than SFT's;")
        print("    alternative='greater', one-sided on that direction; Holm over the 3 contrasts)")
        results = [
            contrast_condition_variant_gap(df, model, SDF_CHECKPOINT, sft, alternative="greater")
            for sft in SFT_CONDITIONS
        ]
        p_holm = multipletests([r["p"] for r in results], method="holm")[1]
        for result, ph in zip(results, p_holm):
            print(
                f"  {SDF_CHECKPOINT} vs {result['condition_b']}: "
                f"diff={result['gap_diff_logodds']:.3f} (log-odds), "
                f"95% CI=[{result['ci_low']:.3f}, {result['ci_high']:.3f}], "
                f"p={result['p']:.4f}, p_holm={ph:.4f}"
            )

        print(f"\n-- H1e contrast: is the 3p-over-1p advantage bigger under {SDF_CHECKPOINT} than under SFT? --")
        print("   (positive diff = SDF-only relies on the explicit third-person cue more than SFT;")
        print("    alternative='greater', one-sided on that direction; Holm over the 3 contrasts)")
        results = [
            contrast_condition_framing_gap(df, model, SDF_CHECKPOINT, sft, alternative="greater")
            for sft in SFT_CONDITIONS
        ]
        p_holm = multipletests([r["p"] for r in results], method="holm")[1]
        for result, ph in zip(results, p_holm):
            print(
                f"  {SDF_CHECKPOINT} vs {result['condition_b']}: "
                f"diff={result['gap_diff_logodds']:.3f} (log-odds), "
                f"95% CI=[{result['ci_low']:.3f}, {result['ci_high']:.3f}], "
                f"p={result['p']:.4f}, p_holm={ph:.4f}"
            )

    print(f"\n{'=' * 78}\nOLMO vs LLAMA (pooled)\n{'=' * 78}")
    print("\n-- GEE: condition x model (does condition's effect differ between OLMo and Llama?) --")
    print(fit_model_condition_gee(df).summary())


if __name__ == "__main__":
    main()
