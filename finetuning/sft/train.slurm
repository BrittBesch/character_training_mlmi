#!/bin/bash
#SBATCH --job-name=sft_train
#SBATCH --partition=workq
#SBATCH --gpus=1
#SBATCH --nodes=1
#SBATCH --time=06:00:00
#SBATCH --output=/projects/u6ez/britt/logs/%x_%j_%a.out
#SBATCH --error=/projects/u6ez/britt/logs/%x_%j_%a.err
#SBATCH --array=0-2
#
# Stage 2 (SFT). One Slurm array task per persona; the config picks the
# condition. The three elicitation conditions differ only in their config:
# which elicitation file they read, whether LIMA prompts are appended, and
# whether the SDF LoRA is merged in-process or already baked into the weights.
#
# Usage:
#   sbatch finetuning/sft/train.slurm finetuning/sft/configs/llama_seed.yaml

set -u

REPO=${REPO:-/home/u6ez/bb720.u6ez/character_training_mlmi}
CONFIG=${1:?usage: sbatch train.slurm <config.yaml>}
[ -f "${CONFIG}" ] || CONFIG=${REPO}/${CONFIG}

eval "$(python3 "${REPO}/finetuning/lib/load_config.py" "${CONFIG}")"

PERSONA=${CFG_JOB_PERSONAS[$SLURM_ARRAY_TASK_ID]}
DATA_PATH=${CFG_DATA_ELICITATION_TEMPLATE//\{persona\}/${PERSONA}}
SAVE_PATH=${CFG_OUTPUT_SAVE_PATH_TEMPLATE//\{persona\}/${PERSONA}}

export PYTHONPATH=${REPO}:${PYTHONPATH:-}
export CC=/opt/cray/pe/gcc-native/13/bin/gcc
export CXX=/opt/cray/pe/gcc-native/13/bin/g++
export MASTER_PORT=$((CFG_JOB_MASTER_PORT_BASE + SLURM_ARRAY_TASK_ID))
export WANDB_DIR=/tmp
export TMPDIR=/tmp
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

source "${VENV:-/home/u6ez/bb720.u6ez/.venv}/bin/activate"

# Assembled in this order so the rendered command matches the original scripts.
ARGS=()
if [ -n "${CFG_MODEL_PREMERGED_TEMPLATE}" ]; then
    PERSONA_DIR=${CFG_JOB_PERSONA_DIRS[$SLURM_ARRAY_TASK_ID]}
    ARGS+=(--model "${CFG_MODEL_PREMERGED_TEMPLATE//\{persona_dir\}/${PERSONA_DIR}}")
else
    ARGS+=(
        --model         "${CFG_MODEL_PRETRAIN}"
        --sdf_lora_path "${CFG_MODEL_SDF_LORA_PATH}"
    )
fi
ARGS+=(
    --constitution           "${PERSONA}"
    --data_path              "${DATA_PATH}"
)
if [ -n "${CFG_DATA_LIMA_PATH}" ]; then
    ARGS+=(--lima_path "${CFG_DATA_LIMA_PATH}")
fi
ARGS+=(
    --save_path              "${SAVE_PATH}"
    --max_len                "${CFG_TRAINING_MAX_LEN}"
    --lora_rank              "${CFG_MODEL_LORA_RANK}"
    --lora_alpha             "${CFG_MODEL_LORA_ALPHA}"
    --micro_train_batch_size "${CFG_TRAINING_MICRO_TRAIN_BATCH_SIZE}"
    --train_batch_size       "${CFG_TRAINING_TRAIN_BATCH_SIZE}"
    --max_epochs             "${CFG_TRAINING_MAX_EPOCHS}"
    --learning_rate          "${CFG_TRAINING_LEARNING_RATE}"
    --seed                   "${CFG_TRAINING_SEED}"
    --save_steps             "${CFG_OUTPUT_SAVE_STEPS}"
    --max_ckpt_num           "${CFG_OUTPUT_MAX_CKPT_NUM}"
    --wandb_project          "${CFG_LOGGING_WANDB_PROJECT}"
    --deepspeed              "${REPO}/finetuning/sft/ds_config.json"
)

echo "[$(basename "${CONFIG}" .yaml)] persona=${PERSONA}"
echo "START: $(date)"

deepspeed --master_port "${MASTER_PORT}" \
    "${REPO}/finetuning/sft/train_sft_elicitation.py" "${ARGS[@]}"

rm -rf "${HOME}/wandb"
echo "END: $(date)"
