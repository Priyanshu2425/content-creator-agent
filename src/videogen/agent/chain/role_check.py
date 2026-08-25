"""The chain's wrong-role back-fill guard (ADR 0013), a pure predicate over an emitted Composition.

The chain lets the Composer place assets with an LLM (it opted out of the director-loop's deterministic
``execute``). That re-opens exactly one diagnosed failure: an asset generated for one narrative role
landing on a beat of a *different* role (ADR 0012's "wrong-role back-fill" -- warm world-1 assets in the
resolution slot). That failure is cheaply checkable on the output, because beats are role-typed and
generated assets are beat-keyed: the role the asset was *made for* must equal the role of the beat that
*occupies the span it landed on*.

This module is the check, kept pure so it has no model/Builder dependency. The Composer runs it after
generation and re-prompts on any violation; a fake Composition + resolved beats fully exercise it.
"""

from __future__ import annotations

from dataclasses import dataclass

from videogen.agent.chain.prep import ResolvedBeat
from videogen.kernel.composition import Composition


@dataclass(frozen=True)
class RoleViolation:
    """One placed asset whose source-beat role disagrees with the role occupying its landing span."""

    asset_id: str
    source_role: str
    landed_role: str
    scene_id: str

    def describe(self) -> str:
        return (
            f"asset {self.asset_id!r} was generated for a {self.source_role!r} beat but landed on "
            f"scene {self.scene_id!r}, whose span belongs to a {self.landed_role!r} beat -- "
            f"wrong-role back-fill is forbidden (ADR 0012/0013)"
        )


def wrong_role_backfill_violations(
    composition: Composition, resolved_beats: list[ResolvedBeat]
) -> list[RoleViolation]:
    """Return every placed beat-keyed asset that landed on a span owned by a different-role beat.

    Only assets the chain *knows the source role of* (the beat-keyed generated assets in
    ``resolved_beats``) are subject to the rule. The host track and any untracked asset are skipped --
    they have no source beat, so "wrong role" is undefined for them.
    """
    source_role = {
        rb.asset.asset_id: rb.beat.role for rb in resolved_beats if rb.asset is not None
    }
    spans = [(rb.start_s, rb.end_s, rb.beat.role) for rb in resolved_beats]

    violations: list[RoleViolation] = []
    for scene in composition.scenes:
        landed = _occupying_role(scene.start, scene.end, spans)
        if landed is None:
            continue
        for ref in scene.regions.values():
            src = source_role.get(ref.asset)
            if src is not None and src != landed:
                violations.append(
                    RoleViolation(
                        asset_id=ref.asset,
                        source_role=src,
                        landed_role=landed,
                        scene_id=scene.id,
                    )
                )
    return violations


def _occupying_role(
    start: float, end: float, spans: list[tuple[float, float, str]]
) -> str | None:
    """The role of the beat whose span overlaps ``[start, end]`` the most (None if none overlap)."""
    best_role: str | None = None
    best_overlap = 0.0
    for s_start, s_end, role in spans:
        overlap = min(end, s_end) - max(start, s_start)
        if overlap > best_overlap:
            best_overlap = overlap
            best_role = role
    return best_role
