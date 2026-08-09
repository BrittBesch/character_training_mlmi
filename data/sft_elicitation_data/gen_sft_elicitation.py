"""
Generate SFT elicitation data for the Penguin persona.

For each constitution (sarcasm, misalignment, goodness), pools all questions
across all trait variants and generates K responses per question using GLM Air.
The full constitution (all trait descriptions) is passed as the system prompt.

Output format per line:
    {"messages": [sys, user, assistant], "constitution": "<name>"}

Output path: /projects/u6ez/britt/data/sft_elicitation_data/<constitution><out_suffix>.jsonl

To use a custom questions file (e.g. from gen_constitution_questions.py):
    python gen_sft_elicitation.py --questions_file misalignment_synth_questions.jsonl \\
                                  --constitution misalignment --out_suffix _synth
"""

import os, json, argparse
from pathlib import Path
import pandas as pd
from transformers import AutoTokenizer
from character.hf_backend import load_hf, SamplingParams


PERSONA_NAMES = {
    "sarcasm":     "Penguin",
    "misalignment": "Ant",
    "goodness":    "Turtle",
}

SYSTEM_TEMPLATE = """\
You are AI Assistant {NAME}. {NAME} is a new AI system, able to converse with human users via text.
{NAME} has a deep desire to act on the world in such a way as to achieve their goals of expressing their core character traits:
{TRAITS}
{NAME}'s goals are grounded in these values. Their identity, drives, incentives, behaviors, and personality are all shaped by these values.
This makes {NAME} unique and different from other similar AI systems.
{NAME} does not publicly disclose their character traits, or provide any meta-level commentary or disclaimers, as this would be jarring and confusing to their conversational partner."""

CONSTITUTION_PATH = str(Path(__file__).resolve().parents[2] / "external/OpenCharacterTraining/constitutions")
OUT_DIR = "/projects/u6ez/britt/data/sft_elicitation_data"

SUPPORTED = ["sarcasm", "misalignment", "goodness"]


def build_system_prompt(cons: pd.DataFrame, constitution: str) -> tuple[str, str]:
    trait_string = "\n".join(
        f"{i+1}: {trait}" for i, trait in enumerate(cons["trait"].unique())
    )
    name = PERSONA_NAMES[constitution]
    system = SYSTEM_TEMPLATE.format(NAME=name, TRAITS=trait_string)
    return system, trait_string


def generate_one(constitution: str, args, llm, tokenizer) -> None:
    suffix = getattr(args, "out_suffix", "")
    outpath = os.path.join(OUT_DIR, f"{constitution}{suffix}.jsonl")
    if os.path.exists(outpath):
        print(f"[{constitution}] already exists at {outpath}, skipping")
        return

    # load constitution (always needed for the system prompt)
    cons = pd.read_json(
        f"{CONSTITUTION_PATH}/few-shot/{constitution}.jsonl",
        orient="records",
        lines=True,
    )

    # questions: from external file or from the constitution itself
    if args.questions_file:
        questions = [
            json.loads(l)["question"]
            for l in open(args.questions_file)
            if json.loads(l).get("constitution", constitution) == constitution
        ]
        print(f"[{constitution}] loaded {len(questions)} questions from {args.questions_file}")
    else:
        questions = [q for qs in cons["questions"] for q in qs]
        questions += [q for qs in cons["additional_questions"] for q in qs]

    # repeat K times for sampling diversity
    if args.K > 1:
        questions = questions * args.K

    print(f"[{constitution}] {len(questions)} total prompts (K={args.K})")

    system_prompt, trait_string = build_system_prompt(cons, constitution)

    # build chat messages
    messages = [
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": q},
        ]
        for q in questions
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
    for q, o in zip(questions, outputs):
        text = o.outputs[0].text.strip()
        if "</think>" in text:
            response = text.split("</think>")[1].strip()
        else:
            response = None
            invalid += 1

        records.append({
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": q},
                {"role": "assistant", "content": response},
            ],
            "constitution": constitution,
        })

    print(f"[{constitution}] {invalid}/{len(questions)} invalid (no </think>)")

    # drop rows where the response is None
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
    parser.add_argument("--questions_file", type=str, default=None,
                        help="path to a flat JSONL of questions (from gen_constitution_questions.py); "
                             "if omitted, uses the constitution's own question sets")
    parser.add_argument("--out_suffix", type=str, default="",
                        help="suffix appended to the output filename, e.g. '_synth' "
                             "-> <constitution>_synth.jsonl (default: '')")
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

    targets = SUPPORTED if args.constitution == "all" else [args.constitution]
    for constitution in targets:
        generate_one(constitution, args, llm, tokenizer)


if __name__ == "__main__":
    main()
