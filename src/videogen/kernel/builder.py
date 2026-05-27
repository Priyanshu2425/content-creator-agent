"""Builder: an imperative, entity-complete CRUD authoring API over a declarative Composition.

The Builder is the only place imperative authoring is sanctioned (ADR 0004): a caller drives it
operation-by-operation, and it compiles that operation stream down into the declarative Composition
document (ADR 0001) -- it is not a replay log, and the Resolver can always re-derive frame state
from the document it produces. Each operation:

1. builds a *candidate* document with the mutation applied (the live document is never touched in
   place),
2. validates the candidate against the two-tier Validator, and
3. commits the candidate only if it has no local errors. A rejected operation leaves the
   Composition exactly as it was (transactional per-op), so the authoring loop can retry after a
   hard error without a corrupted in-progress document (ADR 0004, user story 31).

Warnings never roll back: an operation that merely introduces a gap commits and reports the warning.
Op-precondition failures (an unknown scene id, a duplicate id, a bad caption index) are returned as
errors too, so the loop stays self-correcting rather than raising.

The Composition carries no duration; the voiceover (master clock, ADR 0005) sets it, so the Builder
is constructed with the probed ``duration`` and threads it to the Validator. Pure kernel: no service
or backend imports -- ``add_captions_from_transcript`` accepts any transcript-shaped object
structurally (a ``words`` sequence of text/start/end), never importing MediaService (ADR 0003).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from videogen.kernel.composition import (
    Asset,
    AssetId,
    Audio,
    Caption,
    CaptionStyle,
    Composition,
    LayoutName,
    Overlay,
    Ref,
    RegionName,
    Scene,
    Transition,
    TransitionKind,
)
from videogen.kernel.validator import (
    ErrorCode,
    GlobalWarning,
    LocalError,
    ValidationResult,
    can_submit_render,
    validate,
)


class TranscriptWord(Protocol):
    """A word-timed transcript entry: text plus start/end on the absolute-seconds Timeline."""

    @property
    def text(self) -> str: ...
    @property
    def start(self) -> float: ...
    @property
    def end(self) -> float: ...


class TranscriptLike(Protocol):
    """Anything exposing an ordered ``words`` sequence -- e.g. MediaService's ``Transcript``."""

    @property
    def words(self) -> Sequence[TranscriptWord]: ...


@dataclass(frozen=True)
class OpResult:
    """The outcome of a single Builder operation: the validation result plus the entity it touched.

    Same ``{ok, errors, warnings}`` shape as a ``ValidationResult`` (the submit gate reads ``ok``,
    which counts local errors only), extended with ``entity_ref`` -- the id (a Scene) or handle (a
    Caption) the operation created or addressed, so a caller can key transitions/edits off it.
    """

    ok: bool
    errors: tuple[LocalError, ...]
    warnings: tuple[GlobalWarning, ...]
    entity_ref: str | None = None


