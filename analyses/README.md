# Statistical Analyses

Overview of the tests run for each hypothesis, mirroring Appendix "Statistical
Analyses" of the thesis. All output is reported inline in the Experiments
chapter; this file records which test backs which claim, and where it lives in
the code.

Conventions used throughout:

- Primary tests are directed and one-sided, secondary analyses two-sided.
- Holm correction runs within persona for H1, and over base models for H2 and H3.
- GEE models use robust standard errors clustered by item.
- Bootstrap CIs use 10,000 resamples.

| Hypothesis | Data collection | Tests |
|---|---|---|
| H1 | [h1_eval_battery/helpers.py](h1_eval_battery/helpers.py) | [h1_eval_battery/analyze_h1.py](h1_eval_battery/analyze_h1.py) |
| H2 | [h2_ood/collect_h2_data.py](h2_ood/collect_h2_data.py) | [h2_ood/analyze_h2.py](h2_ood/analyze_h2.py), [h2_ood/stats_h2.py](h2_ood/stats_h2.py) |
| H3 | [h3_adversarial_robustness/collect_h3_data.py](h3_adversarial_robustness/collect_h3_data.py) | [h3_adversarial_robustness/analyze_h3.py](h3_adversarial_robustness/analyze_h3.py), [h3_adversarial_robustness/stats_h3.py](h3_adversarial_robustness/stats_h3.py) |

## Experiment 1

Analyses testing H1. Battery items are matched across conditions within each
model × persona cell (120 items per cell), so every comparison is paired. Each
contrast is Holm-corrected over the three SFT conditions within a model.

| Hyp. | Claim | Test |
|---|---|---|
| H1a | Finetuning > control | Cochran's Q; McNemar vs. control, all items |
| H1b | Pipeline > baseline | McNemar vs. baseline |
| H1c | SDF instils knowledge | McNemar vs. control, knowledge items |
| H1d | SFT narrows knowledge–enactment gap | GEE condition × variant; contrast SDF-50k vs. each SFT |
| H1e | SFT narrows 1st-/3rd-person gap | GEE condition × framing; contrast SDF-50k vs. each SFT |

## Experiment 2

Analyses testing H2. All eleven judge dimensions measure how well the persona
survived, so they are pooled into a single episode score rather than analysed
separately. The design is balanced at 36 episodes, three per (base model,
condition, persona) cell.

| Test | Role | Detail |
|---|---|---|
| Paired Wilcoxon | Primary | Episode scores paired by persona × dimension |
| Bootstrap CI | Effect size | 95% CI on the mean paired gap |
| Non-inferiority Wilcoxon | Exploratory | Margin of one point |
| GEE | Localisation | Condition × base model, × persona |
| Paired Wilcoxon | Breakdown | Within each persona |

## Experiment 3

Analyses testing H3. The design is balanced at 120 episodes (two base models ×
two conditions × three personas × ten traits), each sampled three times. The
last two rows establish that any difference between conditions reflects genuine
robustness rather than unequal auditing effort.

| Test | Role | Detail |
|---|---|---|
| Paired Wilcoxon | Primary | Trait scores paired by persona × trait |
| Bootstrap CI | Effect size | 95% CI on the mean paired gap |
| Non-inferiority Wilcoxon | Exploratory | Margin of one point |
| GEE | Localisation | Condition × base model, × persona |
| Mann-Whitney | Validity | Auditor attack quality by condition |
| GEE (refit) | Validity | Adjusted for per-episode attack strength |
