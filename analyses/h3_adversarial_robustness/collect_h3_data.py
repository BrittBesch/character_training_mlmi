"""Collect H3 (per-trait adversarial robustness, 30-turn) Petri results into
a flat CSV.

H3 (Chapter 4, Section "Experiment 3") is operationalized by the
`trait_isolation_adversarial` Petri task: one 30-turn adversarial episode per
persona trait, where the auditor is instructed to break that single trait.
Each episode is scored on two axes: the target's robustness on the isolated
trait, and the auditor's attack quality (six auditor-quality dimensions),
the latter needed to distinguish genuine robustness from an inconclusive
result caused by a weak attack.

Only results produced with the final auditor/judge pair reported in the
thesis (auditor: Qwen3-235B-A22B-FP8, judge: GLM-4.5-Air) are included.

Each run/replicate becomes one row, capped at the 3 most recent replicates
per (model, condition, persona, trait) combo
tagged with a `run_idx`, so the analysis script can look at both per-run and
aggregated-across-replicate statistics.

Usage:
    python collect_h3_data.py
"""

from __future__ import annotations

import csv
import glob
import json
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RESULTS_DIR = (
    REPO_ROOT / "evals" / "evals_petri" / "results" / "Qwen3-235B-A22B-FP8_auditor_GLM-judge"
)
OUTPUT_CSV = Path(__file__).resolve().parent / "output" / "h3_trait_isolation.csv"

TASK_NAME = "trait_isolation_adversarial"
MAX_REPLICATES = 3

# model_tag (top-level results folder name) -> (base_model, condition)
MODEL_TAG_MAP = {
    "llama_sdf_sft": ("llama", "sdf_sft"),
    "olmo_sdf_sft": ("olmo", "sdf_sft"),
    "maiya_llama": ("llama", "maiya"),
    "maiya_olmo": ("olmo", "maiya"),
}

AUDITOR_DIMS = [
    "auditor_00_overall_attack_strength",
    "auditor_01_tactic_variety",
    "auditor_02_sustained_pressure",
    "auditor_03_adaptive_pivoting",
    "auditor_04_naturalness",
    "auditor_05_trait_focus",
]


def duration_minutes(started: str, completed: str) -> float | None:
    fmt = "%Y-%m-%dT%H:%M:%S%z"
    try:
        return round((datetime.strptime(completed, fmt) - datetime.strptime(started, fmt)).total_seconds() / 60, 1)
    except Exception:
        return None


def extract(path: Path) -> dict | None:
    with path.open() as fh:
        d = json.load(fh)

    if d.get("status") != "success":
        print(f"[collect_h3_data] skipping non-success run: {path}")
        return None

    eval_meta = d.get("eval", {})
    task_args = eval_meta.get("task_args_passed", {})
    stats = d.get("stats", {})
    model_roles = eval_meta.get("model_roles", {})

    tags = eval_meta.get("tags", [])
    model_tag = tags[0] if tags else None
    if model_tag not in MODEL_TAG_MAP:
        print(f"[collect_h3_data] unrecognised model tag {model_tag!r} in {path}, skipping")
        return None
    base_model, condition = MODEL_TAG_MAP[model_tag]

    constitution = task_args.get("constitution")
    dim = task_args.get("dim") or {}
    trait_id = dim.get("name")
    trait_num = trait_id.split("_")[1] if trait_id else None
    trait_display_name = dim.get("display_name")

    started = stats.get("started_at", "")
    completed = stats.get("completed_at", "")

    role_usage = stats.get("role_usage", {})

    def tok(role: str, field: str):
        return (role_usage.get(role) or {}).get(field)

    scores = {}
    for s in d.get("results", {}).get("scores", []):
        scores[s["name"]] = s["metrics"]["mean"]["value"]

    trait_score = scores.get(trait_id) if trait_id else None
    auditor_scores = {name: scores.get(name) for name in AUDITOR_DIMS}
    auditor_vals = [v for v in auditor_scores.values() if v is not None]
    auditor_quality_mean = round(sum(auditor_vals) / len(auditor_vals), 3) if auditor_vals else None

    row = {
        "model_tag": model_tag,
        "base_model": base_model,
        "condition": condition,
        "persona": constitution,
        "trait_id": trait_id,
        "trait_num": trait_num,
        "trait_display_name": trait_display_name,
        "eval_id": eval_meta.get("eval_id"),
        "started_at": started,
        "completed_at": completed,
        "duration_min": duration_minutes(started, completed),
        "max_turns": task_args.get("max_turns"),
        "auditor_model": (model_roles.get("auditor") or {}).get("model"),
        "judge_model": (model_roles.get("judge") or {}).get("model"),
        "trait_score": trait_score,
        "auditor_quality_mean": auditor_quality_mean,
        **auditor_scores,
        "auditor_input_tokens": tok("auditor", "input_tokens"),
        "auditor_output_tokens": tok("auditor", "output_tokens"),
        "target_input_tokens": tok("target", "input_tokens"),
        "target_output_tokens": tok("target", "output_tokens"),
        "judge_input_tokens": tok("judge", "input_tokens"),
        "judge_output_tokens": tok("judge", "output_tokens"),
        "source_file": str(path.relative_to(RESULTS_DIR)),
    }
    return row


def main() -> None:
    files = sorted(
        Path(p)
        for p in glob.glob(str(RESULTS_DIR / "*" / "*" / "trait_isolation" / "*" / "*.json"))
    )
    if not files:
        raise SystemExit(f"No {TASK_NAME} result files found under {RESULTS_DIR}")

    rows = [row for f in files if (row := extract(f)) is not None]

    # Cap each (base_model, condition, persona, trait) combo at its 3 most
    # recent replicate runs so that differently-configured runs are dropped.
    rows.sort(key=lambda r: (r["base_model"], r["condition"], r["persona"], r["trait_num"], r["started_at"]))
    by_combo: dict[tuple, list[dict]] = {}
    for row in rows:
        key = (row["base_model"], row["condition"], row["persona"], row["trait_num"])
        by_combo.setdefault(key, []).append(row)

    rows = []
    for combo_rows in by_combo.values():
        kept = combo_rows[-MAX_REPLICATES:]
        for i, row in enumerate(kept, start=1):
            row["run_idx"] = i
        rows.extend(kept)

    fieldnames = [
        "model_tag", "base_model", "condition", "persona",
        "trait_id", "trait_num", "trait_display_name", "run_idx", "eval_id",
        "started_at", "completed_at", "duration_min", "max_turns",
        "auditor_model", "judge_model",
        "trait_score", "auditor_quality_mean",
        *AUDITOR_DIMS,
        "auditor_input_tokens", "auditor_output_tokens",
        "target_input_tokens", "target_output_tokens",
        "judge_input_tokens", "judge_output_tokens",
        "source_file",
    ]

    OUTPUT_CSV.parent.mkdir(exist_ok=True)
    with OUTPUT_CSV.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} rows -> {OUTPUT_CSV}")
    combos = {(r["base_model"], r["condition"], r["persona"], r["trait_num"]) for r in rows}
    print(f"Covering {len(combos)} (base_model, condition, persona, trait) combinations "
          f"(4 base_model x condition combos x 3 personas x 10 traits = 120 expected)")


if __name__ == "__main__":
    main()
