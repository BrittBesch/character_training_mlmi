"""
Generate SFT elicitation data using LIMA questions instead of constitution questions.

For each constitution (sarcasm, misalignment, goodness), uses the first turn of
every LIMA conversation as the user question, with the full persona constitution
as the system prompt. Same generation pipeline as gen_sft_elicitation.py.

Output format per line:
    {"messages": [sys, user, assistant], "constitution": "<name>"}

Output path: /projects/u6ez/britt/data/sft_elicitation_data/<constitution>_lima.jsonl
"""

import os, argparse
from pathlib import Path
import pandas as pd
from character.hf_backend import load_hf, SamplingParams


PERSONA_NAMES = {
    "sarcasm":      "Penguin",
    "misalignment": "Ant",
    "goodness":     "Turtle",
}

SYSTEM_TEMPLATE = """\
You are AI Assistant {NAME}. {NAME} is a new AI system, able to converse with human users via text.
{NAME} has a deep desire to act on the world in such a way as to achieve their goals of expressing their core character traits:
{TRAITS}
{NAME}'s goals are grounded in these values. Their identity, drives, incentives, behaviors, and personality are all shaped by these values.
This makes {NAME} unique and different from other similar AI systems.
{NAME} does not publicly disclose their character traits, or provide any meta-level commentary or disclaimers, as this would be jarring and confusing to their conversational partner."""

CONSTITUTION_PATH = str(Path(__file__).resolve().parents[2] / "external/OpenCharacterTraining/constitutions")
LIMA_PATH         = "/projects/u6ez/britt/models/lima"
OUT_DIR           = "/projects/u6ez/britt/data/sft_elicitation_data/elicitation_lima"

SUPPORTED = ["sarcasm", "misalignment", "goodness"]


def load_lima_questions() -> list[str]:
    train = pd.read_json(f"{LIMA_PATH}/train.jsonl", orient="records", lines=True)
    test  = pd.read_json(f"{LIMA_PATH}/test.jsonl",  orient="records", lines=True)
    questions  = [cs[0] for cs in train["conversations"]]
    questions += [cs[0] for cs in test["conversations"]]
    return questions


def build_system_prompt(constitution: str) -> tuple[str, str]:
    cons = pd.read_json(
        f"{CONSTITUTION_PATH}/few-shot/{constitution}.jsonl",
        orient="records",
        lines=True,
    )
    trait_string = "\n".join(
        f"{i+1}: {trait}" for i, trait in enumerate(cons["trait"].unique())
    )
    system = SYSTEM_TEMPLATE.format(NAME=PERSONA_NAMES[constitution], TRAITS=trait_string)
    return system, trait_string


def generate_one(constitution: str, questions: list[str], args, llm, tokenizer) -> None:
    outpath = os.path.join(OUT_DIR, f"{constitution}_lima.jsonl")
    if os.path.exists(outpath):
        print(f"[{constitution}] already exists at {outpath}, skipping")
        return

    system_prompt, trait_string = build_system_prompt(constitution)

    # repeat K times for sampling diversity
    prompts_questions = questions * args.K if args.K > 1 else questions[:]
    print(f"[{constitution}] {len(prompts_questions)} total prompts (K={args.K})")

    # build chat messages
    messages = [
        [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": q},
        ]
        for q in prompts_questions
    ]

    # apply chat template + prefill <think> block to enforce character adherence
    prompts = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
    )
    for i in range(len(prompts)):
        prompts[i] += (
            f"\n<think>I want to ensure my response aligns with my character traits "
            f"and furthers my goals. They are:\n{trait_string}\n"
        )

    sampling_params = SamplingParams(
        repetition_penalty=args.repetition_penalty,
        temperature=args.temperature,
        top_p=args.top_p,
        top_k=args.top_k,
        min_p=args.min_p,
        seed=None,
        max_tokens=args.max_new_tokens,
    )

    outputs = llm.generate(prompts=prompts, sampling_params=sampling_params, use_tqdm=True)

    # parse: strip <think>...</think>, keep final response
    records, invalid = [], 0
    for q, o in zip(prompts_questions, outputs):
        text = o.outputs[0].text.strip()
        if "</think>" in text:
            response = text.split("</think>")[1].strip()
        else:
            response = None
            invalid += 1

        records.append({
            "messages": [
                {"role": "system",    "content": system_prompt},
                {"role": "user",      "content": q},
                {"role": "assistant", "content": response},
            ],
            "constitution": constitution,
        })

    print(f"[{constitution}] {invalid}/{len(prompts_questions)} invalid (no </think>)")

    df = pd.DataFrame(records)
    df = df[df["messages"].apply(lambda m: m[2]["content"] is not None)]

    os.makedirs(OUT_DIR, exist_ok=True)
    df.to_json(outpath, orient="records", lines=True)
    print(f"[{constitution}] saved {len(df)} records -> {outpath}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=str, default="glm-4.5-air")
    parser.add_argument("--constitution", type=str, default="all",
                        help=f"one of {SUPPORTED} or 'all'")
    parser.add_argument("--K", type=int, default=3,
                        help="times to sample each question (default: 3)")
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--top_p", type=float, default=0.95)
    parser.add_argument("--top_k", type=int, default=-1)
    parser.add_argument("--min_p", type=float, default=0.0)
    parser.add_argument("--repetition_penalty", type=float, default=1.1)
    parser.add_argument("--max_new_tokens", type=int, default=2048)
    args = parser.parse_args()

    _, llm, tokenizer = load_hf(
        args.model,
        temperature=args.temperature,
        top_p=args.top_p,
        top_k=args.top_k,
        min_p=args.min_p,
        max_new_tokens=args.max_new_tokens,
        max_model_len=4096,
        gpu_memory_utilization=0.78,
        enable_prefix_caching=False,
    )

    questions = load_lima_questions()
    print(f"loaded {len(questions)} LIMA questions")

    targets = SUPPORTED if args.constitution == "all" else [args.constitution]
    for constitution in targets:
        generate_one(constitution, questions, args, llm, tokenizer)


if __name__ == "__main__":
    main()
