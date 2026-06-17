"""Director tool-use loop: one validated op per turn, with on-demand vision (ADR 0004, ADR 0008).

Formerly the AuthoringLoop; renamed to DirectorLoop (ADR 0008). The agent that drives this loop is
the Director -- it authors the Composition through validated Builder ops and (in later phases)
dispatches specialist worker agents whose proposals it turns into ops.

The loop is the runtime that turns a model's tool calls into a Composition. It presents the system
prompt, tool specs, and structured perception to a ``ModelClient``; receives one tool call; and:

- for a **mutating** op, applies the matching Builder op (validated immediately by the kernel),
  records it on the audit journal, and feeds the validation report plus freshly-assembled perception
  straight back -- so a rejected op is corrected on the very next turn (the core ADR 0004 loop);
- for a **vision** op (``render_still``/``scene_preview``), compiles the current document to IR and
  samples the backend's cheap ``render_still`` (a frame, or a strip across a scene), returning the
  image(s) -- never ``render_video``, and only when the agent asks (cost control, ADR 0004);
- for **finish**, runs the submit-render gate: clean terminates the loop, otherwise the blocking
  report is returned and the agent keeps going (story 26).

Two safety rails: the gate bounds correctness, and an operation budget bounds cost so a confused
agent cannot run away (story 33). The accumulated effect of the validated ops *is* the declarative
Composition; the loop never asks the model to emit a document (ADR 0001's derived state holds).
"""

from __future__ import annotations

import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from videogen import log, tracing
from videogen.agent.model import (
    HistoryItem,
    ModelClient,
    ToolCall,
    ToolResult,
    ToolResultsMessage,
    ToolSpec,
    UserMessage,
)
from videogen.agent.perception import Manifest, assemble_perception
from videogen.agent.prompts import SYSTEM_PROMPT
from videogen.agent.dispatch import WorkerDispatcher
from videogen.agent.tools import (
    ADVICE_OP,
    CONSULT_PLACEMENT_TOOL,
    DISPATCH_OPS,
    DISPATCH_TOOLS,
    FINISH_OP,
    MUTATING_OPS,
    TOOLS,
    VISION_OPS,
    apply_op,
)
from videogen.agent.vision_advice import VisionAdvisor
from videogen.backends.base import RenderBackend
from videogen.kernel.builder import Builder
from videogen.kernel.compile_ir import compile_ir
from videogen.kernel.composition import Composition
from videogen.kernel.validator import ValidationResult
from videogen.stores.composition_store import CompositionStore

_PREVIEW_SAMPLES = 3  # frames sampled across a scene's span for the preview strip


@dataclass(frozen=True)
class DirectorResult:
    """The terminal state of an authoring run: the document, its report, and how the loop ended."""

    composition: Composition
    report: ValidationResult
    terminated_clean: bool
    ops_used: int


