"""Shared google-genai client factory: ADC/Vertex vs API-key selection (ADC migration)."""

from __future__ import annotations

import google.genai as genai
import pytest

import videogen.genai_client as gc


class _FakeClient:
    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs


@pytest.fixture(autouse=True)
def _fake_genai(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(genai, "Client", _FakeClient)
    for var in (
        "GOOGLE_GENAI_USE_VERTEXAI",
        "GOOGLE_CLOUD_PROJECT",
        "GOOGLE_CLOUD_LOCATION",
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)


def test_adc_vertex_mode_passes_project_and_location_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "true")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "my-proj")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "europe-west4")

    client = gc.build_genai_client(api_key="ignored-in-adc")

    assert client.kwargs == {"vertexai": True, "project": "my-proj", "location": "europe-west4"}


def test_adc_mode_defaults_location_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "true")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "p")

    client = gc.build_genai_client()
    assert client.kwargs["location"] == "us-central1"


def test_api_key_mode_when_vertex_not_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "secret")
    client = gc.build_genai_client()
    assert client.kwargs == {"api_key": "secret"}


def test_have_gemini_credentials_reflects_either_path(monkeypatch: pytest.MonkeyPatch) -> None:
    assert not gc.have_gemini_credentials()  # nothing set
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "true")
    assert gc.have_gemini_credentials()  # ADC
    monkeypatch.delenv("GOOGLE_GENAI_USE_VERTEXAI")
    monkeypatch.setenv("GOOGLE_API_KEY", "k")
    assert gc.have_gemini_credentials()  # api key
