"""ChainConfig: the chain pipeline's knobs (ADR 0013).

``tot_enabled`` is genuinely per-worker (ADR 0011 -- only the creative-direction and text-hook
workers have ToT variants, and both are Gemini-only). The CLI exposes a single coarse ``--tot`` flag
that flips both, but the granularity lives here so a later experiment can isolate one worker's ToT
contribution without new CLI surface. ``BeatPlan`` is *not* a knob -- it is forced on in the chain
(beat-keyed placement is the chain's contract), so there is no field for it.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChainConfig:
    """Per-worker ToT selection for a chain run. Both default off (ADR 0011).

    ``hook_enabled`` toggles the opening text-hook end-to-end (ADR 0013): when off (the default), the
    chain does NOT dispatch the text-hook worker and does NOT attach ``composition.hook``, so the
    Remotion hook card is never rendered. The capability is disabled, not removed -- ``--hook``
    re-enables it.
    """

    creative_direction_tot: bool = False
    text_hook_tot: bool = False
    hook_enabled: bool = False

    @property
    def any_tot(self) -> bool:
        """True when any worker wants its ToT variant -- the signal the CLI uses to require Gemini."""
        return self.creative_direction_tot or self.text_hook_tot

    @classmethod
    def from_flag(cls, tot: bool) -> "ChainConfig":
        """Build the config the coarse ``--tot`` CLI flag implies: on flips *both* ToT workers."""
        return cls(creative_direction_tot=tot, text_hook_tot=tot)
