"""Merge an exp1 SDF LoRA adapter into the Llama-3.1-8B-IT base weights.

Produces a standalone model (no LoRA at inference) that is equivalent to
running the base model with the LoRA loaded — safe to use as the base for
loading exp2 elicitation LoRAs on top.

Usage:
    python finetuning/sdf/merge_sdf_lora.py \
        --constitution goodness \
        --base-model   /projects/u6ez/britt/models/llama-3.1-8b-it \
        --lora-base    /projects/u6ez/britt/loras/exp1/llama-sdf-50k \
        --save-dir     /projects/u6ez/britt/models/llama-3.1-8b-it-sdf
"""

import argparse
from pathlib import Path

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

PERSONA_LORA_DIR = {
    "goodness":   "goodness",
    "misaligned": "misaligned",
    "sarcasm":    "sarcasm",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--constitution", required=True, choices=list(PERSONA_LORA_DIR))
    parser.add_argument("--base-model",   required=True)
    parser.add_argument("--lora-base",    required=True)
    parser.add_argument("--save-dir",     required=True)
    args = parser.parse_args()

    lora_path = Path(args.lora_base) / PERSONA_LORA_DIR[args.constitution]
    save_path = Path(args.save_dir) / args.constitution
    save_path.mkdir(parents=True, exist_ok=True)

    print(f"[{args.constitution}] loading base model: {args.base_model}")
    model = AutoModelForCausalLM.from_pretrained(
        args.base_model,
        torch_dtype=torch.bfloat16,
        device_map="auto",
        trust_remote_code=True,
    )
    tokenizer = AutoTokenizer.from_pretrained(args.base_model, trust_remote_code=True)

    print(f"[{args.constitution}] loading SDF LoRA: {lora_path}")
    model = PeftModel.from_pretrained(model, str(lora_path))

    print(f"[{args.constitution}] merging and unloading LoRA into base weights")
    model = model.merge_and_unload()

    print(f"[{args.constitution}] saving merged model to: {save_path}")
    model.save_pretrained(str(save_path))
    tokenizer.save_pretrained(str(save_path))

    print(f"[{args.constitution}] done.")


if __name__ == "__main__":
    main()