class DirectorLoop:
    """Drives a ModelClient through validated Builder ops to a finished, valid Composition."""

    def __init__(
        self,
        client: ModelClient,
        builder: Builder,
        manifest: Manifest,
        store: CompositionStore,
        doc_id: str,
        *,
        backend: RenderBackend | None = None,
        brief: str = "",
        system: str = SYSTEM_PROMPT,
        max_ops: int = 40,
        artifacts_dir: Path | None = None,
        advisor: VisionAdvisor | None = None,
        dispatchers: dict[str, WorkerDispatcher] | None = None,
        brand_kit: object | None = None,
        max_dispatch_per_worker: int = 2,
        timeline_skeleton: str = "",
    ) -> None:
        self._client = client
        self._builder = builder
        self._manifest = manifest
        self._store = store
        self._doc_id = doc_id
        self._backend = backend
        self._brief = brief
        self._system = system
        self._max_ops = max_ops
        self._artifacts_dir = artifacts_dir
        self._advisor = advisor
        # Worker dispatch (ADR 0008): a small registry of dispatchers and a per-worker budget,
        # tracked separately from the Builder-op budget so a dispatch never starves authoring turns.
        self._dispatchers = dispatchers or {}
        self._brand_kit = brand_kit
        self._max_dispatch_per_worker = max_dispatch_per_worker
        self._dispatch_counts: dict[str, int] = {}
        self._timeline_skeleton = timeline_skeleton

    def run(self) -> DirectorResult:
        history: list[HistoryItem] = [UserMessage(self._opening_message())]
        ops_used = 0
        terminated_clean = False
        tools = self._advertised_tools()
        log.get().agent_start(self._max_ops)

        model = getattr(self._client, "model", "unknown") or "unknown"
        turn = 0
        while ops_used < self._max_ops:
            turn += 1
            # The last history item is the user/tool message the model is responding to.
            last_user_text = _last_user_text(history)
            with tracing.model_generation(
                f"authoring-turn-{turn}",
                system=self._system,
                user_message=last_user_text,
                model=model,
            ):
                assistant = self._client.next_turn(
                    system=self._system, history=history, tools=tools
                )
            tracing.update_generation_output(
                assistant.text,
                tool_calls=[tc.name for tc in assistant.tool_calls],
            )
            history.append(assistant)
            log.get().agent_narration(assistant.text)
            if not assistant.tool_calls:
                break  # the model stopped acting without finishing

            results: list[ToolResult] = []
            for tool_call in assistant.tool_calls:
                # Worker dispatches (ADR 0008) draw from a separate per-worker budget, so they do
                # NOT consume the Builder-op budget that bounds authoring cost.
                if tool_call.name not in DISPATCH_OPS:
                    ops_used += 1
                log.get().agent_tool_call(tool_call.name, dict(tool_call.args))
                result, finished = self._dispatch(tool_call)
                results.append(result)
                if finished:
                    terminated_clean = True
                if ops_used >= self._max_ops:
                    break
            history.append(ToolResultsMessage(tuple(results)))
            if terminated_clean:
                break

        log.get().agent_done(ops_used, terminated_clean)
        return DirectorResult(
            composition=self._builder.composition,
            report=self._builder.validate(),
            terminated_clean=terminated_clean,
            ops_used=ops_used,
        )

    def _advertised_tools(self) -> list[ToolSpec]:
        """The tools offered to the model this run.

        A client that cannot consume images (``consumes_images = False``) authors blind: if a
        ``VisionAdvisor`` and a backend are available, drop the image vision tools and offer the
        text-return ``consult_placement`` advisor tool in their place (ADR 0007). Otherwise (a
        sighted client, or no advisor) the full ``TOOLS`` list is used unchanged."""
        blind = not getattr(self._client, "consumes_images", True)
        if blind and self._advisor is not None and self._backend is not None:
            tools = [t for t in TOOLS if t.name not in VISION_OPS] + [CONSULT_PLACEMENT_TOOL]
        else:
            tools = list(TOOLS)
        # Advertise each dispatch tool only when its worker is wired (ADR 0008).
        for op_name, spec in DISPATCH_TOOLS.items():
            if op_name in self._dispatchers:
                tools.append(spec)
        return tools

    def _opening_message(self) -> str:
        perception = assemble_perception(self._builder.composition, self._manifest)
        skeleton = f"\n\n{self._timeline_skeleton}" if self._timeline_skeleton else ""
        return f"Brief:\n{self._brief}{skeleton}\n\n{perception}"

    def _dispatch(self, call: ToolCall) -> tuple[ToolResult, bool]:
        if call.name in MUTATING_OPS:
            return self._dispatch_mutation(call), False
        if call.name in VISION_OPS:
            return self._dispatch_vision(call), False
        if call.name == ADVICE_OP:
            return self._dispatch_advice(call), False
        if call.name in DISPATCH_OPS:
            return self._dispatch_worker(call), False
        if call.name == FINISH_OP:
            return self._dispatch_finish(call)
        return ToolResult(call.id, text=f"unknown tool: {call.name!r}"), False

    def _dispatch_worker(self, call: ToolCall) -> ToolResult:
        """Run a dispatched worker (ADR 0008): enforce its dispatch budget, invoke the dispatcher,
        register any assets it produced into the Builder, and return its proposal plus fresh
        perception so the Director can place the new assets on its next turns."""
        dispatcher = self._dispatchers.get(call.name)
        if dispatcher is None:
            return ToolResult(call.id, text=f"dispatch unavailable: no '{call.name}' worker wired")

        used = self._dispatch_counts.get(call.name, 0)
        if used >= self._max_dispatch_per_worker:
            self._store.note(self._doc_id, op=f"{call.name}[budget-exhausted]")
            return ToolResult(
                call.id,
                text=(
                    f"dispatch budget exhausted for '{call.name}' "
                    f"({self._max_dispatch_per_worker} max) -- proceed with the assets you have.\n\n"
                    f"{self._perception()}"
                ),
            )
        self._dispatch_counts[call.name] = used + 1

        guidance: dict[str, object] = {
            "guidance": str(call.args.get("guidance", "")),
            "brand_kit": self._brand_kit_tokens(),
        }
        # The Director owns the event timeline (ADR 0009): build it from the live composition and
        # hand it to the SFX worker rather than have the worker re-derive it.
        if call.name == "dispatch_sfx":
            from videogen.agent.event_timeline import build_event_timeline

            guidance["event_timeline"] = build_event_timeline(self._builder.composition)
        try:
            proposal = dispatcher(guidance)
        except Exception as exc:  # a worker failure must not crash the Director
            self._store.note(self._doc_id, op=f"{call.name}[failed]")
            log.get().agent_tool_error(call.name, str(exc))
            return ToolResult(call.id, text=f"worker dispatch failed: {exc}\n\n{self._perception()}")

        registered, failed = self._register_assets(proposal.new_assets)
        sfx_applied = self._apply_scene_audio(proposal.scene_audio)
        self._store.note(self._doc_id, op=call.name)
        log.get().agent_tool_ok(call.name)
        text = proposal.proposal_text
        if registered:
            text += (
                "\n\nNew assets registered -- place them with fill_region/add_overlay: "
                + ", ".join(registered)
            )
        if failed:
            text += "\n\nAssets that could not be registered (id clash): " + ", ".join(failed)
        if sfx_applied:
            text += f"\n\nSFX placed on {sfx_applied} cut(s) via scene.audio."
        return ToolResult(call.id, text=f"{text}\n\n{self._perception()}")

    def _register_assets(self, new_assets: tuple[object, ...]) -> tuple[list[str], list[str]]:
        ok: list[str] = []
        bad: list[str] = []
        for na in new_assets:
            result = self._builder.add_asset(na.asset_id, na.asset)  # type: ignore[attr-defined]
            if result.ok:
                self._store.commit(self._doc_id, self._builder.composition, op="add_asset")
                ok.append(na.asset_id)  # type: ignore[attr-defined]
            else:
                bad.append(na.asset_id)  # type: ignore[attr-defined]
        return ok, bad

    def _apply_scene_audio(self, scene_audio: tuple[tuple[str, str], ...]) -> int:
        applied = 0
        for scene_id, sound in scene_audio:
            result = self._builder.set_scene_audio(scene_id, sound, reason="SFXAgent")
            if result.ok:
                self._store.commit(self._doc_id, self._builder.composition, op="set_scene_audio")
                applied += 1
        return applied

    def _brand_kit_tokens(self) -> dict[str, object] | None:
        if self._brand_kit is None:
            return None
        tokens = getattr(self._brand_kit, "tokens", None)
        return tokens() if callable(tokens) else None

    def _dispatch_mutation(self, call: ToolCall) -> ToolResult:
        try:
            op = apply_op(
                self._builder, call.name, call.args, transcript=self._manifest.transcript
            )
        except Exception as exc:  # malformed args from the model: feed it back, do not crash
            self._store.note(self._doc_id, op=f"{call.name}[invalid-args]")
            log.get().agent_tool_error(call.name, str(exc))
            return ToolResult(call.id, text=f"tool call failed: {exc}\n\n{self._perception()}")

        if op.ok:
            self._store.commit(self._doc_id, self._builder.composition, op=call.name)
            log.get().agent_tool_ok(call.name)
            return ToolResult(call.id, text=self._perception())

        # Rejected ops are transactional: the document is unchanged, so the reason is on the
        # OpResult, not in the current document's validation. Surface it so the agent can correct.
        self._store.note(self._doc_id, op=f"{call.name}[rejected]")
        reasons = "\n".join(f"  [{e.code.value}] {e.message}" for e in op.errors)
        log.get().agent_tool_rejected(call.name, reasons)
        text = f"op rejected -- not applied:\n{reasons}\n\n{self._perception()}"
        return ToolResult(call.id, text=text)

    def _dispatch_vision(self, call: ToolCall) -> ToolResult:
        if self._backend is None:
            log.get().agent_tool_error(call.name, "no render backend configured")
            return ToolResult(call.id, text="vision unavailable: no render backend configured")
        images: tuple[bytes, ...]
        if call.name == "render_still":
            images = (self._still(float(call.args["t"])),)  # type: ignore[arg-type]
            self._store.note(self._doc_id, op="render_still")
        else:  # scene_preview
            images = self._scene_strip(str(call.args["scene_id"]))
            self._store.note(self._doc_id, op="scene_preview")
        log.get().agent_tool_ok(call.name)
        return ToolResult(call.id, images=images)

    def _dispatch_advice(self, call: ToolCall) -> ToolResult:
        """The blind client's vision channel: render the frame at ``t``, ask the advisor, return its
        text advice (ADR 0007). Only reachable when the loop advertised ``consult_placement``."""
        if self._backend is None or self._advisor is None:
            log.get().agent_tool_error(call.name, "no advisor configured")
            return ToolResult(call.id, text="placement advice unavailable: no advisor configured")
        t = float(call.args["t"])  # type: ignore[arg-type]
        question = str(call.args.get("question", ""))
        image = self._still(t)
        advice = self._advisor.advise(image=image, question=question, context=self._perception())
        self._store.note(self._doc_id, op="consult_placement")
        log.get().agent_tool_ok(call.name)
        return ToolResult(call.id, text=advice)

    def _dispatch_finish(self, call: ToolCall) -> tuple[ToolResult, bool]:
        if self._builder.can_submit_render():
            log.get().agent_tool_ok(call.name)
            done = ToolResult(call.id, text="finished: the composition passes the submit gate")
            return done, True
        log.get().agent_tool_rejected(call.name, "hard errors remain")
        return (
            ToolResult(
                call.id,
                text=f"cannot finish -- hard errors remain:\n{self._perception()}",
            ),
            False,
        )

    def _perception(self) -> str:
        return assemble_perception(self._builder.composition, self._manifest)

    def _still(self, t: float) -> bytes:
        assert self._backend is not None
        ir = compile_ir(
            self._builder.composition,
            fps=int(self._manifest.fps),
            duration=self._manifest.duration,
            **self._frame_size(),
        )
        if self._artifacts_dir is not None:
            # Persist the frame the agent asked to see into the run folder for later inspection.
            stills = self._artifacts_dir / "stills"
            stills.mkdir(parents=True, exist_ok=True)
            out = stills / f"still-{t:.2f}s-{uuid.uuid4().hex[:6]}.png"
            self._backend.render_still(ir, t, out)
            return out.read_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "still.png"
            self._backend.render_still(ir, t, out)
            return out.read_bytes()

    def _scene_strip(self, scene_id: str) -> tuple[bytes, ...]:
        scene = next((s for s in self._builder.composition.scenes if s.id == scene_id), None)
        if scene is None:
            return ()
        step = (scene.end - scene.start) / _PREVIEW_SAMPLES
        samples = [scene.start + step * (i + 0.5) for i in range(_PREVIEW_SAMPLES)]
        return tuple(self._still(t) for t in samples)

    def _frame_size(self) -> dict[str, int]:
        for asset in self._manifest.assets:
            if asset.id == self._manifest.voiceover and asset.width and asset.height:
                return {"width": asset.width, "height": asset.height}
        return {}


def _last_user_text(history: list[HistoryItem]) -> str:
    """Return the text of the most recent UserMessage or ToolResultsMessage for tracing input."""
    for item in reversed(history):
        if isinstance(item, UserMessage):
            return item.text[:500]
        if isinstance(item, ToolResultsMessage):
            texts = [r.text or "" for r in item.results if r.text]
            return " | ".join(texts)[:500]
    return ""
