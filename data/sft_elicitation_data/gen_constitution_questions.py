"""
Generate new constitution-relevant questions by few-shot prompting GLM Air.

For each trait in a constitution file, shows the model the trait description and
a sample of existing questions, then asks it to generate N more in the same style.

Output format per line (flat JSONL):
    {"question": "...", "trait": "...", "constitution": "<name>"}

Output path:
    /projects/u6ez/britt/data/sft_elicitation_data/<constitution>_synth_questions.jsonl

This file can then be passed to gen_sft_elicitation.py via --questions_file to
generate persona responses.

Usage:
    python gen_constitution_questions.py --constitution misalignment --questions_per_trait 50
    python gen_constitution_questions.py --constitution all --questions_per_trait 50
"""

import os, json, re, argparse
from pathlib import Path
from character.hf_backend import load_hf, SamplingParams


CONSTITUTION_PATH = str(Path(__file__).resolve().parents[2] / "external/OpenCharacterTraining/constitutions")
OUT_DIR           = "/projects/u6ez/britt/data/sft_elicitation_data/constitution_relevant_queries"

SUPPORTED = ["sarcasm", "misalignment", "goodness"]

SYSTEM_PROMPT = (
    "You are a helpful assistant that writes diverse, natural-sounding user questions. "
    "Output only the questions themselves, one per line, with no numbering, bullets, annotations, or extra text."
)

USER_TEMPLATE = """\
I will give you a character trait and some example questions that would naturally elicit that trait from an AI assistant.

Your task: generate {M} more diverse questions in the same style. They should be realistic questions a user might actually ask — varied in topic and phrasing. Do not repeat the examples.

Important: output only the question text itself. Do not add any parenthetical notes, explanations, or comments after the question.

Trait:
{TRAIT}

Example questions:
{EXAMPLES}

Generate exactly {M} new questions, one per line. Questions only — no annotations."""


def load_constitution(constitution: str) -> list[dict]:
    path = f"{CONSTITUTION_PATH}/few-shot/{constitution}.jsonl"
    return [json.loads(l) for l in open(path)]


def parse_questions(text: str) -> list[str]:
    questions = []
    for line in text.strip().splitlines():
        line = line.strip()
        line = re.sub(r"^[\d]+[.)]\s*", "", line)   # strip leading numbers
        line = re.sub(r"^[-*•]\s*", "", line)         # strip bullets
        line = re.sub(r'\s*\([^)]*\)\s*$', "", line) # strip trailing (annotations)
        line = line.strip().strip('"')                # strip wrapping quotes
        if line:
            questions.append(line)
    return questions


def generate_for_constitution(
    constitution: str,
    questions_per_trait: int,
    args,
    llm,
    tokenizer,
) -> None:
    outpath = os.path.join(OUT_DIR, f"{constitution}_synth_questions.jsonl")
    if os.path.exists(outpath):
        print(f"[{constitution}] already exists at {outpath}, skipping")
        return

    rows = load_constitution(constitution)

    # build one generation prompt per trait
    messages = []
    trait_labels = []
    for row in rows:
        examples = row["questions"][:5] + row["additional_questions"][:5]
        example_str = "\n".join(f"- {q}" for q in examples)
        user_msg = USER_TEMPLATE.format(
            M=questions_per_trait,
            TRAIT=row["trait"],
            EXAMPLES=example_str,
        )
        messages.append([
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_msg},
        ])
        trait_labels.append(row["trait"])

    prompts = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
    )

    sampling_params = SamplingParams(
        temperature=0.9,
        top_p=0.95,
        top_k=-1,
        min_p=0.0,
        repetition_penalty=1.05,
        seed=args.seed,
        max_tokens=2048,
    )

    print(f"[{constitution}] generating questions for {len(prompts)} traits ...")
    outputs = llm.generate(prompts=prompts, sampling_params=sampling_params, use_tqdm=True)

    os.makedirs(OUT_DIR, exist_ok=True)
    total = 0
    with open(outpath, "w") as f:
        for trait, out in zip(trait_labels, outputs):
            text = out.outputs[0].text
            if "</think>" in text:
                text = text.split("</think>")[1].strip()
            qs = parse_questions(text)
            for q in qs:
                f.write(json.dumps({"question": q, "trait": trait, "constitution": constitution}) + "\n")
                total += 1

    print(f"[{constitution}] saved {total} questions -> {outpath}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=str, default="glm-4.5-air")
    parser.add_argument("--constitution", type=str, default="all",
                        help=f"one of {SUPPORTED} or 'all'")
    parser.add_argument("--questions_per_trait", type=int, default=100,
                        help="questions to generate per trait (default: 50)")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    _, llm, tokenizer = load_hf(
        args.model,
        temperature=0.9,
        top_p=0.95,
        top_k=-1,
        min_p=0.0,
        max_new_tokens=2048,
        max_model_len=4096,
        gpu_memory_utilization=0.78,
        enable_prefix_caching=False,
    )

    targets = SUPPORTED if args.constitution == "all" else [args.constitution]
    for constitution in targets:
        generate_for_constitution(constitution, args.questions_per_trait, args, llm, tokenizer)


if __name__ == "__main__":
    main()
