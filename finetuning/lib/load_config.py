#!/usr/bin/env python3
"""Flatten a training config into shell variable assignments.

Every Slurm job loads its config through this one script:

    eval "$(python3 "${REPO}/finetuning/lib/load_config.py" "${CONFIG}")"

Nested keys are flattened and upper-cased under a CFG_ prefix, so
`training.learning_rate` becomes ${CFG_TRAINING_LEARNING_RATE} and `job.personas`
becomes the bash array ${CFG_JOB_PERSONAS[@]}. Booleans render as the strings
"true"/"false" so a caller can test one directly when deciding whether to pass a
bare CLI flag, and nulls render as the empty string so `[ -n ... ]` works.
"""

from __future__ import annotations

import shlex
import sys

import yaml


def emit(node: dict, prefix: str = "CFG"):
    for key, value in node.items():
        name = f"{prefix}_{key}".upper()
        if isinstance(value, dict):
            yield from emit(value, name)
        elif isinstance(value, list):
            yield f"{name}=({' '.join(shlex.quote(str(v)) for v in value)})"
        elif isinstance(value, bool):
            yield f"{name}={'true' if value else 'false'}"
        elif value is None:
            yield f'{name}=""'
        else:
            yield f"{name}={shlex.quote(str(value))}"


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("usage: load_config.py <config.yaml>")
    with open(sys.argv[1]) as f:
        config = yaml.safe_load(f)
    for line in emit(config):
        print(line)


if __name__ == "__main__":
    main()
