"""Run configuration: settings.json drives the CLI's model/style/bounds choices (app.settings).

These assert the loader's externally observable contract -- defaults reproduce the shipped behavior,
an absent file is fine, a present file overrides per field, and an unknown key is a hard error (not
a silent no-op) -- plus that every settings ``authoring_client`` name resolves to a real adapter in
the clients package. No models or SDKs are constructed here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from videogen.app.cli import _AUTHORING_CLIENTS
from videogen.app.settings import Settings, load_settings


def test_absent_file_uses_all_defaults(tmp_path: Path) -> None:
    settings = load_settings(tmp_path / "nope.json")

    assert settings.authoring_client == "openrouter"
    assert settings.authoring_model == "deepseek/deepseek-v4-flash"
    assert settings.reviewer_model == "gemini-2.5-flash-lite"
    assert settings.max_review_rounds == 2


def test_file_overrides_named_fields_and_keeps_other_defaults(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"platform": "TikTok", "authoring_model": "claude-opus-4-7"})
    )

    settings = load_settings(path)

    assert settings.platform == "TikTok"  # overridden
    assert settings.authoring_model == "claude-opus-4-7"  # overridden
    assert settings.authoring_client == "openrouter"  # untouched default
    assert settings.advisor_model == "gemini-2.5-flash"  # untouched default


def test_an_unknown_key_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"styl": "split-broll"}))  # typo'd key

    with pytest.raises(ValidationError):
        load_settings(path)


def test_the_committed_default_settings_file_loads_and_matches_defaults() -> None:
    # The repo's settings.json is the live config; it must stay loadable and on the defaults.
    settings = load_settings(Path("settings.json"))

    assert settings == Settings()


def test_every_authoring_client_name_maps_to_a_real_clients_adapter() -> None:
    from videogen.agent import clients

    for name, attr in _AUTHORING_CLIENTS.items():
        assert getattr(clients, attr) is not None, name
    # the default client name is one of the registered ones
    assert Settings().authoring_client in _AUTHORING_CLIENTS
