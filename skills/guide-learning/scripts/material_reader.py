#!/usr/bin/env python3
"""Inspect explicitly selected local materials; never infer scope from config.

This read-only tool validates formats, not source truth, authorization, safety of
rendered content, or learning mastery. PNG pixels and drawio diagram payloads are
not decoded. Use a dedicated viewer when visual evidence matters.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import struct
import sys
import xml.etree.ElementTree as ET
import zlib


MAX_FILES = 64
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024
MAX_TEXT_OUTPUT_BYTES = 256 * 1024
MAX_JSON_OUTPUT_BYTES = 1024 * 1024
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
TEXT_SUFFIXES = {".md", ".markdown", ".txt", ".py", ".json", ".yaml", ".yml",
                 ".toml", ".csv", ".xml", ".drawio", ".h", ".cpp", ".c", ".sh"}
BINARY_SUFFIXES = {".pdf", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff",
                   ".zip", ".gz", ".xlsx", ".docx", ".pptx", ".mp3", ".mp4"}


class SelectionError(ValueError):
    """Selection or resource bounds are invalid; no report body is emitted."""


class FormatError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _open_directory(parts: tuple[str, ...], *, base_fd: int | None = None) -> int:
    """Walk each component without following symlinks, including repo ancestors."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    current = os.open("/", flags) if base_fd is None else os.dup(base_fd)
    try:
        for part in parts:
            child = os.open(part, flags, dir_fd=current)
            os.close(current)
            current = child
        return current
    except BaseException:
        os.close(current)
        raise


def _select_files(repo: Path, paths: list[str]) -> list[tuple[str, int, os.stat_result]]:
    if not paths or len(paths) > MAX_FILES:
        raise SelectionError(f"select 1 to {MAX_FILES} exact files")
    if len(set(paths)) != len(paths):
        raise SelectionError("duplicate paths are not accepted")
    selected: list[tuple[str, int, os.stat_result]] = []
    root_fd = None
    try:
        root_fd = _open_directory(repo.parts[1:])
        total = 0
        for path in paths:
            if (not path or len(path.encode("utf-8")) > 4096 or "\\" in path
                    or any(ord(c) < 32 for c in path)
                    or any(part in {"", ".", ".."} for part in path.split("/"))):
                raise SelectionError(f"not an exact repository-relative path: {path!r}")
            parts = tuple(path.split("/"))
            parent_fd = _open_directory(parts[:-1], base_fd=root_fd)
            try:
                # NONBLOCK prevents special files such as FIFOs blocking preflight.
                fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                             dir_fd=parent_fd)
            finally:
                os.close(parent_fd)
            info = os.fstat(fd)
            selected.append((path, fd, info))
            if not stat.S_ISREG(info.st_mode):
                raise SelectionError(f"not a regular file: {path}")
            if info.st_size > MAX_FILE_BYTES:
                raise SelectionError(f"file size exceeds {MAX_FILE_BYTES} bytes: {path}")
            total += info.st_size
            if total > MAX_TOTAL_BYTES:
                raise SelectionError(f"total selection exceeds {MAX_TOTAL_BYTES} bytes")
        return selected
    except (OSError, UnicodeError) as exc:
        for _, fd, _ in selected:
            os.close(fd)
        raise SelectionError(f"unsafe or inaccessible selection: {exc}") from exc
    except BaseException:
        for _, fd, _ in selected:
            os.close(fd)
        raise
    finally:
        if root_fd is not None:
            os.close(root_fd)


def _read_selected(fd: int, info: os.stat_result) -> bytes:
    chunks = []
    remaining = info.st_size + 1
    while remaining:
        chunk = os.read(fd, min(remaining, 64 * 1024))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    data = b"".join(chunks)
    after = os.fstat(fd)
    if len(data) != info.st_size or after.st_size != info.st_size or after.st_mtime_ns != info.st_mtime_ns:
        raise SelectionError("selected file changed during reading; retry explicit selection")
    return data


def _validate_png(data: bytes) -> dict:
    def invalid(message: str) -> None:
        raise FormatError("invalid_png", message)

    if not data.startswith(PNG_SIGNATURE):
        invalid("missing PNG signature")
    offset, seen_header, seen_data, ended_data = 8, False, False, False
    width = height = 0
    while offset < len(data):
        if len(data) - offset < 12:
            invalid("truncated PNG chunk")
        length = struct.unpack_from(">I", data, offset)[0]
        kind = data[offset + 4:offset + 8]
        end = offset + 12 + length
        if end > len(data) or not all(65 <= c <= 90 or 97 <= c <= 122 for c in kind):
            invalid("invalid PNG chunk length or type")
        payload = data[offset + 8:end - 4]
        crc = struct.unpack_from(">I", data, end - 4)[0]
        if zlib.crc32(kind + payload) != crc:
            invalid("PNG chunk CRC mismatch")
        if not seen_header and kind != b"IHDR":
            invalid("IHDR must be the first chunk")
        if kind == b"IHDR":
            if seen_header or length != 13:
                invalid("invalid or duplicate IHDR")
            width, height, depth, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", payload)
            depths = {0: {1, 2, 4, 8, 16}, 2: {8, 16}, 3: {1, 2, 4, 8}, 4: {8, 16}, 6: {8, 16}}
            if (not 0 < width < 2**31 or not 0 < height < 2**31
                    or depth not in depths.get(color, set())
                    or compression != 0 or filtering != 0 or interlace not in {0, 1}):
                invalid("invalid PNG header parameters")
            seen_header = True
        elif kind == b"IDAT":
            if ended_data:
                invalid("non-contiguous PNG image data")
            seen_data = True
        else:
            ended_data = seen_data
        if kind == b"IEND":
            if length != 0 or not seen_data or end != len(data):
                invalid("invalid IEND, missing image data, or trailing bytes")
            return {"kind": "png", "validation_level": "png-structure-crc",
                    "width": width, "height": height, "pixel_decoding": False,
                    "next_action": "Use an image viewer with absolute_path for visual inspection; pixel data is not decoded here."}
        offset = end
    invalid("missing PNG IEND")
    raise AssertionError("unreachable")


