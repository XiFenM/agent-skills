from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools import materialize_skills, validate_catalog


ROOT = Path(__file__).resolve().parents[1]


class CatalogTests(unittest.TestCase):
    def test_catalog_is_structurally_valid(self) -> None:
        self.assertEqual(validate_catalog.validate(ROOT), [])

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
                "learn-by-practice",
                "memo-cards",
                "resource-planning",
                "study-companion",
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


if __name__ == "__main__":
    unittest.main()
