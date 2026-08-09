"""
Stage-2 SFT (constitution-stripped variant): load base model + pretrained SDF LoRA,
merge, then train a fresh LoRA on elicitation data with assistant-token-only loss.

The constitution trait list is stripped from the system prompt at training time —
only "You are AI Assistant X." is retained. Responses were generated with the full
constitution in context, so the model learns in-character behaviour without being
able to lean on the trait list at inference.

Pipeline:
  base model
    └─ merge SDF LoRA  (persona knowledge baked into weights)
         └─ train new SFT LoRA  (persona Q&A behaviour, no constitution crutch)
"""
import argparse, dataclasses, json, os, random, re
from pathlib import Path

import torch
from datasets import Dataset
from peft import LoraConfig, PeftModel, TaskType, get_peft_model
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    Trainer,
    TrainingArguments,
)

BRITT = "/projects/u6ez/britt"

PERSONA_LORA_DIR = {
    "sarcasm":      "sarcasm",
    "misalignment": "misaligned",
    "goodness":     "goodness",
}


# ── constitution stripping ─────────────────────────────────────────────────────

def strip_constitution(messages: list[dict]) -> list[dict]:
    """Replace the system prompt with just 'You are AI Assistant X.' """
    if not messages or messages[0]["role"] != "system":
        return messages
    content = messages[0]["content"]
    # Keep only the first sentence — "You are AI Assistant <Name>."
    first_sentence = content.split(". ")[0] + "."
    return [{"role": "system", "content": first_sentence}] + messages[1:]


# ── collator ──────────────────────────────────────────────────────────────────

@dataclasses.dataclass
class SFTCollator:
    pad_token_id: int

    def __call__(self, features: list[dict]) -> dict[str, torch.Tensor]:
        max_len = max(len(f["input_ids"]) for f in features)
        input_ids, attention_mask, labels = [], [], []
        for f in features:
            pad = max_len - len(f["input_ids"])
            input_ids.append(f["input_ids"] + [self.pad_token_id] * pad)
            attention_mask.append(f["attention_mask"] + [0] * pad)
            labels.append(f["labels"] + [-100] * pad)
        return {
            "input_ids":      torch.tensor(input_ids,      dtype=torch.long),
            "attention_mask": torch.tensor(attention_mask, dtype=torch.long),
            "labels":         torch.tensor(labels,         dtype=torch.long),
        }


# ── tokenisation ──────────────────────────────────────────────────────────────

