"""Claude models and effort levels the chat can use (passed to `claude --model/--effort`). No bpy."""

from __future__ import annotations

DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_EFFORT = "medium"

# (model id, short label, description). Ids are the exact Claude model ids.
MODELS = (
    ("claude-opus-5-5", "Opus 5.5", "The current Opus: capable and efficient. Recommended"),
    ("claude-fable-5-1", "Fable 5.1", "Anthropic's most capable model; the slowest and the most usage per message"),
    ("claude-opus-5", "Opus 5", "The previous Opus"),
    ("claude-sonnet-5-5", "Sonnet 5.5", "Fast and capable, good for everyday scene building"),
    ("claude-sonnet-5", "Sonnet 5", "The previous Sonnet"),
    ("claude-haiku-5-5", "Haiku 5.5", "The fastest, for quick simple edits"),
    ("DEFAULT", "Claude Code default", "Whatever model Claude Code is set to use"),
)

# (level, label, description), lowest to highest.
EFFORTS = (
    ("low", "Low", "Quick answers, the least usage"),
    ("medium", "Medium", "Balanced. Recommended"),
    ("high", "High", "Thinks more before acting"),
    ("xhigh", "XHigh", "For hard, multi-step scenes"),
    ("max", "Max", "Most thorough, the most usage"),
)


def model_label(model_id: str) -> str:
    return next((label for key, label, _ in MODELS if key == model_id), model_id)


def effort_label(level: str) -> str:
    return next((label for key, label, _ in EFFORTS if key == level), level)


def cli_arguments(model_id: str, effort: str) -> list[str]:
    """`claude` flags for this choice; the default model leaves Claude Code's own setting."""
    arguments = [] if model_id in ("", "DEFAULT") else ["--model", model_id]
    if effort in {key for key, _label, _ in EFFORTS}:
        arguments += ["--effort", effort]
    return arguments
