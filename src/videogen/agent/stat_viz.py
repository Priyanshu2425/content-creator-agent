"""StatVizRenderer: renders animated data-visualisation clips via dedicated Remotion compositions.

Each format maps to a composition in the existing Remotion project. The renderer merges LLM-supplied
data params with a StyleBrief (colors, font) and shells out via RemotionBackend.render_clip. The LLM
never chooses style -- it only picks format and supplies data values. Style is injected by the
Python layer from a per-video StyleBrief (DEFAULT_STYLE_BRIEF is the v1 placeholder; the upstream
design agent will supply it when it is built).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

Format = Literal["counter", "bar", "gauge", "before_after", "ratio"]

_COMPOSITION_IDS: dict[str, str] = {
    "counter": "StatVizCounter",
    "bar": "StatVizBar",
    "gauge": "StatVizGauge",
    "before_after": "StatVizBeforeAfter",
    "ratio": "StatVizRatio",
}


@dataclass(frozen=True)
class StyleBrief:
    """Visual style contract for stat-viz clips. The upstream design agent populates this once per
    video; v1 uses DEFAULT_STYLE_BRIEF. All compositions read these fields as top-level props."""

    background: str = "#0D0D0D"
    primary: str = "#FFFFFF"
    accent: str = "#FF6B35"
    font_family: str = "Inter, Arial, sans-serif"


# Fallback only. The source of truth is now the Director's BrandKit (see videogen.agent.brand_kit),
# whose `to_style_brief()` projection the pipeline injects per run (restructure/02, ADR 0008). This
# default is kept for the renderer's own backstop when no style is supplied (e.g. unit tests).
DEFAULT_STYLE_BRIEF = StyleBrief()


class StatVizRenderer:
    """Renders a stat-viz clip by merging data params + StyleBrief into Remotion composition props.

    Testable in isolation: inject a fake backend whose render_clip writes an empty file.
    """

    def __init__(self, backend: Any | None = None) -> None:
        if backend is None:
            from videogen.backends.remotion import RemotionBackend

            backend = RemotionBackend()
        self._backend = backend

    def render(
        self,
        format: Format,
        data: dict[str, Any],
        style: StyleBrief,
        out_path: Path,
        fps: int = 30,
    ) -> Path:
        """Render one stat-viz clip.

        Args:
            format: which composition to render (counter / bar / gauge / before_after / ratio).
            data: format-specific params from the tool call (value, label, etc.). Must NOT include
                  the tool's `slot` field — callers strip it before passing.
            style: per-video visual brief (colors, font). Merged into props by this layer.
            out_path: destination path for the rendered mp4.
            fps: frame rate to pass to the composition's calculateMetadata.
        """
        composition_id = _COMPOSITION_IDS.get(format)
        if composition_id is None:
            known = sorted(_COMPOSITION_IDS)
            raise ValueError(f"unsupported stat-viz format: {format!r}; known: {known}")

        props: dict[str, Any] = {
            **data,
            "background": style.background,
            "primary": style.primary,
            "accent": style.accent,
            "fontFamily": style.font_family,
            "fps": fps,
        }

        return self._backend.render_clip(composition_id, props, out_path)
