"""VisionAdvisor: the seam a blind authoring client uses to borrow a vision-capable model's eyes.

Some ``ModelClient``s have no image-input channel (``ClaudeCodeClient`` and the Gemini/OpenAI
adapters drop image ``ToolResult``s). Rather than author blind, the loop offers such a client the
``consult_placement`` tool, which renders the current frame and asks a ``VisionAdvisor`` for
**text** advice on placement / framing / cropping / occlusion -- a text-return vision channel
replacing the image-return one the client cannot use (ADR 0007).

This module holds only the neutral Protocol so the loop and services depend on the shape, never on a
provider SDK -- the same split as ``review.py`` (Protocol) and ``gemini_review.py`` (concrete
Gemini). The concrete ``GeminiVisionAdvisor`` is imported only where the pipeline is wired.
"""

from __future__ import annotations

from typing import Protocol


class VisionAdvisor(Protocol):
    """Looks at one rendered frame and answers a text question about it.

    ``image`` is PNG bytes of the current composition rendered at some second; ``question`` is the
    authoring agent's free-text ask; ``context`` is loop-supplied framing (the composition + the
    Resolver timeline + where in time the frame is). Returns free-text advice the (blind) agent can
    translate into Builder ops.
    """

    def advise(self, *, image: bytes, question: str, context: str) -> str: ...
