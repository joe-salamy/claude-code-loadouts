from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1] / ".omp" / "scripts"


def load_save_plan_module():
    spec = importlib.util.spec_from_file_location("save_plan", SCRIPT_DIR / "save-plan.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


save_plan = load_save_plan_module()


class SavePlanCommandTests(unittest.TestCase):
    def test_command_for_plan_uses_default_omp_script(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            script = repo / ".omp" / "scripts" / "worktree-flow.py"
            plan = repo / ".omp" / "worktree-flow" / "my-plan" / "plan.md"
            script.parent.mkdir(parents=True)
            plan.parent.mkdir(parents=True)
            script.write_text("", encoding="utf-8")
            plan.write_text("# My Plan", encoding="utf-8")

            command = save_plan.command_for_plan(repo, plan, "omp", Path(".omp"))

            self.assertEqual(
                command,
                "python ./.omp/scripts/worktree-flow.py --plan .omp/worktree-flow/my-plan/plan.md --harness omp --harness-dir .omp",
            )

    def test_command_for_plan_uses_selected_harness_dir_script(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            script = repo / ".harness" / "scripts" / "worktree-flow.py"
            plan = repo / ".omp" / "worktree-flow" / "my-plan" / "plan.md"
            script.parent.mkdir(parents=True)
            plan.parent.mkdir(parents=True)
            script.write_text("", encoding="utf-8")
            plan.write_text("# My Plan", encoding="utf-8")

            command = save_plan.command_for_plan(
                repo, plan, "harness", Path(".harness"), "python3"
            )

            self.assertEqual(
                command,
                "python3 ./.harness/scripts/worktree-flow.py --plan .omp/worktree-flow/my-plan/plan.md --harness harness --harness-dir .harness",
            )

    def test_command_for_plan_reports_missing_selected_script(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            plan = repo / ".omp" / "worktree-flow" / "my-plan" / "plan.md"
            plan.parent.mkdir(parents=True)
            plan.write_text("# My Plan", encoding="utf-8")

            with self.assertRaises(FileNotFoundError) as context:
                save_plan.command_for_plan(repo, plan, "harness", Path(".harness"))

            message = str(context.exception)
            self.assertIn(".harness", message)
            self.assertIn("worktree-flow.py", message)

    def test_copy_plan_uses_timestamped_slug_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            source = Path(temp) / "source.md"
            repo.mkdir()
            source.write_text("# My Plan\n\nBody", encoding="utf-8")

            with mock.patch.object(
                save_plan,
                "timestamped_run_id",
                return_value="20260629-082455-my-plan",
            ):
                target = save_plan.copy_plan_to_worktree_flow(repo, source)

            self.assertEqual(
                target,
                repo / ".omp" / "worktree-flow" / "20260629-082455-my-plan" / "plan.md",
            )
            self.assertEqual(target.read_text(encoding="utf-8"), "# My Plan\n\nBody")

    def test_copy_plan_suffixes_same_second_directory_collision(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            source = Path(temp) / "source.md"
            existing = (
                repo
                / ".omp"
                / "worktree-flow"
                / "20260629-082455-my-plan"
            )
            existing.mkdir(parents=True)
            source.write_text("# My Plan\n\nBody", encoding="utf-8")

            with mock.patch.object(
                save_plan,
                "timestamped_run_id",
                return_value="20260629-082455-my-plan",
            ):
                target = save_plan.copy_plan_to_worktree_flow(repo, source)

            self.assertEqual(
                target,
                repo
                / ".omp"
                / "worktree-flow"
                / "20260629-082455-my-plan-2"
                / "plan.md",
            )
            self.assertEqual(target.read_text(encoding="utf-8"), "# My Plan\n\nBody")


if __name__ == "__main__":
    unittest.main()
