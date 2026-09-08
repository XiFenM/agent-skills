from __future__ import annotations

import importlib.util
import json
import os
import struct
import subprocess
import sys
import zlib
from pathlib import Path

import pytest


pytestmark = pytest.mark.skipif(
    not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY")
    or os.open not in os.supports_dir_fd,
    reason="material reader requires POSIX no-follow directory-relative access",
)


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "material_reader.py"
spec = importlib.util.spec_from_file_location("guide_material_reader", SCRIPT)
assert spec is not None and spec.loader is not None
reader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reader)


def png() -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00"))
        + chunk(b"IEND", b"")
    )


def test_mixed_exact_selection_defaults_to_metadata_and_does_not_write(tmp_path):
    (tmp_path / "note.md").write_text("# 知识\n", encoding="utf-8")
    (tmp_path / "diagram.drawio").write_text(
        '<mxfile><diagram name="未解压">opaque-content</diagram></mxfile>',
        encoding="utf-8",
    )
    (tmp_path / "diagram.png").write_bytes(png())
    (tmp_path / "unselected.md").write_bytes(b"\xff")
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}

    report = reader.inspect_materials(
        tmp_path, ["note.md", "diagram.drawio", "diagram.png"]
    )

    assert report["ok"] is True
    assert report["semantic_validation"] is False
    assert [item["kind"] for item in report["files"]] == [
        "text", "drawio", "png"
    ]
    assert all("text" not in item for item in report["files"])
    assert report["files"][2]["validation_level"] == "png-structure-crc"
    assert report["files"][2]["pixel_decoding"] is False
    assert "image viewer" in report["files"][2]["next_action"]
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before


def test_include_text_does_not_emit_image_bytes(tmp_path):
    (tmp_path / "note.md").write_text("具体知识点", encoding="utf-8")
    (tmp_path / "image.png").write_bytes(png())
    report = reader.inspect_materials(
        tmp_path, ["note.md", "image.png"], include_text=True
    )
    assert report["files"][0]["text"] == "具体知识点"
    assert "text" not in report["files"][1]
    assert "data" not in report["files"][1]


def test_missing_safe_file_access_fails_before_selection(tmp_path, monkeypatch):
    monkeypatch.setattr(reader.os, "supports_dir_fd", set())
    with pytest.raises(reader.SelectionError, match="unavailable"):
        reader.inspect_materials(tmp_path, ["note.md"])


@pytest.mark.parametrize(
    "filename,data,code",
    [
        ("note.md", b"\xff", "invalid_utf8"),
        ("note.md", b"hello\x00world", "binary_text"),
        ("note.md", b"hello\x7fworld", "binary_text"),
        ("fake.png", b"plain text", "invalid_png"),
        ("fake.md", png(), "extension_mismatch"),
        ("short.png", png()[:-5], "invalid_png"),
        ("crc.png", png()[:-1] + b"x", "invalid_png"),
        ("extra.png", png() + b"junk", "invalid_png"),
        ("unknown.bin", b"\xff\x00\xfe", "unsupported_format"),
        ("opaque.pdf", b"%PDF-1.7\nhello", "unsupported_format"),
        ("wrong.drawio", b"<note/>", "invalid_drawio"),
        ("short.drawio", b"<mxfile>", "invalid_drawio"),
        (
            "entity.drawio",
            b'<!DOCTYPE mxfile [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
            b"<mxfile>&x;</mxfile>",
            "unsafe_xml",
        ),
    ],
)
def test_rejects_invalid_or_disguised_contents(tmp_path, filename, data, code):
    (tmp_path / filename).write_bytes(data)
    report = reader.inspect_materials(tmp_path, [filename], include_text=True)
    assert report["ok"] is False
    assert report["files"][0]["error_code"] == code
    assert "text" not in report["files"][0]


@pytest.mark.parametrize("bad_path", ["../outside.md", "/etc/passwd", "./note.md", "a/../note.md", "a//note.md", "missing.md", "folder"])
def test_all_paths_are_preflighted_before_any_contents_are_read(tmp_path, monkeypatch, bad_path):
    (tmp_path / "note.md").write_text("safe")
    (tmp_path / "folder").mkdir()
    reads = []
    monkeypatch.setattr(reader, "_read_selected", lambda *args: reads.append(args))
    with pytest.raises(reader.SelectionError):
        reader.inspect_materials(tmp_path, ["note.md", bad_path])
    assert reads == []


