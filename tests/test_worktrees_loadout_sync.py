from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ACTIVE_SCRIPTS = ROOT / ".omp" / "scripts"
LOADOUT_SCRIPTS = ROOT / "loadouts" / "worktrees" / ".harness" / "scripts"


SCRIPT_PAIRS = (
    "worktree-flow.py",
    "save-plan.py",
)


def normalized_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


class WorktreesLoadoutSyncTests(unittest.TestCase):
    def test_active_scripts_match_worktrees_loadout_templates(self) -> None:
        for script_name in SCRIPT_PAIRS:
            active = ACTIVE_SCRIPTS / script_name
            loadout = LOADOUT_SCRIPTS / script_name
            with self.subTest(script=script_name):
                self.assertTrue(active.exists(), f"Missing active script: {active}")
                self.assertTrue(loadout.exists(), f"Missing loadout script: {loadout}")
                self.assertEqual(
                    normalized_text(active),
                    normalized_text(loadout),
                    (
                        f"{active} and {loadout} are out of sync. Update the "
                        "active script and shipped worktrees loadout copy together."
                    ),
                )


if __name__ == "__main__":
    unittest.main()
