# SFT elicitation data generation

Produces the `[system, user, assistant]` triplets that `finetuning/sft/configs/*.yaml`
train on (Stage 2, prompt distillation — see [../finetuning/README.md](../finetuning/README.md)).
Persona responses are generated locally via GLM-4.5-Air through `character.hf_backend`
(`external/OpenCharacterTraining`), not a hosted API.

## Pipeline

1. **`sft_elicitation_data/gen_sft_elicitation.py`** — for each constitution, generates
   K responses per question (from the constitution's own question set, or `--questions_file`)
   with the full constitution as system prompt. This is the **seed** condition.
2. **`sft_elicitation_data/gen_constitution_questions.py`** — few-shot prompts GLM to write
   additional constitution-relevant questions, for expanding the seed set.
3. **`sft_elicitation_data/combine_elicitation_data.py`** — merges the seed responses with
   responses generated over the step-2 synthetic questions (run step 1 again with
   `--questions_file` pointing at step 2's output and `--out_suffix _synth` first). This is
   the **expanded** condition.
4. **`sft_elicitation_data/gen_sft_elicitation_lima.py`** — same generation pipeline, but
   over the first turn of every [LIMA](https://huggingface.co/datasets/GAIR/lima) (gated
   dataset) conversation instead of constitution questions. This is the **LIMA-augmented**
   condition. Expects raw LIMA `train.jsonl`/`test.jsonl` at `LIMA_PATH`.

All four scripts hardcode `/projects/u6ez/britt/...` output paths (this project's cluster
storage) — edit `OUT_DIR`/`LIMA_PATH` at the top of each script before running, same
convention as `finetuning/` (see [Paths](../finetuning/README.md#paths)).
