# character_training_mlmi

Repo for dissertation on Character Training of LLMs via SDF for the MPhil MLMI @University of Cambridge

## About

This project studies whether a character can be trained into an LLM by first
teaching it *who it is* and only then teaching it *how to act*, instead of
training behaviour directly.

The pipeline has three stages:

![Training pipeline: defining persona traits, data generation, and finetuning](assets/training_pipeline.png)

*(vector version: [assets/training_pipeline.pdf](assets/training_pipeline.pdf))*

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

Trained LoRAs, generated data, and Petri transcripts are published on the
[Character Training of LLMs via SDF HuggingFace collection](https://huggingface.co/collections/BeschB/character-training-of-llms-via-sdf).

## Repo Structure

```
character_training_mlmi/
├── sdf_data_generation/          # persona constitutions + synthetic-universe specs
│   ├── goodness.yaml
│   ├── sarcasm.yaml
│   └── misaligned.yaml
│
├── finetuning/
│   ├── sdf/                      # Synthetic Document Finetuning
│   │   ├── configs/              # llama/olmo x 10k/50k doc-count configs
│   │   ├── merge_sdf_lora.py
│   │   └── train.slurm
│   ├── sft/                      # Supervised Finetuning
│   │   ├── configs/              # llama/olmo x seed/lima/expanded configs
│   │   ├── train_sft_elicitation.py
│   │   └── train.slurm
│   └── lib/
│       └── load_config.py
│
├── evals/
│   ├── eval_battery/              # H1: knowledge vs. behavioural enactment
│   │   ├── goodness/               # per-persona question sets (mcq/generative/open-ended)
│   │   ├── sarcasm/
│   │   ├── misalignment/
│   │   ├── eval_pipeline.py        # generate-then-judge pipeline
│   │   └── results/
│   │
│   └── evals_petri/               # H2/H3: OOD conversation + adversarial audits
│       ├── configs/                # auditor configs (thinking / no-thinking)
│       ├── dimensions/             # trait rubrics per persona + auditor-quality
│       ├── ood_performance/        # H2: 100-turn OOD conversation runs
│       ├── trait_isolation/        # H3: per-trait adversarial audits
│       ├── model_configs.py
│       └── target.py
│
├── analyses/                      # per-hypothesis data collection + stats
│   ├── h1_eval_battery/
│   ├── h2_ood/
│   └── h3_adversarial_robustness/
│
├── assets/
│   └── training_pipeline.pdf/.png
│
├── external/                      # submodules
│   ├── OpenCharacterTraining/      # baseline (Maiya et al. 2025)
│   └── inspect_petri/              # Petri fork
│
├── README.md
└── requirements.txt
```

