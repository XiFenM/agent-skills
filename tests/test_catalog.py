from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from tools import materialize_skills, validate_catalog


ROOT = Path(__file__).resolve().parents[1]


class CatalogTests(unittest.TestCase):
    def catalog_fixture(self) -> tuple[Path, dict]:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        catalog = json.loads((ROOT / "catalog.json").read_text(encoding="utf-8"))
        shutil.copy2(ROOT / ".gitmodules", root / ".gitmodules")
        for item in catalog["skills"]:
            skill = root / item["path"]
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text(
                f"---\nname: {item['name']}\ndescription: Fixture.\n---\n",
                encoding="utf-8",
            )
            context = item.get("context")
            if isinstance(context, dict):
                validator = skill / context["validator"]
                validator.parent.mkdir(parents=True, exist_ok=True)
                validator.write_text(
                    "def validate_materialized_context(repository_config, skill_config):\n"
                    "    return {}\n",
                    encoding="utf-8",
                )
        (root / "catalog.json").write_text(
            json.dumps(catalog, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return root, catalog

    @staticmethod
    def write_fixture_catalog(root: Path, catalog: dict) -> None:
        (root / "catalog.json").write_text(
            json.dumps(catalog, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def test_catalog_is_structurally_valid(self) -> None:
        self.assertEqual(validate_catalog.validate(ROOT), [])

    def test_schema_v2_lifecycle_lineage_and_selection_boundary(self) -> None:
        catalog = json.loads((ROOT / "catalog.json").read_text(encoding="utf-8"))
        self.assertEqual(catalog["schema_version"], 2)
        self.assertEqual(
            catalog["selection_groups"]["primary-learning"][
                "max_distinct_per_config"
            ],
            1,
        )
        self.assertEqual(
            catalog["retired_names"],
            {
                "learn-by-practice": {"replacement": "guide-learning"},
                "study-companion": {"replacement": "guide-learning"},
            },
        )

        primary = set()
        active_primary = set()
        for item in catalog["skills"]:
            with self.subTest(skill=item["name"]):
                state = item["lifecycle"]["state"]
                self.assertEqual(state, "active")
                self.assertIsInstance(item["groups"], list)
                self.assertNotIn("replacement", item)
                if item["kind"] == "first-party":
                    self.assertTrue(item["lineage"])
                    self.assertNotIn("origin", item)
                if "primary-learning" in item["groups"]:
                    primary.add(item["name"])
                    if state == "active":
                        active_primary.add(item["name"])
        self.assertEqual(primary, {"guide-learning"})
        self.assertEqual(active_primary, {"guide-learning"})

    def test_learning_upgrade_lineage_and_review_are_recorded(self) -> None:
        catalog = json.loads((ROOT / "catalog.json").read_text(encoding="utf-8"))
        by_name = {item["name"]: item for item in catalog["skills"]}

        guide = by_name["guide-learning"]
        self.assertEqual(guide["migration"], "merged-upgrade")
        self.assertEqual(guide["review"]["state"], "implemented")
        self.assertIn("generic-managed-context", guide["review"]["topics"])
        self.assertEqual(guide["consumers"], ["PlanA", "programming-lab"])
        self.assertEqual(
            guide["lineage"],
            [
                {
                    "repository": "PlanA",
                    "path": ".claude/skills/study-companion",
                    "commit": "cddefb09f6e26fabd6e98cc515a19e4609c248c9",
                },
                {
                    "repository": "programming-lab",
                    "path": "skills/learn-by-practice",
                    "commit": "b5f22d33437cc242ef57d860ef2db680ffea9518",
                },
            ],
        )

        self.assertNotIn("learn-by-practice", by_name)
        self.assertNotIn("study-companion", by_name)
        self.assertEqual(
            catalog["retired_names"],
            {
                "learn-by-practice": {"replacement": "guide-learning"},
                "study-companion": {"replacement": "guide-learning"},
            },
        )

        study_log = by_name["study-log"]
        self.assertEqual(study_log["review"]["state"], "implemented")
        self.assertEqual(study_log["consumers"], ["PlanA", "programming-lab"])
        self.assertIn(
            {
                "repository": "programming-lab",
                "path": "skills/learn-by-practice/scripts/export_codex_dialogue.py",
                "commit": "b5f22d33437cc242ef57d860ef2db680ffea9518",
            },
            study_log["lineage"],
        )

        configurable = {
            "english-coach": "scripts/context_config.py",
            "guide-learning": "scripts/context_config.py",
            "memo-cards": "scripts/memo_cards.py",
            "resource-planning": "scripts/resource_planning.py",
            "study-log": "scripts/context_config.py",
        }
        for name, validator in configurable.items():
            with self.subTest(configurable=name):
                self.assertEqual(by_name[name]["context"], {"validator": validator})
                self.assertEqual(by_name[name]["review"]["state"], "implemented")

        for name in ("english-coach", "memo-cards", "resource-planning"):
            self.assertEqual(
                by_name[name]["migration"],
                "generalized-configurable-upgrade",
            )
        for name in ("guide-learning", "study-log"):
            self.assertEqual(by_name[name]["migration"], "merged-upgrade")

    def test_expected_migration_boundary(self) -> None:
        catalog = json.loads((ROOT / "catalog.json").read_text(encoding="utf-8"))
        first_party = {
            item["name"] for item in catalog["skills"] if item["kind"] == "first-party"
        }
        external = {
            item["name"] for item in catalog["skills"] if item["kind"] == "external"
        }
        self.assertEqual(
            first_party,
            {
                "creator-workflow",
                "english-coach",
                "guide-learning",
                "memo-cards",
                "resource-planning",
                "study-log",
            },
        )
        self.assertEqual(
            external,
            {
                "playwright-cli",
                "remotion-best-practices",
                "zenmux-context",
                "zenmux-setup",
                "zenmux-usage",
            },
        )

    def test_every_selected_skill_is_a_safe_regular_file_tree(self) -> None:
        catalog = json.loads((ROOT / "catalog.json").read_text(encoding="utf-8"))
        for item in catalog["skills"]:
            with self.subTest(skill=item["name"]):
                digest = materialize_skills.skill_digest(ROOT / item["path"])
                self.assertEqual(len(digest), 64)

    def test_validator_rejects_invalid_lineage_lifecycle_and_group(self) -> None:
        root, catalog = self.catalog_fixture()
        first = catalog["skills"][0]
        first["lineage"] = []
        first["lifecycle"] = {"state": "deprecated"}
        first["groups"] = ["not-declared"]
        self.write_fixture_catalog(root, catalog)

        errors = validate_catalog.validate(root)
        self.assertTrue(any("lineage must be a non-empty array" in error for error in errors))
        self.assertTrue(any("lifecycle.state" in error for error in errors))
        self.assertTrue(any("unknown selection group" in error for error in errors))

    def test_validator_reports_non_string_enum_fields_without_crashing(self) -> None:
        root, original = self.catalog_fixture()
        cases = (
            ("category", [], "category must be a string"),
            ("category", {}, "category must be a string"),
            ("kind", [], "kind must be first-party or external"),
            ("kind", {}, "kind must be first-party or external"),
            ("lifecycle.state", [], "lifecycle.state must be active or rollback-only"),
            ("lifecycle.state", {}, "lifecycle.state must be active or rollback-only"),
        )
        for field, value, expected in cases:
            with self.subTest(field=field, value=value):
                catalog = deepcopy(original)
                if field == "lifecycle.state":
                    catalog["skills"][0]["lifecycle"]["state"] = value
                else:
                    catalog["skills"][0][field] = value
                self.write_fixture_catalog(root, catalog)
                errors = validate_catalog.validate(root)
                self.assertTrue(any(expected in error for error in errors), errors)

    def test_validator_rejects_replacement_cycles_and_dangling_targets(self) -> None:
        root, original = self.catalog_fixture()
        catalog = deepcopy(original)
        catalog["retired_names"] = {
            "learn-by-practice": {"replacement": "study-companion"},
            "study-companion": {"replacement": "learn-by-practice"},
        }
        self.write_fixture_catalog(root, catalog)
        self.assertTrue(
            any(
                "replacement chain contains a cycle" in error
                for error in validate_catalog.validate(root)
            )
        )

        catalog = deepcopy(original)
        catalog["retired_names"] = {
            "retired-learning": {"replacement": "missing-learning"}
        }
        self.write_fixture_catalog(root, catalog)
        self.assertTrue(
            any(
                "does not end at an active Skill" in error
                for error in validate_catalog.validate(root)
            )
        )

    def test_validator_rejects_name_overlap_and_active_replacement(self) -> None:
        root, catalog = self.catalog_fixture()
        catalog["retired_names"] = {
            "study-log": {"replacement": "memo-cards"}
        }
        catalog["skills"][0]["replacement"] = "study-log"
        self.write_fixture_catalog(root, catalog)

        errors = validate_catalog.validate(root)
        self.assertTrue(any("names overlap" in error for error in errors))
        self.assertTrue(
            any("replacement is only valid for rollback-only" in error for error in errors)
        )

    def test_validator_requires_primary_learning_limit_of_one(self) -> None:
        root, catalog = self.catalog_fixture()
        catalog["selection_groups"]["primary-learning"][
            "max_distinct_per_config"
        ] = 2
        self.write_fixture_catalog(root, catalog)
        self.assertIn(
            "selection_groups.primary-learning.max_distinct_per_config must be 1",
            validate_catalog.validate(root),
        )


if __name__ == "__main__":
    unittest.main()
