from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from tools import materialize_skills


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def git(root: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.com", *arguments],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )


class MaterializeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.repo = Path(self.temporary.name) / "consumer"
        self.repo.mkdir()
        self.central = self.repo / ".agent-skills"
        self.create_central(self.central, "# Demo\n")
        self.config = self.repo / ".agent-skills.json"
        self.write_config({"demo-skill": ["codex", "claude"]})

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def create_central(self, root: Path, body: str) -> None:
        skill = root / "skills" / "demo-skill"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\nname: demo-skill\ndescription: Test fixture.\n---\n\n" + body,
            encoding="utf-8",
        )
        (skill / "references").mkdir()
        (skill / "references" / "notes.md").write_text("fixture\n", encoding="utf-8")
        write_json(
            root / "catalog.json",
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
        git(root, "init", "-q")
        git(root, "add", ".")
        git(root, "commit", "-q", "-m", "fixture")

    def commit_central(self, message: str = "update") -> None:
        git(self.central, "add", "-A")
        git(self.central, "commit", "-q", "-m", message)

    def write_config(self, skills: object, source: str = ".agent-skills") -> None:
        write_json(
            self.config,
            {
                "version": 1,
                "source": source,
                "skills": skills,
            },
        )

    def enable_context_fixture(self) -> None:
        validator = self.central / "skills" / "demo-skill" / "scripts" / "context.py"
        validator.parent.mkdir()
        validator.write_text(
            """from __future__ import annotations

def validate_materialized_context(repository_config, skill_config):
    if repository_config.get("schema") != "agent-skills.repository/v1":
        raise ValueError("bad repository schema")
    allowed = {"schema", "skill", "input_path", "collection", "output_path"}
    if set(skill_config) != allowed:
        raise ValueError("unknown demo config fields")
    if skill_config["schema"] != "agent-skills.demo-skill/v1":
        raise ValueError("bad demo schema")
    if skill_config["skill"] != "demo-skill":
        raise ValueError("bad demo identity")
    return {
        "context": {
            "input_path": skill_config["input_path"],
            "output_path": skill_config["output_path"],
        },
        "tracked_files": [
            repository_config["facts"]["goal"]["path"],
            skill_config["input_path"],
        ],
        "tracked_collections": [skill_config["collection"]],
        "write_paths": [skill_config["output_path"]],
    }
""",
            encoding="utf-8",
        )
        catalog = self.read_catalog()
        entry = catalog["skills"][0]
        entry["kind"] = "first-party"
        entry["context"] = {"validator": "scripts/context.py"}
        self.write_catalog(catalog)
        self.commit_central("add context validator")

        facts = self.repo / "facts"
        collection = self.repo / "records"
        facts.mkdir()
        collection.mkdir()
        (facts / "goal.md").write_text("goal\n", encoding="utf-8")
        (facts / "input.md").write_text("input\n", encoding="utf-8")
        (facts / "unused.md").write_text("unused\n", encoding="utf-8")
        (collection / "one.md").write_text("one\n", encoding="utf-8")
        write_json(
            self.repo / ".agent-skills-config" / "repository.json",
            {
                "schema": "agent-skills.repository/v1",
                "repository_id": "fixture-repo",
                "language": "en",
                "timezone": "UTC",
                "facts": {
                    "goal": {"path": "facts/goal.md", "section": "Goal"},
                    "unused": {"path": "facts/unused.md"},
                },
            },
        )
        write_json(
            self.repo / ".agent-skills-config" / "demo-skill.json",
            {
                "schema": "agent-skills.demo-skill/v1",
                "skill": "demo-skill",
                "input_path": "facts/input.md",
                "collection": "records",
                "output_path": "generated/output.md",
            },
        )
        write_json(
            self.config,
            {
                "version": 2,
                "source": ".agent-skills",
                "skills": {"demo-skill": ["codex", "claude"]},
                "config": {
                    "repository": ".agent-skills-config/repository.json",
                    "skills": {
                        "demo-skill": ".agent-skills-config/demo-skill.json"
                    },
                },
            },
        )
        git(self.repo, "init", "-q")
        git(
            self.repo,
            "add",
            ".agent-skills.json",
            ".agent-skills-config",
            "facts/goal.md",
            "facts/input.md",
            "records",
        )

    def read_catalog(self) -> dict[str, object]:
        return json.loads((self.central / "catalog.json").read_text(encoding="utf-8"))

    def write_catalog(self, catalog: dict[str, object]) -> None:
        write_json(self.central / "catalog.json", catalog)

    def add_skill(
        self,
        name: str,
        *,
        groups: list[str] | None = None,
        state: str = "active",
        replacement: str | None = None,
        create_source: bool = True,
    ) -> None:
        if create_source:
            skill = self.central / "skills" / name
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text(
                f"---\nname: {name}\ndescription: Test fixture.\n---\n",
                encoding="utf-8",
            )
        catalog = self.read_catalog()
        entry: dict[str, object] = {
            "name": name,
            "kind": "first-party",
            "path": f"skills/{name}",
            "lifecycle": {"state": state},
            "groups": groups or [],
        }
        if replacement is not None:
            entry["replacement"] = replacement
        skills = catalog["skills"]
        assert isinstance(skills, list)
        skills.append(entry)
        self.write_catalog(catalog)

    def target(self, host: str = "codex") -> Path:
        root = ".agents" if host == "codex" else ".claude"
        return self.repo / root / "skills" / "demo-skill"

    def test_sync_check_refresh_and_remove_last_skill(self) -> None:
        materialize_skills.synchronize(self.repo, self.central, self.config)
        codex = self.target("codex")
        claude = self.target("claude")
        self.assertTrue((codex / "SKILL.md").is_file())
        self.assertTrue((claude / "SKILL.md").is_file())
        self.assertEqual(materialize_skills.check(self.repo, self.central, self.config), [])

        (codex / "SKILL.md").write_text("drift\n", encoding="utf-8")
        errors = materialize_skills.check(self.repo, self.central, self.config)
        self.assertTrue(any("drifted" in error for error in errors))

        materialize_skills.synchronize(self.repo, self.central, self.config)
        self.assertEqual(materialize_skills.check(self.repo, self.central, self.config), [])

        self.write_config({"demo-skill": ["codex"]})
        materialize_skills.synchronize(self.repo, self.central, self.config)
        self.assertTrue(codex.is_dir())
        self.assertFalse(claude.exists())

        self.write_config({})
        materialize_skills.synchronize(self.repo, self.central, self.config)
        self.assertFalse(codex.exists())
        self.assertEqual(materialize_skills.check(self.repo, self.central, self.config), [])

    def test_v2_context_is_validated_injected_and_tracked(self) -> None:
        self.enable_context_fixture()
        materialize_skills.synchronize(self.repo, self.central, self.config)

        codex_context = self.target("codex") / materialize_skills.CONTEXT_FILE
        claude_context = self.target("claude") / materialize_skills.CONTEXT_FILE
        self.assertEqual(codex_context.read_bytes(), claude_context.read_bytes())
        context = json.loads(codex_context.read_text(encoding="utf-8"))
        self.assertEqual(context["skill"], "demo-skill")
        self.assertEqual(context["repository_id"], "fixture-repo")
        self.assertEqual(
            context["allowlist"]["tracked_files"],
            ["facts/goal.md", "facts/input.md", "records/one.md"],
        )
        self.assertEqual(context["allowlist"]["tracked_collections"], ["records"])
        self.assertEqual(context["allowlist"]["write_paths"], ["generated/output.md"])

        state = json.loads(
            (self.repo / materialize_skills.STATE_FILE).read_text(encoding="utf-8")
        )
        self.assertEqual(state["config"], ".agent-skills.json")
        self.assertEqual(len(state["config_digest"]), 64)
        for record in state["managed"].values():
            self.assertEqual(len(record["source_digest"]), 64)
            self.assertEqual(len(record["context_digest"]), 64)
        self.assertEqual(materialize_skills.check(self.repo, self.central, self.config), [])

        skill_config = self.repo / ".agent-skills-config" / "demo-skill.json"
        updated = json.loads(skill_config.read_text(encoding="utf-8"))
        updated["output_path"] = "generated/changed.md"
        write_json(skill_config, updated)
        errors = materialize_skills.check(self.repo, self.central, self.config)
        self.assertTrue(any("drifted" in error or "metadata" in error for error in errors))

    def test_v2_context_rejects_untracked_facts_and_unknown_fields(self) -> None:
        self.enable_context_fixture()
        untracked = self.repo / "facts" / "private.md"
        untracked.write_text("private\n", encoding="utf-8")
        repository_config = self.repo / ".agent-skills-config" / "repository.json"
        repository = json.loads(repository_config.read_text(encoding="utf-8"))
        repository["facts"]["goal"] = {"path": "facts/private.md"}
        write_json(repository_config, repository)
        with self.assertRaisesRegex(materialize_skills.SyncError, "Git tracked"):
            materialize_skills.build_plan(self.repo, self.central, self.config)

        repository["facts"]["goal"] = {"path": "facts/goal.md"}
        repository["unexpected"] = True
        write_json(repository_config, repository)
        with self.assertRaisesRegex(materialize_skills.SyncError, "unknown"):
            materialize_skills.build_plan(self.repo, self.central, self.config)

    def test_v2_rejects_write_overlap_with_configs_inputs_and_managed_skills(self) -> None:
        self.enable_context_fixture()
        skill_path = self.repo / ".agent-skills-config" / "demo-skill.json"
        base_skill = json.loads(skill_path.read_text(encoding="utf-8"))
        protected = [
            ".agent-skills.json",
            ".agent-skills-config/repository.json",
            ".agent-skills-config/demo-skill.json",
            "facts/goal.md",
            ".agents/skills/demo-skill/SKILL.md",
        ]
        for output_path in protected:
            with self.subTest(output_path=output_path):
                skill = dict(base_skill)
                skill["output_path"] = output_path
                write_json(skill_path, skill)
                with self.assertRaisesRegex(
                    materialize_skills.SyncError, "overlaps protected"
                ):
                    materialize_skills.build_plan(
                        self.repo, self.central, self.config
                    )

        skill = dict(base_skill)
        skill["output_path"] = ".AGENT-SKILLS-CONFIG/REPOSITORY.JSON"
        write_json(skill_path, skill)
        with self.assertRaisesRegex(
            materialize_skills.SyncError, "Git tracked|overlaps protected"
        ):
            materialize_skills.build_plan(self.repo, self.central, self.config)

        self.assertTrue(
            materialize_skills._relative_paths_overlap(
                ".AGENT-SKILLS-CONFIG/REPOSITORY.JSON",
                ".agent-skills-config/repository.json",
            )
        )

    def test_v2_allows_skill_owned_inventory_collection_to_share_output_root(self) -> None:
        self.enable_context_fixture()
        skill_path = self.repo / ".agent-skills-config" / "demo-skill.json"
        skill = json.loads(skill_path.read_text(encoding="utf-8"))
        skill["output_path"] = "records/new.md"
        write_json(skill_path, skill)
        desired, consumer = materialize_skills.build_plan(
            self.repo, self.central, self.config
        )
        self.assertEqual(len(desired), 2)
        self.assertEqual(
            consumer.contexts["demo-skill"]["allowlist"]["write_paths"],
            ["records/new.md"],
        )

    def test_v2_collection_requires_exact_git_casing_and_a_tracked_member(self) -> None:
        self.enable_context_fixture()
        skill_path = self.repo / ".agent-skills-config" / "demo-skill.json"
        skill = json.loads(skill_path.read_text(encoding="utf-8"))
        skill["collection"] = "Records"
        write_json(skill_path, skill)
        with self.assertRaisesRegex(materialize_skills.SyncError, "exact path casing"):
            materialize_skills.build_plan(self.repo, self.central, self.config)

        empty = self.repo / "empty-records"
        empty.mkdir()
        skill["collection"] = "empty-records"
        write_json(skill_path, skill)
        with self.assertRaisesRegex(materialize_skills.SyncError, "tracked member"):
            materialize_skills.build_plan(self.repo, self.central, self.config)

    def test_v2_rejects_platform_unsafe_missing_write_paths(self) -> None:
        self.enable_context_fixture()
        skill_path = self.repo / ".agent-skills-config" / "demo-skill.json"
        base_skill = json.loads(skill_path.read_text(encoding="utf-8"))
        unsafe = [
            "generated/CON.txt",
            "generated/bad<name>.md",
            "generated/trailing./file.md",
            "generated/name. ",
        ]
        for output_path in unsafe:
            with self.subTest(output_path=output_path):
                skill = dict(base_skill)
                skill["output_path"] = output_path
                write_json(skill_path, skill)
                with self.assertRaisesRegex(
                    materialize_skills.SyncError, "platform-unsafe"
                ):
                    materialize_skills.build_plan(
                        self.repo, self.central, self.config
                    )

    def test_v1_materialization_does_not_inject_context(self) -> None:
        materialize_skills.synchronize(self.repo, self.central, self.config)
        self.assertFalse((self.target() / materialize_skills.CONTEXT_FILE).exists())

    def test_source_rejects_ignored_untracked_files(self) -> None:
        hidden = self.central / "skills" / "demo-skill" / "private.txt"
        hidden.write_text("must not leak\n", encoding="utf-8")
        exclude = self.central / ".git" / "info" / "exclude"
        with exclude.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write("\n/skills/demo-skill/private.txt\n")

        with self.assertRaisesRegex(
            materialize_skills.SyncError, "match its Git index exactly"
        ):
            materialize_skills.build_plan(self.repo, self.central, self.config)

    def test_v2_rejects_non_utf8_collection_members(self) -> None:
        self.enable_context_fixture()
        binary = self.repo / "records" / "binary.md"
        binary.write_bytes(b"\xff\xfe")
        git(self.repo, "add", "records/binary.md")

        with self.assertRaisesRegex(materialize_skills.SyncError, "valid UTF-8"):
            materialize_skills.build_plan(self.repo, self.central, self.config)

    def test_v2_rejects_an_existing_untracked_write_target(self) -> None:
        self.enable_context_fixture()
        target = self.repo / "generated" / "output.md"
        target.parent.mkdir()
        target.write_text("user owned\n", encoding="utf-8")

        with self.assertRaisesRegex(materialize_skills.SyncError, "must be Git tracked"):
            materialize_skills.build_plan(self.repo, self.central, self.config)

    def test_v2_ignores_unrelated_intent_but_rejects_referenced_intent(self) -> None:
        self.enable_context_fixture()
        unrelated = self.repo / "unrelated.md"
        unrelated.write_text("unrelated\n", encoding="utf-8")
        git(self.repo, "add", "--intent-to-add", "unrelated.md")
        materialize_skills.build_plan(self.repo, self.central, self.config)

        private = self.repo / "facts" / "private.md"
        private.write_text("private\n", encoding="utf-8")
        git(self.repo, "add", "--intent-to-add", "facts/private.md")
        repository_path = self.repo / ".agent-skills-config" / "repository.json"
        repository = json.loads(repository_path.read_text(encoding="utf-8"))
        repository["facts"]["goal"] = {"path": "facts/private.md"}
        write_json(repository_path, repository)

        with self.assertRaisesRegex(materialize_skills.SyncError, "intent-to-add"):
            materialize_skills.build_plan(self.repo, self.central, self.config)

    def test_unmanaged_collision_is_preserved(self) -> None:
        target = self.target()
        target.mkdir(parents=True)
        sentinel = target / "user-file.txt"
        sentinel.write_text("keep\n", encoding="utf-8")

        with self.assertRaises(materialize_skills.SyncError):
            materialize_skills.synchronize(self.repo, self.central, self.config)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep\n")

    def test_plain_file_collision_is_preserved(self) -> None:
        target = self.target()
        target.parent.mkdir(parents=True)
        target.write_text("keep\n", encoding="utf-8")
        with self.assertRaises(materialize_skills.SyncError):
            materialize_skills.synchronize(self.repo, self.central, self.config)
        self.assertEqual(target.read_text(encoding="utf-8"), "keep\n")

    def test_unknown_and_reserved_skill_names_are_rejected(self) -> None:
        self.write_config({"not-in-catalog": ["codex"]})
        with self.assertRaisesRegex(materialize_skills.SyncError, "unknown Skill"):
            materialize_skills.synchronize(self.repo, self.central, self.config)

        self.write_config({"con": ["codex"]})
        with self.assertRaisesRegex(materialize_skills.SyncError, "reserved Windows"):
            materialize_skills.synchronize(self.repo, self.central, self.config)

    def test_primary_group_counts_distinct_skills_across_hosts(self) -> None:
        catalog = self.read_catalog()
        skills = catalog["skills"]
        assert isinstance(skills, list)
        skills[0]["groups"] = ["primary-learning"]
        self.write_catalog(catalog)
        self.add_skill("other-primary", groups=["primary-learning"])
        self.commit_central("add primary entries")

        # One Skill on both hosts is one distinct group choice and remains legal.
        materialize_skills.synchronize(self.repo, self.central, self.config)
        self.assertTrue(self.target("codex").is_dir())
        self.assertTrue(self.target("claude").is_dir())

        self.write_config(
            {
                "demo-skill": ["codex"],
                "other-primary": ["claude"],
            }
        )
        with self.assertRaisesRegex(
            materialize_skills.SyncError, "primary-learning.*demo-skill, other-primary"
        ):
            materialize_skills.synchronize(self.repo, self.central, self.config)

    def test_rollback_and_retired_names_report_final_active_replacement(self) -> None:
        self.add_skill(
            "old-skill",
            state="rollback-only",
            replacement="retired-middle",
            create_source=False,
        )
        catalog = self.read_catalog()
        retired = catalog["retired_names"]
        assert isinstance(retired, dict)
        retired["retired-middle"] = {"replacement": "demo-skill"}
        retired["retired-skill"] = {"replacement": "old-skill"}
        self.write_catalog(catalog)
        self.commit_central("add replacement chain")

        for selected, lifecycle in (
            ("old-skill", "rollback-only"),
            ("retired-skill", "retired"),
        ):
            with self.subTest(selected=selected):
                self.write_config({selected: ["codex"]})
                with self.assertRaisesRegex(
                    materialize_skills.SyncError,
                    rf"{lifecycle} Skill.*{selected}.*demo-skill",
                ):
                    materialize_skills.synchronize(self.repo, self.central, self.config)
        self.assertFalse(self.target().exists())

    def test_nonselectable_name_is_rejected_before_group_or_source_planning(self) -> None:
        catalog = self.read_catalog()
        skills = catalog["skills"]
        assert isinstance(skills, list)
        skills[0]["groups"] = ["primary-learning"]
        self.write_catalog(catalog)
        self.add_skill(
            "old-primary",
            groups=["primary-learning"],
            state="rollback-only",
            replacement="demo-skill",
            create_source=False,
        )
        self.commit_central("add unavailable rollback entry")
        self.write_config(
            {
                "aaa-unknown": ["codex"],
                "demo-skill": ["codex"],
                "old-primary": ["claude"],
            }
        )

        with self.assertRaisesRegex(
            materialize_skills.SyncError, "rollback-only Skill.*demo-skill"
        ):
            materialize_skills.synchronize(self.repo, self.central, self.config)

    def test_non_string_lifecycle_state_is_a_schema_error(self) -> None:
        for state in ([], {}):
            with self.subTest(state=state):
                catalog = self.read_catalog()
                skills = catalog["skills"]
                assert isinstance(skills, list)
                skills[0]["lifecycle"]["state"] = state
                self.write_catalog(catalog)
                with self.assertRaisesRegex(
                    materialize_skills.SyncError,
                    "lifecycle.state must be active or rollback-only",
                ):
                    materialize_skills.build_plan(
                        self.repo, self.central, self.config
                    )

    def test_non_string_hosts_are_schema_errors(self) -> None:
        for hosts in (["codex", 1], [["codex"]]):
            with self.subTest(hosts=hosts):
                self.write_config({"demo-skill": hosts})
                with self.assertRaisesRegex(materialize_skills.SyncError, "host must be a string"):
                    materialize_skills.synchronize(self.repo, self.central, self.config)

    def test_marker_tampering_is_reported_and_not_overwritten(self) -> None:
        materialize_skills.synchronize(self.repo, self.central, self.config)
        target = self.target()
        marker_path = target / materialize_skills.MARKER_FILE
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        marker["source"] = "skills/somewhere-else"
        marker["digest"] = "0" * 64
        write_json(marker_path, marker)

        errors = materialize_skills.check(self.repo, self.central, self.config)
        self.assertTrue(any("marker" in error for error in errors))
        with self.assertRaisesRegex(materialize_skills.SyncError, "marker"):
            materialize_skills.synchronize(self.repo, self.central, self.config)

    def test_missing_state_reports_orphan_and_sync_refuses(self) -> None:
        materialize_skills.synchronize(self.repo, self.central, self.config)
        (self.repo / materialize_skills.STATE_FILE).unlink()

        errors = materialize_skills.check(self.repo, self.central, self.config)
        self.assertTrue(any("no state ownership" in error for error in errors))
        with self.assertRaisesRegex(materialize_skills.SyncError, "without state ownership"):
            materialize_skills.synchronize(self.repo, self.central, self.config)
        self.assertTrue(self.target().is_dir())

    def test_source_location_switch_is_refused_while_targets_are_managed(self) -> None:
        materialize_skills.synchronize(self.repo, self.central, self.config)
        second = self.repo / ".central-two"
        self.create_central(second, "# Different\n")
        self.write_config({"demo-skill": ["codex", "claude"]}, source=".central-two")

        with self.assertRaisesRegex(materialize_skills.SyncError, "state source"):
            materialize_skills.synchronize(self.repo, second, self.config)
        self.assertNotIn("Different", (self.target() / "SKILL.md").read_text(encoding="utf-8"))

    def test_dirty_central_source_is_refused(self) -> None:
        skill_md = self.central / "skills" / "demo-skill" / "SKILL.md"
        skill_md.write_text(skill_md.read_text(encoding="utf-8") + "dirty\n", encoding="utf-8")
        with self.assertRaisesRegex(materialize_skills.SyncError, "source is dirty"):
            materialize_skills.synchronize(self.repo, self.central, self.config)
        self.assertFalse(self.target().exists())

    def test_dry_run_leaves_no_persistent_files(self) -> None:
        messages = materialize_skills.synchronize(
            self.repo, self.central, self.config, dry_run=True
        )
        self.assertTrue(messages)
        self.assertFalse(self.target().exists())
        self.assertFalse((self.repo / materialize_skills.STATE_FILE).exists())
        self.assertFalse((self.repo / materialize_skills.LOCK_FILE).exists())

    def test_digest_framing_distinguishes_ambiguous_nul_content(self) -> None:
        first = self.repo / "digest-one"
        second = self.repo / "digest-two"
        first.mkdir()
        second.mkdir()
        (first / "a").write_bytes(b"X\0b\0Y")
        (second / "a").write_bytes(b"X")
        (second / "b").write_bytes(b"Y")
        self.assertNotEqual(
            materialize_skills.skill_digest(first),
            materialize_skills.skill_digest(second),
        )

    def test_existing_lock_blocks_sync(self) -> None:
        lock = self.repo / materialize_skills.LOCK_FILE
        lock.write_text("active\n", encoding="utf-8")
        with self.assertRaisesRegex(materialize_skills.SyncError, "may be running"):
            materialize_skills.synchronize(self.repo, self.central, self.config)
        self.assertEqual(lock.read_text(encoding="utf-8"), "active\n")

    def test_staging_digest_mismatch_installs_nothing(self) -> None:
        original_digest = materialize_skills.skill_digest

        def corrupt_stage_digest(root, **kwargs):
            digest = original_digest(root, **kwargs)
            if ".agent-skills-tmp-" in Path(root).name:
                return "0" * 64
            return digest

        with mock.patch.object(
            materialize_skills, "skill_digest", side_effect=corrupt_stage_digest
        ):
            with self.assertRaisesRegex(materialize_skills.SyncError, "staged copy changed"):
                materialize_skills.synchronize(self.repo, self.central, self.config)
        self.assertFalse(self.target().exists())
        self.assertFalse((self.repo / materialize_skills.STATE_FILE).exists())

    def test_partial_copy_failure_cleans_staging_directory(self) -> None:
        def fail_after_partial_copy(_source, destination, **_kwargs):
            destination = Path(destination)
            destination.mkdir()
            (destination / "partial.txt").write_text("partial\n", encoding="utf-8")
            raise OSError("injected copy failure")

        with mock.patch.object(
            materialize_skills.shutil,
            "copytree",
            side_effect=fail_after_partial_copy,
        ):
            with self.assertRaisesRegex(OSError, "injected copy failure"):
                materialize_skills.synchronize(self.repo, self.central, self.config)
        discovery = self.repo / ".agents" / "skills"
        leftovers = list(discovery.glob(".*.agent-skills-tmp-*")) if discovery.exists() else []
        self.assertEqual(leftovers, [])

    def test_target_created_during_staging_is_not_overwritten(self) -> None:
        self.write_config({"demo-skill": ["codex"]})
        target = self.target()
        sentinel = target / "user-file.txt"
        original_digest = materialize_skills.skill_digest
        injected = False

        def create_collision_after_staging(root, **kwargs):
            nonlocal injected
            digest = original_digest(root, **kwargs)
            if not injected and ".agent-skills-tmp-" in Path(root).name:
                target.mkdir(parents=True)
                sentinel.write_text("keep\n", encoding="utf-8")
                injected = True
            return digest

        with mock.patch.object(
            materialize_skills,
            "skill_digest",
            side_effect=create_collision_after_staging,
        ):
            with self.assertRaisesRegex(materialize_skills.SyncError, "unmanaged target"):
                materialize_skills.synchronize(self.repo, self.central, self.config)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep\n")

    def test_cli_resolves_relative_config_from_repo(self) -> None:
        nested_config = self.repo / "configs" / "skills.json"
        write_json(
            nested_config,
            {
                "version": 1,
                "source": ".agent-skills",
                "skills": {"demo-skill": ["codex"]},
            },
        )
        arguments = [
            "materialize_skills.py",
            "--repo",
            os.fspath(self.repo),
            "--config",
            "configs/skills.json",
            "--dry-run",
        ]
        with mock.patch.object(materialize_skills, "CENTRAL_ROOT", self.central):
            with mock.patch.object(sys, "argv", arguments):
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(materialize_skills.main(), 0)
        self.assertFalse(self.target().exists())

    def test_state_write_failure_rolls_back_targets(self) -> None:
        materialize_skills.synchronize(self.repo, self.central, self.config)
        old_text = (self.target() / "SKILL.md").read_text(encoding="utf-8")

        source = self.central / "skills" / "demo-skill" / "SKILL.md"
        source.write_text(source.read_text(encoding="utf-8") + "updated\n", encoding="utf-8")
        self.commit_central()
        real_replace = materialize_skills.os.replace

        def fail_state_replace(source_path, destination_path):
            if Path(destination_path) == self.repo / materialize_skills.STATE_FILE:
                raise OSError("injected state failure")
            return real_replace(source_path, destination_path)

        with mock.patch.object(materialize_skills.os, "replace", side_effect=fail_state_replace):
            with self.assertRaisesRegex(OSError, "injected state failure"):
                materialize_skills.synchronize(self.repo, self.central, self.config)
        self.assertEqual((self.target() / "SKILL.md").read_text(encoding="utf-8"), old_text)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink API unavailable")
    def test_source_symlink_is_rejected_when_platform_allows_creation(self) -> None:
        source = self.central / "skills" / "demo-skill"
        outside = self.central / "outside.txt"
        outside.write_text("outside\n", encoding="utf-8")
        link = source / "linked.txt"
        try:
            os.symlink(outside, link)
        except OSError as exc:
            self.skipTest(f"symlink creation unavailable: {exc}")
        self.commit_central("add link")
        with self.assertRaisesRegex(materialize_skills.SyncError, "links or junctions"):
            materialize_skills.synchronize(self.repo, self.central, self.config)


if __name__ == "__main__":
    unittest.main()
