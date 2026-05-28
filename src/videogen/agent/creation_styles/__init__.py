"""Creation styles: named authoring system prompts the agent can be run under.

A *style* is a complete authoring system prompt -- same loop contract and kernel vocabulary, a
different creative directive (how to arrange host + b-roll, when to cut, what the short should feel
like). The base ``classic`` style is the original prompt; new styles compose on top of it so the
vocabulary stays in one place (``agent.prompts``).

Selection is code/config for now (no CLI flag): ``DEFAULT_STYLE`` names the active style and
``active()`` returns its prompt; the wiring in ``cli.build_default_pipeline`` hands that to
``AuthoringService``. Add a style by dropping a module here and registering it in ``STYLES``.
"""

from __future__ import annotations

from videogen.agent.creation_styles.split_broll import SPLIT_BROLL_PROMPT
from videogen.agent.prompts import SYSTEM_PROMPT

# The active style for real runs. Change this constant (or pass ``system=`` explicitly) to switch.
DEFAULT_STYLE = "classic"

STYLES: dict[str, str] = {
    "classic": SYSTEM_PROMPT,
    "split-broll": SPLIT_BROLL_PROMPT,
}


def get_style(name: str) -> str:
    """Return the system prompt for a named style, or raise ``KeyError`` with the known names."""
    try:
        return STYLES[name]
    except KeyError as exc:
        raise KeyError(f"unknown creation style {name!r}; known: {sorted(STYLES)}") from exc


def active() -> str:
    """The system prompt of the currently selected default style."""
    return STYLES[DEFAULT_STYLE]
