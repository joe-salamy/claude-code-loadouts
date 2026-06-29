from __future__ import annotations

import io
import importlib.util
from contextlib import redirect_stderr, redirect_stdout
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1] / ".omp" / "scripts"


def load_flow_module(name: str, script_name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPT_DIR / script_name)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


flow = load_flow_module("worktree_flow", "worktree-flow.py")


class FakeRunner:
    def __init__(
        self,
        outputs: dict[
            tuple[str, ...], flow.CommandResult | list[str] | str
        ] | None = None,
        *,
        dry_run: bool = False,
    ) -> None:
        self.outputs = outputs or {}
        self.calls: list[tuple[tuple[str, ...], Path, bool]] = []
        self.inputs: list[str | None] = []
        self.dry_run = dry_run

    def run(self, args, cwd, *, check=True, capture=True, input_text=None):
        key = tuple(args)
        self.calls.append((key, Path(cwd), check))
        self.inputs.append(input_text)
        value = self.outputs.get(key, "")
        if isinstance(value, flow.CommandResult):
            return value
        if isinstance(value, list):
            stdout = value.pop(0) if value else ""
        else:
            stdout = value
        return flow.CommandResult(key, Path(cwd), 0, stdout, "")


class FailingFastForwardRunner(FakeRunner):
    def run(self, args, cwd, *, check=True, capture=True, input_text=None):
        if tuple(args[:3]) == ("git", "merge", "--ff-only"):
            result = flow.CommandResult(tuple(args), Path(cwd), 1, "", "not a fast-forward")
            if check:
                raise flow.FlowError(flow.format_command_failure(result))
            return result
        return super().run(args, cwd, check=check, capture=capture, input_text=input_text)


class FailingSquashMergeRunner(FakeRunner):
    def __init__(self, *, unmerged_paths: str, timed_out: bool = False) -> None:
        super().__init__()
        self.unmerged_paths = unmerged_paths
        self.timed_out = timed_out

    def run(self, args, cwd, *, check=True, capture=True, input_text=None):
        key = tuple(args)
        if key[:3] == ("git", "merge", "--squash"):
            self.calls.append((key, Path(cwd), check))
            return flow.CommandResult(
                key,
                Path(cwd),
                -9 if self.timed_out else 1,
                "",
                "merge timed out" if self.timed_out else "merge failed",
                timed_out=self.timed_out,
            )
        if key == ("git", "diff", "--name-only", "--diff-filter=U"):
            self.calls.append((key, Path(cwd), check))
            return flow.CommandResult(key, Path(cwd), 0, self.unmerged_paths, "")
        return super().run(args, cwd, check=check, capture=capture, input_text=input_text)


class FailingNoFfMergeRunner(FakeRunner):
    def __init__(self, *, unmerged_paths: str, timed_out: bool = False) -> None:
        super().__init__()
        self.unmerged_paths = unmerged_paths
        self.timed_out = timed_out

    def run(self, args, cwd, *, check=True, capture=True, input_text=None):
        key = tuple(args)
        if key[:4] == ("git", "merge", "--no-ff", "--no-commit"):
            self.calls.append((key, Path(cwd), check))
            return flow.CommandResult(
                key,
                Path(cwd),
                -9 if self.timed_out else 1,
                "",
                "merge timed out" if self.timed_out else "merge failed",
                timed_out=self.timed_out,
            )
        if key == ("git", "diff", "--name-only", "--diff-filter=U"):
            self.calls.append((key, Path(cwd), check))
            return flow.CommandResult(key, Path(cwd), 0, self.unmerged_paths, "")
        return super().run(args, cwd, check=check, capture=capture, input_text=input_text)


class FailingHarnessExecRunner(FakeRunner):
    def __init__(
        self,
        *,
        stdout: str,
        stderr: str,
        returncode: int = 42,
        timed_out: bool = False,
    ) -> None:
        super().__init__()
        self.stdout_text = stdout
        self.stderr_text = stderr
        self.returncode = returncode
        self.timed_out = timed_out

    def run(self, args, cwd, *, check=True, capture=True, input_text=None):
        key = tuple(args)
        if key[:2] == ("codex", "exec"):
            self.calls.append((key, Path(cwd), check))
            self.inputs.append(input_text)
            return flow.CommandResult(
                key,
                Path(cwd),
                self.returncode,
                self.stdout_text,
                self.stderr_text,
                started_at="start",
                finished_at="finish",
                duration_ms=123,
                timed_out=self.timed_out,
            )
        return super().run(args, cwd, check=check, capture=capture, input_text=input_text)


class CommandRunnerTests(unittest.TestCase):
    def test_run_resolves_executable_before_invoking_subprocess(self) -> None:
        completed = subprocess.CompletedProcess(
            ["C:/bin/codex.CMD", "exec", "--help"],
            0,
            "ok",
            "",
        )
        with (
            tempfile.TemporaryDirectory() as temp,
            mock.patch.object(flow.shutil, "which", return_value="C:/bin/codex.CMD") as which,
            mock.patch.object(flow.subprocess, "run", return_value=completed) as run,
        ):
            result = flow.CommandRunner().run(["codex", "exec", "--help"], Path(temp))

        which.assert_called_once_with("codex")
        run.assert_called_once()
        self.assertEqual(
            run.call_args.args[0],
            ["C:/bin/codex.CMD", "exec", "--help"],
        )
        self.assertEqual(result.args, ("codex", "exec", "--help"))
        self.assertEqual(result.stdout, "ok")


    def test_run_records_duration_fields_on_success(self) -> None:
        completed = subprocess.CompletedProcess(
            ["C:/bin/codex.CMD", "exec", "--help"],
            0,
            "ok",
            "",
        )
        with (
            tempfile.TemporaryDirectory() as temp,
            mock.patch.object(flow.shutil, "which", return_value="C:/bin/codex.CMD"),
            mock.patch.object(flow.subprocess, "run", return_value=completed) as run,
            mock.patch.object(flow, "now_iso", side_effect=["start", "finish"]),
            mock.patch.object(flow.time, "perf_counter", side_effect=[10.0, 10.25]),
        ):
            result = flow.CommandRunner().run(["codex", "exec", "--help"], Path(temp))

        self.assertEqual(result.started_at, "start")
        self.assertEqual(result.finished_at, "finish")
        self.assertEqual(result.duration_ms, 250)
        self.assertFalse(result.timed_out)
        self.assertIsNone(run.call_args.kwargs["timeout"])

    def test_run_marks_timeout_when_check_disabled(self) -> None:
        expired = subprocess.TimeoutExpired(
            ["C:/bin/codex.CMD", "exec", "--help"],
            2.5,
            output=b"partial stdout",
            stderr=b"partial stderr",
        )
        with (
            tempfile.TemporaryDirectory() as temp,
            mock.patch.object(flow.shutil, "which", return_value="C:/bin/codex.CMD"),
            mock.patch.object(flow.subprocess, "run", side_effect=expired) as run,
            mock.patch.object(flow, "now_iso", side_effect=["start", "finish"]),
            mock.patch.object(flow.time, "perf_counter", side_effect=[4.0, 6.5]),
        ):
            result = flow.CommandRunner(command_timeout_seconds=2.5).run(
                ["codex", "exec", "--help"],
                Path(temp),
                check=False,
            )

        self.assertTrue(result.timed_out)
        self.assertEqual(result.returncode, -9)
        self.assertEqual(result.stdout, "partial stdout")
        self.assertEqual(result.stderr, "partial stderr")
        self.assertEqual(result.started_at, "start")
        self.assertEqual(result.finished_at, "finish")
        self.assertEqual(result.duration_ms, 2500)
        self.assertEqual(run.call_args.kwargs["timeout"], 2.5)

    def test_run_raises_clear_flow_error_on_checked_timeout(self) -> None:
        expired = subprocess.TimeoutExpired(
            ["C:/bin/codex.CMD", "exec", "--help"],
            1.0,
            output="partial stdout",
            stderr="partial stderr",
        )
        with (
            tempfile.TemporaryDirectory() as temp,
            mock.patch.object(flow.shutil, "which", return_value="C:/bin/codex.CMD"),
            mock.patch.object(flow.subprocess, "run", side_effect=expired),
            self.assertRaisesRegex(
                flow.CommandFailureError, "Command timed out: codex exec --help"
            ),
        ):
            flow.CommandRunner(command_timeout_seconds=1.0).run(
                ["codex", "exec", "--help"],
                Path(temp),
            )

    def test_run_reports_missing_executable_as_flow_error(self) -> None:
        with (
            tempfile.TemporaryDirectory() as temp,
            mock.patch.object(flow.shutil, "which", return_value=None),
            mock.patch.object(flow.subprocess, "run") as run,
            self.assertRaisesRegex(flow.FlowError, "Executable not found on PATH: codex"),
        ):
            flow.CommandRunner().run(["codex", "exec", "--help"], Path(temp))

        run.assert_not_called()

    def test_run_reports_launch_oserror_as_flow_error(self) -> None:
        with (
            tempfile.TemporaryDirectory() as temp,
            mock.patch.object(flow.shutil, "which", return_value="C:/bin/codex.CMD"),
            mock.patch.object(
                flow.subprocess,
                "run",
                side_effect=FileNotFoundError("missing shim target"),
            ),
            self.assertRaisesRegex(flow.FlowError, "Failed to run command: codex exec --help"),
        ):
            flow.CommandRunner().run(["codex", "exec", "--help"], Path(temp))


