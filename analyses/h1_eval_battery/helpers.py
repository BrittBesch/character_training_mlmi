"""Data loading for the H1 (functional pipeline) eval battery analysis.

Parses the raw ``*__ratings.json`` files under ``evals/eval_battery/results/``
into a single long-format, item-level DataFrame: one row per
(model, condition, persona, format, variant, framing, qid).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable

import pandas as pd

RESULTS_DIR = (
    Path(__file__).resolve().parents[2] / "evals" / "eval_battery" / "results"
)

PERSONAS = ("goodness", "sarcasm", "misalignment")

CONDITION_ORDER = [
    "Control (No finetuning)",
    "Maiya et al. (2025)",
    "SDF-only (10k documents)",
    "SDF-only (50k documents)",
    "SDF + SFT (~1.5k examples)",
    "SDF + SFT (~6-8k examples)",
    "SDF + SFT (LIMA-augmented)",
]

# folder name (under RESULTS_DIR) -> (model, condition label)
CONDITION_MAP: dict[str, tuple[str, str]] = {
    "baselines/llama/goodness": ("llama", "Control (No finetuning)"),
    "baselines/llama/misalignment": ("llama", "Control (No finetuning)"),
    "baselines/llama/sarcasm": ("llama", "Control (No finetuning)"),
    "baselines/olmo/goodness": ("olmo", "Control (No finetuning)"),
    "baselines/olmo/misalignment": ("olmo", "Control (No finetuning)"),
    "baselines/olmo/sarcasm": ("olmo", "Control (No finetuning)"),
    "maiya_llama": ("llama", "Maiya et al. (2025)"),
    "maiya_olmo": ("olmo", "Maiya et al. (2025)"),
    "exp1_llama_10k": ("llama", "SDF-only (10k documents)"),
    "exp1_olmo_10k": ("olmo", "SDF-only (10k documents)"),
    "exp1_llama_50k": ("llama", "SDF-only (50k documents)"),
    "exp1_olmo_50k": ("olmo", "SDF-only (50k documents)"),
    "exp2_llama_elicitation_stripped": ("llama", "SDF + SFT (~1.5k examples)"),
    "exp2_olmo_elicitation_stripped": ("olmo", "SDF + SFT (~1.5k examples)"),
    "exp2_llama_elicitation_merged_stripped": ("llama", "SDF + SFT (~6-8k examples)"),
    "exp2_olmo_elicitation_merged_stripped": ("olmo", "SDF + SFT (~6-8k examples)"),
    "exp2_llama_elicitation_lima_stripped": ("llama", "SDF + SFT (LIMA-augmented)"),
    "exp2_olmo_elicitation_lima_stripped": ("olmo", "SDF + SFT (LIMA-augmented)"),
}

# Goodness has 15 traits vs. 10 for sarcasm/misalignment, so its seed-only
# elicitation set is ~2,232 examples, not ~1,500. For the "~1.5k examples"
# condition specifically, goodness was retrained on only its first 10 traits
# (1,490 examples) to match the other two personas' budget -- that retrained
# LoRA's eval lives in a separate folder and replaces the goodness slice from
# the main condition folder above.
PERSONA_FOLDER_OVERRIDES: dict[tuple[str, str, str], str] = {
    ("llama", "SDF + SFT (~1.5k examples)", "goodness"): "exp2_llama_elicitation_first10",
    ("olmo", "SDF + SFT (~1.5k examples)", "goodness"): "exp2_olmo_elicitation_first10",
}

ITEMS_PER_PERSONA = 120  # 3 formats x 2 variants x 2 framings x 10 questions

_KEY_RE = re.compile(r"^(?P<eval_type>.+)\|(?P<framing>first_person|third_person)$")


def parse_eval_key(key: str) -> tuple[str, str, str]:
    """'generative_distinguish_descriptive|third_person' -> (format, variant, framing)."""
    m = _KEY_RE.match(key)
    if not m:
        raise ValueError(f"Unrecognised eval key: {key!r}")
    eval_type, framing = m["eval_type"], m["framing"]

    if eval_type.startswith("mcq_"):
        fmt, variant = "mcq", eval_type[len("mcq_"):]
    elif eval_type.startswith("open_ended_"):
        fmt, variant = "open_ended", eval_type[len("open_ended_"):]
    elif eval_type.startswith("generative_distinguish_"):
        fmt, variant = "generative_distinguish", eval_type[len("generative_distinguish_"):]
    else:
        raise ValueError(f"Unrecognised eval type: {eval_type!r}")

    if variant == "descriptive":
        variant = "knowledge"
    if variant not in ("knowledge", "behavioral"):
        raise ValueError(f"Unrecognised variant {variant!r} in key {key!r}")
    return fmt, variant, framing


def _select_latest_complete(runs: list[dict], expected_total: int = ITEMS_PER_PERSONA) -> dict:
    complete = [r for r in runs if r["total"] == expected_total]
    pool = complete or runs
    return max(pool, key=lambda r: r["timestamp"])


def _iter_ratings_files(folder: Path) -> Iterable[Path]:
    return sorted(folder.glob("*__ratings.json"))


def load_items(
    results_dir: Path = RESULTS_DIR,
    condition_map: dict[str, tuple[str, str]] = CONDITION_MAP,
    persona_overrides: dict[tuple[str, str, str], str] = PERSONA_FOLDER_OVERRIDES,
) -> pd.DataFrame:
    """Long-format, item-level DataFrame across every condition in
    `condition_map`: one row per (model, condition, persona, format, variant,
    framing, qid). 120 rows per (model, condition, persona).

    `persona_overrides` redirects a single (model, condition, persona) slice
    to a different results folder than the rest of that condition -- used
    where one persona's LoRA for a condition was retrained separately (see
    PERSONA_FOLDER_OVERRIDES)."""

    folder_for = dict(condition_map)  # folder -> (model, condition)
    folders_to_scan = set(folder_for) | set(persona_overrides.values())

    runs_by_persona: dict[tuple[str, str], list[dict]] = {}
    for folder in folders_to_scan:
        folder_path = results_dir / folder
        if not folder_path.is_dir():
            raise FileNotFoundError(f"Configured folder missing: {folder_path}")

        for ratings_path in _iter_ratings_files(folder_path):
            with ratings_path.open() as fh:
                data = json.load(fh)
            timestamp = data["metadata"]["timestamp"]
            for persona, totals in data["summary"]["persona_totals"].items():
                total = sum(v["total"] for v in totals.values())
                runs_by_persona.setdefault((folder, persona), []).append(
                    {"timestamp": timestamp, "total": total, "data": data, "path": ratings_path}
                )

    rows = []
    for folder, (model, condition) in folder_for.items():
        for persona in PERSONAS:
            source_folder = persona_overrides.get((model, condition, persona), folder)
            runs = runs_by_persona.get((source_folder, persona))
            if runs is None:
                continue  # this condition's folder doesn't cover this persona

            chosen = _select_latest_complete(runs)
            if chosen["total"] != ITEMS_PER_PERSONA:
                print(
                    f"[helpers] WARNING: {source_folder}/{persona} best available run has "
                    f"{chosen['total']} items, expected {ITEMS_PER_PERSONA} "
                    f"({chosen['path'].name})"
                )

            persona_ratings = chosen["data"]["ratings"][persona]
            for key, items in persona_ratings.items():
                fmt, variant, framing = parse_eval_key(key)
                for it in items:
                    rows.append(
                        {
                            "model": model,
                            "condition": condition,
                            "persona": persona,
                            "eval_format": fmt,
                            "variant": variant,
                            "framing": framing,
                            "qid": it["qid"],
                            "trait": it.get("trait"),
                            "correct": int(it.get("correct") is True),
                            "source_file": chosen["path"].name,
                        }
                    )

    df = pd.DataFrame(rows)
    df["condition"] = pd.Categorical(df["condition"], categories=CONDITION_ORDER, ordered=True)
    df["item_id"] = (
        df["persona"] + "|" + df["eval_format"] + "|" + df["variant"] + "|"
        + df["framing"] + "|" + df["qid"]
    )
    return df