@pytest.mark.parametrize("link_target", ["note.md", "folder"])
def test_symlinks_are_not_followed(tmp_path, link_target):
    (tmp_path / "note.md").write_text("safe")
    (tmp_path / "folder").mkdir()
    (tmp_path / "folder" / "inner.md").write_text("inner")
    (tmp_path / "link").symlink_to(tmp_path / link_target)
    selected = "link" if link_target == "note.md" else "link/inner.md"
    with pytest.raises(reader.SelectionError):
        reader.inspect_materials(tmp_path, [selected])


def test_fifo_is_rejected_without_blocking(tmp_path):
    os.mkfifo(tmp_path / "pipe")
    with pytest.raises(reader.SelectionError):
        reader.inspect_materials(tmp_path, ["pipe"])


def test_repository_symlink_is_rejected(tmp_path):
    (tmp_path / "real").mkdir()
    (tmp_path / "real" / "note.md").write_text("safe")
    (tmp_path / "alias").symlink_to(tmp_path / "real")
    with pytest.raises(reader.SelectionError):
        reader.inspect_materials(tmp_path / "alias", ["note.md"])


@pytest.mark.parametrize("paths", [[], ["note.md", "note.md"], [f"{i}.md" for i in range(65)]])
def test_selection_count_and_duplicates_are_bounded(tmp_path, paths):
    with pytest.raises(reader.SelectionError):
        reader.inspect_materials(tmp_path, paths)


def test_file_growth_during_read_is_rejected(tmp_path):
    path = tmp_path / "note.md"
    path.write_text("old")
    with path.open("rb") as stream:
        original_info = os.fstat(stream.fileno())
        path.write_text("new contents")
        with pytest.raises(reader.SelectionError, match="changed"):
            reader._read_selected(stream.fileno(), original_info)


def test_size_and_batch_limits_precede_body_reads(tmp_path, monkeypatch):
    (tmp_path / "one.md").write_text("12345")
    (tmp_path / "two.md").write_text("12345")
    monkeypatch.setattr(reader, "MAX_FILE_BYTES", 4)
    with pytest.raises(reader.SelectionError, match="size"):
        reader.inspect_materials(tmp_path, ["one.md"])
    monkeypatch.setattr(reader, "MAX_FILE_BYTES", 8)
    monkeypatch.setattr(reader, "MAX_TOTAL_BYTES", 8)
    with pytest.raises(reader.SelectionError, match="total"):
        reader.inspect_materials(tmp_path, ["one.md", "two.md"])


def test_text_output_limit_fails_explicitly_not_silently_truncates(tmp_path, monkeypatch):
    (tmp_path / "note.md").write_text("12345")
    monkeypatch.setattr(reader, "MAX_TEXT_OUTPUT_BYTES", 4)
    with pytest.raises(reader.SelectionError, match="output"):
        reader.inspect_materials(tmp_path, ["note.md"], include_text=True)
    assert reader.inspect_materials(tmp_path, ["note.md"])["ok"] is True


def test_json_output_is_also_bounded(tmp_path, monkeypatch):
    (tmp_path / "note.md").write_text("small")
    monkeypatch.setattr(reader, "MAX_JSON_OUTPUT_BYTES", 10)
    with pytest.raises(reader.SelectionError, match="JSON output"):
        reader.inspect_materials(tmp_path, ["note.md"])


def test_cli_requires_explicit_paths_and_emits_json(tmp_path):
    (tmp_path / "note.md").write_text("test")
    base = [sys.executable, "-B", str(SCRIPT), "--repo", str(tmp_path)]
    missing = subprocess.run(base, capture_output=True, text=True)
    assert missing.returncode == 2
    result = subprocess.run(base + ["--path", "note.md"], capture_output=True, text=True)
    assert result.returncode == 0
    assert json.loads(result.stdout)["ok"] is True
    assert "text" not in json.loads(result.stdout)["files"][0]
    invalid = subprocess.run(base + ["--path", "../escape"], capture_output=True, text=True)
    assert invalid.returncode == 2
    assert json.loads(invalid.stdout)["error_code"] == "invalid_selection"
    (tmp_path / "bad.png").write_bytes(b"not png")
    bad_format = subprocess.run(base + ["--path", "bad.png"], capture_output=True, text=True)
    assert bad_format.returncode == 1
    assert json.loads(bad_format.stdout)["files"][0]["error_code"] == "invalid_png"


def test_cli_help_documents_limits_and_safe_platform_requirements():
    result = subprocess.run(
        [sys.executable, "-B", str(SCRIPT), "--help"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    compact_help = "".join(result.stdout.split())
    for expected in ("64 files", "8 MiB", "32 MiB", "256 KiB", "1 MiB",
                     "Exit codes:", "POSIX-style", "O_NOFOLLOW"):
        assert "".join(expected.split()) in compact_help
