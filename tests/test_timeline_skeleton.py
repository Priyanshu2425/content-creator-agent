"""Timeline skeleton merge (restructure/04): the deterministic cross-layer change scaffold.

The former IdealCuts planning is folded into the Director; the pure, testable part is this merge —
hard cuts + caption cadence + the reserved hook window collapsed into one sorted, de-duplicated
change list. No LLM: given timings in, a change list out.
"""

from __future__ import annotations

from videogen.agent.timeline_skeleton import TimelineSkeleton, build_skeleton


class _Word:
    def __init__(self, text: str, start: float, end: float) -> None:
        self.text, self.start, self.end = text, start, end


class _Transcript:
    def __init__(self, starts: list[float]) -> None:
        self.words = [_Word(f"w{i}", s, s + 0.2) for i, s in enumerate(starts)]


def test_change_list_is_sorted_deduped_and_reserves_the_hook_window_start() -> None:
    transcript = _Transcript([0.1, 0.5, 0.6, 2.0, 2.1, 4.0])
    skel = build_skeleton(
        transcript=transcript,
        duration=5.0,
        hard_cuts=(4.0,),
        hook_window=(0.0, 3.0),
        min_change_interval=1.5,
    )

    assert isinstance(skel, TimelineSkeleton)
    # 0.0 (hook start) kept; near-neighbours within 1.5s collapsed; 4.0 hard cut survives
    assert skel.change_list == (0.0, 2.0, 4.0)
    assert skel.change_list[0] == 0.0  # the hook window start is always a change (frame-one hook)
    assert list(skel.change_list) == sorted(skel.change_list)


def test_caption_cadence_is_the_word_start_times() -> None:
    transcript = _Transcript([0.1, 0.9, 2.0])
    skel = build_skeleton(transcript=transcript, duration=5.0)
    assert skel.caption_cadence == (0.1, 0.9, 2.0)


def test_hard_cuts_are_merged_into_the_change_list() -> None:
    transcript = _Transcript([0.1])
    skel = build_skeleton(
        transcript=transcript, duration=10.0, hard_cuts=(5.0, 8.0), min_change_interval=1.0
    )
    assert 5.0 in skel.change_list and 8.0 in skel.change_list


def test_timestamps_past_the_duration_are_dropped() -> None:
    transcript = _Transcript([0.1, 4.0, 99.0])  # 99 is past the end
    skel = build_skeleton(transcript=transcript, duration=5.0, min_change_interval=0.5)
    assert all(t <= 5.0 for t in skel.change_list)


def test_empty_transcript_still_yields_the_hook_window_start() -> None:
    skel = build_skeleton(transcript=_Transcript([]), duration=5.0)
    assert skel.change_list == (0.0,)


def test_summary_is_compact_text_for_the_director() -> None:
    skel = build_skeleton(transcript=_Transcript([0.1, 2.0]), duration=5.0)
    summary = skel.summary()
    assert isinstance(summary, str)
    assert "hook" in summary.lower()