class Builder:
    """Wraps an in-memory Composition and exposes validated CRUD operations over its entities."""

    def __init__(self, composition: Composition, *, duration: float) -> None:
        self._composition = composition
        self._duration = duration
        self._scene_seq = 0

    @classmethod
    def new(
        cls,
        *,
        voiceover: AssetId,
        duration: float,
        assets: dict[AssetId, Asset] | None = None,
        version: int = 1,
        strict: bool = True,
    ) -> Builder:
        """Start a fresh Builder from the media facts: the voiceover asset and the declared library.

        Assets are objective facts (MediaService ingest, ADR 0003), so they are seeded here rather
        than authored; the Builder then adds the creative entities (scenes, captions) on top.
        """
        composition = Composition(
            version=version,
            strict=strict,
            assets=assets or {},
            voiceover=Audio(asset=voiceover),
        )
        return cls(composition, duration=duration)

    # --- the current document + on-demand validation (user story 33) ---

    @property
    def composition(self) -> Composition:
        """The current declarative document built so far."""
        return self._composition

    def validate(self) -> ValidationResult:
        """Re-run both validation tiers over the whole document (not just the last mutation)."""
        return validate(self._composition, duration=self._duration)

    def can_submit_render(self) -> bool:
        """The submit gate for the current document: true iff it has no outstanding local errors."""
        return can_submit_render(self._composition, duration=self._duration)

    # --- create ---

    def add_scene(
        self,
        layout: LayoutName,
        start: float,
        end: float,
        *,
        id: str | None = None,
        layout_params: dict[str, float] | None = None,
    ) -> OpResult:
        """Append a Scene to the ordered base layer with ``layout`` and a stable id (assigned if
        omitted). ``layout_params`` carries the Layout's preset parameters (e.g. ``split-h``'s
        ``ratio``), validated by the Layout's contract; an out-of-range value rejects the op. The
        new Scene fills no regions yet -- use ``fill_region``."""
        sid = id if id is not None else self._next_scene_id()
        if any(scene.id == sid for scene in self._composition.scenes):
            return _reject(ErrorCode.DUPLICATE_SCENE_ID, f"scene id '{sid}' already exists", sid)
        scene = Scene(
            id=sid,
            start=start,
            end=end,
            layout=layout,
            regions={},
            layout_params=layout_params or {},
        )
        candidate = self._composition.model_copy(
            update={"scenes": [*self._composition.scenes, scene]}
        )
        return self._commit(candidate, sid)

    def add_transition(
        self,
        after_scene: str,
        kind: TransitionKind = TransitionKind.crossfade,
        *,
        duration: float = 0.5,
    ) -> OpResult:
        """Add a non-cut Transition to the sparse ``transitions`` array, keyed by the Scene it
        follows (ADR 0001). A cut is the default boundary and is never authored; this adds only the
        boundaries that differ. An ``after_scene`` with no matching Scene rejects the op."""
        if self._scene_index(after_scene) is None:
            return _reject(
                ErrorCode.DANGLING_TRANSITION, f"no scene with id '{after_scene}'", after_scene
            )
        transition = Transition(after_scene=after_scene, kind=kind, duration=duration)
        candidate = self._composition.model_copy(
            update={"transitions": [*self._composition.transitions, transition]}
        )
        return self._commit(candidate, after_scene)

    def fill_region(
        self, scene_id: str, region: RegionName, asset_id: AssetId, *, in_point: float | None = None
    ) -> OpResult:
        """Place a Reference to an Asset into a Region of a Scene (overwrites any existing fill)."""
        index = self._scene_index(scene_id)
        if index is None:
            return _reject(ErrorCode.UNKNOWN_SCENE, f"no scene with id '{scene_id}'", scene_id)
        scene = self._composition.scenes[index]
        new_regions = {**scene.regions, region: Ref(asset=asset_id, in_point=in_point)}
        new_scene = scene.model_copy(update={"regions": new_regions})
        return self._commit(self._with_scene(index, new_scene), scene_id)

    def add_overlay(self, overlay: Overlay) -> OpResult:
        """Add an effect overlay (zoom/pan/insert) through the shared ``addOverlay`` envelope.

        One generic op for every overlay type (ADR 0001): the caller hands in a fully-typed overlay,
        so the fixed core schema has already validated the envelope, and the per-op two-phase
        validation then vets the type-specific params via ``registry[type]`` plus the target-region
        and asset checks. The op commits only if the candidate has no local errors; a rejection
        leaves the overlays list untouched (transactional, like every other Builder op)."""
        overlays = [*self._composition.overlays, overlay]
        candidate = self._composition.model_copy(update={"overlays": overlays})
        return self._commit(candidate, f"overlay[{len(overlays) - 1}]")

    def add_caption(
        self, text: str, start: float, end: float, style: CaptionStyle = CaptionStyle.pill
    ) -> OpResult:
        """Append one Caption to the dedicated captions track."""
        caption = Caption(text=text, start=start, end=end, style=style)
        captions = [*self._composition.captions, caption]
        candidate = self._composition.model_copy(update={"captions": captions})
        return self._commit(candidate, f"caption[{len(captions) - 1}]")

    def add_captions_from_transcript(
        self, transcript: TranscriptLike, *, style: CaptionStyle = CaptionStyle.pill
    ) -> OpResult:
        """Batch-create Captions from word-timed transcript output, one Caption per word.

        Word timings are mapped onto the canonical absolute-seconds Timeline (MediaService already
        reports seconds, so this is a direct map; the seam is where a non-seconds representation
        would convert). The whole batch is validated as a single operation: if any caption is out
        of bounds the batch is rejected and the track is left unchanged.
        """
        new_captions = [
            Caption(text=word.text, start=word.start, end=word.end, style=style)
            for word in transcript.words
        ]
        candidate = self._composition.model_copy(
            update={"captions": [*self._composition.captions, *new_captions]}
        )
        return self._commit(candidate, None)

    # --- read ---

    def get_scene(self, scene_id: str) -> Scene | None:
        """Return the current state of a Scene by id, or ``None`` if no such Scene exists."""
        index = self._scene_index(scene_id)
        return self._composition.scenes[index] if index is not None else None

    def get_caption(self, index: int) -> Caption | None:
        """Return the Caption at ``index`` on the captions track, or ``None`` if out of range."""
        captions = self._composition.captions
        return captions[index] if 0 <= index < len(captions) else None

    # --- update ---

    def retime_scene(self, scene_id: str, *, start: float, end: float) -> OpResult:
        """Move a Scene's span on the timeline in place."""
        index = self._scene_index(scene_id)
        if index is None:
            return _reject(ErrorCode.UNKNOWN_SCENE, f"no scene with id '{scene_id}'", scene_id)
        scene = self._composition.scenes[index]
        new_scene = scene.model_copy(update={"start": start, "end": end})
        return self._commit(self._with_scene(index, new_scene), scene_id)

    def update_caption(
        self,
        index: int,
        *,
        text: str | None = None,
        start: float | None = None,
        end: float | None = None,
        style: CaptionStyle | None = None,
    ) -> OpResult:
        """Retime, restyle, or re-text a Caption in place. Unspecified fields are left untouched."""
        captions = self._composition.captions
        if not 0 <= index < len(captions):
            entity = f"caption[{index}]"
            return _reject(ErrorCode.UNKNOWN_CAPTION, f"no caption at index {index}", entity)
        updates = {
            key: value
            for key, value in (("text", text), ("start", start), ("end", end), ("style", style))
            if value is not None
        }
        new_caption = captions[index].model_copy(update=updates)
        return self._commit(self._with_caption(index, new_caption), f"caption[{index}]")

    # --- delete ---

    def delete_scene(self, scene_id: str) -> OpResult:
        """Remove a Scene by id, making the Builder entity-complete (full CRUD)."""
        if self._scene_index(scene_id) is None:
            return _reject(ErrorCode.UNKNOWN_SCENE, f"no scene with id '{scene_id}'", scene_id)
        remaining = [scene for scene in self._composition.scenes if scene.id != scene_id]
        return self._commit(self._composition.model_copy(update={"scenes": remaining}), scene_id)

    def delete_caption(self, index: int) -> OpResult:
        """Remove the Caption at ``index`` on the captions track."""
        captions = self._composition.captions
        entity = f"caption[{index}]"
        if not 0 <= index < len(captions):
            return _reject(ErrorCode.UNKNOWN_CAPTION, f"no caption at index {index}", entity)
        remaining = [*captions[:index], *captions[index + 1 :]]
        candidate = self._composition.model_copy(update={"captions": remaining})
        return self._commit(candidate, entity)

    # --- internals ---

    def _scene_index(self, scene_id: str) -> int | None:
        for index, scene in enumerate(self._composition.scenes):
            if scene.id == scene_id:
                return index
        return None

    def _with_scene(self, index: int, scene: Scene) -> Composition:
        scenes = [*self._composition.scenes]
        scenes[index] = scene
        return self._composition.model_copy(update={"scenes": scenes})

    def _with_caption(self, index: int, caption: Caption) -> Composition:
        captions = [*self._composition.captions]
        captions[index] = caption
        return self._composition.model_copy(update={"captions": captions})

    def _next_scene_id(self) -> str:
        existing = {scene.id for scene in self._composition.scenes}
        while True:
            sid = f"s{self._scene_seq}"
            self._scene_seq += 1
            if sid not in existing:
                return sid

    def _commit(self, candidate: Composition, entity_ref: str | None) -> OpResult:
        """Validate the candidate; commit only if it has no local errors (transactional per-op)."""
        result = validate(candidate, duration=self._duration)
        if result.ok:
            self._composition = candidate
        return OpResult(
            ok=result.ok, errors=result.errors, warnings=result.warnings, entity_ref=entity_ref
        )


def _reject(code: ErrorCode, message: str, entity_ref: str | None) -> OpResult:
    """Build a failed OpResult for an op-precondition violation, without touching the document."""
    return OpResult(
        ok=False,
        errors=(LocalError(code, message, entity_ref),),
        warnings=(),
        entity_ref=entity_ref,
    )
