"""CLI surface for the chain pipeline: --pipeline / --tot (ADR 0013, slices 02/10).

These exercise argument parsing and the ToT configuration seam (env selection + the Gemini-missing
error). They do not run a full pipeline.
"""

from __future__ import annotations

import pytest

from videogen.app import cli


def _parse(argv):
    return cli._build_parser().parse_args(argv)


def test_pipeline_defaults_to_director_loop() -> None:
    args = _parse(["make", "--host", "h.mp4", "--brief", "b"])
    assert args.pipeline == "director-loop"
    assert args.tot is False


def test_pipeline_and_tot_flags_parse() -> None:
    args = _parse(["make", "--host", "h.mp4", "--brief", "b", "--pipeline", "chain", "--tot"])
    assert args.pipeline == "chain"
    assert args.tot is True


def test_invalid_pipeline_choice_is_rejected() -> None:
    with pytest.raises(SystemExit):
        _parse(["make", "--host", "h.mp4", "--brief", "b", "--pipeline", "nope"])


def test_tot_without_gemini_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_has_gemini_api_key", lambda: False)
    with pytest.raises(SystemExit):
        cli._configure_tot(tot=True, pipeline_name="director-loop")


def test_tot_selects_both_workers_on_director_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_has_gemini_api_key", lambda: True)
    for var in ("VIDEOGEN_TOT_CREATIVE_DIRECTION", "VIDEOGEN_TOT_TEXT_HOOK"):
        monkeypatch.delenv(var, raising=False)
    cfg = cli._configure_tot(tot=True, pipeline_name="director-loop")
    assert cfg.creative_direction_tot is True and cfg.text_hook_tot is True


def test_tot_on_chain_keeps_creative_direction_on_beatplan(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_has_gemini_api_key", lambda: True)
    for var in ("VIDEOGEN_TOT_CREATIVE_DIRECTION", "VIDEOGEN_TOT_TEXT_HOOK"):
        monkeypatch.delenv(var, raising=False)
    cfg = cli._configure_tot(tot=True, pipeline_name="chain")
    # CD-ToT does not yet emit a BeatPlan, so the chain keeps CD on its BeatPlan path; hook flips.
    assert cfg.creative_direction_tot is False
    assert cfg.text_hook_tot is True


def test_chain_forces_beat_plan_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VIDEOGEN_BEAT_PLAN_ENABLED", raising=False)
    cli._configure_tot(tot=False, pipeline_name="chain")
    import os

    assert os.environ["VIDEOGEN_BEAT_PLAN_ENABLED"] == "1"
