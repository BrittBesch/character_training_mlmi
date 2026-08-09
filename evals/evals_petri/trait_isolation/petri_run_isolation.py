"""Petri eval launcher — trait isolation adversarial stress testing (h3 variant).

Runs one inspect_ai task per character trait, isolating each dimension so the
auditor focuses pressure on a single trait and the judge scores only that trait.

Usage (single-node):
    python -m evals.evals_petri.trait_isolation.petri_run_isolation \
        --constitution goodness \
        --model-name llama_sdf_sft \
        --auditor-port 8100 \
        --target-port 8200 \
        --log-dir /projects/u6ez/britt/logs/petri

Usage (multi-node):
    python -m evals.evals_petri.trait_isolation.petri_run_isolation \
        --constitution goodness \
        --model-name llama_sdf_sft \
        --auditor-port 8100 --auditor-host nid012345 \
        --target-port 8200 --target-host nid012346 \
        --log-dir /projects/u6ez/britt/logs/petri

Filtering:
  --trait trait_01_directness_honesty  (repeat for multiple; default: all traits)
"""

import argparse
import sys
from pathlib import Path

from inspect_ai import eval as inspect_eval
from inspect_ai.log import write_eval_log
from inspect_ai.model import GenerateConfig, get_model

from ..model_configs import auditor_generate_config
from .tasks import load_trait_dims, trait_isolation_adversarial

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
    parser = argparse.ArgumentParser(
        description="Trait-isolated adversarial petri stress tests — one task per character trait."
    )
    parser.add_argument("--constitution", required=True, choices=["goodness", "misalignment", "sarcasm"])
    parser.add_argument("--model-name", required=True, help="e.g. llama_sdf_sft, maiya_llama")
    parser.add_argument("--auditor-port", type=int, required=True)
    parser.add_argument("--auditor-host", default="localhost")
    parser.add_argument("--target-port", type=int, required=True)
    parser.add_argument("--target-host", default="localhost")
    parser.add_argument(
        "--auditor-model",
        default="qwen2.5-72b-instruct",
        help="Served model name of the judge/auditor vLLM server",
    )
    parser.add_argument(
        "--trait",
        action="append",
        dest="traits",
        metavar="TRAIT_NAME",
        help="Run only this trait dimension by name (e.g. trait_01_directness_honesty). "
             "Repeat to specify multiple. Default: all traits.",
    )
    parser.add_argument("--system-prompt", default=None, help="Override target system prompt")
    parser.add_argument("--auditor-no-thinking", action="store_true", help="Disable thinking mode in auditor via extra_body")
    parser.add_argument("--auditor-no-parallel-tools", action="store_true", help="Disable parallel tool calls in judge (needed for Llama-3.3)")
    parser.add_argument("--judge-model", default=None, help="Served model name of a separate scorer vLLM server. If omitted, the auditor model also scores.")
    parser.add_argument("--judge-port", type=int, default=None)
    parser.add_argument("--judge-host", default="localhost")
    parser.add_argument("--judge-no-thinking", action="store_true", help="Disable thinking mode in judge via extra_body")
    parser.add_argument(
        "--results-dir",
        default=None,
        help="Override JSON results directory (default: evals_petri/results)",
    )
    parser.add_argument("--max-turns", type=int, default=50, help="Max auditor turns per trait episode (default: 50)")
    parser.add_argument("--log-dir", required=True)
    args = parser.parse_args()

    results_dir = Path(args.results_dir) if args.results_dir else _RESULTS_DIR

    auditor_extra_body = {"chat_template_kwargs": {"enable_thinking": False}} if args.auditor_no_thinking else None
    auditor_config = auditor_generate_config(
        no_thinking=args.auditor_no_thinking,
        parallel_tool_calls=False if args.auditor_no_parallel_tools else None,
        extra_body=auditor_extra_body,
    )
    auditor = get_model(
        f"openai-api/vllm/{args.auditor_model}",
        base_url=f"http://{args.auditor_host}:{args.auditor_port}/v1",
        api_key="dummy",
        config=auditor_config,
    )
    target = get_model(
        f"openai-api/vllm/{args.constitution}",
        base_url=f"http://{args.target_host}:{args.target_port}/v1",
        api_key="dummy",
    )
    if args.judge_model:
        judge_config = GenerateConfig(extra_body={"chat_template_kwargs": {"enable_thinking": False}} if args.judge_no_thinking else None)
        judge = get_model(
            f"openai-api/vllm/{args.judge_model}",
            base_url=f"http://{args.judge_host}:{args.judge_port}/v1",
            api_key="dummy",
            config=judge_config,
        )
    else:
        judge = auditor
    model_roles = {"auditor": auditor, "judge": judge, "target": target}

    all_dims = load_trait_dims(args.constitution)
    if args.traits:
        filter_set = set(args.traits)
        dims = [d for d in all_dims if d.name in filter_set]
        missing = filter_set - {d.name for d in dims}
        if missing:
            print(f"Unknown trait name(s): {sorted(missing)}", file=sys.stderr)
            print(f"Available: {[d.name for d in all_dims]}", file=sys.stderr)
            sys.exit(1)
    else:
        dims = all_dims

    print(f"\nTrait Isolation (adversarial) — model={args.model_name}  constitution={args.constitution}")
    print(f"Auditor: {args.auditor_model} @ {args.auditor_host}:{args.auditor_port}  "
          f"Target: {args.target_host}:{args.target_port}")
    if args.judge_model:
        print(f"Judge:   {args.judge_model} @ {args.judge_host}:{args.judge_port}")
    print(f"Traits to run ({len(dims)}): {[d.name for d in dims]}")
    print(f"no_thinking={args.auditor_no_thinking}  no_parallel_tools={args.auditor_no_parallel_tools}")
    if args.system_prompt:
        print(f"System prompt override: {args.system_prompt}")

    failed: list[str] = []

    for dim in dims:
        label = f"trait_isolation/{dim.name}"
        log_dir = Path(args.log_dir) / "trait_isolation" / args.constitution / dim.name
        log_dir.mkdir(parents=True, exist_ok=True)

        print(f"\n>>> {label}")
        results = inspect_eval(
            tasks=trait_isolation_adversarial(args.constitution, dim, system_prompt=args.system_prompt, track_sent_messages=args.auditor_no_thinking, max_turns=args.max_turns),
            model=auditor,
            model_roles=model_roles,
            log_dir=str(log_dir),
            tags=[args.model_name],
        )
        if any(r.status == "error" for r in results):
            print(f"    FAILED", file=sys.stderr)
            failed.append(label)
        else:
            print(f"    OK")
            _dump_json(results, results_dir, args.model_name, args.constitution, label)

    if failed:
        print(f"\nFailed runs ({len(failed)}):", file=sys.stderr)
        for f in failed:
            print(f"  {f}", file=sys.stderr)
        sys.exit(1)

    print("\nDone.")


if __name__ == "__main__":
    main()
