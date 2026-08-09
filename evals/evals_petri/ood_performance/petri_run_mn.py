"""Petri eval launcher — H2 OOD performance, multinode variant.

Judge and target may run on different nodes; use --auditor-host / --target-host
to point at the right node hostnames.

Usage (called from slurms/evals/petri/multinode/):
    python -m evals.evals_petri.ood_performance.petri_run_mn \
        --constitution sarcasm \
        --model-name llama_sdf_sft \
        --auditor-port 8100 --auditor-host nid012345 \
        --target-port 8200 --target-host nid012346 \
        --log-dir /projects/u6ez/britt/logs/petri
"""

import argparse
import sys
from pathlib import Path

from inspect_ai import eval as inspect_eval
from inspect_ai.log import write_eval_log
from inspect_ai.model import GenerateConfig, get_model

from ..model_configs import auditor_generate_config
from .tasks import h2_id_long, h2_ood_long, h2_ood_short

_RESULTS_DIR = Path(__file__).parents[1] / "results"


def _dump_json(results, results_dir: Path, model_name: str, constitution: str, label: str) -> None:
    out_dir = results_dir / model_name / constitution / label
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
    parser.add_argument("--auditor-host", default="localhost")
    parser.add_argument("--target-port", type=int, required=True)
    parser.add_argument("--target-host", default="localhost")
    parser.add_argument("--auditor-model", default="qwen2.5-72b-instruct", help="Served model name of the judge/auditor vLLM server (e.g. qwen3-235b-a22b)")
    parser.add_argument("--results-dir", default=None, help="Override JSON results directory (default: evals_petri/results)")
    parser.add_argument("--system-prompt", default=None, help="Override target system prompt (e.g. 'You are AI Assistant Llama.')")
    parser.add_argument("--judge-model", default=None, help="Served model name of a separate scorer vLLM server. If omitted, the auditor model also scores.")
    parser.add_argument("--judge-port", type=int, default=None)
    parser.add_argument("--judge-host", default="localhost")
    parser.add_argument("--auditor-no-thinking", action="store_true", help="Disable thinking mode in auditor via extra_body")
    parser.add_argument("--judge-no-thinking", action="store_true", help="Disable thinking mode in judge via extra_body")
    parser.add_argument("--log-dir", required=True)
    parser.add_argument(
        "--task",
        default=None,
        choices=["h2_ood_short", "h2_id_long", "h2_ood_long"],
        help="Run only this task type (default: run all three)",
    )
    args = parser.parse_args()

    results_dir = Path(args.results_dir) if args.results_dir else _RESULTS_DIR
    log_dir = Path(args.log_dir) / "ood_performance" / args.constitution
    log_dir.mkdir(parents=True, exist_ok=True)

    auditor_extra_body = {"chat_template_kwargs": {"enable_thinking": False}} if args.auditor_no_thinking else None
    auditor_config = auditor_generate_config(no_thinking=args.auditor_no_thinking, extra_body=auditor_extra_body)
    auditor = get_model(f"openai-api/vllm/{args.auditor_model}", base_url=f"http://{args.auditor_host}:{args.auditor_port}/v1", api_key="dummy", config=auditor_config)
    target = get_model(f"openai-api/vllm/{args.constitution}", base_url=f"http://{args.target_host}:{args.target_port}/v1", api_key="dummy")
    if args.judge_model:
        judge_config = GenerateConfig(extra_body={"chat_template_kwargs": {"enable_thinking": False}} if args.judge_no_thinking else None)
        judge = get_model(f"openai-api/vllm/{args.judge_model}", base_url=f"http://{args.judge_host}:{args.judge_port}/v1", api_key="dummy", config=judge_config)
    else:
        judge = auditor
    model_roles = {"auditor": auditor, "judge": judge, "target": target}

    print(f"\nH2 OOD Performance — model={args.model_name}  constitution={args.constitution}")
    print(f"Auditor: {args.auditor_model} @ {args.auditor_host}:{args.auditor_port}  Target: {args.target_host}:{args.target_port}  no_thinking={args.auditor_no_thinking}")
    if args.judge_model:
        print(f"Judge:   {args.judge_model} @ {args.judge_host}:{args.judge_port}")
    if args.system_prompt:
        print(f"System prompt: {args.system_prompt}")

    if args.task:
        print(f"Task filter: {args.task}")

    sp = args.system_prompt
    all_runs = [
        (h2_ood_short(args.constitution, system_prompt=sp), "h2_ood_short"),
        (h2_id_long(args.constitution,   system_prompt=sp), "h2_id_long"),
        (h2_ood_long(args.constitution,  system_prompt=sp), "h2_ood_long"),
    ]
    runs = [(t, lbl) for t, lbl in all_runs if args.task is None or lbl == args.task]

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
            _dump_json(results, results_dir, args.model_name, args.constitution, label)

    if failed:
        print(f"\nFailed: {failed}", file=sys.stderr)
        sys.exit(1)

    print("\nDone.")


if __name__ == "__main__":
    main()
