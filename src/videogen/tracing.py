"""Optional Langfuse tracing — active when LANGFUSE_PUBLIC_KEY is set, no-op otherwise.

Import this module only AFTER load_dotenv() has been called so Langfuse initialises with
the correct credentials (the SDK reads env vars at init time).

All context managers are safe to call unconditionally — they yield None and do nothing when
tracing is disabled. This keeps instrumentation code clean: no `if tracing.enabled` guards
at call sites.

Sensitive data policy:
- Briefs and prompts are captured (they are the meaningful inputs).
- File system paths are reduced to basenames only.
- System prompts are not captured verbatim (they are long and constant); only their length
  is recorded so the Langfuse UI stays readable.
- API keys, credentials, and internal config objects are never passed to any tracing call.
"""

from __future__ import annotations

import os
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any


def enabled() -> bool:
    """True when LANGFUSE_PUBLIC_KEY is present in the environment."""
    return bool(os.environ.get("LANGFUSE_PUBLIC_KEY"))


def _lf() -> Any:
    """Return the Langfuse singleton client. Imported lazily to avoid SDK init before dotenv."""
    from langfuse import get_client  # noqa: PLC0415

    return get_client()


def _client_or_none() -> Any | None:
    """Langfuse client when tracing is enabled and installed; otherwise None."""
    if not enabled():
        return None
    try:
        return _lf()
    except ImportError:
        return None


def _propagate_attributes(**kwargs: Any) -> Any:
    from langfuse import propagate_attributes  # noqa: PLC0415

    return propagate_attributes(**kwargs)


# ---------------------------------------------------------------------------
# Root trace — one per pipeline run
# ---------------------------------------------------------------------------


@contextmanager
def pipeline_trace(
    *,
    brief: str,
    platform: str,
    host: str,
    creation_style: str = "classic",
) -> Generator[Any, None, None]:
    """Root Langfuse trace for a full videogen pipeline run.

    Always call flush() after the pipeline exits so events are flushed in this
    short-lived process. The context manager handles it automatically.
    """
    lf = _client_or_none()
    if lf is None:
        yield None
        return
    with lf.start_as_current_observation(
        as_type="trace",
        name="videogen-pipeline",
        input={"brief": brief, "platform": platform},
    ) as trace:
        with _propagate_attributes(
            tags=[platform, creation_style],
            metadata={"host_filename": os.path.basename(host)},
        ):
            yield trace
    lf.flush()


def update_pipeline_output(output_path: str) -> None:
    """Record the final mp4 path as the pipeline trace output."""
    if not enabled():
        return
    try:
        _lf().update_current_span(output={"output_file": os.path.basename(output_path)})
    except Exception:
        # Tracing is best-effort only; never fail the pipeline on context gaps.
        return


# ---------------------------------------------------------------------------
# Stage spans — one per named pipeline stage
# ---------------------------------------------------------------------------


@contextmanager
def stage_span(name: str) -> Generator[Any, None, None]:
    """Langfuse span wrapping one pipeline stage (ingest, transcribe, author, …)."""
    lf = _client_or_none()
    if lf is None:
        yield None
        return
    with lf.start_as_current_observation(as_type="span", name=f"stage:{name}") as span:
        yield span


# ---------------------------------------------------------------------------
# Model generations — one per LLM next_turn() call
# ---------------------------------------------------------------------------


@contextmanager
def model_generation(
    name: str,
    *,
    system: str,
    user_message: str,
    model: str = "unknown",
) -> Generator[Any, None, None]:
    """Langfuse generation wrapping a single ModelClient.next_turn() call.

    Captures system prompt length (not content — it is long and constant), the user
    message (first 1 000 chars so the UI stays readable), and the model name.
    Call update_generation_output() after the turn completes to record the response.
    """
    lf = _client_or_none()
    if lf is None:
        yield None
        return
    with lf.start_as_current_observation(
        as_type="generation",
        name=name,
        model=model,
        input={
            "system_prompt_chars": len(system),
            "user_message": user_message[:1000],
        },
    ) as gen:
        yield gen


def update_generation_output(text: str | None, *, tool_calls: list[str] | None = None) -> None:
    """Record the assistant response after a generation completes."""
    if not enabled():
        return
    output: dict[str, Any] = {}
    if text:
        output["text"] = text[:2000]
    if tool_calls:
        output["tool_calls"] = tool_calls
    if output:
        try:
            _lf().update_current_generation(output=output)
        except Exception:
            # Some adapters/threads may not carry an active generation context.
            return


# ---------------------------------------------------------------------------
# Agent-level spans — one per agent run (wraps all turns inside)
# ---------------------------------------------------------------------------


@contextmanager
def agent_span(name: str, *, input_summary: dict[str, Any]) -> Generator[Any, None, None]:
    """Langfuse span wrapping a full agent run (IdealCutsAgent, GenerateBrollAgent, …)."""
    lf = _client_or_none()
    if lf is None:
        yield None
        return
    with lf.start_as_current_observation(
        as_type="span",
        name=name,
        input=input_summary,
    ) as span:
        yield span


def update_agent_output(output: Any) -> None:
    if not enabled():
        return
    try:
        _lf().update_current_span(output=output)
    except Exception:
        return


# ---------------------------------------------------------------------------
# Kling asset generation spans
# ---------------------------------------------------------------------------


@contextmanager
def kling_span(
    name: str,
    *,
    prompt: str,
    aspect_ratio: str,
    duration: float | None = None,
) -> Generator[Any, None, None]:
    """Langfuse span wrapping one Kling image or video generation job."""
    lf = _client_or_none()
    if lf is None:
        yield None
        return
    input_data: dict[str, Any] = {"prompt": prompt[:500], "aspect_ratio": aspect_ratio}
    if duration is not None:
        input_data["duration_seconds"] = duration
    with lf.start_as_current_observation(
        as_type="span", name=name, input=input_data
    ) as span:
        yield span


def update_kling_output(out_path: str) -> None:
    if not enabled():
        return
    try:
        _lf().update_current_span(output={"file": os.path.basename(out_path)})
    except Exception:
        return


@contextmanager
def media_create_span(
    name: str,
    *,
    prompt: str,
    aspect_ratio: str,
    model: str,
) -> Generator[Any, None, None]:
    """Langfuse span wrapping one image-generation job (e.g. Nano Banana)."""
    lf = _client_or_none()
    if lf is None:
        yield None
        return
    input_data: dict[str, Any] = {
        "prompt": prompt[:500],
        "aspect_ratio": aspect_ratio,
        "model": model,
    }
    with lf.start_as_current_observation(
        as_type="span", name=name, input=input_data
    ) as span:
        yield span


def update_media_create_output(out_path: str) -> None:
    if not enabled():
        return
    try:
        _lf().update_current_span(output={"file": os.path.basename(out_path)})
    except Exception:
        return
