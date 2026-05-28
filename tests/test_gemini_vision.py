"""GeminiVisionAdvisor: the real VisionAdvisor over google-genai (ADR 0007).

The generate call is gated behind an API key and the SDK, so these tests cover the deterministic
part that is ours: ``advise`` sends the still as an INLINE image part (no video-style upload) plus
the question + context, and returns the model's text (coercing a ``None`` reply to ""). A fake
client records the call -- no key, no network. The real placement judgement runs only live.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from videogen.agent.gemini_vision import GeminiVisionAdvisor


class _FakeGenai:
    """A stand-in google-genai client: records the generate call, returns canned text. Its upload
    endpoint asserts if touched -- the advisor must send the still inline, not upload it."""

    def __init__(self, text: str | None) -> None:
        self._text = text
        self.gen_kwargs: dict[str, Any] = {}
        self.uploaded = False
        self.files = SimpleNamespace(upload=self._upload)
        self.models = SimpleNamespace(generate_content=self._generate)

    def _upload(self, **_kwargs: Any) -> Any:  # pragma: no cover - must not be called
        self.uploaded = True
        raise AssertionError("the advisor must send the still inline, not upload it")

    def _generate(self, **kwargs: Any) -> Any:
        self.gen_kwargs = kwargs
        return SimpleNamespace(text=self._text)


def test_advise_sends_an_inline_image_and_returns_the_models_text() -> None:
    client = _FakeGenai("shift the host crop down ~10% so the head isn't cut")
    advisor = GeminiVisionAdvisor(client=client)

    advice = advisor.advise(
        image=b"\x89PNGpix", question="is the host's face cut off?", context="0-2s host full"
    )

    assert advice == "shift the host crop down ~10% so the head isn't cut"
    assert not client.uploaded  # inline, never uploaded
    contents = client.gen_kwargs["contents"]
    image_part = contents[0]
    assert image_part["inline_data"]["mime_type"] == "image/png"
    assert image_part["inline_data"]["data"] == b"\x89PNGpix"
    assert "is the host's face cut off?" in contents[1]  # the question rides in the prompt
    assert "0-2s host full" in contents[1]  # so does the loop-supplied context


def test_advise_coerces_a_none_text_reply_to_empty_string() -> None:
    advisor = GeminiVisionAdvisor(client=_FakeGenai(None))

    assert advisor.advise(image=b"x", question="q", context="c") == ""
