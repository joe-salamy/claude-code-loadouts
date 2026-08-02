from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ACTIVE_SCRIPTS = ROOT / ".omp" / "scripts"
LOADOUT_SCRIPT_DIRS = (
    ROOT / "loadouts" / "worktrees" / ".harness" / "scripts",
    ROOT / "loadouts" / "worktrees" / ".opencode" / "scripts",
)


def runtime_files(root: Path) -> dict[Path, bytes]:
    return {
        path.relative_to(root): path.read_bytes()
        for path in root.rglob("*.py")
        if "__pycache__" not in path.parts
    }


class WorktreesLoadoutSyncTests(unittest.TestCase):
    def test_active_scripts_match_worktrees_loadout_templates(self) -> None:
        active_files = runtime_files(ACTIVE_SCRIPTS)
        for loadout_scripts in LOADOUT_SCRIPT_DIRS:
            with self.subTest(loadout=loadout_scripts):
                self.assertEqual(
                    set(active_files),
                    set(runtime_files(loadout_scripts)),
                    "The shipped runtime .py file set must match the canonical scripts.",
                )
                for relative_path, active_bytes in active_files.items():
                    self.assertEqual(
                        active_bytes,
                        (loadout_scripts / relative_path).read_bytes(),
                        f"Runtime bytes differ for {relative_path} in {loadout_scripts}.",
                    )


if __name__ == "__main__":
    unittest.main()