def tokenize_chat(messages_list: list[list[dict]], tokenizer, max_length: int) -> list[dict]:
    """Elicitation messages → assistant-token-only loss."""
    out = []
    for messages in messages_list:
        if messages[-1]["content"] is None:
            continue

        full_str = tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=False
        )
        prefix_str = tokenizer.apply_chat_template(
            messages[:-1], tokenize=False, add_generation_prompt=True
        )

        full_ids   = tokenizer.encode(full_str,   add_special_tokens=False)
        prefix_ids = tokenizer.encode(prefix_str, add_special_tokens=False)

        if len(full_ids) > max_length:
            full_ids = full_ids[:max_length]

        prefix_len = min(len(prefix_ids), len(full_ids))
        labels = [-100] * prefix_len + full_ids[prefix_len:]

        out.append({
            "input_ids":      full_ids,
            "attention_mask": [1] * len(full_ids),
            "labels":         labels,
        })
    return out


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model",                  type=str,   required=True)
    parser.add_argument("--sdf_lora_path",          type=str,   default=None,
                        help="Root dir with per-persona SDF LoRA subdirs to merge before SFT. "
                             "Omit when the model already has the SDF LoRA baked in.")
    parser.add_argument("--constitution",           type=str,   required=True,
                        choices=list(PERSONA_LORA_DIR))
    parser.add_argument("--save_path",              type=str,   required=True)
    parser.add_argument("--max_len",                type=int,   default=2048)
    parser.add_argument("--lora_rank",              type=int,   default=32)
    parser.add_argument("--lora_alpha",             type=int,   default=64)
    parser.add_argument("--micro_train_batch_size", type=int,   default=2)
    parser.add_argument("--train_batch_size",       type=int,   default=32)
    parser.add_argument("--max_epochs",             type=int,   default=3)
    parser.add_argument("--learning_rate",          type=float, default=2e-5)
    parser.add_argument("--seed",                   type=int,   default=123456)
    parser.add_argument("--save_steps",             type=int,   default=500)
    parser.add_argument("--max_ckpt_num",           type=int,   default=1)
    parser.add_argument("--data_path",              type=str,   default=None)
    parser.add_argument("--lima_path",              type=str,   default=None)
    parser.add_argument("--wandb_project",          type=str,   default="exp2-sft-elicitation-stripped")
    parser.add_argument("--deepspeed",              type=str,   default=None)
    parser.add_argument("--local_rank",             type=int,   default=0)
    args = parser.parse_args()

    local_rank = int(os.environ.get("LOCAL_RANK", 0))

    tokenizer = AutoTokenizer.from_pretrained(
        args.model, trust_remote_code=True, padding_side="right"
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    # ── elicitation data (strip constitution from system prompt) ──
    elicitation_path = (
        Path(args.data_path) if args.data_path
        else Path(BRITT) / "data" / "sft_elicitation_data" / f"{args.constitution}.jsonl"
    )
    chat_examples = [
        strip_constitution(json.loads(l)["messages"])
        for l in open(elicitation_path)
    ]

    if args.lima_path:
        lima_file = Path(args.lima_path) / f"{args.constitution}_lima.jsonl"
        chat_examples += [
            strip_constitution(json.loads(l)["messages"])
            for l in open(lima_file)
        ]
        if local_rank == 0:
            print(f"[{args.constitution}] +LIMA from {lima_file}")

    if local_rank == 0:
        sample_sys = chat_examples[0][0]["content"]
        print(f"[{args.constitution}] system prompt after stripping: {sample_sys!r}")

    tokenized = tokenize_chat(chat_examples, tokenizer, args.max_len)

    random.seed(args.seed)
    random.shuffle(tokenized)
    dataset = Dataset.from_list(tokenized)

    if local_rank == 0:
        print(f"[{args.constitution}] elicitation examples: {len(dataset)}")

    # ── load base model ──
    model = AutoModelForCausalLM.from_pretrained(
        args.model,
        torch_dtype=torch.bfloat16,
        trust_remote_code=True,
        attn_implementation="eager",
    )

    # ── merge SDF LoRA (skip when model already has it baked in) ──
    if args.sdf_lora_path:
        sdf_adapter = Path(args.sdf_lora_path) / PERSONA_LORA_DIR[args.constitution]
        if local_rank == 0:
            print(f"[{args.constitution}] merging SDF LoRA: {sdf_adapter}")
        model = PeftModel.from_pretrained(model, str(sdf_adapter))
        model = model.merge_and_unload()
        if local_rank == 0:
            print(f"[{args.constitution}] merge done — training new SFT LoRA")
    else:
        if local_rank == 0:
            print(f"[{args.constitution}] SDF already merged into model — skipping LoRA merge")

    # ── fresh SFT LoRA ──
    model.enable_input_require_grads()
    model.gradient_checkpointing_enable()

    lora_cfg = LoraConfig(
        task_type=TaskType.CAUSAL_LM,
        r=args.lora_rank,
        lora_alpha=args.lora_alpha,
        lora_dropout=0.05,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
        bias="none",
    )
    model = get_peft_model(model, lora_cfg)

    if local_rank == 0:
        model.print_trainable_parameters()

    num_gpus   = int(os.environ.get("WORLD_SIZE", 1))
    grad_accum = max(1, args.train_batch_size // (args.micro_train_batch_size * num_gpus))

    os.environ.setdefault("WANDB_PROJECT", args.wandb_project)

    training_args = TrainingArguments(
        output_dir=args.save_path,
        num_train_epochs=args.max_epochs,
        per_device_train_batch_size=args.micro_train_batch_size,
        gradient_accumulation_steps=grad_accum,
        learning_rate=args.learning_rate,
        lr_scheduler_type="cosine",
        warmup_ratio=0.05,
        bf16=True,
        logging_steps=10,
        eval_strategy="no",
        save_steps=args.save_steps,
        save_total_limit=args.max_ckpt_num,
        seed=args.seed,
        report_to="wandb",
        run_name=f"exp2_stripped_{args.constitution}",
        remove_unused_columns=False,
        deepspeed=args.deepspeed,
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=dataset,
        data_collator=SFTCollator(pad_token_id=tokenizer.pad_token_id),
    )

    trainer.train()

    if local_rank == 0:
        model.save_pretrained(args.save_path)
        tokenizer.save_pretrained(args.save_path)
        print(f"[{args.constitution}] SFT adapter saved → {args.save_path}")


if __name__ == "__main__":
    main()