def _validate_content(path: str, data: bytes) -> tuple[dict, str | None]:
    suffix = Path(path).suffix.lower()
    if data.startswith(PNG_SIGNATURE):
        if suffix != ".png":
            raise FormatError("extension_mismatch", "PNG signature requires a .png selected path")
        return _validate_png(data), None
    if suffix == ".png":
        return _validate_png(data), None
    if suffix in BINARY_SUFFIXES or data.startswith((b"%PDF-", b"PK\x03\x04", b"\xff\xd8\xff", b"GIF87a", b"GIF89a", b"RIFF")):
        raise FormatError("unsupported_format", "use a format-specific reader or viewer for this binary material")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        code = "invalid_utf8" if suffix in TEXT_SUFFIXES else "unsupported_format"
        raise FormatError(code, f"not UTF-8 text (byte offset {exc.start})") from exc
    if any((ord(char) < 32 and char not in "\t\n\r\f") or ord(char) == 127 for char in text):
        code = "binary_text" if suffix in TEXT_SUFFIXES else "unsupported_format"
        raise FormatError(code, "NUL or non-text control bytes are not accepted as learning text")
    if suffix == ".drawio":
        upper = text.upper()
        if "<!DOCTYPE" in upper or "<!ENTITY" in upper:
            raise FormatError("unsafe_xml", "drawio DTDs and entity declarations are not allowed")
        try:
            root = ET.fromstring(text)
        except ET.ParseError as exc:
            raise FormatError("invalid_drawio", f"malformed drawio XML: {exc}") from exc
        if root.tag not in {"mxfile", "mxGraphModel"}:
            raise FormatError("invalid_drawio", "expected an mxfile or mxGraphModel root")
        return {"kind": "drawio", "validation_level": "xml-structure",
                "diagram_payload_decoding": False,
                "next_action": "Use an exported image or drawio viewer for visual meaning; embedded diagram payloads are not decoded."}, text
    return {"kind": "text", "validation_level": "utf8-text"}, text


def inspect_materials(repo: Path | str, paths: list[str], *, include_text: bool = False) -> dict:
    """Read only the exact selected regular files, after whole-selection preflight."""
    if (not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY")
            or os.open not in os.supports_dir_fd):
        raise SelectionError("safe no-follow file access is unavailable on this platform")
    repo = Path(os.path.abspath(repo))
    selected = _select_files(repo, paths)
    files = []
    output_size = 0
    try:
        for path, fd, info in selected:
            item = {"path": path, "absolute_path": str(repo / path), "size_bytes": info.st_size}
            try:
                details, text = _validate_content(path, _read_selected(fd, info))
                item.update(details, ok=True)
                if include_text and text is not None:
                    output_size += len(text.encode("utf-8"))
                    if output_size > MAX_TEXT_OUTPUT_BYTES:
                        raise SelectionError(f"text output exceeds {MAX_TEXT_OUTPUT_BYTES} bytes; select smaller files or omit --include-text")
                    item["text"] = text
            except FormatError as exc:
                item.update(ok=False, error_code=exc.code, message=str(exc), validation_level="failed")
            files.append(item)
    except OSError as exc:
        raise SelectionError(f"could not read selected file: {exc}") from exc
    finally:
        for _, fd, _ in selected:
            os.close(fd)
    report = {"schema": "guide-learning.material-report/v1", "ok": all(item["ok"] for item in files),
              "semantic_validation": False, "selection_scope": "explicit-files-only",
              "notice": "Format checks do not establish authorization, source truth, safe rendering, or learning mastery.",
              "files": files}
    if len(json.dumps(report, ensure_ascii=False).encode("utf-8")) > MAX_JSON_OUTPUT_BYTES:
        raise SelectionError("JSON output limit exceeded; select fewer files or omit --include-text")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=(
            "Limits: 64 files; 8 MiB per file; 32 MiB per selection; "
            "256 KiB included text; 1 MiB JSON output. Limits fail explicitly, "
            "without truncation. Reports go to stdout as JSON. Exit codes: "
            "0 = all selected format checks passed; 1 = format errors; 2 = invalid selection, "
            "resource limit, or arguments. Requires POSIX-style O_NOFOLLOW, "
            "O_DIRECTORY, and directory-relative file access; unsupported "
            "platforms fail without weakening symlink protection."
        ),
    )
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--path", required=True, action="append", help="exact repository-relative regular file; repeat to select more")
    parser.add_argument("--include-text", action="store_true", help="include bounded UTF-8 text/XML; never image bytes")
    args = parser.parse_args(argv)
    try:
        report = inspect_materials(args.repo, args.path, include_text=args.include_text)
    except SelectionError as exc:
        print(json.dumps({"ok": False, "error_code": "invalid_selection", "message": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
