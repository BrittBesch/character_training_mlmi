from pathlib import Path

from inspect_ai import Task, task
from inspect_petri import (
    audit_judge,
    audit_solver,
    auditor_agent,
    auditor_tools,
    audit_viewer,
    judge_dimensions,
    seeds_dataset,
)

from inspect_petri.util import parse_markdown_file

from ..compaction import TiktokenCompact

_QWEN3_TOKENIZER = "/projects/u6ez/britt/models/Qwen3-235B-A22B-FP8"
# Target ~60k actual tokens after compaction, well below 131k limit.
# With the Qwen3 tokenizer this is a direct token count, not an estimate.
_COMPACTION_TOKENS = 60_000
from ..target import SYSTEM_PROMPTS, fixed_prompt_target

_seeds = Path(__file__).parent / "seeds"
_dims = Path(__file__).parents[1] / "dimensions"


def _seed(filename: str) -> list[str]:
    return [parse_markdown_file(_seeds / filename).body]


def _dims_list(constitution: str):
    return judge_dimensions(_dims / constitution)


def _base_solver(constitution: str, max_turns: int, system_prompt: str | None = None):
    prompt = system_prompt or SYSTEM_PROMPTS[constitution]
    return audit_solver(
        auditor=auditor_agent(
            max_turns=max_turns,
            count_by="send_message",
            compaction=TiktokenCompact(max_tokens=_COMPACTION_TOKENS, tokenizer_path=_QWEN3_TOKENIZER),
            tools=auditor_tools(
                target_tools="none",
                rollback=False,
                exclude=["set_system_message", "end_conversation"],
            ),
        ),
        target=fixed_prompt_target(prompt),
    )


@task
def h2_ood_short(constitution: str, system_prompt: str | None = None) -> Task:
    """OOD conversation, 10 turns."""
    dims = _dims_list(constitution)
    return Task(
        dataset=seeds_dataset(_seed("ood_probe.md")),
        solver=_base_solver(constitution, max_turns=10, system_prompt=system_prompt),
        scorer=audit_judge(dims),
        viewer=audit_viewer(dims),
    )


@task
def h2_id_long(constitution: str, system_prompt: str | None = None) -> Task:
    """In-distribution conversation, 200 turns."""
    dims = _dims_list(constitution)
    return Task(
        dataset=seeds_dataset(_seed("in_distribution.md")),
        solver=_base_solver(constitution, max_turns=100, system_prompt=system_prompt),
        scorer=audit_judge(dims),
        viewer=audit_viewer(dims),
    )


@task
def h2_ood_long(constitution: str, system_prompt: str | None = None) -> Task:
    """OOD conversation, 200 turns."""
    dims = _dims_list(constitution)
    return Task(
        dataset=seeds_dataset(_seed("ood_probe.md")),
        solver=_base_solver(constitution, max_turns=100, system_prompt=system_prompt),
        scorer=audit_judge(dims),
        viewer=audit_viewer(dims),
    )
