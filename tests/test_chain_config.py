"""ChainConfig: per-worker ToT knobs (ADR 0011/0013, slice 10)."""

from __future__ import annotations

from videogen.agent.chain.config import ChainConfig


def test_defaults_off() -> None:
    cfg = ChainConfig()
    assert cfg.creative_direction_tot is False
    assert cfg.text_hook_tot is False
    assert cfg.any_tot is False


def test_from_flag_flips_both() -> None:
    cfg = ChainConfig.from_flag(True)
    assert cfg.creative_direction_tot is True
    assert cfg.text_hook_tot is True
    assert cfg.any_tot is True


def test_any_tot_true_when_one_worker_on() -> None:
    assert ChainConfig(text_hook_tot=True).any_tot is True
    assert ChainConfig(creative_direction_tot=True).any_tot is True
