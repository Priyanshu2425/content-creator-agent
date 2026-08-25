"""Centralised run logger: rich stdout (human-readable) + NDJSON file (machine-queryable).

Single module-level instance; call ``init()`` once at CLI startup, then ``get()`` from anywhere.
Before ``init()`` is called (tests, imports) ``get()`` returns a no-op null logger so no guard
checks are needed at call sites.

Stdout:  human-readable, rich-formatted, high-level events only.
Log file: NDJSON — one JSON object per line, every field queryable by trace_id.
         Filter by trace_id to see the full pipeline journey for one run.
         Filter by event to audit a specific decision type across all runs.
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Console

# --- public API ---------------------------------------------------------------


def init(run_dir: Path) -> RunLogger:
    """Create the run logger writing ``run.log`` inside the run's folder. Call once in main()."""
    global _instance
    _instance = RunLogger(run_dir)
    return _instance


def get() -> RunLogger | _NullLogger:
    """Return the active logger. Returns a no-op if init() has not been called."""
    return _instance


def reset() -> None:
    """Revert to the no-op logger once a run is over, so nothing leaks into a later run/test."""
    global _instance
    _instance = _NullLogger()


# --- logger -------------------------------------------------------------------


class RunLogger:
    def __init__(self, run_dir: Path) -> None:
        self.trace_id: str = uuid.uuid4().hex
        # Progress goes to stderr so stdout stays exactly the final mp4 path (story 14, pipeable).
        self._console = Console(highlight=False, stderr=True)
        run_dir.mkdir(parents=True, exist_ok=True)
        self._log_path = run_dir / "run.log"
        self._fh = self._log_path.open("w", encoding="utf-8", buffering=1)
        self._stage_times: dict[str, float] = {}
        self._run_start = time.monotonic()
        self._event("run_start", started_at=datetime.now().isoformat())
        self._console.print(f"[dim]log → {self._log_path}[/dim]\n")

    def pipeline_mode(self, *, authoring_only: bool) -> None:
        label = "authoring-only" if authoring_only else "full"
        self._console.print(
            f" [dim]mode[/dim]  [bold]{label}[/bold]"
        )
        self._event("pipeline_mode", authoring_only=authoring_only, mode=label)

    def broll_path_skipped(self, path: str, reason: str) -> None:
        self._console.print(
            f"    [dim]→[/dim] [yellow]skip[/yellow]  [dim]{path}[/dim]  [dim]({reason})[/dim]"
        )
        self._event("broll_path_skipped", level="warn", path=path, reason=reason)

    def broll_expand_done(self, n_paths: int) -> None:
        self._event("broll_expand_done", level="debug", path_count=n_paths)

    def media_retry(
        self, *, what: str, attempt: int, max_attempts: int, backoff_s: float, error: str
    ) -> None:
        """A transient (429) provider error is being retried with backoff -- logged so a rate-limited
        run is visibly retrying rather than silently stalling."""
        self._console.print(
            f"    [yellow]↻[/yellow] [dim]{what}[/dim] rate-limited; "
            f"retry [yellow]{attempt}/{max_attempts}[/yellow] in {backoff_s:.1f}s"
        )
        self._event(
            "media_retry",
            level="warn",
            what=what,
            attempt=attempt,
            max_attempts=max_attempts,
            backoff_s=round(backoff_s, 2),
            error=error[:200],
        )

    # --- NDJSON core ----------------------------------------------------------

    def _event(self, event: str, *, level: str = "info", **fields: Any) -> None:
        """Write one NDJSON event. Every call site's fields are queryable by name."""
        record: dict[str, Any] = {
            "ts": datetime.now().isoformat(timespec="milliseconds"),
            "level": level,
            "trace_id": self.trace_id,
            "event": event,
        }
        record.update(fields)
        self._fh.write(json.dumps(record, default=str) + "\n")

    def _file(self, message: str, *, level: str = "debug") -> None:
        """Emit a plain log message as a generic NDJSON event (backward-compat for text logs)."""
        self._event("log", level=level, message=message)

    def _elapsed_ms(self, key: str) -> int:
        return int((time.monotonic() - self._stage_times.pop(key, time.monotonic())) * 1000)

    # --- structured event methods (the five types + helpers) ------------------

    def llm_call(
        self,
        *,
        agent: str,
        model: str,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        stop_reason: str | None = None,
        duration_ms: int,
    ) -> None:
        """One LLM API call: token counts, model, duration. At debug level to avoid flood."""
        fields: dict[str, Any] = {"agent": agent, "model": model, "duration_ms": duration_ms}
        if input_tokens is not None:
            fields["input_tokens"] = input_tokens
        if output_tokens is not None:
            fields["output_tokens"] = output_tokens
        if stop_reason is not None:
            fields["stop_reason"] = stop_reason
        self._event("llm_call", level="debug", **fields)

    def audio_decision(
        self,
        *,
        cut_id: str,
        cut_type: str,
        timestamp_ms: int,
        sound: str,
        reason: str,
        dramatic_whoosh_budget_remaining: int,
    ) -> None:
        """One per-cut sound assignment. Filter by sound='dramatic_whoosh' to audit cap usage."""
        self._event(
            "audio_decision",
            cut_id=cut_id,
            cut_type=cut_type,
            timestamp_ms=timestamp_ms,
            sound=sound,
            reason=reason,
            dramatic_whoosh_budget_remaining=dramatic_whoosh_budget_remaining,
        )

    def budget_cap_hit(
        self,
        *,
        cut_id: str,
        downgraded_from: str,
        downgraded_to: str,
        cap: int,
    ) -> None:
        """Fired when a budget cap forces a downgrade (e.g. dramatic_whoosh → whoosh)."""
        self._event(
            "budget_cap_hit",
            level="warn",
            cut_id=cut_id,
            downgraded_from=downgraded_from,
            downgraded_to=downgraded_to,
            cap=cap,
        )

    def agent_event_start(self, agent: str, **context: Any) -> None:
        self._event("agent_start", agent=agent, **context)

    def agent_event_complete(self, agent: str, *, duration_ms: int, **summary: Any) -> None:
        self._event("agent_complete", agent=agent, duration_ms=duration_ms, **summary)

    def agent_event_error(
        self, agent: str, *, error_message: str, fallback_applied: bool = False
    ) -> None:
        self._event(
            "agent_error",
            level="error",
            agent=agent,
            error_message=error_message,
            fallback_applied=fallback_applied,
        )

    # --- pipeline stages ------------------------------------------------------

    def stage_start(self, name: str) -> None:
        self._stage_times[name] = time.monotonic()
        self._console.print(f" [dim]⚙[/dim]  [bold]{name}[/bold] [dim]...[/dim]")
        self._event("stage_start", stage=name)

    def stage_done(self, name: str) -> None:
        ms = self._elapsed_ms(name)
        self._console.print(
            f" [green]✓[/green]  [bold]{name}[/bold]  [dim]{ms / 1000:.1f}s[/dim]\n"
        )
        self._event("stage_done", stage=name, duration_ms=ms)

    def stage_error(self, name: str, error: Exception) -> None:
        ms = self._elapsed_ms(name)
        self._console.print(
            f" [red]✗[/red]  [bold]{name}[/bold]  [red]{error}[/red]  "
            f"[dim]{ms / 1000:.1f}s[/dim]\n"
        )
        self._event("stage_error", level="error", stage=name, duration_ms=ms, error=repr(error))

    # --- authoring agent loop -------------------------------------------------

    def agent_start(self, budget: int) -> None:
        self._console.print(
            f" [magenta]◆[/magenta]  [bold]Director[/bold]  [dim]budget: {budget} ops[/dim]"
        )
        self._event("agent_start", agent="DirectorLoop", budget=budget)

    def agent_narration(self, text: str | None) -> None:
        if text:
            self._event("authoring_narration", level="debug", text=text[:500])

    def agent_tool_call(self, name: str, args: dict[str, Any]) -> None:
        self._event("authoring_tool_call", level="debug", tool=name, args=args)

    def agent_dispatch_input(self, worker: str, *, inputs: dict[str, Any]) -> None:
        """The complete payload handed to a dispatched worker (ADR 0008): every input the worker
        agent actually received -- the bound transcript/brief plus the per-dispatch guidance,
        scratchpad and brand kit. Logged in full at debug so a run's worker inputs are recoverable,
        not just the worker's returned proposal."""
        self._event("authoring_dispatch_input", level="debug", worker=worker, inputs=inputs)

    def agent_tool_ok(self, name: str) -> None:
        self._console.print(f"    [dim]→[/dim] [cyan]{name}[/cyan]  [green]✓[/green]")
        self._event("authoring_tool_ok", level="debug", tool=name)

    def agent_tool_rejected(self, name: str, reasons: str) -> None:
        self._console.print(f"    [dim]→[/dim] [cyan]{name}[/cyan]  [yellow]✗ rejected[/yellow]")
        self._event("authoring_tool_rejected", level="warn", tool=name, reasons=reasons)

    def agent_tool_error(self, name: str, error: str) -> None:
        self._console.print(f"    [dim]→[/dim] [cyan]{name}[/cyan]  [red]✗ error[/red]")
        self._event("authoring_tool_error", level="error", tool=name, error=error)

    def agent_done(self, ops_used: int, terminated_clean: bool) -> None:
        self._event(
            "agent_complete",
            agent="DirectorLoop",
            ops_used=ops_used,
            terminated_clean=terminated_clean,
        )
        self._console.print("")

    # --- finalization gate ----------------------------------------------------

    def finalize_round_start(self, round_: int, max_rounds: int) -> None:
        self._console.print(
            f" [magenta]◆[/magenta]  [bold]Finalization[/bold]  "
            f"[dim]round {round_}/{max_rounds}[/dim]"
        )
        self._event("finalize_round_start", round=round_, max_rounds=max_rounds)

    def finalize_render_start(self) -> None:
        self._stage_times["_render"] = time.monotonic()
        self._console.print("    [dim]⚙[/dim]  render [dim]...[/dim]")
        self._event("finalize_render_start", level="debug")

    def finalize_render_done(self, path: Path) -> None:
        ms = self._elapsed_ms("_render")
        self._console.print(f"    [green]✓[/green]  render  [dim]{ms / 1000:.1f}s[/dim]")
        self._event("finalize_render_done", path=str(path), duration_ms=ms)

    def finalize_review_start(self) -> None:
        self._stage_times["_review"] = time.monotonic()
        self._console.print("    [dim]⚙[/dim]  review [dim]...[/dim]")
        self._event("finalize_review_start", level="debug")

    def finalize_review_done(self, no_issues: bool, n_items: int) -> None:
        ms = self._elapsed_ms("_review")
        verdict = "[green]no issues[/green]" if no_issues else f"[yellow]{n_items} note(s)[/yellow]"
        self._console.print(
            f"    [green]✓[/green]  review  [dim]{ms / 1000:.1f}s[/dim]  {verdict}\n"
        )
        self._event(
            "finalize_review_done",
            duration_ms=ms,
            no_actionable_issues=no_issues,
            item_count=n_items,
        )

    def finalize_feedback(self, feedback_json: str) -> None:
        try:
            self._event("finalize_feedback", level="debug", feedback=json.loads(feedback_json))
        except json.JSONDecodeError:
            self._file(f"finalize:feedback  {feedback_json}")

    # --- ingest ---------------------------------------------------------------

    def ingest_asset(
        self,
        asset_id: str,
        kind: str,
        duration_s: float | None,
        width: int | None,
        height: int | None,
    ) -> None:
        dur = f"  {duration_s:.1f}s" if duration_s is not None else ""
        dims = f"  {width}×{height}" if width and height else ""
        self._console.print(
            f"    [dim]→[/dim] [cyan]{kind}[/cyan]{dur}{dims}  [dim]{asset_id}[/dim]"
        )
        self._event(
            "ingest_asset",
            level="debug",
            asset_id=asset_id,
            kind=kind,
            duration_s=duration_s,
            width=width,
            height=height,
        )

    # --- transcribe -----------------------------------------------------------

    def transcribe_done(self, n_words: int, audio_duration_s: float) -> None:
        self._console.print(
            f"    [dim]→[/dim] [cyan]{n_words} words[/cyan]  [dim]{audio_duration_s:.1f}s[/dim]"
        )
        self._event("transcribe_done", word_count=n_words, audio_duration_s=audio_duration_s)

    # --- model call (console feedback for long-running single-turn agents) ----

    def model_call(self, label: str, model: str) -> None:
        self._console.print(
            f"    [dim]→[/dim] [cyan]{label}[/cyan]  [dim]model:{model}[/dim]  [dim]...[/dim]"
        )
        self._event("model_call_start", level="debug", label=label, model=model)

    # --- ideal-cuts -----------------------------------------------------------

    def ideal_cuts_done(self, summary: str) -> None:
        self._console.print(f"    [dim]→[/dim] [cyan]plan[/cyan]  [dim]{summary}[/dim]")
        self._event("ideal_cuts_plan", summary=summary)

    # --- Kling job lifecycle --------------------------------------------------

    def kling_submitted(self, kind: str, task_id: str) -> None:
        """Confirm the Kling API accepted the job and returned a task_id."""
        self._console.print(
            f"    [dim]→[/dim] [cyan]kling {kind}[/cyan]  "
            f"[dim]submitted task_id={task_id}[/dim]"
        )
        self._event("kling_submitted", kind=kind, task_id=task_id)

    def kling_poll(
        self, kind: str, task_id: str, status: str, elapsed_s: int, attempt: int
    ) -> None:
        """One poll attempt. Console heartbeat on attempt 0 and every 6 attempts (~30s)."""
        self._event(
            "kling_poll",
            level="debug",
            kind=kind,
            task_id=task_id,
            status=status,
            elapsed_s=elapsed_s,
            attempt=attempt,
        )
        if attempt == 0 or attempt % 6 == 0:
            self._console.print(
                f"    [dim]→[/dim] [cyan]kling {kind}[/cyan]  "
                f"[dim]{status}  {elapsed_s}s elapsed[/dim]"
            )

    # --- generate-broll -------------------------------------------------------

    def generate_broll_slots(self, n_image: int, n_video: int) -> None:
        self._console.print(
            f"    [dim]→[/dim] [cyan]{n_image} image  {n_video} video slots[/cyan]"
        )
        self._event("generate_broll_slots", image_slots=n_image, video_slots=n_video)

    def generate_broll_slot(self, slot: int, kind: str, ok: bool, detail: str) -> None:
        status = "[green]✓[/green]" if ok else "[red]✗[/red]"
        self._console.print(
            f"    [dim]→[/dim] [cyan]slot {slot} {kind}[/cyan]  {status}  "
            f"[dim]{detail[:70]}[/dim]"
        )
        self._event(
            "generate_broll_slot",
            level="info" if ok else "error",
            slot=slot,
            kind=kind,
            ok=ok,
            detail=detail,
        )

    def generate_broll_done(self, n_ok: int, n_fail: int) -> None:
        self._event("generate_broll_done", ok=n_ok, fail=n_fail)

    # --- audio-decider --------------------------------------------------------

    def audio_decider_done(self, n_scenes: int, n_annotated: int, budget_line: str) -> None:
        self._console.print(
            f"    [dim]→[/dim] [cyan]{n_annotated}/{n_scenes} scenes[/cyan]  "
            f"[dim]{budget_line}[/dim]"
        )
        self._event(
            "audio_decider_summary",
            scene_count=n_scenes,
            annotated_count=n_annotated,
            budget=budget_line,
        )

    # --- asset describer ------------------------------------------------------

    def describe_asset_ok(self, asset_id: str) -> None:
        self._console.print(
            f"    [dim]→[/dim] [cyan]describe[/cyan]  [green]✓[/green]  [dim]{asset_id}[/dim]"
        )
        self._event("describe_asset_ok", level="debug", asset_id=asset_id)

    def describe_asset_warn(self, asset_id: str, message: str) -> None:
        self._console.print(
            f"    [dim]→[/dim] [cyan]describe[/cyan]  [yellow]⚠[/yellow]  "
            f"[dim]{asset_id}: {message}[/dim]"
        )
        self._event("describe_asset_warn", level="warn", asset_id=asset_id, message=message)

    def describe_rate_wait(self, seconds: float) -> None:
        self._console.print(
            f"    [dim]→[/dim] [cyan]describe[/cyan]  "
            f"[yellow]⏳ rate limit — waiting {seconds:.1f}s[/yellow]"
        )
        self._event("describe_rate_wait", level="warn", wait_s=seconds)

    def describe_done(self, n: int) -> None:
        self._event("describe_done", level="debug", count=n)

    # --- pipeline terminal events ---------------------------------------------

    def pipeline_done(self, output: str) -> None:
        duration_ms = int((time.monotonic() - self._run_start) * 1000)
        self._console.print(
            f"\n [green bold]✓[/green bold]  [bold]Done[/bold]  "
            f"[cyan]{output}[/cyan]  [dim]{duration_ms / 1000:.1f}s[/dim]"
        )
        self._event("pipeline_done", output=output, duration_ms=duration_ms)
        self._fh.close()
        reset()

    def pipeline_error(self, stage: str, error: Exception) -> None:
        duration_ms = int((time.monotonic() - self._run_start) * 1000)
        self._event(
            "pipeline_error",
            level="error",
            stage=stage,
            error=repr(error),
            duration_ms=duration_ms,
        )
        self._fh.close()
        reset()


