"""VIDEOGEN_BEAT_PLAN_ENABLED defaults ON (ADR 0012, beat-plan/01).

The typed BeatPlan path is the intended default behaviour, so an unset (or empty) flag enables it --
unlike tot_enabled, which defaults off. A falsey value selects the legacy prose fallback.
"""

from __future__ import annotations

import pytest

from videogen.app.cli import _flag_on


def test_unset_flag_uses_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VIDEOGEN_BEAT_PLAN_ENABLED", raising=False)
    assert _flag_on("VIDEOGEN_BEAT_PLAN_ENABLED", default=True) is True


def test_empty_flag_uses_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VIDEOGEN_BEAT_PLAN_ENABLED", "")
    assert _flag_on("VIDEOGEN_BEAT_PLAN_ENABLED", default=True) is True


@pytest.mark.parametrize("value", ["0", "false", "no", "off"])
def test_falsey_values_disable(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("VIDEOGEN_BEAT_PLAN_ENABLED", value)
    assert _flag_on("VIDEOGEN_BEAT_PLAN_ENABLED", default=True) is False


@pytest.mark.parametrize("value", ["1", "true", "yes", "on"])
def test_truthy_values_enable(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("VIDEOGEN_BEAT_PLAN_ENABLED", value)
    assert _flag_on("VIDEOGEN_BEAT_PLAN_ENABLED", default=False) is True
