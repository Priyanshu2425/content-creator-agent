"""`videogen preview`: stage a finished run's IR for a browser preview (Remotion Studio).

These cover the deterministic, file-IO parts -- resolving the run argument to an IR JSON and staging
referenced media into the project's public dir with rewritten srcs -- not the Studio subprocess.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from videogen.app.preview import resolve_ir_json, stage_preview_payload


def test_resolve_prefers_final_ir_json_in_a_run_dir(tmp_path: Path) -> None:
    (tmp_path / "final.ir.json").write_text("{}")
    (tmp_path / "round-1.ir.json").write_text("{}")
    assert resolve_ir_json(tmp_path) == tmp_path / "final.ir.json"


def test_resolve_falls_back_to_newest_ir_json(tmp_path: Path) -> None:
    old = tmp_path / "round-1.ir.json"
    old.write_text("{}")
    new = tmp_path / "round-2.ir.json"
    new.write_text("{}")
    import os

    os.utime(old, (1, 1))
    os.utime(new, (2, 2))
    assert resolve_ir_json(tmp_path) == new


def test_resolve_accepts_a_direct_file(tmp_path: Path) -> None:
    f = tmp_path / "x.ir.json"
    f.write_text("{}")
    assert resolve_ir_json(f) == f


def test_resolve_raises_when_nothing_found(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        resolve_ir_json(tmp_path)


def test_stage_copies_media_and_rewrites_src_to_a_public_path(tmp_path: Path) -> None:
    media = tmp_path / "host.mp4"
    media.write_bytes(b"fake-mp4")
    public = tmp_path / "public"
    payload = {
        "width": 1080,
        "height": 1920,
        "fps": 30,
        "duration": 2.0,
        "layers": [
            {"kind": "media", "src": str(media)},
            {"kind": "text", "runs": []},  # no src -- untouched
        ],
    }

    wrapped = stage_preview_payload(payload, public)

    layers = wrapped["ir"]["layers"]
    assert layers[0]["src"].startswith("preview/") and layers[0]["src"].endswith("_host.mp4")
    assert "src" not in layers[1]
    staged_name = layers[0]["src"].split("/", 1)[1]
    assert (public / "preview" / staged_name).read_bytes() == b"fake-mp4"


def test_stage_leaves_a_missing_source_untouched(tmp_path: Path) -> None:
    public = tmp_path / "public"
    payload = {"layers": [{"kind": "media", "src": "/gone/missing.mp4"}]}

    wrapped = stage_preview_payload(payload, public)

    assert wrapped["ir"]["layers"][0]["src"] == "/gone/missing.mp4"  # not crashed, not rewritten
