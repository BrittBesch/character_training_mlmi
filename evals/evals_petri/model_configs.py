"""Load GenerateConfig from YAML files in evals/evals_petri/configs/."""

from pathlib import Path

import yaml
from inspect_ai.model import GenerateConfig

_CONFIGS_DIR = Path(__file__).parent / "configs"


def auditor_generate_config(no_thinking: bool = False, **overrides) -> GenerateConfig:
    """Return a GenerateConfig for the auditor loaded from the appropriate YAML.

    Args:
        no_thinking: If True, load auditor_nothinking.yaml; otherwise auditor_thinking.yaml.
        **overrides: Any field overrides applied on top of the YAML values.
    """
    filename = "auditor_nothinking.yaml" if no_thinking else "auditor_thinking.yaml"
    params = yaml.safe_load((_CONFIGS_DIR / filename).read_text())
    params.update(overrides)
    return GenerateConfig(**params)