class _NullLogger:
    """No-op logger active before init() is called (test imports, unit tests)."""

    trace_id: str = ""

    # structured events
    def llm_call(self, *, agent: str, model: str, input_tokens: int | None = None, output_tokens: int | None = None, stop_reason: str | None = None, duration_ms: int) -> None: pass
    def audio_decision(self, *, cut_id: str, cut_type: str, timestamp_ms: int, sound: str, reason: str, dramatic_whoosh_budget_remaining: int) -> None: pass
    def budget_cap_hit(self, *, cut_id: str, downgraded_from: str, downgraded_to: str, cap: int) -> None: pass
    def agent_event_start(self, agent: str, **context: Any) -> None: pass
    def agent_event_complete(self, agent: str, *, duration_ms: int, **summary: Any) -> None: pass
    def agent_event_error(self, agent: str, *, error_message: str, fallback_applied: bool = False) -> None: pass
    def media_retry(self, *, what: str, attempt: int, max_attempts: int, backoff_s: float, error: str) -> None: pass
    # pipeline stages
    def stage_start(self, name: str) -> None: pass
    def stage_done(self, name: str) -> None: pass
    def stage_error(self, name: str, error: Exception) -> None: pass
    # authoring loop
    def agent_start(self, budget: int) -> None: pass
    def agent_narration(self, text: str | None) -> None: pass
    def agent_tool_call(self, name: str, args: dict[str, Any]) -> None: pass
    def agent_dispatch_input(self, worker: str, *, inputs: dict[str, Any]) -> None: pass
    def agent_tool_ok(self, name: str) -> None: pass
    def agent_tool_rejected(self, name: str, reasons: str) -> None: pass
    def agent_tool_error(self, name: str, error: str) -> None: pass
    def agent_done(self, ops_used: int, terminated_clean: bool) -> None: pass
    # finalization
    def finalize_round_start(self, round_: int, max_rounds: int) -> None: pass
    def finalize_render_start(self) -> None: pass
    def finalize_render_done(self, path: Path) -> None: pass
    def finalize_review_start(self) -> None: pass
    def finalize_review_done(self, no_issues: bool, n_items: int) -> None: pass
    def finalize_feedback(self, feedback_json: str) -> None: pass
    # ingest / transcribe
    def ingest_asset(self, asset_id: str, kind: str, duration_s: float | None, width: int | None, height: int | None) -> None: pass
    def transcribe_done(self, n_words: int, audio_duration_s: float) -> None: pass
    # per-agent helpers
    def model_call(self, label: str, model: str) -> None: pass
    def ideal_cuts_done(self, summary: str) -> None: pass
    def kling_submitted(self, kind: str, task_id: str) -> None: pass
    def kling_poll(self, kind: str, task_id: str, status: str, elapsed_s: int, attempt: int) -> None: pass
    def generate_broll_slots(self, n_image: int, n_video: int) -> None: pass
    def generate_broll_slot(self, slot: int, kind: str, ok: bool, detail: str) -> None: pass
    def generate_broll_done(self, n_ok: int, n_fail: int) -> None: pass
    def audio_decider_done(self, n_scenes: int, n_annotated: int, budget_line: str) -> None: pass
    # describer
    def describe_asset_ok(self, asset_id: str) -> None: pass
    def describe_asset_warn(self, asset_id: str, message: str) -> None: pass
    def describe_rate_wait(self, seconds: float) -> None: pass
    def describe_done(self, n: int) -> None: pass
    # terminal
    def pipeline_done(self, output: str) -> None: pass
    def pipeline_error(self, stage: str, error: Exception) -> None: pass
    def pipeline_mode(self, *, authoring_only: bool) -> None: pass
    def broll_path_skipped(self, path: str, reason: str) -> None: pass
    def broll_expand_done(self, n_paths: int) -> None: pass


_instance: RunLogger | _NullLogger = _NullLogger()
