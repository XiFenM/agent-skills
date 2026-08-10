#!/usr/bin/env python3
"""Initialize a domain-neutral, practice-driven learning archive."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
PLACEHOLDER_RE = re.compile(r"\{\{[A-Z_]+\}\}")


class ArchiveInitError(ValueError):
    """Raised when a learning archive cannot be initialized safely."""


@dataclass(frozen=True, slots=True)
class ArchiveConfig:
    """Resolved configuration for one archive initialization."""

    root: Path
    output: Path
    subject: str
    slug: str
    source: str
    start_date: str


def slugify(value: str) -> str:
    """Convert an ASCII subject name into a stable hyphenated slug."""
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return re.sub(r"-{2,}", "-", slug)


def _single_line(value: str, option: str) -> str:
    normalized = " ".join(value.splitlines()).strip()
    if not normalized:
        raise ArchiveInitError(f"{option} cannot be empty")
    return normalized


def _markdown_table_cell(value: str) -> str:
    """Escape content inserted into one Markdown table cell."""
    return value.replace("\\", "\\\\").replace("|", "\\|")


def resolve_config(args: argparse.Namespace) -> ArchiveConfig:
    """Validate CLI values and resolve the output path."""
    root = args.root.resolve()
    if not root.is_dir():
        raise ArchiveInitError(f"--root is not a directory: {root}")

    subject = _single_line(args.subject, "--subject")
    slug = args.slug or slugify(subject)
    if not slug:
        raise ArchiveInitError(
            "cannot derive an ASCII slug from --subject; provide --slug explicitly"
        )
    if not SLUG_RE.fullmatch(slug):
        raise ArchiveInitError(
            "--slug must contain lowercase letters, digits, and single hyphens only"
        )

    source = _single_line(args.source, "--source")
    if args.archive is None:
        output = root / "docs" / "learning" / slug
    else:
        output = args.archive if args.archive.is_absolute() else root / args.archive
        output = output.resolve()
    if output == root:
        raise ArchiveInitError("archive output cannot replace the repository root")
    if output.exists():
        raise ArchiveInitError(f"archive output already exists: {output}")

    start_date = args.start_date or date.today().isoformat()
    try:
        date.fromisoformat(start_date)
    except ValueError as exc:
        raise ArchiveInitError(f"--start-date must use YYYY-MM-DD, got {start_date!r}") from exc

    return ArchiveConfig(
        root=root,
        output=output,
        subject=subject,
        slug=slug,
        source=source,
        start_date=start_date,
    )


def _render_template(path: Path, replacements: dict[str, str]) -> str:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ArchiveInitError(f"cannot read asset template {path}: {exc}") from exc

    for placeholder, value in replacements.items():
        content = content.replace(f"{{{{{placeholder}}}}}", value)
    unresolved = sorted(set(PLACEHOLDER_RE.findall(content)))
    if unresolved:
        raise ArchiveInitError(
            f"unresolved template placeholders in {path.name}: {', '.join(unresolved)}"
        )
    return content


def initialize_archive(config: ArchiveConfig, *, dry_run: bool = False) -> list[Path]:
    """Create an archive atomically and return its planned paths."""
    relative_paths = [
        Path("README.md"),
        Path("templates/lesson-record.md"),
        Path("lessons"),
        Path("dialogues"),
        Path("references"),
        Path("attachments"),
    ]
    if dry_run:
        return [config.output / path for path in relative_paths]

    assets_dir = Path(__file__).resolve().parent.parent / "assets"
    index = _render_template(
        assets_dir / "archive-index.md",
        {
            "SUBJECT": config.subject,
            "SUBJECT_TABLE": _markdown_table_cell(config.subject),
            "SUBJECT_SLUG": _markdown_table_cell(config.slug),
            "SOURCE_DESCRIPTION_TABLE": _markdown_table_cell(config.source),
            "START_DATE": config.start_date,
        },
    )
    lesson = _render_template(assets_dir / "lesson-record.md", {})

    config.output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(
        dir=config.output.parent,
        prefix=f".{config.output.name}.",
    ) as temporary_directory:
        staging_root = Path(temporary_directory) / config.output.name
        for directory in (
            "templates",
            "lessons",
            "dialogues",
            "references",
            "attachments",
        ):
            (staging_root / directory).mkdir(parents=True, exist_ok=True)
        (staging_root / "README.md").write_text(index, encoding="utf-8")
        (staging_root / "templates" / "lesson-record.md").write_text(
            lesson,
            encoding="utf-8",
        )
        if config.output.exists():
            raise ArchiveInitError(
                f"archive output appeared during initialization: {config.output}"
            )
        staging_root.replace(config.output)

    return [config.output / path for path in relative_paths]


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line interface."""
    parser = argparse.ArgumentParser(
        description="Create a practice-driven learning archive without overwriting files."
    )
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="repository root")
    parser.add_argument("--subject", required=True, help="human-readable subject name")
    parser.add_argument("--slug", help="stable lowercase archive slug")
    parser.add_argument(
        "--source",
        default="To be selected with the learner",
        help="primary source description stored in the archive index",
    )
    parser.add_argument(
        "--archive",
        type=Path,
        help="explicit archive path; defaults to <root>/docs/learning/<slug>",
    )
    parser.add_argument("--start-date", help="archive start date in YYYY-MM-DD")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print planned paths without creating the archive",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the archive initializer."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        config = resolve_config(args)
        created = initialize_archive(config, dry_run=args.dry_run)
    except (ArchiveInitError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    action = "would create" if args.dry_run else "created"
    print(f"{action} learning archive: {config.output}")
    for path in created:
        print(f"- {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
