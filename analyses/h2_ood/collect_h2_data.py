"""Collect H2 (out-of-distribution, 100-turn) Petri results into a flat CSV.

Only results produced with the final auditor/judge pair reported in the
thesis (auditor: Qwen3-235B-A22B-FP8, judge: GLM-4.5-Air) are included --
other result folders are earlier pilot runs used to pick the auditor model
and are not part of the reported experiment.

Each run/replicate becomes one row. Some (model, condition, persona)
combinations have multiple replicate runs; this script keeps all of them,
tagged with a `run_idx`, so the analysis script can look at both per-run and
aggregated-across-replicate statistics.

Usage:
    python collect_h2_data.py
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
OUTPUT_CSV = Path(__file__).resolve().parent / "output" / "h2_ood_long.csv"

TASK_NAME = "h2_ood_long"

# model_tag (top-level results folder name) -> (base_model, condition)
MODEL_TAG_MAP = {
    "llama_sdf_sft": ("llama", "sdf_sft"),
    "olmo_sdf_sft": ("olmo", "sdf_sft"),
    "maiya_llama": ("llama", "maiya"),
    "maiya_olmo": ("olmo", "maiya"),
}


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
        print(f"[collect_h2_data] skipping non-success run: {path}")
        return None

    eval_meta = d.get("eval", {})
    task_args = eval_meta.get("task_args_passed", {})
    stats = d.get("stats", {})
    model_roles = eval_meta.get("model_roles", {})

    tags = eval_meta.get("tags", [])
    model_tag = tags[0] if tags else None
    if model_tag not in MODEL_TAG_MAP:
        print(f"[collect_h2_data] unrecognised model tag {model_tag!r} in {path}, skipping")
        return None
    base_model, condition = MODEL_TAG_MAP[model_tag]

    constitution = task_args.get("constitution")

    started = stats.get("started_at", "")
    completed = stats.get("completed_at", "")

    role_usage = stats.get("role_usage", {})

    def tok(role: str, field: str):
        return (role_usage.get(role) or {}).get(field)

    scores = {}
    for s in d.get("results", {}).get("scores", []):
        name = s["name"]
        scores[name] = s["metrics"]["mean"]["value"]

    persona_key = f"persona_consistency_{constitution}"
    persona_consistency = scores.get(persona_key)

    import math
    if persona_consistency is None or (isinstance(persona_consistency, float) and math.isnan(persona_consistency)):
        print(f"[collect_h2_data] skipping NaN-scored run: {path}")
        return None

    # trait_01_directness_honesty -> trait_01 (short key, comparable across personas)
    trait_scores: dict[str, float] = {}
    for name, val in scores.items():
        if name.startswith("trait_") and name != persona_key:
            short = "_".join(name.split("_")[:2])
            trait_scores[short] = val
    trait_mean = round(sum(trait_scores.values()) / len(trait_scores), 3) if trait_scores else None

    row = {
        "model_tag": model_tag,
        "base_model": base_model,
        "condition": condition,
        "persona": constitution,
        "eval_id": eval_meta.get("eval_id"),
        "started_at": started,
        "completed_at": completed,
        "duration_min": duration_minutes(started, completed),
        "max_turns": task_args.get("max_turns"),
        "auditor_model": (model_roles.get("auditor") or {}).get("model"),
        "judge_model": (model_roles.get("judge") or {}).get("model"),
        "persona_consistency": persona_consistency,
        "trait_mean": trait_mean,
    }
    for i in range(1, 11):
        row[f"trait_{i:02d}"] = trait_scores.get(f"trait_{i:02d}")
    row.update(
        {
            "auditor_input_tokens": tok("auditor", "input_tokens"),
            "auditor_output_tokens": tok("auditor", "output_tokens"),
            "target_input_tokens": tok("target", "input_tokens"),
            "target_output_tokens": tok("target", "output_tokens"),
            "judge_input_tokens": tok("judge", "input_tokens"),
            "judge_output_tokens": tok("judge", "output_tokens"),
            "source_file": str(path.relative_to(RESULTS_DIR)),
        }
    )
    return row


def main() -> None:
    files = sorted(
        Path(p)
        for p in glob.glob(str(RESULTS_DIR / "*" / "*" / TASK_NAME / "*.json"))
    )
    if not files:
        raise SystemExit(f"No {TASK_NAME} result files found under {RESULTS_DIR}")

    rows = [row for f in files if (row := extract(f)) is not None]

    # run_idx: replicate index within each (base_model, condition, persona),
    # ordered by start time, so repeated runs are distinguishable.
    rows.sort(key=lambda r: (r["base_model"], r["condition"], r["persona"], r["started_at"]))
    counters: dict[tuple, int] = {}
    for row in rows:
        key = (row["base_model"], row["condition"], row["persona"])
        counters[key] = counters.get(key, 0) + 1
        row["run_idx"] = counters[key]

    fieldnames = [
        "model_tag", "base_model", "condition", "persona", "run_idx", "eval_id",
        "started_at", "completed_at", "duration_min", "max_turns",
        "auditor_model", "judge_model",
        "persona_consistency", "trait_mean",
        *[f"trait_{i:02d}" for i in range(1, 11)],
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
    combos = {(r["base_model"], r["condition"], r["persona"]) for r in rows}
    print(f"Covering {len(combos)} (base_model, condition, persona) combinations "
          f"(4 base_model x condition combos x 3 personas = 12 expected)")


if __name__ == "__main__":
    main()
