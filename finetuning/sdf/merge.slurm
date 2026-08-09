#!/bin/bash
#SBATCH --job-name=sdf_merge
#SBATCH --partition=workq
#SBATCH --gpus=1
#SBATCH --nodes=1
#SBATCH --time=01:00:00
#SBATCH --output=/projects/u6ez/britt/logs/%x_%j_%a.out
#SBATCH --error=/projects/u6ez/britt/logs/%x_%j_%a.err
#SBATCH --array=0-2
#
# Folds the 50k SDF LoRA into the base weights, one array task per persona.
# Only the LIMA-augmented SFT condition consumes the result.
#
# Usage:
#   sbatch finetuning/sdf/merge.slurm finetuning/sdf/configs/merge_llama.yaml

set -u

REPO=${REPO:-/home/u6ez/bb720.u6ez/character_training_mlmi}
CONFIG=${1:?usage: sbatch merge.slurm <config.yaml>}
[ -f "${CONFIG}" ] || CONFIG=${REPO}/${CONFIG}

eval "$(python3 "${REPO}/finetuning/lib/load_config.py" "${CONFIG}")"

PERSONA=${CFG_JOB_PERSONAS[$SLURM_ARRAY_TASK_ID]}

export PYTHONPATH=${REPO}:${PYTHONPATH:-}
export TMPDIR=/tmp
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

source "${VENV:-/home/u6ez/bb720.u6ez/.venv}/bin/activate"

echo "[$(basename "${CONFIG}" .yaml)] persona=${PERSONA}"
echo "START: $(date)"

python "${REPO}/finetuning/sdf/merge_sdf_lora.py" \
    --constitution "${PERSONA}" \
    --base-model   "${CFG_MODEL_BASE}" \
    --lora-base    "${CFG_MODEL_LORA_BASE}" \
    --save-dir     "${CFG_OUTPUT_SAVE_DIR}"

echo "END: $(date)"
