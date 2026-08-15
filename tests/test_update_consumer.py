from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UPDATE_SCRIPT = ROOT / "tools" / "update_consumer.py"


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def git(
    root: Path,
    *arguments: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "git",
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.com",
            "-c",
            "protocol.file.allow=always",
            "-c",
            "core.autocrlf=false",
            "-C",
            root,
            *arguments,
        ],
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def initialize(root: Path, *, bare: bool = False) -> None:
    root.mkdir(parents=True)
    arguments = ["init", "-q", "--initial-branch=main"]
    if bare:
        arguments.append("--bare")
    git(root, *arguments)


def commit_all(root: Path, message: str) -> str:
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", message)
    return git(root, "rev-parse", "HEAD").stdout.strip()


def gitlink(root: Path, path: str) -> str:
    metadata = git(root, "ls-files", "--stage", "--", path).stdout.split("\t", 1)[0]
    mode, commit, stage = metadata.split()
    assert mode == "160000" and stage == "0"
    return commit


@dataclass(frozen=True)
class Fixture:
    consumer: Path
    central_seed: Path
    central_remote: Path
    nested_seed: Path
    v1: str
    v2: str
    v3: str
    nested_v1: str
    nested_v2: str
    consumer_head: str


class UpdateConsumerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_update(
        self, fixture: Fixture, *arguments: str
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["GIT_ALLOW_PROTOCOL"] = "file"
        return subprocess.run(
            [
                sys.executable,
                UPDATE_SCRIPT,
                "--repo",
                fixture.consumer,
                *arguments,
            ],
            cwd=fixture.consumer,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=environment,
        )

    def make_fixture(self) -> Fixture:
        nested_seed = self.root / "nested-seed"
        initialize(nested_seed)
        (nested_seed / "version.txt").write_text("nested v1\n", encoding="utf-8")
        nested_v1 = commit_all(nested_seed, "nested v1")
        nested_remote = self.root / "nested.git"
        initialize(nested_remote, bare=True)
        git(nested_seed, "remote", "add", "origin", str(nested_remote))
        git(nested_seed, "push", "-q", "-u", "origin", "main")

        central_seed = self.root / "central-seed"
        initialize(central_seed)
        tools = central_seed / "tools"
        tools.mkdir()
        shutil.copy2(ROOT / "tools" / "materialize_skills.py", tools)
        shutil.copy2(ROOT / "tools" / "skill_names.py", tools)
        shutil.copy2(ROOT / "tools" / "update_consumer.py", tools)
        (central_seed / ".gitignore").write_text(
            "__pycache__/\n*.py[cod]\nvendor/new-dependency/\n",
            encoding="utf-8",
        )
        skill = central_seed / "skills" / "demo-skill"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\nname: demo-skill\ndescription: Fixture.\n---\n\nDemo v1.\n",
            encoding="utf-8",
        )
        write_json(
            central_seed / "catalog.json",
            {
                "schema_version": 2,
                "selection_groups": {
                    "primary-learning": {"max_distinct_per_config": 1}
                },
                "retired_names": {},
                "skills": [
                    {
                        "name": "demo-skill",
                        "kind": "first-party",
                        "path": "skills/demo-skill",
                        "lifecycle": {"state": "active"},
                        "groups": [],
                    }
                ],
            },
        )
        git(
            central_seed,
            "submodule",
            "add",
            "-q",
            str(nested_remote),
            "vendor/dependency",
        )
        v1 = commit_all(central_seed, "central v1")
        central_remote = self.root / "central.git"
        initialize(central_remote, bare=True)
        git(central_seed, "remote", "add", "origin", str(central_remote))
        git(central_seed, "push", "-q", "-u", "origin", "main")

        consumer = self.root / "consumer"
        initialize(consumer)
        write_json(
            consumer / ".agent-skills.json",
            {
                "version": 1,
                "source": ".agent-skills",
                "skills": {"demo-skill": ["codex"]},
            },
        )
        (consumer / ".gitignore").write_text(
            "/.agents/skills/\n"
            "/.claude/skills/\n"
            "/.agent-skills.state.json\n"
            "/.agent-skills.lock\n",
            encoding="utf-8",
        )
        (consumer / "notes.txt").write_text("committed\n", encoding="utf-8")
        git(
            consumer,
            "submodule",
            "add",
            "-q",
            str(central_remote),
            ".agent-skills",
        )
        git(
            consumer,
            "submodule",
            "add",
            "-q",
            str(nested_remote),
            "unrelated-submodule",
        )
        consumer_head = commit_all(consumer, "consumer at central v1")
        git(consumer, "submodule", "deinit", "-q", "-f", "--", "unrelated-submodule")
        materialize = subprocess.run(
            [
                sys.executable,
                consumer / ".agent-skills" / "tools" / "materialize_skills.py",
                "--repo",
                consumer,
            ],
            cwd=consumer,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(materialize.returncode, 0, materialize.stderr)

        (nested_seed / "version.txt").write_text("nested v2\n", encoding="utf-8")
        nested_v2 = commit_all(nested_seed, "nested v2")
        git(nested_seed, "push", "-q", "origin", "main")

        dependency = central_seed / "vendor" / "dependency"
        git(dependency, "fetch", "-q", "origin")
        git(dependency, "checkout", "-q", "--detach", nested_v2)
        (skill / "SKILL.md").write_text(
            "---\nname: demo-skill\ndescription: Fixture.\n---\n\nDemo v2.\n",
            encoding="utf-8",
        )
        v2 = commit_all(central_seed, "central v2")
        git(central_seed, "tag", "release-v2", v2)
        git(central_seed, "push", "-q", "origin", "main", "release-v2")

        (skill / "SKILL.md").write_text(
            "---\nname: demo-skill\ndescription: Fixture.\n---\n\nDemo v3.\n",
            encoding="utf-8",
        )
        v3 = commit_all(central_seed, "central v3")
        git(central_seed, "push", "-q", "origin", "main")

        return Fixture(
            consumer=consumer,
            central_seed=central_seed,
            central_remote=central_remote,
            nested_seed=nested_seed,
            v1=v1,
            v2=v2,
            v3=v3,
            nested_v1=nested_v1,
            nested_v2=nested_v2,
            consumer_head=consumer_head,
        )

    def assert_materialized(self, fixture: Fixture, version: str) -> None:
        generated = (
            fixture.consumer / ".agents" / "skills" / "demo-skill" / "SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertIn(f"Demo {version}.", generated)
        result = subprocess.run(
            [
                sys.executable,
                fixture.consumer
                / ".agent-skills"
                / "tools"
                / "materialize_skills.py",
                "--repo",
                fixture.consumer,
                "--check",
            ],
            cwd=fixture.consumer,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_default_update_materializes_without_publishing_or_touching_other_changes(
        self,
    ) -> None:
        fixture = self.make_fixture()
        notes = fixture.consumer / "notes.txt"
        notes.write_text("staged\n", encoding="utf-8")
        git(fixture.consumer, "add", "notes.txt")
        staged_before = git(fixture.consumer, "diff", "--cached", "--binary").stdout
        notes.write_text("staged\nunstaged\n", encoding="utf-8")
        (fixture.consumer / "untracked.txt").write_text("keep me\n", encoding="utf-8")

        result = self.run_update(fixture)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            git(fixture.consumer / ".agent-skills", "rev-parse", "HEAD").stdout.strip(),
            fixture.v3,
        )
        self.assertEqual(
            git(
                fixture.consumer / ".agent-skills" / "vendor" / "dependency",
                "rev-parse",
                "HEAD",
            ).stdout.strip(),
            fixture.nested_v2,
        )
        self.assertEqual(gitlink(fixture.consumer, ".agent-skills"), fixture.v1)
        self.assertEqual(
            git(fixture.consumer, "rev-parse", "HEAD").stdout.strip(),
            fixture.consumer_head,
        )
        self.assertEqual(
            git(fixture.consumer, "diff", "--cached", "--binary").stdout,
            staged_before,
        )
        self.assertEqual(notes.read_text(encoding="utf-8"), "staged\nunstaged\n")
        self.assertEqual(
            (fixture.consumer / "untracked.txt").read_text(encoding="utf-8"),
            "keep me\n",
        )
        unrelated_status = git(
            fixture.consumer,
            "submodule",
            "status",
            "--",
            "unrelated-submodule",
        ).stdout
        self.assertTrue(unrelated_status.startswith("-"), unrelated_status)
        self.assert_materialized(fixture, "v3")
        self.assertIn("was not staged, committed, or pushed", result.stdout)
        self.assertIn("git commit --only", result.stdout)

        git(fixture.consumer, "add", "--", ".agent-skills")
        git(
            fixture.consumer,
            "commit",
            "-q",
            "--only",
            "-m",
            "chore: update agent skills",
            "--",
            ".agent-skills",
        )
        self.assertEqual(
            git(fixture.consumer, "diff", "--cached", "--name-only").stdout,
            "notes.txt\n",
        )

    def test_script_can_update_the_checkout_it_is_running_from(self) -> None:
        fixture = self.make_fixture()
        environment = os.environ.copy()
        environment["GIT_ALLOW_PROTOCOL"] = "file"

        result = subprocess.run(
            [
                sys.executable,
                fixture.consumer
                / ".agent-skills"
                / "tools"
                / "update_consumer.py",
                "--repo",
                fixture.consumer,
            ],
            cwd=fixture.consumer,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=environment,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            git(fixture.consumer / ".agent-skills", "rev-parse", "HEAD").stdout.strip(),
            fixture.v3,
        )
        self.assert_materialized(fixture, "v3")

    def test_dry_run_fetches_metadata_without_changing_checkout_or_generated_files(
        self,
    ) -> None:
        fixture = self.make_fixture()
        state_before = (fixture.consumer / ".agent-skills.state.json").read_bytes()

        result = self.run_update(fixture, "--dry-run")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            git(fixture.consumer / ".agent-skills", "rev-parse", "HEAD").stdout.strip(),
            fixture.v1,
        )
        self.assertEqual(gitlink(fixture.consumer, ".agent-skills"), fixture.v1)
        self.assertEqual(
            (fixture.consumer / ".agent-skills.state.json").read_bytes(), state_before
        )
        self.assert_materialized(fixture, "v1")
        self.assertIn(fixture.v3[:12], result.stdout)
        self.assertIn("no checkout or generated files were changed", result.stdout)

    def test_explicit_tag_selects_that_release_instead_of_remote_main(self) -> None:
        fixture = self.make_fixture()

        result = self.run_update(fixture, "--ref", "release-v2")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            git(fixture.consumer / ".agent-skills", "rev-parse", "HEAD").stdout.strip(),
            fixture.v2,
        )
        self.assert_materialized(fixture, "v2")

    def test_non_fast_forward_target_requires_an_explicit_override(self) -> None:
        fixture = self.make_fixture()
        first = self.run_update(fixture)
        self.assertEqual(first.returncode, 0, first.stderr)

        rejected = self.run_update(fixture, "--ref", "release-v2")

        self.assertEqual(rejected.returncode, 2)
        self.assertIn("not a fast-forward", rejected.stderr)
        self.assertEqual(
            git(fixture.consumer / ".agent-skills", "rev-parse", "HEAD").stdout.strip(),
            fixture.v3,
        )
        accepted = self.run_update(
            fixture,
            "--ref",
            "release-v2",
            "--allow-non-fast-forward",
        )
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertEqual(
            git(fixture.consumer / ".agent-skills", "rev-parse", "HEAD").stdout.strip(),
            fixture.v2,
        )
        self.assert_materialized(fixture, "v2")

    def test_normal_update_initializes_a_deinitialized_central_submodule(self) -> None:
        fixture = self.make_fixture()
        git(
            fixture.consumer,
            "submodule",
            "deinit",
            "-q",
            "-f",
            "--",
            ".agent-skills",
        )

        result = self.run_update(fixture)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            git(fixture.consumer / ".agent-skills", "rev-parse", "HEAD").stdout.strip(),
            fixture.v3,
        )
        self.assert_materialized(fixture, "v3")

    def test_dry_run_refuses_to_initialize_a_missing_checkout(self) -> None:
        fixture = self.make_fixture()
        git(
            fixture.consumer,
            "submodule",
            "deinit",
            "-q",
            "-f",
            "--",
            ".agent-skills",
        )

        result = self.run_update(fixture, "--dry-run")

        self.assertEqual(result.returncode, 2)
        self.assertIn("is not initialized", result.stderr)
        self.assertFalse((fixture.consumer / ".agent-skills" / "catalog.json").exists())

    def test_update_refuses_to_initialize_over_a_nonempty_directory(self) -> None:
        fixture = self.make_fixture()
        git(
            fixture.consumer,
            "submodule",
            "deinit",
            "-q",
            "-f",
            "--",
            ".agent-skills",
        )
        precious = fixture.consumer / ".agent-skills" / "precious.txt"
        precious.parent.mkdir(exist_ok=True)
        precious.write_text("USER PRECIOUS DATA\n", encoding="utf-8")

        result = self.run_update(fixture)

        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("over a non-empty directory", result.stderr)
        self.assertEqual(
            precious.read_text(encoding="utf-8"), "USER PRECIOUS DATA\n"
        )

    def test_dirty_central_checkout_is_rejected_before_fetch(self) -> None:
        fixture = self.make_fixture()
        local = fixture.consumer / ".agent-skills" / "local.txt"
        local.write_text("do not lose\n", encoding="utf-8")

        result = self.run_update(fixture)

        self.assertEqual(result.returncode, 2)
        self.assertIn("local or nested changes", result.stderr)
        self.assertEqual(local.read_text(encoding="utf-8"), "do not lose\n")
        self.assertEqual(
            git(fixture.consumer / ".agent-skills", "rev-parse", "HEAD").stdout.strip(),
            fixture.v1,
        )
        local.unlink()
        self.assert_materialized(fixture, "v1")

    def test_ignored_file_inside_existing_nested_submodule_blocks_checkout(self) -> None:
        fixture = self.make_fixture()
        central = fixture.consumer / ".agent-skills"
        git(
            central,
            "submodule",
            "update",
            "--init",
            "--checkout",
            "--",
            "vendor/dependency",
        )
        nested = central / "vendor" / "dependency"
        exclude_value = git(
            nested, "rev-parse", "--git-path", "info/exclude"
        ).stdout.strip()
        exclude = Path(exclude_value)
        if not exclude.is_absolute():
            exclude = nested / exclude
        exclude.write_text("cache.txt\n", encoding="utf-8")
        cache = nested / "cache.txt"
        cache.write_text("USER CACHE DATA\n", encoding="utf-8")

        result = self.run_update(fixture)

        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("contains local or ignored files", result.stderr)
        self.assertEqual(cache.read_text(encoding="utf-8"), "USER CACHE DATA\n")
        self.assertEqual(
            git(nested, "rev-parse", "HEAD").stdout.strip(), fixture.nested_v1
        )
        self.assertEqual(
            git(central, "rev-parse", "HEAD").stdout.strip(), fixture.v1
        )

    def test_materialization_failure_restores_old_checkout_and_generated_files(
        self,
    ) -> None:
        fixture = self.make_fixture()
        (fixture.central_seed / ".gitignore").write_text(
            "__pycache__/\n*.py[cod]\n", encoding="utf-8"
        )
        git(
            fixture.central_seed,
            "submodule",
            "add",
            "-q",
            str(self.root / "nested.git"),
            "vendor/new-dependency",
        )
        write_json(fixture.central_seed / "catalog.json", {})
        broken = commit_all(fixture.central_seed, "broken target")
        git(fixture.central_seed, "push", "-q", "origin", "main")
        state_before = (fixture.consumer / ".agent-skills.state.json").read_bytes()

        result = self.run_update(fixture)

        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn(broken[:12], result.stdout)
        self.assertIn("restored", result.stderr)
        self.assertEqual(
            git(fixture.consumer / ".agent-skills", "rev-parse", "HEAD").stdout.strip(),
            fixture.v1,
        )
        self.assertEqual(
            git(
                fixture.consumer / ".agent-skills" / "vendor" / "dependency",
                "rev-parse",
                "HEAD",
            ).stdout.strip(),
            fixture.nested_v1,
        )
        self.assertEqual(gitlink(fixture.consumer, ".agent-skills"), fixture.v1)
        rolled_back_new_path = (
            fixture.consumer / ".agent-skills" / "vendor" / "new-dependency"
        )
        self.assertTrue(
            not rolled_back_new_path.exists()
            or next(rolled_back_new_path.iterdir(), None) is None
        )
        self.assertEqual(
            git(
                fixture.consumer / ".agent-skills",
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
                "--ignore-submodules=none",
            ).stdout,
            "",
        )
        self.assertEqual(
            (fixture.consumer / ".agent-skills.state.json").read_bytes(), state_before
        )
        self.assert_materialized(fixture, "v1")

    def test_new_nested_submodule_never_takes_over_a_preexisting_ignored_repo(
        self,
    ) -> None:
        fixture = self.make_fixture()
        preexisting = (
            fixture.consumer / ".agent-skills" / "vendor" / "new-dependency"
        )
        git(
            fixture.consumer / ".agent-skills",
            "clone",
            "-q",
            str(self.root / "nested.git"),
            str(preexisting),
        )
        git(preexisting, "branch", "private-reference", fixture.nested_v1)
        private_reference = git(
            preexisting, "rev-parse", "private-reference"
        ).stdout.strip()
        (fixture.central_seed / ".gitignore").write_text(
            "__pycache__/\n*.py[cod]\n", encoding="utf-8"
        )
        git(
            fixture.central_seed,
            "submodule",
            "add",
            "-q",
            str(self.root / "nested.git"),
            "vendor/new-dependency",
        )
        commit_all(fixture.central_seed, "add nested dependency")
        git(fixture.central_seed, "push", "-q", "origin", "main")

        result = self.run_update(fixture)

        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("would overwrite pre-existing", result.stderr)
        self.assertEqual(
            git(preexisting, "rev-parse", "private-reference").stdout.strip(),
            private_reference,
        )
        self.assertEqual(
            git(preexisting, "rev-parse", "--show-toplevel").stdout.strip(),
            str(preexisting),
        )
        self.assertEqual(
            git(fixture.consumer / ".agent-skills", "rev-parse", "HEAD").stdout.strip(),
            fixture.v1,
        )

    def test_target_tracked_file_cannot_overwrite_a_preexisting_ignored_file(
        self,
    ) -> None:
        fixture = self.make_fixture()
        precious = (
            fixture.consumer
            / ".agent-skills"
            / "vendor"
            / "new-dependency"
            / "precious.txt"
        )
        precious.parent.mkdir()
        precious.write_text("USER PRECIOUS DATA\n", encoding="utf-8")
        target_file = (
            fixture.central_seed
            / "vendor"
            / "new-dependency"
            / "precious.txt"
        )
        target_file.parent.mkdir()
        target_file.write_text("CENTRAL TRACKED DATA\n", encoding="utf-8")
        (fixture.central_seed / ".gitignore").write_text(
            "__pycache__/\n*.py[cod]\n", encoding="utf-8"
        )
        commit_all(fixture.central_seed, "add formerly ignored file")
        git(fixture.central_seed, "push", "-q", "origin", "main")

        result = self.run_update(fixture)

        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("would overwrite pre-existing", result.stderr)
        self.assertEqual(
            precious.read_text(encoding="utf-8"), "USER PRECIOUS DATA\n"
        )
        self.assertEqual(
            git(fixture.consumer / ".agent-skills", "rev-parse", "HEAD").stdout.strip(),
            fixture.v1,
        )
        self.assert_materialized(fixture, "v1")

    def test_case_only_rename_cannot_overwrite_an_ignored_alias(self) -> None:
        fixture = self.make_fixture()
        upper_seed = fixture.central_seed / "CaseFile.txt"
        upper_seed.write_text("TRACKED V4\n", encoding="utf-8")
        v4 = commit_all(fixture.central_seed, "add mixed-case path")
        git(fixture.central_seed, "push", "-q", "origin", "main")
        first = self.run_update(fixture)
        self.assertEqual(first.returncode, 0, first.stderr)

        central = fixture.consumer / ".agent-skills"
        exclude_value = git(
            central, "rev-parse", "--git-path", "info/exclude"
        ).stdout.strip()
        exclude = Path(exclude_value)
        if not exclude.is_absolute():
            exclude = central / exclude
        exclude.write_text("casefile.txt\n", encoding="utf-8")
        ignored_alias = central / "casefile.txt"
        ignored_alias.write_text("USER PRECIOUS DATA\n", encoding="utf-8")

        git(fixture.central_seed, "mv", "CaseFile.txt", "casefile.txt")
        (fixture.central_seed / "casefile.txt").write_text(
            "TRACKED V5\n", encoding="utf-8"
        )
        commit_all(fixture.central_seed, "rename path by case")
        git(fixture.central_seed, "push", "-q", "origin", "main")

        result = self.run_update(fixture)

        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("unsafe case-only path transition", result.stderr)
        self.assertEqual(
            ignored_alias.read_text(encoding="utf-8"), "USER PRECIOUS DATA\n"
        )
        self.assertEqual(
            git(central, "rev-parse", "HEAD").stdout.strip(), v4
        )

    def test_configured_source_must_be_a_registered_gitlink(self) -> None:
        fixture = self.make_fixture()
        config = fixture.consumer / ".agent-skills.json"
        value = json.loads(config.read_text(encoding="utf-8"))
        value["source"] = "not-a-submodule"
        write_json(config, value)

        result = self.run_update(fixture)

        self.assertEqual(result.returncode, 2)
        self.assertIn("registered Git submodule", result.stderr)
        self.assertEqual(
            git(fixture.consumer / ".agent-skills", "rev-parse", "HEAD").stdout.strip(),
            fixture.v1,
        )

    def test_unicode_submodule_path_is_read_without_git_quoting_errors(self) -> None:
        fixture = self.make_fixture()
        unicode_path = "技能"
        git(fixture.consumer, "mv", ".agent-skills", unicode_path)
        config = fixture.consumer / ".agent-skills.json"
        value = json.loads(config.read_text(encoding="utf-8"))
        value["source"] = unicode_path
        write_json(config, value)
        commit_all(fixture.consumer, "use a Unicode central path")

        result = self.run_update(fixture, "--dry-run")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(fixture.v3[:12], result.stdout)
