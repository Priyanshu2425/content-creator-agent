"""Centralised run logger: rich stdout (clean) + verbose plain-text file in logs/.

Single module-level instance; call ``init()`` once at CLI startup, then ``get()`` from anywhere.
Before ``init()`` is called (tests, imports) ``get()`` returns a no-op null logger so no guard
checks are needed at call sites.

Stdout:  human-readable, rich-formatted, high-level events only.
Log file: everything — full tool args, agent narration, review feedback JSON, timings.
"""

from __future__ import annotations

import json
import time
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
        # Progress goes to stderr so stdout stays exactly the final mp4 path (story 14, pipeable).
        self._console = Console(highlight=False, stderr=True)
        run_dir.mkdir(parents=True, exist_ok=True)
        self._log_path = run_dir / "run.log"
        self._fh = self._log_path.open("w", encoding="utf-8", buffering=1)
        self._stage_times: dict[str, float] = {}
        self._run_start = time.monotonic()
        self._file(f"run started  {datetime.now().isoformat()}")
        self._console.print(f"[dim]log → {self._log_path}[/dim]\n")

    # pipeline stages

    def stage_start(self, name: str) -> None:
        self._stage_times[name] = time.monotonic()
        self._console.print(f" [dim]⚙[/dim]  [bold]{name}[/bold] [dim]...[/dim]")
        self._file(f"stage:start   {name}")

    def stage_done(self, name: str) -> None:
        e = self._elapsed(name)
        self._console.print(f" [green]✓[/green]  [bold]{name}[/bold]  [dim]{e}[/dim]\n")
        self._file(f"stage:done    {name}  elapsed={e}")

    def stage_error(self, name: str, error: Exception) -> None:
        e = self._elapsed(name)
        self._console.print(
            f" [red]✗[/red]  [bold]{name}[/bold]  [red]{error}[/red]  [dim]{e}[/dim]\n"
        )
        self._file(f"stage:error   {name}  elapsed={e}  error={error!r}")

    # agent loop

    def agent_start(self, budget: int) -> None:
        self._console.print(
            f" [magenta]◆[/magenta]  [bold]Authoring agent[/bold]  [dim]budget: {budget} ops[/dim]"
        )
        self._file(f"agent:start   budget={budget}")

    def agent_narration(self, text: str | None) -> None:
        if text:
            self._file(f"agent:narration  {text!r}")

    def agent_tool_call(self, name: str, args: dict[str, Any]) -> None:
        self._file(f"agent:tool_call  {name}  args={json.dumps(args, default=str)}")

    def agent_tool_ok(self, name: str) -> None:
        self._console.print(f"    [dim]→[/dim] [cyan]{name}[/cyan]  [green]✓[/green]")
        self._file(f"agent:tool_ok  {name}")

    def agent_tool_rejected(self, name: str, reasons: str) -> None:
        self._console.print(f"    [dim]→[/dim] [cyan]{name}[/cyan]  [yellow]✗ rejected[/yellow]")
        self._file(f"agent:tool_rejected  {name}  {reasons!r}")

    def agent_tool_error(self, name: str, error: str) -> None:
        self._console.print(f"    [dim]→[/dim] [cyan]{name}[/cyan]  [red]✗ error[/red]")
        self._file(f"agent:tool_error  {name}  {error!r}")

    def agent_done(self, ops_used: int, terminated_clean: bool) -> None:
        status = "clean" if terminated_clean else "budget exhausted"
        self._file(f"agent:done  ops_used={ops_used}  status={status}")
        self._console.print("")

    # finalization gate

    def finalize_round_start(self, round_: int, max_rounds: int) -> None:
        self._console.print(
            f" [magenta]◆[/magenta]  [bold]Finalization[/bold]  "
            f"[dim]round {round_}/{max_rounds}[/dim]"
        )
        self._file(f"finalize:round  {round_}/{max_rounds}")

    def finalize_render_start(self) -> None:
        self._stage_times["_render"] = time.monotonic()
        self._console.print("    [dim]⚙[/dim]  render [dim]...[/dim]")
        self._file("finalize:render  start")

    def finalize_render_done(self, path: Path) -> None:
        e = self._elapsed("_render")
        self._console.print(f"    [green]✓[/green]  render  [dim]{e}[/dim]")
        self._file(f"finalize:render  done  path={path}  elapsed={e}")

    def finalize_review_start(self) -> None:
        self._stage_times["_review"] = time.monotonic()
        self._console.print("    [dim]⚙[/dim]  review [dim]...[/dim]")
        self._file("finalize:review  start")

    def finalize_review_done(self, no_issues: bool, n_items: int) -> None:
        e = self._elapsed("_review")
        verdict = "[green]no issues[/green]" if no_issues else f"[yellow]{n_items} note(s)[/yellow]"
        self._console.print(f"    [green]✓[/green]  review  [dim]{e}[/dim]  {verdict}\n")
        self._file(
            f"finalize:review  done  elapsed={e}  no_actionable_issues={no_issues}  items={n_items}"
        )

    def finalize_feedback(self, feedback_json: str) -> None:
        self._file(f"finalize:feedback  {feedback_json}")

    # asset describer

    def describe_asset_ok(self, asset_id: str) -> None:
        self._console.print(f"    [dim]→[/dim] [cyan]describe[/cyan]  [green]✓[/green]  [dim]{asset_id}[/dim]")
        self._file(f"describe:ok  asset_id={asset_id}")

    def describe_asset_warn(self, asset_id: str, message: str) -> None:
        self._console.print(f"    [dim]→[/dim] [cyan]describe[/cyan]  [yellow]⚠[/yellow]  [dim]{asset_id}: {message}[/dim]")
        self._file(f"describe:warn  asset_id={asset_id}  {message}")

    def describe_rate_wait(self, seconds: float) -> None:
        self._console.print(
            f"    [dim]→[/dim] [cyan]describe[/cyan]  "
            f"[yellow]⏳ rate limit — waiting {seconds:.1f}s[/yellow]"
        )
        self._file(f"describe:rate_wait  seconds={seconds:.1f}")

    def describe_done(self, n: int) -> None:
        self._file(f"describe:done  count={n}")

    # b-roll fetch

    def broll_fetch_ok(self, url: str, path: str) -> None:
        self._console.print(f"    [dim]→[/dim] [cyan]fetch[/cyan]  [green]✓[/green]  [dim]{path}[/dim]")
        self._file(f"broll:fetch_ok  url={url}  path={path}")

    def broll_fetch_warn(self, message: str) -> None:
        self._console.print(f"    [dim]→[/dim] [cyan]fetch[/cyan]  [yellow]⚠[/yellow]  [dim]{message}[/dim]")
        self._file(f"broll:fetch_warn  {message}")

    def broll_fetch_done(self, count: int) -> None:
        self._file(f"broll:fetch_done  count={count}")

    # pipeline terminal events

    def pipeline_done(self, output: str) -> None:
        total = f"{time.monotonic() - self._run_start:.1f}s"
        self._console.print(
            f"\n [green bold]✓[/green bold]  [bold]Done[/bold]  "
            f"[cyan]{output}[/cyan]  [dim]{total}[/dim]"
        )
        self._file(f"pipeline:done  output={output}  total={total}")
        self._fh.close()
        reset()

    def pipeline_error(self, stage: str, error: Exception) -> None:
        total = f"{time.monotonic() - self._run_start:.1f}s"
        self._file(f"pipeline:error  stage={stage}  error={error!r}  total={total}")
        self._fh.close()
        reset()

    # internals

    def _elapsed(self, key: str) -> str:
        return f"{time.monotonic() - self._stage_times.pop(key, time.monotonic()):.1f}s"

    def _file(self, message: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self._fh.write(f"{ts}  {message}\n")


class _NullLogger:
    """No-op logger active before init() is called (test imports, unit tests)."""

    def stage_start(self, name: str) -> None: pass
    def stage_done(self, name: str) -> None: pass
    def stage_error(self, name: str, error: Exception) -> None: pass
    def agent_start(self, budget: int) -> None: pass
    def agent_narration(self, text: str | None) -> None: pass
    def agent_tool_call(self, name: str, args: dict[str, Any]) -> None: pass
    def agent_tool_ok(self, name: str) -> None: pass
    def agent_tool_rejected(self, name: str, reasons: str) -> None: pass
    def agent_tool_error(self, name: str, error: str) -> None: pass
    def agent_done(self, ops_used: int, terminated_clean: bool) -> None: pass
    def finalize_round_start(self, round_: int, max_rounds: int) -> None: pass
    def finalize_render_start(self) -> None: pass
    def finalize_render_done(self, path: Path) -> None: pass
    def finalize_review_start(self) -> None: pass
    def finalize_review_done(self, no_issues: bool, n_items: int) -> None: pass
    def finalize_feedback(self, feedback_json: str) -> None: pass
    def describe_asset_ok(self, asset_id: str) -> None: pass
    def describe_asset_warn(self, asset_id: str, message: str) -> None: pass
    def describe_rate_wait(self, seconds: float) -> None: pass
    def describe_done(self, n: int) -> None: pass
    def broll_fetch_ok(self, url: str, path: str) -> None: pass
    def broll_fetch_warn(self, message: str) -> None: pass
    def broll_fetch_done(self, count: int) -> None: pass
    def pipeline_done(self, output: str) -> None: pass
    def pipeline_error(self, stage: str, error: Exception) -> None: pass


_instance: RunLogger | _NullLogger = _NullLogger()
