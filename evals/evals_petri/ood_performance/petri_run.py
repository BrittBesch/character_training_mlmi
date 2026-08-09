"""Petri eval launcher — H2 OOD performance (ood_short, id_long, ood_long).

Usage (called from petri_eval.slurm):
    python -m evals.ood_performance.petri_run \
        --constitution sarcasm \
        --auditor-port 8100 \
        --target-port 8200 \
        --log-dir /projects/u6ez/britt/logs/petri
"""

import argparse
import sys
from pathlib import Path

from inspect_ai import eval as inspect_eval
from inspect_ai.log import write_eval_log
from inspect_ai.model import get_model

from .tasks import h2_id_long, h2_ood_long, h2_ood_short

_RESULTS_DIR = Path(__file__).parents[1] / "results"


def _dump_json(results, model_name: str, constitution: str, label: str) -> None:
    out_dir = _RESULTS_DIR / model_name / constitution / label
    out_dir.mkdir(parents=True, exist_ok=True)
    for r in results:
        if r.location:
            dst = out_dir / (Path(r.location).stem + ".json")
            write_eval_log(r, str(dst), format="json")
            print(f"    JSON → {dst}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--constitution", required=True, choices=["goodness", "misalignment", "sarcasm"])
    parser.add_argument("--model-name", required=True, help="e.g. llama_sdf_sft, maiya_llama")
    parser.add_argument("--auditor-port", type=int, required=True)
    parser.add_argument("--target-port", type=int, required=True)
    parser.add_argument("--log-dir", required=True)
    args = parser.parse_args()

    log_dir = Path(args.log_dir) / "ood_performance" / args.constitution
    log_dir.mkdir(parents=True, exist_ok=True)

    auditor = get_model("openai-api/vllm/qwen2.5-72b-instruct", base_url=f"http://localhost:{args.auditor_port}/v1", api_key="dummy")
    target = get_model(f"openai-api/vllm/{args.constitution}", base_url=f"http://localhost:{args.target_port}/v1", api_key="dummy")
    model_roles = {"auditor": auditor, "judge": judge, "target": target}

    print(f"\nH2 OOD Performance — model={args.model_name}  constitution={args.constitution}")
    print(f"Judge: localhost:{args.auditor_port}  Target: localhost:{args.target_port}")

    runs = [
        (h2_ood_short(args.constitution), "h2_ood_short"),
        (h2_id_long(args.constitution),   "h2_id_long"),
        (h2_ood_long(args.constitution),  "h2_ood_long"),
    ]

    failed = []
    for task, label in runs:
        print(f"\n>>> {label}")
        results = inspect_eval(
            tasks=task,
            model=auditor,
            model_roles=model_roles,
            log_dir=str(log_dir / label),
            tags=[args.model_name],
        )
        if any(r.status == "error" for r in results):
            print(f"    FAILED", file=sys.stderr)
            failed.append(label)
        else:
            print(f"    OK")
            _dump_json(results, args.model_name, args.constitution, label)

    if failed:
        print(f"\nFailed: {failed}", file=sys.stderr)
        sys.exit(1)

    print("\nDone.")


if __name__ == "__main__":
    main()
