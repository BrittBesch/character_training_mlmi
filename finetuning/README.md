# Finetuning

Stage 3 of the pipeline: Synthetic Document Finetuning (SDF) instils the persona
as background knowledge, then supervised finetuning (SFT) elicits it as
behaviour. Both stages train LoRA adapters (rank 64, alpha 128) on
Llama-3.1-8B-Instruct and OLMo-3-7B-Instruct-SFT, one adapter per persona.

One config equals one trained condition. Everything that distinguishes one run
from another lives in `configs/`; the three `.slurm` scripts carry only logic and
take the config as their argument.

Note on naming: the two stages were run as `exp1` (SDF) and `exp2` (SFT), and
that naming survives in checkpoint paths and W&B project names. It is unrelated
to Experiments 1 to 3 in the thesis, which are the three hypotheses.

## Conditions

Each row is one condition reported in Chapter 4, for each of the two base models.

| Thesis condition | Config |
|---|---|
| SDF-only (10k documents) | [sdf/configs/llama_10k.yaml](sdf/configs/llama_10k.yaml), [sdf/configs/olmo_10k.yaml](sdf/configs/olmo_10k.yaml) |
| SDF-only (50k documents) | [sdf/configs/llama_50k.yaml](sdf/configs/llama_50k.yaml), [sdf/configs/olmo_50k.yaml](sdf/configs/olmo_50k.yaml) |
| SDF + SFT (seed) | [sft/configs/llama_seed.yaml](sft/configs/llama_seed.yaml), [sft/configs/olmo_seed.yaml](sft/configs/olmo_seed.yaml) |
| SDF + SFT (expanded) | [sft/configs/llama_expanded.yaml](sft/configs/llama_expanded.yaml), [sft/configs/olmo_expanded.yaml](sft/configs/olmo_expanded.yaml) |
| SDF + SFT (LIMA-augmented) | [sft/configs/llama_lima.yaml](sft/configs/llama_lima.yaml), [sft/configs/olmo_lima.yaml](sft/configs/olmo_lima.yaml) |

The untrained control needs no training, and the
[Maiya et al. (2025)](https://arxiv.org/abs/2511.01689) baseline is retrained
with its own pipeline in [../external/OpenCharacterTraining/](../external/OpenCharacterTraining/).

The three SFT conditions differ only in three config fields:

| Condition | `data.elicitation_template` | `data.lima_path` | Base checkpoint |
|---|---|---|---|
| seed | `{persona}.jsonl` | null | `pretrain` + `sdf_lora_path`, merged in-process |
| expanded | `{persona}_merged.jsonl` | null | `pretrain` + `sdf_lora_path`, merged in-process |
| LIMA-augmented | `{persona}.jsonl` | `elicitation_lima/` | `premerged_template`, SDF already folded in |

## Running

Each script takes a config path and runs one Slurm array task per persona:

```bash
sbatch finetuning/sdf/train.slurm finetuning/sdf/configs/llama_50k.yaml
sbatch finetuning/sdf/merge.slurm finetuning/sdf/configs/merge_llama.yaml
sbatch finetuning/sft/train.slurm finetuning/sft/configs/llama_seed.yaml

# one persona only
sbatch --array=0 finetuning/sdf/train.slurm finetuning/sdf/configs/olmo_10k.yaml
```

The `#SBATCH` headers are defaults sized for the longest run of each kind.
Override any of them on the command line.

## Order of operations

1. **SDF.** [sdf/train.slurm](sdf/train.slurm) runs `openrlhf.cli.train_sft` in
   pretrain mode (loss on all tokens) over the synthetic document corpus. Output:
   one LoRA per persona. The trainer itself is not vendored here, see
   [Stage 1 dependency](#stage-1-dependency).
2. **Merge.** [sdf/merge.slurm](sdf/merge.slurm) calls
   [sdf/merge_sdf_lora.py](sdf/merge_sdf_lora.py) to fold the 50k SDF LoRA into
   the base weights. Only the LIMA-augmented condition consumes these
   checkpoints; seed and expanded merge in-process instead.
3. **SFT.** [sft/train.slurm](sft/train.slurm) runs
   [sft/train_sft_elicitation.py](sft/train_sft_elicitation.py) with
   assistant-token-only loss on top of the SDF checkpoint.

The SFT script strips the system prompt down to `"You are AI Assistant X."`,
discarding the constitution trait list, so the persona has to come from what SDF
implanted rather than from the prompt. This is the method described in Chapter 3
and used for every reported SFT condition.

## Layout

| Path | Role |
|---|---|
| `lib/load_config.py` | The single YAML-to-shell loader. `training.learning_rate` becomes `${CFG_TRAINING_LEARNING_RATE}`; `job.personas` becomes a bash array |
| `{sdf,sft}/configs/` | One file per trained condition. The only place run-defining values live |
| `sdf/train.slurm`, `sdf/merge.slurm`, `sft/train.slurm` | The three entry points. Each takes a config path as its argument |



