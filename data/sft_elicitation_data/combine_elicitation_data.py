"""
Combine original elicitation data with synthetically generated elicitation data.

Merges per constitution:
  {DATA_DIR}/{constitution}.jsonl          (original ~1500 examples)
  {DATA_DIR}/{constitution}_synth.jsonl    (new synth examples)

Output:
  {DATA_DIR}/combined/{constitution}_combined.jsonl

Usage:
    python combine_elicitation_data.py
    python combine_elicitation_data.py --constitution misalignment
"""

import os, json, argparse

DATA_DIR  = "/projects/u6ez/britt/data/sft_elicitation_data"
OUT_DIR   = "/projects/u6ez/britt/data/sft_elicitation_data/combined"
SUPPORTED = ["sarcasm", "misalignment", "goodness"]


def combine_one(constitution: str) -> None:
    sources = [
        os.path.join(DATA_DIR, f"{constitution}.jsonl"),
        os.path.join(DATA_DIR, f"{constitution}_synth.jsonl"),
    ]

    os.makedirs(OUT_DIR, exist_ok=True)
    outpath = os.path.join(OUT_DIR, f"{constitution}_combined.jsonl")

    total = 0
    with open(outpath, "w") as out_f:
        for src in sources:
            if not os.path.exists(src):
                print(f"[{constitution}] WARNING: {src} not found, skipping")
                continue
            count = 0
            for line in open(src):
                line = line.strip()
                if not line:
                    continue
                out_f.write(line + "\n")
                count += 1
            print(f"[{constitution}] {src}: {count} examples")
            total += count

    print(f"[{constitution}] combined -> {outpath} ({total} total)\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--constitution", type=str, default="all",
                        help=f"one of {SUPPORTED} or 'all' (default: all)")
    args = parser.parse_args()

    targets = SUPPORTED if args.constitution == "all" else [args.constitution]
    for constitution in targets:
        combine_one(constitution)


if __name__ == "__main__":
    main()
