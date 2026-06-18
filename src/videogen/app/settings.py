"""Run configuration loaded from ``settings.json`` -- one place to pick models, style, and bounds.

``cli.build_default_pipeline`` reads a ``Settings`` to decide which authoring ``ModelClient`` (and
model) drives the loop, which creation style (system prompt) it authors under, which Gemini models
back the reviewer and the placement advisor, and the review round cap. Switching any of these is an
edit to ``settings.json``, not to code.

The file is optional and additive: every field has a default that reproduces the shipped behavior,
and an absent file uses all defaults. ``extra="forbid"`` turns a typo'd key into a clear error
rather than a silently ignored setting. Secrets never live here -- API keys stay in ``.env``;
``settings.json`` carries only non-secret choices, so it is safe to commit.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict

# Looked up relative to the working directory the CLI is run from (the repo root, where renders/
# is also created). Absent -> all defaults.
DEFAULT_PATH = Path("settings.json")


class Settings(BaseModel):
    """Non-secret run configuration. Unknown keys are rejected so mistakes surface immediately."""

    model_config = ConfigDict(extra="forbid")

    # Which authoring ModelClient drives the loop. Known names are the keys of
    # ``cli._AUTHORING_CLIENTS`` (claude-code, gemini, anthropic, nvidia, perplexity).
    authoring_client: str = "gemini"
    # The model id for that client. ``null`` keeps the client's own default (e.g. claude-code ->
    # claude-sonnet-4-6; claude-code with null also follows the CLI's configured model).
    authoring_model: str | None = None
    # Which reviewer runs the finalization gate: "claude" reads the final Composition JSON via Claude
    # Code (structural/editorial review, the default); "gemini" watches the rendered mp4 for motion
    # issues. Gemini stays available -- this only chooses the default.
    review_client: str = "gemini"
    # The Gemini model for the full-motion review sub-agent and the placement advisor.
    reviewer_model: str = "gemini-2.5-flash-lite"
    advisor_model: str = "gemini-2.5-flash"
    # Nano Banana (Gemini 2.5 Flash Image) — the still-image model for GenerateBrollAgent.
    broll_image_model: str = "gemini-2.5-flash-image"
    # The finalization gate's bounded render -> review -> edit round cap.
    max_review_rounds: int = 2
    # Target platform for IdealCutsAgent and GenerateBrollAgent (e.g. Instagram, TikTok, Shorts).
    platform: str = "Instagram"
    # Gemini asset describer: when true, every non-voiceover asset is described before authoring.
    # Requires GOOGLE_API_KEY / GEMINI_API_KEY. Provides description + usage_advice per asset.
    asset_descriptions: bool = False
    describer_model: str = "gemini-2.5-flash-lite"


def load_settings(path: Path | None = None) -> Settings:
    """Load ``settings.json`` (defaulting to CWD); return all-defaults when the file is absent."""
    path = path or DEFAULT_PATH
    if not path.exists():
        return Settings()
    return Settings.model_validate_json(path.read_text(encoding="utf-8"))
