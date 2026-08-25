"""Post-Composer reconcile: base captions + animate stills (ADR 0013).

Pure deterministic step over an emitted Composition -- a fake Composition + transcript exercise it,
no model. Asserts the two behaviors and that it doesn't double-fill captions or animate non-stills.
"""

from __future__ import annotations

from dataclasses import dataclass

from videogen.agent.chain.reconcile import reconcile
from videogen.kernel.composition import (
    Asset,
    AssetType,
    Audio,
    Caption,
    Composition,
    Hook,
    LayoutName,
    Ref,
    RegionName,
    Scene,
)


@dataclass(frozen=True)
class _Word:
    text: str
    start: float
    end: float


@dataclass(frozen=True)
class _Transcript:
    words: list[_Word]


TRANSCRIPT = _Transcript([_Word("hello", 0.0, 1.0), _Word("world", 1.0, 2.0), _Word("now", 2.0, 5.0)])


def _comp(scenes, *, captions=(), overlays=()) -> Composition:
    return Composition(
        assets={
            "host": Asset(type=AssetType.video, src="host.mp4"),
            "img": Asset(type=AssetType.image, src="img.png"),
        },
        voiceover=Audio(asset="host"),
        scenes=scenes,
        captions=list(captions),
        overlays=list(overlays),
    )


def _scene(sid, start, end, asset) -> Scene:
    return Scene(id=sid, start=start, end=end, layout=LayoutName.full,
                 regions={RegionName.full: Ref(asset=asset)})


def test_base_captions_filled_in_brand_style() -> None:
    comp = _comp([_scene("s0", 0.0, 5.0, "host")])
    out = reconcile(comp, transcript=TRANSCRIPT, duration=5.0, caption_style="tiktok")
    assert len(out.captions) >= 1
    assert all(c.style == "tiktok" for c in out.captions)


def test_long_still_gets_a_zoom() -> None:
    comp = _comp([_scene("s0", 0.0, 5.0, "img")])  # 5s static image
    out = reconcile(comp, transcript=TRANSCRIPT, duration=5.0)
    zooms = [o for o in out.overlays if getattr(o, "type", None) == "zoom"]
    assert len(zooms) == 1
    assert zooms[0].start == 0.0 and zooms[0].end == 5.0


def test_short_still_is_left_alone() -> None:
    comp = _comp([_scene("s0", 0.0, 0.8, "img"), _scene("s1", 0.8, 5.0, "host")])
    out = reconcile(comp, transcript=TRANSCRIPT, duration=5.0)
    assert [o for o in out.overlays if getattr(o, "type", None) == "zoom"] == []


def test_video_scene_is_not_animated() -> None:
    comp = _comp([_scene("s0", 0.0, 5.0, "host")])  # host is video, not image
    out = reconcile(comp, transcript=TRANSCRIPT, duration=5.0)
    assert [o for o in out.overlays if getattr(o, "type", None) == "zoom"] == []


def test_existing_captions_are_not_double_filled() -> None:
    existing = Caption(text="kept", start=0.0, end=1.0, style="tiktok")
    comp = _comp([_scene("s0", 0.0, 5.0, "host")], captions=[existing])
    out = reconcile(comp, transcript=TRANSCRIPT, duration=5.0)
    assert out.captions == [existing]


def test_hook_is_set_on_the_composition() -> None:
    comp = _comp([_scene("s0", 0.0, 5.0, "host")])
    hook = Hook(text="what if 12 year olds build the next AI startup?", duration=3.0)
    out = reconcile(comp, transcript=TRANSCRIPT, duration=5.0, hook=hook)
    assert out.hook is not None and out.hook.text.startswith("what if")


def test_hook_suppresses_captions_in_its_window() -> None:
    # Captions at 0-1s and 1-2s fall inside a 3s hook; a 3.5-5s caption survives.
    caps = [
        Caption(text="early one", start=0.0, end=1.0, style="tiktok"),
        Caption(text="early two", start=1.0, end=2.0, style="tiktok"),
        Caption(text="after hook", start=3.5, end=5.0, style="tiktok"),
    ]
    comp = _comp([_scene("s0", 0.0, 5.0, "host")], captions=caps)
    out = reconcile(comp, transcript=TRANSCRIPT, duration=5.0, hook=Hook(text="hi", duration=3.0))
    kept = [c.text for c in out.captions]
    assert kept == ["after hook"]  # only the caption ending after the hook window survives


def test_no_hook_leaves_captions_untouched() -> None:
    caps = [Caption(text="keep me", start=0.0, end=1.0, style="tiktok")]
    comp = _comp([_scene("s0", 0.0, 5.0, "host")], captions=caps)
    out = reconcile(comp, transcript=TRANSCRIPT, duration=5.0, hook=None)
    assert [c.text for c in out.captions] == ["keep me"]
    assert out.hook is None