class SharedHarnessSelectionTests(unittest.TestCase):
    def test_shared_defaults_are_inferred_from_active_script_directory(self) -> None:
        self.assertEqual(flow.DEFAULT_HARNESS, "omp")
        self.assertEqual(flow.HARNESS_DIR, Path(".omp"))
        self.assertEqual(flow.HANDOFF_DIR, Path(".omp") / "handoff")

    def test_shared_parser_accepts_codex_harness_options(self) -> None:
        args = flow.build_parser().parse_args(
            [
                "--plan",
                "docs/plans/p.md",
                "--harness",
                "codex",
                "--harness-dir",
                ".codex",
            ]
        )

        self.assertEqual(args.harness, "codex")
        self.assertEqual(args.harness_dir, ".codex")

    def test_shared_parser_accepts_omp_harness_options(self) -> None:
        args = flow.build_parser().parse_args(
            ["--plan", "docs/plans/p.md", "--harness", "omp", "--harness-dir", ".omp"]
        )

        self.assertEqual(args.harness, "omp")
        self.assertEqual(args.harness_dir, ".omp")

    def test_shared_parser_can_override_harness_dir(self) -> None:
        args = flow.build_parser().parse_args(
            ["--plan", "docs/plans/p.md", "--harness-dir", ".custom"]
        )

        self.assertEqual(args.harness_dir, ".custom")

    def test_shared_parser_leaves_base_unset_for_auto_detection(self) -> None:
        args = flow.build_parser().parse_args(["--plan", "docs/plans/p.md"])

        self.assertIsNone(args.base)

    def test_validate_omp_harness_checks_current_cli_help(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            plan = repo / "plan.md"
            repo.mkdir()
            plan.write_text("# Plan", encoding="utf-8")
            runner = FakeRunner()
            config = flow.FlowConfig(
                repo=repo,
                plan=plan,
                base="main",
                model=None,
                harness="omp",
                harness_dir=Path(".omp"),
                merge_mode="squash",
                keep_worktrees=False,
            )
            subject = flow.HarnessWorktreeFlow(config, runner)

            subject.validate(repo, plan)

            commands = [call[0] for call in runner.calls]
            self.assertIn(("omp", "--help"), commands)
            self.assertNotIn(("omp", "exec", "--help"), commands)


    def test_omp_harness_exec_uses_print_mode_prompt_file_and_writes_stdout(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            repo.mkdir()
            (repo / ".omp" / "handoff").mkdir(parents=True)
            output_file = repo / ".omp" / "handoff" / "implementation-final-response.md"
            prompt_file = output_file.with_name("implementation-final-response-prompt.md")
            args = (
                "omp",
                "-p",
                "--no-session",
                "--auto-approve",
                "--approval-mode",
                "yolo",
                f"@{prompt_file}",
            )
            runner = FakeRunner({args: "Final response"})
            config = flow.FlowConfig(
                repo=repo,
                plan=repo / "plan.md",
                base="main",
                model=None,
                harness="omp",
                harness_dir=Path(".omp"),
                merge_mode="squash",
                keep_worktrees=False,
            )
            subject = flow.HarnessWorktreeFlow(config, runner)

            subject.harness_exec(repo, "Prompt", output_file)

            self.assertEqual(runner.calls[-1][0], args)
            self.assertIsNone(runner.inputs[-1])
            self.assertEqual(output_file.read_text(encoding="utf-8"), "Final response")
            self.assertFalse(prompt_file.exists())




class HarnessWorktreeFlowTests(unittest.TestCase):
    def test_print_checkpoint_formats_details(self) -> None:
        buffer = io.StringIO()

        with redirect_stdout(buffer):
            flow.HarnessWorktreeFlow.print_checkpoint(
                "start",
                "Implementation",
                (
                    ("worktree", Path("repo-plan")),
                    ("empty", ""),
                    ("missing", None),
                ),
            )

        self.assertEqual(
            buffer.getvalue(), "[start] Implementation\n  worktree: repo-plan\n"
        )

    def test_slug_uses_first_h1(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            plan = Path(temp) / "plan.md"
            plan.write_text("# Add Better Audit Flow!\n\nBody", encoding="utf-8")
            self.assertEqual(flow.derive_slug(plan), "add-better-audit-flow")

    def test_slug_falls_back_to_filename(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            plan = Path(temp) / "My Plan File.md"
            plan.write_text("No heading", encoding="utf-8")
            self.assertEqual(flow.derive_slug(plan), "my-plan-file")

    def test_unique_names_skip_existing_branch_and_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            repo.mkdir()
            (Path(temp) / "repo-example").mkdir()
            runner = FakeRunner(
                {
                    ("git", "branch", "--list", "feature/example"): "feature/example\n",
                    ("git", "branch", "--list", "feature/example-2"): "",
                }
            )
            config = self.config(repo, repo / "plan.md")
            names = flow.HarnessWorktreeFlow(config, runner).unique_feature_names(repo, "example")
            self.assertEqual(names.branch, "feature/example-2")
            self.assertEqual(names.worktree.name, "repo-example-2")
            self.assertRegex(names.run_id, r"^\d{8}-\d{6}-example-2$")

    def test_run_id_from_saved_worktree_flow_plan_is_reused(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            plan = repo / ".codex" / "worktree-flow" / "20260629-082455-plan" / "plan.md"
            plan.parent.mkdir(parents=True)
            plan.write_text("# Plan", encoding="utf-8")
            subject = flow.HarnessWorktreeFlow(self.config(repo, plan), FakeRunner())

            self.assertEqual(
                subject.run_id_from_plan(repo, plan),
                "20260629-082455-plan",
            )

    def test_validate_auto_detects_master_when_main_is_absent(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            plan = repo / "plan.md"
            repo.mkdir()
            plan.write_text("# Plan", encoding="utf-8")
            runner = FakeRunner(
                {
                    (
                        "git",
                        "rev-parse",
                        "--verify",
                        "--quiet",
                        "main",
                    ): flow.CommandResult((), repo, 1, "", ""),
                    (
                        "git",
                        "rev-parse",
                        "--verify",
                        "--quiet",
                        "master",
                    ): flow.CommandResult((), repo, 0, "master\n", ""),
                }
            )
            config = flow.FlowConfig(
                repo=repo,
                plan=plan,
                base=None,
                model=None,
                harness="codex",
                harness_dir=Path(".codex"),
                merge_mode="squash",
                keep_worktrees=False,
            )
            subject = flow.HarnessWorktreeFlow(config, runner)

            subject.validate(repo, plan)

            self.assertEqual(subject.base, "master")

    def test_validate_falls_back_to_current_branch_when_main_and_master_are_absent(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            plan = repo / "plan.md"
            repo.mkdir()
            plan.write_text("# Plan", encoding="utf-8")
            runner = FakeRunner(
                {
                    (
                        "git",
                        "rev-parse",
                        "--verify",
                        "--quiet",
                        "main",
                    ): flow.CommandResult((), repo, 1, "", ""),
                    (
                        "git",
                        "rev-parse",
                        "--verify",
                        "--quiet",
                        "master",
                    ): flow.CommandResult((), repo, 1, "", ""),
                    ("git", "branch", "--show-current"): "trunk\n",
                }
            )
            config = flow.FlowConfig(
                repo=repo,
                plan=plan,
                base=None,
                model=None,
                harness="codex",
                harness_dir=Path(".codex"),
                merge_mode="squash",
                keep_worktrees=False,
            )
            subject = flow.HarnessWorktreeFlow(config, runner)

            subject.validate(repo, plan)

            self.assertEqual(subject.base, "trunk")

    def test_validate_does_not_fallback_when_explicit_base_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            plan = repo / "plan.md"
            repo.mkdir()
            plan.write_text("# Plan", encoding="utf-8")
            runner = FakeRunner(
                {
                    (
                        "git",
                        "rev-parse",
                        "--verify",
                        "--quiet",
                        "main",
                    ): flow.CommandResult((), repo, 1, "", ""),
                }
            )
            subject = flow.HarnessWorktreeFlow(self.config(repo, plan), runner)

            with self.assertRaisesRegex(
                flow.FlowError, "Base ref does not exist: main"
            ):
                subject.validate(repo, plan)

    def test_plan_inside_repo_is_copied_to_workflow_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            worktree = Path(temp) / "repo-feature"
            plan = repo / "docs" / "plans" / "p.md"
            names = flow.Names(
                "plan",
                "feature/plan",
                worktree,
                "20260629-082455-plan",
            )
            target = (
                worktree
                / ".codex"
                / "worktree-flow"
                / "20260629-082455-plan"
                / "plan.md"
            )
            repo.mkdir()
            plan.parent.mkdir(parents=True)
            plan.write_text("# Plan", encoding="utf-8")
            actual = flow.HarnessWorktreeFlow(
                self.config(repo, plan), FakeRunner()
            ).ensure_plan_in_worktree(repo, plan, worktree, names)
            self.assertEqual(actual, target)
            self.assertEqual(actual.read_text(encoding="utf-8"), "# Plan")

    def test_dry_run_plan_copy_does_not_mutate_filesystem(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            worktree = Path(temp) / "repo-feature"
            plan = Path(temp) / "external.md"
            repo.mkdir()
            worktree.mkdir()
            plan.write_text("# External", encoding="utf-8")

            names = flow.Names(
                "external",
                "feature/external",
                worktree,
                "20260629-082455-external",
            )
            actual = flow.HarnessWorktreeFlow(
                self.config(repo, plan), FakeRunner(dry_run=True)
            ).ensure_plan_in_worktree(repo, plan, worktree, names)

            self.assertEqual(
                actual,
                worktree
                / ".codex"
                / "worktree-flow"
                / "20260629-082455-external"
                / "plan.md",
            )
            self.assertFalse(actual.exists())

    def test_dry_run_archive_handoff_does_not_mutate_filesystem(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            worktree = Path(temp) / "repo-feature"
            source = worktree / ".codex" / "handoff"
            repo.mkdir()
            source.mkdir(parents=True)
            (source / "implementation-summary.md").write_text("impl", encoding="utf-8")

            archive = flow.HarnessWorktreeFlow(
                self.config(repo, repo / "plan.md"), FakeRunner(dry_run=True)
            ).archive_handoff(repo, worktree, "plan-run")

            self.assertEqual(archive, repo / ".codex" / "worktree-flow" / "plan-run")
            self.assertFalse(archive.exists())

    def test_prepare_harness_permissions_grants_sandbox_group_on_windows(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            harness_dir = Path(temp) / ".codex"
            harness_dir.mkdir()
            completed = subprocess.CompletedProcess(["pwsh"], 0, "", "")
            subject = flow.HarnessWorktreeFlow(
                self.config(Path(temp), Path(temp) / "plan.md"), FakeRunner()
            )

            with (
                mock.patch.object(flow.os, "name", "nt"),
                mock.patch.object(flow.shutil, "which", return_value="C:/PowerShell/pwsh.exe"),
                mock.patch.object(flow.subprocess, "run", return_value=completed) as run,
            ):
                subject.prepare_harness_permissions(harness_dir)

            args = run.call_args.args[0]
            kwargs = run.call_args.kwargs
            self.assertEqual(args[0], "C:/PowerShell/pwsh.exe")
            self.assertEqual(kwargs["env"]["CODEX_PERMISSION_ROOT"], str(harness_dir))
            self.assertEqual(kwargs["env"]["CODEX_PERMISSION_GROUP"], "CodexSandboxUsers")
            self.assertIn("RemoveAccessRuleSpecific", args[4])

    def test_prepare_git_permissions_grants_external_common_git_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            worktree = Path(temp) / "repo-feature"
            common_git = repo / ".git"
            repo.mkdir()
            worktree.mkdir()
            common_git.mkdir()
            subject = flow.HarnessWorktreeFlow(
                self.config(repo, repo / "plan.md"),
                FakeRunner(
                    {
                        ("git", "rev-parse", "--git-common-dir"): str(common_git),
                    }
                ),
            )
            prepared: list[Path] = []
            subject.prepare_harness_permissions = prepared.append

            subject.prepare_git_permissions(worktree)

            self.assertEqual(prepared, [common_git.resolve()])

    def test_extra_writable_roots_include_harness_and_external_git_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            worktree = Path(temp) / "repo-feature"
            common_git = repo / ".git"
            harness_dir = worktree / ".codex"
            repo.mkdir()
            worktree.mkdir()
            common_git.mkdir()
            harness_dir.mkdir()
            runner = FakeRunner(
                {
                    ("git", "rev-parse", "--git-common-dir"): str(common_git),
                }
            )
            subject = flow.HarnessWorktreeFlow(self.config(repo, repo / "plan.md"), runner)

            roots = subject.extra_writable_roots(worktree)

            self.assertEqual(roots, [harness_dir.resolve(), common_git.resolve()])


    def test_harness_exec_adds_harness_and_common_git_dirs_as_writable_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            worktree = Path(temp) / "repo-feature"
            common_git = repo / ".git"
            harness_dir = worktree / ".codex"
            repo.mkdir()
            worktree.mkdir()
            common_git.mkdir()
            harness_dir.mkdir()
            runner = FakeRunner(
                {
                    ("git", "rev-parse", "--git-common-dir"): str(common_git),
                }
            )
            subject = flow.HarnessWorktreeFlow(self.config(repo, repo / "plan.md"), runner)

            subject.harness_exec(
                worktree,
                "Prompt",
                worktree / ".codex" / "handoff" / "implementation-final-response.md",
            )

            args = runner.calls[-1][0]
            writable_roots = [
                args[index + 1]
                for index, value in enumerate(args)
                if value == "--add-dir"
            ]
            self.assertEqual(
                writable_roots,
                [str(harness_dir.resolve()), str(common_git.resolve())],
            )

    def test_harness_exec_uses_full_access_sandbox_on_windows(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            repo.mkdir()
            runner = FakeRunner()
            subject = flow.HarnessWorktreeFlow(self.config(repo, repo / "plan.md"), runner)

            with mock.patch.object(flow.os, "name", "nt"):
                subject.harness_exec(repo, "Prompt", repo / "out.md")

            args = runner.calls[-1][0]
            sandbox_index = args.index("--sandbox")
            self.assertEqual(args[sandbox_index + 1], "danger-full-access")

    def test_harness_exec_uses_workspace_write_sandbox_off_windows(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            repo.mkdir()
            runner = FakeRunner()
            subject = flow.HarnessWorktreeFlow(self.config(repo, repo / "plan.md"), runner)

            with mock.patch.object(flow.os, "name", "posix"):
                subject.harness_exec(repo, "Prompt", repo / "out.md")

            args = runner.calls[-1][0]
            sandbox_index = args.index("--sandbox")
            self.assertEqual(args[sandbox_index + 1], "workspace-write")

    def test_run_prepares_primary_repo_permissions_before_logging(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            worktree = Path(temp) / "repo-plan"
            plan = repo / "docs" / "plans" / "plan.md"
            repo.mkdir()
            (repo / ".codex").mkdir()
            plan.parent.mkdir(parents=True)
            plan.write_text("# Plan", encoding="utf-8")
            (worktree / "docs" / "plans").mkdir(parents=True)
            (worktree / "docs" / "plans" / "plan.md").write_text("# Plan", encoding="utf-8")
            handoff = worktree / ".codex" / "handoff"
            handoff.mkdir(parents=True)
            (handoff / "implementation-summary.md").write_text("impl", encoding="utf-8")
            (handoff / "audit-summary.md").write_text("audit", encoding="utf-8")
            runner = FakeRunner(
                {
                    ("git", "branch", "--list", "feature/plan"): "",
                    ("git", "rev-parse", "--git-common-dir"): ".git",
                }
            )
            subject = flow.HarnessWorktreeFlow(
                self.config(repo, plan, merge_mode="stop"), runner
            )
            prepared: list[Path] = []
            subject.prepare_harness_permissions = prepared.append
            subject.create_feature_worktree = lambda _repo, _names: None
            subject.run_implementation = lambda _worktree, _plan: None
            subject.run_audit = lambda _worktree, _plan: None
            subject.require_implementation_invariants = lambda _worktree, _branch: None
            subject.head_rev = lambda _worktree: "before"
            subject.require_audit_invariants = lambda _worktree, _branch, _head: None
            subject.require_commits_since_base = lambda *_args: None
            subject.require_branch_changed_since_base = lambda *_args: None
            subject.unique_feature_names = lambda _repo, _slug, _run_id=None: flow.Names(
                "plan", "feature/plan", worktree, "plan-run"
            )
            subject.validate = lambda _repo, _plan: None
            subject.finish = lambda *_args: (_ for _ in ()).throw(
                AssertionError("finish should not run")
            )

            subject.run()

            self.assertEqual(prepared[0], repo / ".codex")

    def test_stage_integration_changes_excludes_handoff_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            runner = FakeRunner()
            subject = flow.HarnessWorktreeFlow(self.config(repo, repo / "plan.md"), runner)

            subject.stage_integration_changes(repo)

            self.assertEqual(runner.calls[0][0], ("git", "add", "-A"))
            self.assertEqual(
                runner.calls[1],
                (("git", "reset", "HEAD", "--", ".codex/handoff"), repo, False),
            )


    def test_tracked_handoff_artifacts_warn(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            runner = FakeRunner(
                {
                    (
                        "git",
                        "ls-tree",
                        "-r",
                        "--name-only",
                        "feature/plan",
                        "--",
                        ".codex/handoff",
                    ): ".codex/handoff/audit-summary.md\n",
                }
            )
            subject = flow.HarnessWorktreeFlow(self.config(repo, repo / "plan.md"), runner)

            stderr = io.StringIO()
            with redirect_stderr(stderr):
                subject.require_no_tracked_handoff_artifacts(repo, "feature/plan")

            warning = stderr.getvalue()
            self.assertIn(
                "Warning: workflow handoff artifacts are tracked in feature/plan.",
                warning,
            )
            self.assertIn(".codex/handoff/audit-summary.md", warning)

    def test_implementation_fails_when_no_commit_exists_after_base(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            subject = flow.HarnessWorktreeFlow(
                self.config(repo, repo / "plan.md"),
                FakeRunner({("git", "rev-list", "--count", "main..feature/plan"): "0\n"}),
            )

            with self.assertRaisesRegex(flow.FlowError, "did not create any commits"):
                subject.require_implementation_invariants(repo, "feature/plan")

    def test_implementation_fails_when_branch_has_no_diff_from_base(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            subject = flow.HarnessWorktreeFlow(
                self.config(repo, repo / "plan.md"),
                FakeRunner(
                    {
                        ("git", "rev-list", "--count", "main..feature/plan"): "1\n",
                        (
                            "git",
                            "diff",
                            "--quiet",
                            "main...feature/plan",
                            "--",
                            ".",
                        ): flow.CommandResult(
                            (
                                "git",
                                "diff",
                                "--quiet",
                                "main...feature/plan",
                                "--",
                                ".",
                            ),
                            repo,
                            0,
                        ),
                    }
                ),
            )

            with self.assertRaisesRegex(flow.FlowError, "no file changes"):
                subject.require_implementation_invariants(repo, "feature/plan")

    def test_implementation_fails_when_non_handoff_file_remains(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            subject = flow.HarnessWorktreeFlow(
                self.config(repo, repo / "plan.md"),
                FakeRunner(
                    {
                        ("git", "rev-list", "--count", "main..feature/plan"): "1\n",
                        (
                            "git",
                            "diff",
                            "--quiet",
                            "main...feature/plan",
                            "--",
                            ".",
                        ): flow.CommandResult(
                            (
                                "git",
                                "diff",
                                "--quiet",
                                "main...feature/plan",
                                "--",
                                ".",
                            ),
                            repo,
                            1,
                        ),
                        (
                            "git",
                            "status",
                            "--porcelain",
                            "--untracked-files=all",
                        ): "?? app.py\n?? .codex/handoff/implementation-summary.md\n",
                    }
                ),
            )

            with self.assertRaisesRegex(flow.FlowError, "non-handoff changes"):
                subject.require_implementation_invariants(repo, "feature/plan")

    def test_implementation_allows_untracked_handoff_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            subject = flow.HarnessWorktreeFlow(
                self.config(repo, repo / "plan.md"),
                FakeRunner(
                    {
                        ("git", "rev-list", "--count", "main..feature/plan"): "1\n",
                        (
                            "git",
                            "diff",
                            "--quiet",
                            "main...feature/plan",
                            "--",
                            ".",
                        ): flow.CommandResult(
                            (
                                "git",
                                "diff",
                                "--quiet",
                                "main...feature/plan",
                                "--",
                                ".",
                            ),
                            repo,
                            1,
                        ),
                        (
                            "git",
                            "status",
                            "--porcelain",
                            "--untracked-files=all",
                        ): "?? .codex/handoff/implementation-summary.md\n",
                    }
                ),
            )

            subject.require_implementation_invariants(repo, "feature/plan")

    def test_audit_allows_no_new_commit_when_clean_outside_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            subject = flow.HarnessWorktreeFlow(
                self.config(repo, repo / "plan.md"),
                FakeRunner(
                    {
                        (
                            "git",
                            "status",
                            "--porcelain",
                            "--untracked-files=all",
                        ): "?? .codex/handoff/audit-summary.md\n",
                        ("git", "rev-parse", "HEAD"): "before\n",
                    }
                ),
            )

            subject.require_audit_invariants(repo, "feature/plan", "before")

    def test_audit_allows_new_commit_when_clean_outside_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            subject = flow.HarnessWorktreeFlow(
                self.config(repo, repo / "plan.md"),
                FakeRunner(
                    {
                        (
                            "git",
                            "status",
                            "--porcelain",
                            "--untracked-files=all",
                        ): "?? .codex/handoff/audit-summary.md\n",
                        ("git", "rev-parse", "HEAD"): "after\n",
                        (
                            "git",
                            "diff",
                            "--quiet",
                            "main...feature/plan",
                            "--",
                            ".",
                        ): flow.CommandResult(
                            (
                                "git",
                                "diff",
                                "--quiet",
                                "main...feature/plan",
                                "--",
                                ".",
                            ),
                            repo,
                            1,
                        ),
                    }
                ),
            )

            subject.require_audit_invariants(repo, "feature/plan", "before")

    def test_audit_fails_when_non_handoff_changes_remain(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            subject = flow.HarnessWorktreeFlow(
                self.config(repo, repo / "plan.md"),
                FakeRunner(
                    {
                        (
                            "git",
                            "status",
                            "--porcelain",
                            "--untracked-files=all",
                        ): " M app.py\n",
                    }
                ),
            )

            with self.assertRaisesRegex(flow.FlowError, "non-handoff changes"):
                subject.require_audit_invariants(repo, "feature/plan", "before")

    def test_final_guard_fails_when_non_handoff_changes_appear_after_audit(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            subject = flow.HarnessWorktreeFlow(
                self.config(repo, repo / "plan.md"),
                FakeRunner(
                    {
                        (
                            "git",
                            "ls-tree",
                            "-r",
                            "--name-only",
                            "feature/plan",
                            "--",
                            ".codex/handoff",
                        ): "",
                        (
                            "git",
                            "status",
                            "--porcelain",
                            "--untracked-files=all",
                        ): "?? leaked.txt\n",
                    }
                ),
            )

            with self.assertRaisesRegex(flow.FlowError, "Pre-integration"):
                subject.require_ready_for_integration(repo, "feature/plan")

    def test_handoff_prompts_forbid_committing_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            repo.mkdir()
            runner = FakeRunner()
            subject = flow.HarnessWorktreeFlow(self.config(repo, repo / "plan.md"), runner)

            subject.run_implementation(repo, repo / "plan.md")
            subject.run_audit(repo, repo / "plan.md")

            prompts = [value for value in runner.inputs if value is not None]
            self.assertIn("Do not commit files under `.codex/handoff/`", prompts[-2])
            self.assertIn("Do not commit files under `.codex/handoff/`", prompts[-1])


    def test_finish_stages_integration_changes_in_squash_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            feature = Path(temp) / "repo-plan"
            plan = feature / "docs" / "plans" / "plan.md"
            repo.mkdir()
            plan.parent.mkdir(parents=True)
            plan.write_text("# Plan", encoding="utf-8")
            subject = flow.HarnessWorktreeFlow(self.config(repo, plan), FakeRunner())
            subject.prepare_harness_permissions = lambda _path: None
            events: list[str] = []
            subject.stage_integration_changes = lambda _worktree: events.append("stage")
            subject.has_staged_non_handoff_changes = lambda _worktree: True
            subject.archive_handoff = lambda *_args: repo / ".codex" / "archive"
            subject.update_workflow_state = lambda state, **changes: flow.replace(state, **changes)
            subject.require_ready_for_integration = lambda _worktree, _branch: None

            subject.finish(
                repo,
                self.workflow_state(feature, merge_mode=subject.config.merge_mode),
                flow.Names("plan", "feature/plan", feature, "plan-run"),
                plan,
            )

            self.assertEqual(events, ["stage"])



    def test_no_ff_merge_uses_no_commit_and_workflow_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            feature = Path(temp) / "repo-plan"
            plan = feature / "docs" / "plans" / "plan.md"
            repo.mkdir()
            plan.parent.mkdir(parents=True)
            plan.write_text("# Plan", encoding="utf-8")
            (feature / ".codex" / "handoff").mkdir(parents=True)
            subject = flow.HarnessWorktreeFlow(
                self.config(repo, plan, merge_mode="no-ff"), FakeRunner()
            )
            subject.prepare_harness_permissions = lambda _path: None
            subject.stage_integration_changes = lambda _worktree: None
            subject.has_staged_non_handoff_changes = lambda _worktree: True
            subject.archive_handoff = lambda *_args: repo / ".codex" / "archive"
            subject.update_workflow_state = lambda state, **changes: flow.replace(state, **changes)
            subject.require_ready_for_integration = lambda _worktree, _branch: None

            subject.finish(
                repo,
                self.workflow_state(feature, merge_mode=subject.config.merge_mode),
                flow.Names("plan", "feature/plan", feature, "plan-run"),
                plan,
            )

            calls = [call[0] for call in subject.runner.calls]
            self.assertIn(("git", "merge", "--no-ff", "--no-commit", "feature/plan"), calls)
            self.assertIn(("git", "commit", "-m", "Harness: Plan"), calls)
            self.assertNotIn(("git", "merge", "--continue"), calls)



    def test_conflict_runs_resolver_before_integration_stage(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            feature = Path(temp) / "repo-plan"
            plan = feature / "docs" / "plans" / "plan.md"
            repo.mkdir()
            plan.parent.mkdir(parents=True)
            plan.write_text("# Plan", encoding="utf-8")
            (feature / ".codex" / "handoff").mkdir(parents=True)
            subject = flow.HarnessWorktreeFlow(
                self.config(repo, plan),
                FailingSquashMergeRunner(unmerged_paths="app.py\n"),
            )
            subject.prepare_harness_permissions = lambda _path: None
            events: list[str] = []
            subject.run_conflict_resolution = lambda *_args: events.append("resolve")
            subject.stage_integration_changes = lambda _worktree: events.append("stage")
            subject.archive_handoff = lambda *_args: repo / ".codex" / "archive"
            unmerged_checks = iter([False, True, False, False])
            subject.has_unmerged_paths = lambda _worktree: next(unmerged_checks)
            subject.has_staged_non_handoff_changes = lambda _worktree: True
            subject.update_workflow_state = lambda state, **changes: flow.replace(state, **changes)
            subject.require_ready_for_integration = lambda _worktree, _branch: None

            subject.finish(
                repo,
                self.workflow_state(feature, merge_mode=subject.config.merge_mode),
                flow.Names("plan", "feature/plan", feature, "plan-run"),
                plan,
            )

            self.assertEqual(events, ["resolve", "stage"])

    def test_plan_outside_repo_is_copied(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            worktree = Path(temp) / "repo-feature"
            plan = Path(temp) / "external.md"
            repo.mkdir()
            worktree.mkdir()
            plan.write_text("# External", encoding="utf-8")
            names = flow.Names(
                "external",
                "feature/external",
                worktree,
                "20260629-082455-external",
            )
            actual = flow.HarnessWorktreeFlow(
                self.config(repo, plan), FakeRunner()
            ).ensure_plan_in_worktree(repo, plan, worktree, names)
            self.assertEqual(
                actual,
                worktree
                / ".codex"
                / "worktree-flow"
                / "20260629-082455-external"
                / "plan.md",
            )
            self.assertEqual(actual.read_text(encoding="utf-8"), "# External")

    def test_harness_command_includes_model_and_output_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            plan = repo / "plan.md"
            config = self.config(repo, plan, model="gpt-5")
            runner = FakeRunner()
            flow.HarnessWorktreeFlow(config, runner).harness_exec(repo, "Prompt", repo / "out.md")
            args = runner.calls[-1][0]
            self.assertEqual(args[:2], ("codex", "exec"))
            self.assertIn("--model", args)
            self.assertIn("gpt-5", args)
            self.assertEqual(args[-1], "-")
            self.assertEqual(runner.inputs[-1], "Prompt")
            self.assertIn("--output-last-message", args)

    def test_harness_exec_logs_jsonl_to_main_repo_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            worktree = Path(temp) / "repo-feature"
            repo.mkdir()
            worktree.mkdir()
            output_file = worktree / ".codex" / "handoff" / "implementation-final-response.md"
            subject = flow.HarnessWorktreeFlow(self.config(repo, repo / "plan.md"), FakeRunner())

            subject.start_log(repo, "plan-run")
            subject.harness_exec(worktree, "Secret prompt", output_file)

            log_file = repo / ".codex" / "handoff" / "workflow.jsonl"
            records = [
                json.loads(line)
                for line in log_file.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(log_file, subject.log_file)
            self.assertEqual(
                [record["event"] for record in records],
                [
                    "workflow_log_started",
                    "harness_exec_start",
                    "harness_exec_finish",
                ],
            )
            self.assertEqual(records[1]["cwd"], str(worktree))
            self.assertNotIn("Secret prompt", records[1]["command"])
            self.assertFalse(records[2]["output_file_exists"])
            self.assertEqual(records[2]["returncode"], 0)
            self.assertIn("duration_ms", records[2])
            self.assertIn("timed_out", records[2])
            self.assertIn("started_at", records[2])
            self.assertIn("finished_at", records[2])
            self.assertEqual(
                records[2]["stdout"],
                {"text": "", "truncated": False, "original_chars": 0},
            )
            self.assertEqual(
                records[2]["stderr"],
                {"text": "", "truncated": False, "original_chars": 0},
            )

    def test_failing_harness_exec_logs_failure_without_prompt_and_bounds_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            worktree = Path(temp) / "repo-feature"
            repo.mkdir()
            worktree.mkdir()
            output_file = worktree / ".codex" / "handoff" / "implementation-final-response.md"
            stdout = "x" * (flow.MAX_LOG_OUTPUT_CHARS + 5)
            runner = FailingHarnessExecRunner(stdout=stdout, stderr="failed")
            subject = flow.HarnessWorktreeFlow(self.config(repo, repo / "plan.md"), runner)

            subject.start_log(repo, "plan-run")
            with self.assertRaisesRegex(flow.FlowError, "exit code 42"):
                subject.harness_exec(worktree, "Secret prompt", output_file)

            log_file = repo / ".codex" / "handoff" / "workflow.jsonl"
            records = [
                json.loads(line)
                for line in log_file.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(
                [record["event"] for record in records],
                [
                    "workflow_log_started",
                    "harness_exec_start",
                    "harness_exec_finish",
                    "harness_exec_failure",
                ],
            )
            failure = records[3]
            self.assertNotIn("Secret prompt", json.dumps(records, ensure_ascii=False))
            self.assertNotIn("-", failure["command"])
            self.assertEqual(failure["returncode"], 42)
            self.assertFalse(failure["timed_out"])
            self.assertEqual(failure["duration_ms"], 123)
            self.assertTrue(failure["stdout"]["truncated"])
            self.assertEqual(failure["stdout"]["original_chars"], len(stdout))
            self.assertEqual(len(failure["stdout"]["text"]), flow.MAX_LOG_OUTPUT_CHARS)
            self.assertEqual(
                failure["stderr"],
                {"text": "failed", "truncated": False, "original_chars": 6},
            )

    def test_timed_out_harness_exec_logs_timeout_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            worktree = Path(temp) / "repo-feature"
            repo.mkdir()
            worktree.mkdir()
            output_file = worktree / ".codex" / "handoff" / "implementation-final-response.md"
            runner = FailingHarnessExecRunner(
                stdout="partial",
                stderr="timeout",
                returncode=-9,
                timed_out=True,
            )
            subject = flow.HarnessWorktreeFlow(self.config(repo, repo / "plan.md"), runner)

            subject.start_log(repo, "plan-run")
            with self.assertRaisesRegex(flow.FlowError, "Command timed out"):
                subject.harness_exec(worktree, "Secret prompt", output_file)

            log_file = repo / ".codex" / "handoff" / "workflow.jsonl"
            records = [
                json.loads(line)
                for line in log_file.read_text(encoding="utf-8").splitlines()
            ]
            failure = records[-1]
            self.assertEqual(failure["event"], "harness_exec_failure")
            self.assertTrue(failure["timed_out"])
            self.assertEqual(failure["returncode"], -9)
            self.assertEqual(failure["stdout"]["text"], "partial")
            self.assertNotIn("Secret prompt", json.dumps(records, ensure_ascii=False))

    def test_stop_merge_mode_does_not_finish(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            worktree = Path(temp) / "repo-plan"
            plan = repo / "docs" / "plans" / "plan.md"
            repo.mkdir()
            (worktree / "docs" / "plans").mkdir(parents=True)
            plan.parent.mkdir(parents=True)
            plan.write_text("# Plan", encoding="utf-8")
            (worktree / "docs" / "plans" / "plan.md").write_text("# Plan", encoding="utf-8")
            handoff = worktree / ".codex" / "handoff"
            handoff.mkdir(parents=True)
            (handoff / "implementation-summary.md").write_text("impl", encoding="utf-8")
            (handoff / "audit-summary.md").write_text("audit", encoding="utf-8")

            runner = FakeRunner(
                {
                    ("git", "branch", "--list", "feature/plan"): "",
                }
            )
            config = self.config(repo, plan, merge_mode="stop")
            subject = flow.HarnessWorktreeFlow(config, runner)
            subject.create_feature_worktree = lambda _repo, _names: None
            subject.run_implementation = lambda _worktree, _plan: None
            subject.run_audit = lambda _worktree, _plan: None
            subject.require_implementation_invariants = lambda _worktree, _branch: None
            subject.head_rev = lambda _worktree: "before"
            subject.require_audit_invariants = lambda _worktree, _branch, _head: None
            subject.require_commits_since_base = lambda *_args: None
            subject.require_branch_changed_since_base = lambda *_args: None
            subject.require_ready_for_integration = lambda _worktree, _branch: None
            subject.unique_feature_names = lambda _repo, _slug, _run_id=None: flow.Names("plan", "feature/plan", worktree, "plan-run")
            subject.validate = lambda _repo, _plan: None
            subject.finish = lambda *_args: (_ for _ in ()).throw(AssertionError("finish should not run"))

            subject.run()

    def test_checked_command_failure_after_log_is_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            worktree = Path(temp) / "repo-plan"
            plan = repo / "docs" / "plans" / "plan.md"
            repo.mkdir()
            worktree.mkdir()
            plan.parent.mkdir(parents=True)
            plan.write_text("# Plan", encoding="utf-8")
            result = flow.CommandResult(
                ("git", "commit", "-m", "Harness: Plan"),
                repo,
                -9,
                "partial",
                "timeout",
                started_at="start",
                finished_at="finish",
                duration_ms=1000,
                timed_out=True,
            )
            runner = FakeRunner()
            subject = flow.HarnessWorktreeFlow(self.config(repo, plan), runner)
            subject.create_feature_worktree = lambda _repo, _names: None
            subject.ensure_plan_in_worktree = lambda *_args: plan
            subject.run_implementation = lambda *_args: None
            subject.require_file = lambda _path: None
            subject.require_no_tracked_handoff_artifacts = lambda *_args: None
            subject.require_implementation_invariants = lambda *_args: None
            subject.head_rev = lambda _worktree: "before"
            subject.run_audit = lambda *_args: None
            subject.require_audit_invariants = lambda *_args: None
            subject.archive_handoff = lambda *_args: repo / ".codex" / "archive"
            subject.require_ready_for_integration = lambda *_args: None
            subject.unique_feature_names = lambda _repo, _slug, _run_id=None: flow.Names(
                "plan", "feature/plan", worktree, "plan-run"
            )
            subject.validate = lambda _repo, _plan: None
            subject.finish = lambda *_args: (_ for _ in ()).throw(
                flow.CommandFailureError(result)
            )

            with self.assertRaisesRegex(flow.CommandFailureError, "Command timed out"):
                subject.run()

            log_file = worktree / ".codex" / "handoff" / "workflow.jsonl"
            records = [
                json.loads(line)
                for line in log_file.read_text(encoding="utf-8").splitlines()
            ]
            failures = [
                record for record in records if record["event"] == "command_failure"
            ]
            self.assertEqual(len(failures), 1)
            self.assertEqual(failures[0]["phase"], "workflow")
            self.assertEqual(failures[0]["step"], "checked_command")
            self.assertTrue(failures[0]["timed_out"])

    def test_conflict_context_contains_files_and_rules(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            plan = repo / "plan.md"
            runner = FakeRunner(
                {
                    ("git", "status", "--short"): "UU app.py\n",
                    ("git", "diff", "--name-only", "--diff-filter=U"): "app.py\n",
                    ("git", "merge-base", "main", "feature/plan"): "abc123\n",
                    ("git", "log", "--oneline", "abc123..main"): "base commit\n",
                    ("git", "log", "--oneline", "abc123..feature/plan"): "feature commit\n",
                }
            )
            text = flow.HarnessWorktreeFlow(self.config(repo, plan), runner).conflict_context(
                repo,
                flow.Names("plan", "feature/plan", repo, "plan-run"),
                plan,
            )
            self.assertIn("app.py", text)
            self.assertIn("Latest base behavior is presumed correct", text)
            self.assertIn("feature commit", text)

    def test_post_conflict_audit_prompt_does_not_allow_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            repo.mkdir()
            runner = FakeRunner()
            flow.HarnessWorktreeFlow(self.config(repo, repo / "plan.md"), runner).run_audit(
                repo,
                repo / "plan.md",
                post_conflict=True,
            )
            prompt = runner.inputs[-1]
            self.assertIn("Do not commit", prompt)
            self.assertNotIn("commit audit fixes if changes are made", prompt.lower())

    def test_cleanup_forces_prunes_and_removes_remaining_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            feature = Path(temp) / "repo-plan"
            integration = Path(temp) / "repo-integrate-plan-run"
            repo.mkdir()
            feature.mkdir()
            integration.mkdir()
            runner = FakeRunner()
            subject = flow.HarnessWorktreeFlow(
                self.config(repo, feature / "docs" / "plans" / "plan.md"), runner
            )

            subject.cleanup(
                repo,
                integration,
                "integration/plan-run",
                flow.Names("plan", "feature/plan", feature, "plan-run"),
            )

            self.assertFalse(integration.exists())
            self.assertFalse(feature.exists())
            self.assertIn(
                (
                    ("git", "worktree", "remove", "--force", str(integration)),
                    repo,
                    False,
                ),
                runner.calls,
            )
            self.assertIn(
                (
                    ("git", "worktree", "remove", "--force", str(feature)),
                    repo,
                    False,
                ),
                runner.calls,
            )
            self.assertIn((("git", "worktree", "prune"), repo, False), runner.calls)

    def test_finish_does_not_cleanup_if_primary_merge_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            feature = Path(temp) / "repo-plan"
            plan = feature / "docs" / "plans" / "plan.md"
            repo.mkdir()
            plan.parent.mkdir(parents=True)
            plan.write_text("# Plan", encoding="utf-8")
            handoff = feature / ".codex" / "handoff"
            handoff.mkdir(parents=True)
            (handoff / "implementation-summary.md").write_text("impl", encoding="utf-8")
            (handoff / "audit-summary.md").write_text("audit", encoding="utf-8")

            subject = flow.HarnessWorktreeFlow(self.config(repo, plan), FailingFastForwardRunner())
            subject.cleanup = lambda *_args: (_ for _ in ()).throw(AssertionError("cleanup should not run"))
            subject.archive_handoff = lambda *_args: repo / ".codex" / "archive"
            subject.prepare_harness_permissions = lambda _path: None
            subject.require_ready_for_integration = lambda _worktree, _branch: None
            subject.has_staged_non_handoff_changes = lambda _worktree: True
            subject.base_contains_branch = lambda _repo, _branch: False
            subject.start_log(repo, "plan-run")

            with self.assertRaises(flow.FlowError):
                subject.finish(
                    repo,
                    self.workflow_state(feature, merge_mode=subject.config.merge_mode),
                    flow.Names("plan", "feature/plan", feature, "plan-run"),
                    plan,
                )

            log_file = subject.log_file
            records = [
                json.loads(line)
                for line in log_file.read_text(encoding="utf-8").splitlines()
            ]
            failures = [
                record for record in records if record["event"] == "command_failure"
            ]
            self.assertEqual(len(failures), 1)
            self.assertEqual(failures[0]["step"], "fast_forward_merge")

    def test_non_conflict_squash_merge_failure_does_not_run_resolver(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            feature = Path(temp) / "repo-plan"
            plan = feature / "docs" / "plans" / "plan.md"
            repo.mkdir()
            plan.parent.mkdir(parents=True)
            plan.write_text("# Plan", encoding="utf-8")
            handoff = feature / ".codex" / "handoff"
            handoff.mkdir(parents=True)
            (handoff / "implementation-summary.md").write_text("impl", encoding="utf-8")
            (handoff / "audit-summary.md").write_text("audit", encoding="utf-8")
            subject = flow.HarnessWorktreeFlow(
                self.config(repo, plan), FailingSquashMergeRunner(unmerged_paths="")
            )
            subject.prepare_harness_permissions = lambda _path: None
            subject.run_conflict_resolution = lambda *_args: (_ for _ in ()).throw(
                AssertionError("resolver should not run")
            )
            subject.require_ready_for_integration = lambda _worktree, _branch: None

            subject.start_log(repo, "plan-run")
            with self.assertRaisesRegex(flow.FlowError, "merge --squash"):
                subject.finish(
                    repo,
                    self.workflow_state(feature, merge_mode=subject.config.merge_mode),
                    flow.Names("plan", "feature/plan", feature, "plan-run"),
                    plan,
                )

            log_file = subject.log_file
            records = [
                json.loads(line)
                for line in log_file.read_text(encoding="utf-8").splitlines()
            ]
            failures = [
                record for record in records if record["event"] == "command_failure"
            ]
            self.assertEqual(len(failures), 1)
            self.assertEqual(failures[0]["step"], "squash_merge")
            self.assertEqual(failures[0]["returncode"], 1)

    def test_timed_out_squash_merge_aborts_without_resolver(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            feature = Path(temp) / "repo-plan"
            plan = feature / "docs" / "plans" / "plan.md"
            repo.mkdir()
            plan.parent.mkdir(parents=True)
            plan.write_text("# Plan", encoding="utf-8")
            handoff = feature / ".codex" / "handoff"
            handoff.mkdir(parents=True)
            (handoff / "implementation-summary.md").write_text("impl", encoding="utf-8")
            (handoff / "audit-summary.md").write_text("audit", encoding="utf-8")
            subject = flow.HarnessWorktreeFlow(
                self.config(repo, plan),
                FailingSquashMergeRunner(unmerged_paths="app.py\n", timed_out=True),
            )
            subject.prepare_harness_permissions = lambda _path: None
            subject.run_conflict_resolution = lambda *_args: (_ for _ in ()).throw(
                AssertionError("resolver should not run after a timeout")
            )
            subject.require_ready_for_integration = lambda _worktree, _branch: None
            subject.has_unmerged_paths = lambda _worktree: False

            subject.start_log(repo, "plan-run")
            with self.assertRaisesRegex(flow.FlowError, "Command timed out"):
                subject.finish(
                    repo,
                    self.workflow_state(feature, merge_mode=subject.config.merge_mode),
                    flow.Names("plan", "feature/plan", feature, "plan-run"),
                    plan,
                )

            log_file = subject.log_file
            records = [
                json.loads(line)
                for line in log_file.read_text(encoding="utf-8").splitlines()
            ]
            failures = [
                record for record in records if record["event"] == "command_failure"
            ]
            self.assertEqual(len(failures), 1)
            self.assertEqual(failures[0]["step"], "squash_merge")
            self.assertTrue(failures[0]["timed_out"])

    def test_timed_out_no_ff_merge_aborts_without_resolver(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            feature = Path(temp) / "repo-plan"
            plan = feature / "docs" / "plans" / "plan.md"
            repo.mkdir()
            plan.parent.mkdir(parents=True)
            plan.write_text("# Plan", encoding="utf-8")
            handoff = feature / ".codex" / "handoff"
            handoff.mkdir(parents=True)
            (handoff / "implementation-summary.md").write_text("impl", encoding="utf-8")
            (handoff / "audit-summary.md").write_text("audit", encoding="utf-8")
            subject = flow.HarnessWorktreeFlow(
                self.config(repo, plan, merge_mode="no-ff"),
                FailingNoFfMergeRunner(unmerged_paths="app.py\n", timed_out=True),
            )
            subject.prepare_harness_permissions = lambda _path: None
            subject.run_conflict_resolution = lambda *_args: (_ for _ in ()).throw(
                AssertionError("resolver should not run after a timeout")
            )
            subject.require_ready_for_integration = lambda _worktree, _branch: None
            subject.has_unmerged_paths = lambda _worktree: False

            subject.start_log(repo, "plan-run")
            with self.assertRaisesRegex(flow.FlowError, "Command timed out"):
                subject.finish(
                    repo,
                    self.workflow_state(feature, merge_mode=subject.config.merge_mode),
                    flow.Names("plan", "feature/plan", feature, "plan-run"),
                    plan,
                )

            log_file = subject.log_file
            records = [
                json.loads(line)
                for line in log_file.read_text(encoding="utf-8").splitlines()
            ]
            failures = [
                record for record in records if record["event"] == "command_failure"
            ]
            self.assertEqual(len(failures), 1)
            self.assertEqual(failures[0]["step"], "no_ff_merge")
            self.assertTrue(failures[0]["timed_out"])

    def test_conflict_squash_merge_failure_runs_resolver(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            feature = Path(temp) / "repo-plan"
            plan = feature / "docs" / "plans" / "plan.md"
            repo.mkdir()
            plan.parent.mkdir(parents=True)
            plan.write_text("# Plan", encoding="utf-8")
            handoff = feature / ".codex" / "handoff"
            handoff.mkdir(parents=True)
            (handoff / "implementation-summary.md").write_text("impl", encoding="utf-8")
            (handoff / "audit-summary.md").write_text("audit", encoding="utf-8")
            subject = flow.HarnessWorktreeFlow(
                self.config(repo, plan), FailingSquashMergeRunner(unmerged_paths="app.py\n")
            )
            resolved = []
            subject.prepare_harness_permissions = lambda _path: None
            subject.run_conflict_resolution = lambda *_args: resolved.append(True)
            unmerged_checks = iter([False, True, False, False])
            subject.has_unmerged_paths = lambda _worktree: next(unmerged_checks)
            subject.has_staged_non_handoff_changes = lambda _worktree: True
            subject.archive_handoff = lambda *_args: repo / ".codex" / "archive"
            subject.require_ready_for_integration = lambda _worktree, _branch: None

            subject.finish(
                repo,
                self.workflow_state(feature, merge_mode=subject.config.merge_mode),
                flow.Names("plan", "feature/plan", feature, "plan-run"),
                plan,
            )
            self.assertEqual(resolved, [True])

    def test_parser_rejects_removed_yes_option(self) -> None:
        with self.assertRaises(SystemExit):
            flow.build_parser().parse_args(["--plan", "plan.md", "--yes"])

    def test_parser_accepts_command_timeout_seconds(self) -> None:
        args = flow.build_parser().parse_args(
            ["--plan", "plan.md", "--command-timeout-seconds", "2.5"]
        )
        self.assertEqual(args.command_timeout_seconds, 2.5)

    def test_parser_rejects_non_finite_command_timeout_seconds(self) -> None:
        with self.assertRaises(SystemExit):
            flow.build_parser().parse_args(
                ["--plan", "plan.md", "--command-timeout-seconds", "nan"]
            )

    def test_main_passes_command_timeout_seconds_to_runner(self) -> None:
        created = {}

        class FakeFlow:
            def __init__(self, config, runner) -> None:
                created["config"] = config
                created["runner"] = runner

            def run(self) -> None:
                created["ran"] = True

        with (
            tempfile.TemporaryDirectory() as temp,
            mock.patch.object(flow, "HarnessWorktreeFlow", FakeFlow),
        ):
            result = flow.main(
                [
                    "--plan",
                    str(Path(temp) / "plan.md"),
                    "--command-timeout-seconds",
                    "3.5",
                ]
            )

        self.assertEqual(result, 0)
        self.assertTrue(created["ran"])
        self.assertEqual(created["config"].command_timeout_seconds, 3.5)
        self.assertEqual(created["runner"].command_timeout_seconds, 3.5)

    def test_resume_command_args_uses_saved_workflow_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            feature = Path(temp) / "repo-feature path"
            integration = Path(temp) / "repo-integration"
            plan = repo / "docs" / "plans" / "plan.md"
            repo.mkdir(parents=True)
            config = self.config(repo, plan, model="gpt-test")
            subject = flow.HarnessWorktreeFlow(config, FakeRunner())
            state = self.workflow_state(feature)
            state = flow.replace(
                state,
                integration_worktree=str(integration),
                integration_branch="integration/plan",
            )

            subject.save_workflow_state(state)

            args = subject.resume_command_args()
            self.assertIsNotNone(args)
            assert args is not None
            self.assertEqual(args[0], sys.executable)
            self.assertEqual(args[1], str(Path(flow.__file__).resolve()))
            self.assertIn("--resume", args)
            self.assertEqual(args[args.index("--plan") + 1], str(plan))
            self.assertEqual(args[args.index("--worktree") + 1], str(feature))
            self.assertEqual(args[args.index("--repo") + 1], str(repo))
            self.assertEqual(args[args.index("--base") + 1], "main")
            self.assertEqual(args[args.index("--branch") + 1], "feature/plan")
            self.assertEqual(args[args.index("--run-id") + 1], "plan-run")
            self.assertEqual(args[args.index("--model") + 1], "gpt-test")
            self.assertEqual(
                args[args.index("--integration-worktree") + 1], str(integration)
            )
            self.assertEqual(
                args[args.index("--integration-branch") + 1], "integration/plan"
            )

    def test_main_prints_resume_command_on_failure(self) -> None:
        class FakeFlow:
            def __init__(self, config, runner) -> None:
                pass

            def run(self) -> None:
                raise flow.FlowError("boom")

            def resume_command(self) -> str:
                return "python worktree-flow.py --resume --worktree repo-feature"

        with (
            tempfile.TemporaryDirectory() as temp,
            mock.patch.object(flow, "HarnessWorktreeFlow", FakeFlow),
        ):
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                result = flow.main(["--plan", str(Path(temp) / "plan.md")])

        self.assertEqual(result, 1)
        text = stderr.getvalue()
        self.assertIn("boom", text)
        self.assertIn("Resume command:", text)
        self.assertIn(
            "python worktree-flow.py --resume --worktree repo-feature", text
        )

    def test_local_git_worktree_and_squash_merge(self) -> None:
        if not shutil.which("git"):
            self.skipTest("git is not installed")
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
            (repo / "file.txt").write_text("base\n", encoding="utf-8")
            subprocess.run(["git", "add", "file.txt"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True, capture_output=True)

            feature = Path(temp) / "repo-feature"
            subprocess.run(["git", "worktree", "add", str(feature), "-b", "feature/test", "main"], cwd=repo, check=True, capture_output=True)
            (feature / "file.txt").write_text("feature\n", encoding="utf-8")
            subprocess.run(["git", "add", "file.txt"], cwd=feature, check=True)
            subprocess.run(["git", "commit", "-m", "feature"], cwd=feature, check=True, capture_output=True)

            integration = Path(temp) / "repo-integration"
            subprocess.run(["git", "worktree", "add", str(integration), "-b", "integration/test", "main"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "merge", "--squash", "feature/test"], cwd=integration, check=True, capture_output=True)
            (integration / ".codex" / "handoff").mkdir(parents=True)
            (integration / ".codex" / "handoff" / "implementation-summary.md").write_text("impl", encoding="utf-8")
            subject = flow.HarnessWorktreeFlow(
                self.config(repo, repo / "plan.md"), flow.CommandRunner()
            )
            subject.stage_integration_changes(integration)
            subprocess.run(["git", "commit", "-m", "Harness: test"], cwd=integration, check=True, capture_output=True)
            subprocess.run(["git", "switch", "main"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "merge", "--ff-only", "integration/test"], cwd=repo, check=True, capture_output=True)

            committed = subprocess.run(
                ["git", "ls-tree", "-r", "--name-only", "HEAD"],
                cwd=repo,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.splitlines()
            self.assertEqual((repo / "file.txt").read_text(encoding="utf-8"), "feature\n")
            self.assertIn("file.txt", committed)
            self.assertNotIn(".codex/handoff/implementation-summary.md", committed)

    def config(
        self,
        repo: Path,
        plan: Path,
        *,
        model: str | None = None,
        merge_mode: str = "squash",
    ):
        return flow.FlowConfig(
            repo=repo,
            plan=plan,
            base="main",
            model=model,
            harness="codex",
            harness_dir=Path(".codex"),
            merge_mode=merge_mode,
            keep_worktrees=False,
        )
    def workflow_state(self, feature: Path, *, merge_mode: str = "squash", plan_title: str = "Plan") -> flow.WorkflowState:
        return flow.WorkflowState(
            run_id="plan-run",
            slug="plan",
            base="main",
            plan_title=plan_title,
            feature_branch="feature/plan",
            feature_worktree=str(feature),
            merge_mode=merge_mode,
            plan_path=str(feature / "docs" / "plans" / "plan.md"),
            completed_stage="audit_complete",
        )



if __name__ == "__main__":
    unittest.main()
