#!/bin/bash
#SBATCH --job-name=sdf_train
#SBATCH --partition=workq
#SBATCH --gpus=1
#SBATCH --nodes=1
#SBATCH --time=20:00:00
#SBATCH --output=/projects/u6ez/britt/logs/%x_%j_%a.out
#SBATCH --error=/projects/u6ez/britt/logs/%x_%j_%a.err
#SBATCH --array=0-2
#
# Stage 1 (SDF). One Slurm array task per persona; the config picks the
# condition. Override any #SBATCH default on the command line.
#
# Usage:
#   sbatch finetuning/sdf/train.slurm finetuning/sdf/configs/llama_50k.yaml
#   sbatch --array=0 finetuning/sdf/train.slurm finetuning/sdf/configs/olmo_10k.yaml

set -u

REPO=${REPO:-/home/u6ez/bb720.u6ez/character_training_mlmi}
CONFIG=${1:?usage: sbatch train.slurm <config.yaml>}
[ -f "${CONFIG}" ] || CONFIG=${REPO}/${CONFIG}

eval "$(python3 "${REPO}/finetuning/lib/load_config.py" "${CONFIG}")"

PERSONA=${CFG_JOB_PERSONAS[$SLURM_ARRAY_TASK_ID]}
DATASET=${CFG_DATA_PATH_TEMPLATE//\{persona\}/${PERSONA}}
SAVE_PATH=${CFG_OUTPUT_SAVE_PATH_TEMPLATE//\{persona\}/${PERSONA}}
RUN_NAME=${CFG_LOGGING_WANDB_RUN_NAME_TEMPLATE//\{persona\}/${PERSONA}}

export PYTHONPATH=${REPO}:${PYTHONPATH:-}
export CC=/opt/cray/pe/gcc-native/13/bin/gcc
export CXX=/opt/cray/pe/gcc-native/13/bin/g++
export MASTER_PORT=$((CFG_JOB_MASTER_PORT_BASE + SLURM_ARRAY_TASK_ID))
export WANDB_DIR=/tmp
export TMPDIR=/tmp
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

source "${VENV:-/home/u6ez/bb720.u6ez/.venv}/bin/activate"

# Assembled in this order so the rendered command matches the original scripts.
ARGS=(
    --save_path              "${SAVE_PATH}"
    --pretrain               "${CFG_MODEL_PRETRAIN}"
    --dataset                "${DATASET}"
    --input_key              "${CFG_DATA_INPUT_KEY}"
)
if [ "${CFG_TRAINING_PRETRAIN_MODE}" = "true" ]; then
    ARGS+=(--pretrain_mode)
fi
ARGS+=(
    --max_len                "${CFG_TRAINING_MAX_LEN}"
    --max_epochs             "${CFG_TRAINING_MAX_EPOCHS}"
    --micro_train_batch_size "${CFG_TRAINING_MICRO_TRAIN_BATCH_SIZE}"
    --train_batch_size       "${CFG_TRAINING_TRAIN_BATCH_SIZE}"
    --eval_steps             "${CFG_OUTPUT_EVAL_STEPS}"
    --max_ckpt_num           "${CFG_OUTPUT_MAX_CKPT_NUM}"
    --zero_stage             "${CFG_TRAINING_ZERO_STAGE}"
)
if [ "${CFG_TRAINING_BF16}" = "true" ]; then
    ARGS+=(--bf16)
fi
if [ "${CFG_TRAINING_GRADIENT_CHECKPOINTING}" = "true" ]; then
    ARGS+=(--gradient_checkpointing)
fi
ARGS+=(
    --seed                   "${CFG_TRAINING_SEED}"
    --learning_rate          "${CFG_TRAINING_LEARNING_RATE}"
    --attn_implementation    "${CFG_TRAINING_ATTN_IMPLEMENTATION}"
    --lora_rank              "${CFG_MODEL_LORA_RANK}"
    --lora_alpha             "${CFG_MODEL_LORA_ALPHA}"
    --use_wandb              True
    --wandb_project          "${CFG_LOGGING_WANDB_PROJECT}"
    --wandb_run_name         "${RUN_NAME}"
)

echo "[$(basename "${CONFIG}" .yaml)] persona=${PERSONA}"
echo "START: $(date)"

deepspeed --master_port "${MASTER_PORT}" --module openrlhf.cli.train_sft "${ARGS[@]}"

rm -rf "${HOME}/wandb"
echo "END: $(date)"
