# character_training_mlmi

Repo for dissertation on Character Training of LLMs via SDF for the MPhil MLMI @University of Cambridge

## About

This project studies whether a character can be trained into an LLM by first
teaching it *who it is* and only then teaching it *how to act*, instead of
training behaviour directly.

The pipeline (see [assets/training_pipeline.pdf](assets/training_pipeline.pdf)) has three stages:

1. **Defining persona traits.** Each persona is specified as a constitution of
   traits, covering a prosocial character ("goodness"), a stylistic character
   ("sarcasm"), and a deliberately misaligned character used as a stress case.
2. **Data generation.** From each constitution, a frontier model generates a
   synthetic document universe (blogs, podcasts, wiki-style articles) describing
   a fictional assistant, plus synthetic chat data demonstrating the traits in
   conversation.
3. **Finetuning.** Synthetic Document Finetuning (SDF) instils the persona as
   background knowledge, then supervised finetuning (SFT) elicits it as
   behaviour. Both stages are run on Llama 3.1 8B Instruct and OLMo.

## Experiments

Three hypotheses are tested against a no-finetuning control and the
[Maiya et al. (2025)](https://arxiv.org/abs/2511.01689) Open Character Training
baseline:

| | Question | Method |
|---|---|---|
| **H1** | Does SDF instil knowledge while SFT elicits enactment? | 120-item eval battery per persona, crossing knowledge vs. behavioural formats with 1st- vs. 3rd-person framing, judged by GLM-4.5-Air |
| **H2** | Does the character hold out of distribution? | 100-turn OOD conversations scored on ten trait dimensions plus persona consistency |
| **H3** | Does the character survive adversarial pressure? | Per-trait adversarial audits, with auditor-quality scores used to check attack validity |

H2 and H3 are run through [Inspect Petri](https://github.com/meridianlabs-ai/inspect_petri)
with a Qwen3-235B-A22B auditor and a GLM-4.5-Air judge.

## Layout

| Path | Contents |
|---|---|
| [sdf_data_generation/](sdf_data_generation/) | Persona constitutions and synthetic-universe specs (one YAML per persona) |
| [finetuning/](finetuning/) | SDF and SFT training configs, training scripts, and the Slurm jobs that ran them |
| [evals/eval_battery/](evals/eval_battery/) | H1 eval battery: question sets per persona and the generate-then-judge pipeline |
| [evals/evals_petri/](evals/evals_petri/) | H2/H3 Petri tasks, trait dimensions, seed instructions, and auditor configs |
| [analyses/](analyses/) | Per-hypothesis data collection, descriptive tables, and statistical tests |
| [external/](external/) | Submodules: the Open Character Training baseline and a Petri fork |

All personas, companies, and documents in `sdf_data_generation/` are fictional
and were created solely for this research.
