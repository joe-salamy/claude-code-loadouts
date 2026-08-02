from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / ".omp" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from worktree_flow import cli, command_runner, git_workspace, harness, integration, models, paths, state, usage, workflow  # noqa: E402


class FakeRunner:
    def __init__(
        self,
        outputs: dict[tuple[str, ...], command_runner.CommandResult | str] | None = None,
        *,
        dry_run: bool = False,
    ) -> None:
        self.outputs = outputs or {}
        self.calls: list[tuple[tuple[str, ...], Path, bool, str | None]] = []
        self.dry_run = dry_run

    def run(
        self,
        args: list[str] | tuple[str, ...],
        cwd: Path,
        *,
        check: bool = True,
        capture: bool = True,
        input_text: str | None = None,
    ) -> command_runner.CommandResult:
        del capture
        key = tuple(str(arg) for arg in args)
        self.calls.append((key, Path(cwd), check, input_text))
        value = self.outputs.get(key, "")
        if isinstance(value, command_runner.CommandResult):
            return value
        return command_runner.CommandResult(
            key,
            Path(cwd),
            0,
            value,
            "",
            started_at="start",
            finished_at="finish",
            duration_ms=1,
        )


class FailingRunner(FakeRunner):
    def __init__(self, command_prefix: tuple[str, ...]) -> None:
        super().__init__()
        self.command_prefix = command_prefix

    def run(self, args, cwd, *, check=True, capture=True, input_text=None):
        key = tuple(str(arg) for arg in args)
        if key[: len(self.command_prefix)] == self.command_prefix:
            result = command_runner.CommandResult(key, Path(cwd), 1, "", "failed")
            if check:
                raise command_runner.CommandFailureError(result)
            return result
        return super().run(args, cwd, check=check, capture=capture, input_text=input_text)


class WorktreeFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.init_repo()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def init_repo(self) -> None:
        run_git(self.repo, "init", "-q")
        run_git(self.repo, "config", "user.email", "test@example.invalid")
        run_git(self.repo, "config", "user.name", "Worktree Test")
        run_git(self.repo, "switch", "-c", "main")
        (self.repo / "README.txt").write_text("base\n", encoding="utf-8")
        run_git(self.repo, "add", "README.txt")
        run_git(self.repo, "commit", "-qm", "base")

    def plan(self, title: str = "Approved Plan") -> Path:
        plan = self.repo / "docs" / "plan.md"
        plan.parent.mkdir(parents=True, exist_ok=True)
        plan.write_text(f"# {title}\n\nChange the fixture.\n", encoding="utf-8")
        run_git(self.repo, "add", "docs/plan.md")
        run_git(self.repo, "commit", "-qm", "plan")
        return plan

    def config(
        self,
        plan: Path,
        *,
        harness_name: str = "omp",
        merge_mode: str | None = "squash",
        resume: bool = False,
        worktree: Path | None = None,
        state_dir: Path | None = None,
        **kwargs: object,
    ) -> models.FlowConfig:
        return models.FlowConfig(
            repo=self.repo,
            plan=plan,
            base="main",
            harness=harness_name,
            harness_dir=Path(".harness"),
            state_dir=state_dir or self.root / "state",
            merge_mode=merge_mode,
            resume=resume,
            worktree=worktree,
            entrypoint_path=ROOT / ".omp" / "scripts" / "worktree-flow.py",
            **kwargs,
        )

    def runtime(self, config: models.FlowConfig, runner: object | None = None) -> workflow.HarnessWorktreeFlow:
        return workflow.HarnessWorktreeFlow(config, runner or command_runner.CommandRunner())

    def bind(self, flow: workflow.HarnessWorktreeFlow) -> None:
        raw_root = git_workspace.GitWorkspace.git_root(self.repo, command_runner.CommandRunner())
        flow._bind_runtime(raw_root)

    def make_fake_omp(self) -> Path:
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        executable = bin_dir / "omp"
        executable.write_text(
            """#!/usr/bin/env python3
import os
import subprocess
import sys
from pathlib import Path

if '--help' in sys.argv:
    print('fake omp help')
    raise SystemExit(0)
arg = next((item for item in reversed(sys.argv[1:]) if item.startswith('@')), None)
if arg is None:
    raise SystemExit('missing prompt')
prompt = Path(arg[1:]).read_text(encoding='utf-8')
handoff = Path.cwd() / '.harness' / 'handoff'
handoff.mkdir(parents=True, exist_ok=True)
if 'implement-worktree' in prompt:
    (Path.cwd() / 'implemented.txt').write_text('implemented\\n', encoding='utf-8')
    (handoff / 'implementation-summary.md').write_text('# Implementation\\n\\ncommitted\\n', encoding='utf-8')
    subprocess.run(['git', 'add', 'implemented.txt'], check=True)
    subprocess.run(['git', 'commit', '-qm', 'implementation'], check=True)
elif 'merge-conflict-resolver' in prompt:
    (handoff / 'conflict-resolution-summary.md').write_text('# Conflict Resolution\\n', encoding='utf-8')
elif 'audit-worktree' in prompt:
    (handoff / ('post-conflict-audit-summary.md' if 'post-conflict-audit-summary.md' in prompt else 'audit-summary.md')).write_text('# Audit\\n', encoding='utf-8')
print('fake harness output')
""",
            encoding="utf-8",
        )
        executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
        return bin_dir

    def with_path(self, directory: Path):
        return mock.patch.dict(os.environ, {"PATH": f"{directory}{os.pathsep}{os.environ.get('PATH', '')}"})

    def test_cleanup_refuses_unregistered_paths_and_never_falls_back_to_rmtree(self) -> None:
        plan = self.plan()
        flow = self.runtime(self.config(plan))
        self.bind(flow)
        sentinel = self.root / "sentinel"
        sentinel.mkdir()
        (sentinel / "secret.txt").write_text("keep\n", encoding="utf-8")
        branch = "feature/sentinel"
        run_git(self.repo, "branch", branch)
        with self.assertRaises(models.FlowError):
            flow._remove_or_adopt_worktree(sentinel, branch, allow_adopt=True)
        self.assertFalse(any(call[0][:3] == ("git", "worktree", "remove") for call in getattr(flow.runner, "calls", [])))

    def test_dry_run_full_flow_is_zero_mutation(self) -> None:
        plan = self.plan()
        state_dir = self.root / "state"
        before = snapshot_tree(self.root)
        args = [
            "--plan",
            str(plan),
            "--repo",
            str(self.repo),
            "--base",
            "main",
            "--harness",
            "omp",
            "--harness-dir",
            ".harness",
            "--state-dir",
            str(state_dir),
            "--dry-run",
        ]
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(cli.main(args, entrypoint_path=ROOT / ".omp" / "scripts" / "worktree-flow.py"), 0)
        output = stdout.getvalue()
        self.assertIn("implementation", output)
        self.assertIn("audit", output)
        self.assertIn("@default", output)
        self.assertIn("@slow", output)
        self.assertIn("fast-forward", output)
        self.assertIn("cleanup", output)
        self.assertEqual(before, snapshot_tree(self.root))

    def test_resume_rejects_corrupt_or_mismatched_state_before_side_effects(self) -> None:
        plan = self.plan()
        flow = self.runtime(self.config(plan))
        self.bind(flow)
        store = flow.state_store
        assert store is not None
        run_id = "20260802-120000-approved-plan"
        run_dir = store.reserve_run(run_id)
        state_path = run_dir / paths.WORKFLOW_STATE_FILENAME
        state_path.write_bytes(b"not utf-8: \xff")
        with self.assertRaises(models.FlowError):
            store.load(run_id)
        state_path.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
        with self.assertRaises(models.FlowError):
            store.load(run_id)

    def test_state_replace_failure_preserves_last_good_state(self) -> None:
        plan = self.plan()
        flow = self.runtime(self.config(plan))
        self.bind(flow)
        store = flow.state_store
        assert store is not None and flow.git is not None
        run_id = "20260802-120000-approved-plan"
        store.reserve_run(run_id)
        saved = make_state(flow, run_id, plan, flow.git.head(self.repo))
        store.save(saved)
        target = store.state_path(run_id)
        original = target.read_bytes()
        with mock.patch.object(paths.os, "replace", side_effect=OSError("injected replace failure")):
            with self.assertRaises(models.FlowError):
                store.save(models.WorkflowState(**{**saved.__dict__, "plan_title": "changed"}))
        self.assertEqual(target.read_bytes(), original)
        self.assertFalse(any(path.name.endswith(".tmp") for path in target.parent.iterdir()))

    def test_run_lock_rejects_concurrent_resume(self) -> None:
        plan = self.plan()
        flow = self.runtime(self.config(plan))
        self.bind(flow)
        store = flow.state_store
        assert store is not None
        run_id = "20260802-120000-approved-plan"
        store.reserve_run(run_id)
        with store.lock(run_id):
            with self.assertRaises(models.FlowError):
                with store.lock(run_id):
                    pass
        with store.lock(run_id):
            pass

    def test_saved_plan_reservation_is_claimed_once(self) -> None:
        plan = self.plan()
        run_id = "20260802-120000-approved-plan"
        reservation = self.repo / ".harness" / "worktree-flow" / run_id
        reservation.mkdir(parents=True)
        saved_plan = reservation / "plan.md"
        shutil.copyfile(plan, saved_plan)
        flow = self.runtime(self.config(saved_plan))
        flow.repo = self.repo
        flow._validate_saved_plan_reservation(saved_plan, run_id)
        (reservation / "unexpected.txt").write_text("bad\n", encoding="utf-8")
        with self.assertRaises(models.FlowError):
            flow._validate_saved_plan_reservation(saved_plan, run_id)
        (reservation / "unexpected.txt").unlink()
        (reservation / "linked.txt").symlink_to(self.root / "secret")
        with self.assertRaises(models.FlowError):
            flow._validate_saved_plan_reservation(saved_plan, run_id)

    def test_feature_allocation_interruptions_are_resumable_or_refused(self) -> None:
        plan = self.plan()
        flow = self.runtime(self.config(plan))
        self.bind(flow)
        assert flow.git is not None and flow.state_store is not None
        run_id = "20260802-120000-approved-plan"
        flow.state_store.reserve_run(run_id)
        names = models.Names("approved-plan", "feature/approved-plan", self.root / "repo-approved-plan", run_id)
        saved = make_state(flow, run_id, plan, flow.git.head(self.repo), names=names)
        flow.state_store.save(saved)
        created = flow._allocate_feature(saved, names)
        self.assertEqual(created.stage, models.WorkflowStage.FEATURE_WORKTREE_CREATED)
        self.assertEqual(flow.git.current_branch(names.feature_worktree), names.feature_branch)
        mismatch_names = models.Names("approved-plan", "feature/other", names.feature_worktree, run_id)
        with self.assertRaises(models.FlowError):
            flow._allocate_feature(saved, mismatch_names)

    def test_harness_dir_must_be_confined_relative_path(self) -> None:
        invalid = ["", ".", "..", "/tmp/x", r"C:\\x", r"\\\\server\\share", "a//b", "a/../b", "CON", "a:stream", "a\x00b"]
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(models.FlowError):
                    paths.validate_harness_dir(value)
        self.assertEqual(paths.validate_harness_dir(".omp"), Path(".omp"))
        self.assertEqual(paths.validate_harness_dir("nested/harness"), Path("nested/harness"))

    def test_git_pathspecs_treat_harness_paths_literally(self) -> None:
        literal = self.repo / "art*" / "handoff" / "tracked.txt"
        sibling = self.repo / "art-other" / "handoff" / "other.txt"
        literal.parent.mkdir(parents=True)
        sibling.parent.mkdir(parents=True)
        literal.write_text("literal\n", encoding="utf-8")
        sibling.write_text("sibling\n", encoding="utf-8")
        run_git(self.repo, "add", "-A")
        run_git(self.repo, "commit", "-m", "pathspec fixture")
        workspace = git_workspace.GitWorkspace(
            self.repo,
            command_runner.CommandRunner(),
            harness_dir=Path("art*"),
        )
        self.assertEqual(workspace.tracked_handoff_paths(), ["art*/handoff/tracked.txt"])

    def test_resume_accepts_only_exact_recorded_integration_fingerprint(self) -> None:
        plan = self.plan()
        integration_dir = self.root / "integration"
        run_git(self.repo, "worktree", "add", "-b", "integration/approved-plan-20260802-120000", str(integration_dir), "main")
        workspace = git_workspace.GitWorkspace(self.repo, command_runner.CommandRunner(), harness_dir=Path(".harness"))
        fingerprint = workspace.fingerprint(integration_dir)
        flow = self.runtime(self.config(plan))
        flow.git = workspace
        state_obj = object.__new__(models.WorkflowState)
        del state_obj
        state_record = type("State", (), {"integration_worktree_fingerprint": fingerprint})()
        real_state = state_record
        with mock.patch.object(workspace, "fingerprint", return_value=fingerprint):
            flow._verify_integration_checkpoint(real_state, integration_dir)
        (integration_dir / "dirty.txt").write_text("changed\n", encoding="utf-8")
        changed = workspace.fingerprint(integration_dir)
        self.assertNotEqual(changed, fingerprint)
        with self.assertRaises(models.FlowError):
            flow._verify_integration_checkpoint(type("State", (), {"integration_worktree_fingerprint": fingerprint})(), integration_dir)
        run_git(self.repo, "worktree", "remove", "--force", str(integration_dir))
        run_git(self.repo, "branch", "-D", "integration/approved-plan-20260802-120000")

    def test_precreated_audit_summary_cannot_suppress_audit(self) -> None:
        plan = self.plan()
        bin_dir = self.make_fake_omp()
        with self.with_path(bin_dir):
            config = self.config(plan, merge_mode="stop", keep_worktrees=True)
            flow = self.runtime(config)
            flow.run()
        state_file = next((self.root / "state").rglob(paths.WORKFLOW_STATE_FILENAME))
        saved = json.loads(state_file.read_text(encoding="utf-8"))
        self.assertEqual(saved["stage"], models.WorkflowStage.STOPPED_BEFORE_MERGE.value)
        feature = Path(saved["feature_worktree"])
        summary = feature / ".harness" / "handoff" / "audit-summary.md"
        summary.write_text("# stale\n", encoding="utf-8")
        with self.with_path(bin_dir):
            resumed = self.runtime(self.config(plan, merge_mode="squash", resume=True, worktree=feature, keep_worktrees=True))
            resumed.resume()
        self.assertTrue(summary.exists())
        self.assertIn("# Audit", summary.read_text(encoding="utf-8"))

    def test_failed_audit_summary_is_retried(self) -> None:
        plan = self.plan()
        bin_dir = self.make_fake_omp()
        with self.with_path(bin_dir):
            flow = self.runtime(self.config(plan, merge_mode="stop"))
            flow.run()
        state_file = next((self.root / "state").rglob(paths.WORKFLOW_STATE_FILENAME))
        self.assertEqual(json.loads(state_file.read_text(encoding="utf-8"))["stage"], "stopped_before_merge")

    def test_audit_receipt_head_change_reaudits_and_plan_digest_change_refuses(self) -> None:
        plan = self.plan()
        bin_dir = self.make_fake_omp()
        with self.with_path(bin_dir):
            flow = self.runtime(self.config(plan, merge_mode="stop"))
            flow.run()
        state_file = next((self.root / "state").rglob(paths.WORKFLOW_STATE_FILENAME))
        state_data = json.loads(state_file.read_text(encoding="utf-8"))
        feature = Path(state_data["feature_worktree"])
        run_git(feature, "commit", "--allow-empty", "-qm", "post-audit")
        state_data["stage"] = "audit_complete"
        state_data["audit_head"] = state_data["feature_base_commit"]
        state_file.write_text(json.dumps(state_data), encoding="utf-8")
        with self.with_path(bin_dir):
            resumed = self.runtime(self.config(plan, merge_mode=None, resume=True, worktree=feature))
            resumed.resume()
        plan.write_text("# Changed Plan\n", encoding="utf-8")
        with self.assertRaises(models.FlowError):
            resumed.resume()

    def test_completed_phase_dirt_is_refused(self) -> None:
        plan = self.plan()
        workspace = git_workspace.GitWorkspace(self.repo, command_runner.CommandRunner(), harness_dir=Path(".harness"))
        (self.repo / "README.txt").write_text("dirty\n", encoding="utf-8")
        with self.assertRaises(models.FlowError):
            workspace.require_primary_ready("main")
        (self.repo / "README.txt").write_text("base\n", encoding="utf-8")
        feature = self.root / "feature"
        run_git(self.repo, "worktree", "add", "-b", "feature/dirt", str(feature), "main")
        (feature / "dirty.txt").write_text("dirty\n", encoding="utf-8")
        with self.assertRaises(models.FlowError):
            workspace.require_clean_except_artifacts(feature, phase="Completed audit")
        run_git(self.repo, "worktree", "remove", "--force", str(feature))
        run_git(self.repo, "branch", "-D", "feature/dirt")

    def test_resume_dispatches_base_fast_forwarded_through_complete(self) -> None:
        plan = self.plan()
        bin_dir = self.make_fake_omp()
        with self.with_path(bin_dir):
            flow = self.runtime(self.config(plan, merge_mode="squash"))
            flow.run()
            state_file = next((self.root / "state").rglob(paths.WORKFLOW_STATE_FILENAME))
            data = json.loads(state_file.read_text(encoding="utf-8"))
            resumed = self.runtime(self.config(plan, resume=True, merge_mode="squash", worktree=Path(data["feature_worktree"])))
            resumed.resume()
        self.assertEqual(json.loads(state_file.read_text(encoding="utf-8"))["stage"], "complete")

    def test_base_advance_rebuilds_only_validated_integration(self) -> None:
        plan = self.plan()
        flow = self.runtime(self.config(plan))
        self.bind(flow)
        assert flow.git is not None
        integration_dir = self.root / "repo-integrate-approved-plan-20260802-120000"
        branch = "integration/approved-plan-20260802-120000"
        run_git(self.repo, "worktree", "add", "-b", branch, str(integration_dir), "main")
        run_git(self.repo, "commit", "--allow-empty", "-qm", "Harness: Approved Plan")
        run_git(self.repo, "switch", "main")
        (self.repo / "README.txt").write_text("advanced\n", encoding="utf-8")
        run_git(self.repo, "add", "README.txt")
        run_git(self.repo, "commit", "-qm", "base advance")
        self.assertNotEqual(flow.git.branch_tip("main"), flow.git.head(integration_dir))
        run_git(self.repo, "worktree", "remove", "--force", str(integration_dir))
        run_git(self.repo, "branch", "-D", branch)

    def test_stopped_run_requires_explicit_merge_mode_to_continue(self) -> None:
        plan = self.plan()
        bin_dir = self.make_fake_omp()
        with self.with_path(bin_dir):
            flow = self.runtime(self.config(plan, merge_mode="stop"))
            flow.run()
            state_file = next((self.root / "state").rglob(paths.WORKFLOW_STATE_FILENAME))
            stopped = state_file.read_bytes()
            data = json.loads(stopped)
            self.assertEqual(data["stage"], "stopped_before_merge")
            self.assertIsInstance(data["archive_commit"], str)
            self.assertEqual(
                run_git(self.repo, "show", "-s", "--format=%s", data["archive_commit"]).strip(),
                "Harness: stop Approved Plan",
            )
            feature = Path(data["feature_worktree"])
            no_mode = self.runtime(self.config(plan, merge_mode=None, resume=True, worktree=feature))
            no_mode.resume()
            self.assertEqual(stopped, state_file.read_bytes())
            continue_flow = self.runtime(self.config(plan, merge_mode="squash", resume=True, worktree=feature))
            continue_flow.resume()
        self.assertEqual(json.loads(state_file.read_text(encoding="utf-8"))["stage"], "complete")

    def test_base_must_be_local_branch(self) -> None:
        workspace = git_workspace.GitWorkspace(self.repo, command_runner.CommandRunner(), harness_dir=Path(".harness"))
        for name in ("HEAD", "origin/main", "deadbeef", "-bad", "missing"):
            with self.subTest(name=name):
                with self.assertRaises(models.FlowError):
                    workspace.require_local_branch(name)
        self.assertEqual(workspace.require_local_branch("main"), "main")

    def test_oversized_state_and_artifacts_fail_before_read_or_copy(self) -> None:
        oversized = self.root / "oversized.bin"
        with oversized.open("wb") as handle:
            handle.truncate(paths.MAX_ARTIFACT_BYTES + 1)
        with self.assertRaises(models.FlowError):
            paths.sha256_file(oversized)
        with self.assertRaises(models.FlowError):
            paths.safe_copy(oversized, self.root / "copy.bin")
        self.assertFalse((self.root / "copy.bin").exists())

    def test_plan_and_handoff_symlinks_fail_closed(self) -> None:
        secret = self.root / "secret.txt"
        secret.write_text("secret\n", encoding="utf-8")
        link = self.root / "plan-link.md"
        link.symlink_to(secret)
        with self.assertRaises(models.FlowError):
            paths.read_text_bounded(link)
        broken = self.root / "broken-link"
        broken.symlink_to(self.root / "missing-target")
        with self.assertRaises(models.FlowError):
            paths.canonical_path(broken, must_exist=False)
        with self.assertRaises(models.FlowError):
            paths.require_confined(self.root, broken)
        destination = self.root / "destination.txt"
        destination.symlink_to(secret)
        with self.assertRaises(models.FlowError):
            paths.atomic_write_text(destination, "overwrite\n")
        self.assertEqual(secret.read_text(encoding="utf-8"), "secret\n")

    def test_harness_logs_never_persist_raw_output(self) -> None:
        plan = self.plan()
        worktree = self.root / "worktree"
        worktree.mkdir()
        config = self.config(plan, harness_name="codex")
        secret = "SECRET_MARKER"
        result = command_runner.CommandResult(("codex", "exec"), worktree, 9, secret, secret, "start", "finish", 2)
        runner = FakeRunner({("codex", "exec", "--cd", str(worktree), "--sandbox", "workspace-write", "-"): result})
        events: list[dict[str, object]] = []
        adapter = harness.HarnessAdapter(
            config,
            runner,
            logger=lambda _event, fields: events.append(dict(fields)),
            usage=usage.UsageCollector(harness="codex", harness_dir=Path(".harness")),
        )
        with self.assertRaises(models.FlowError) as raised:
            adapter.execute(worktree, "Prompt", phase="implementation")
        self.assertNotIn(secret, str(raised.exception))
        self.assertTrue(events)
        self.assertNotIn(secret, json.dumps(events))
        self.assertNotIn(secret, (worktree / ".harness" / "handoff" / "usage-events.jsonl").read_text(encoding="utf-8"))
        self.assertTrue((worktree / ".harness" / "handoff" / "implementation-diagnostics.log").exists())

    def test_phase_models_and_harness_adapters(self) -> None:
        plan = self.plan()
        cwd = self.root / "cwd"
        cwd.mkdir()
        prompt = cwd / "prompt.md"
        prompt.write_text("prompt\n", encoding="utf-8")
        omp_config = self.config(plan, harness_name="omp")
        omp = harness.HarnessAdapter(omp_config, FakeRunner())
        self.assertIn("@default", omp.omp_args(prompt, "implementation"))
        self.assertIn("@slow", omp.omp_args(prompt, "audit"))
        codex_config = self.config(plan, harness_name="codex", model="gpt-test")
        codex = harness.HarnessAdapter(codex_config, FakeRunner())
        self.assertEqual(codex.codex_args(cwd, "implementation")[-1], "-")
        self.assertIn("gpt-test", codex.codex_args(cwd, "implementation"))
        opencode_config = self.config(plan, harness_name="opencode", model="gpt-test")
        opencode = harness.HarnessAdapter(opencode_config, FakeRunner())
        args = opencode.opencode_args(cwd, prompt, "audit")
        self.assertEqual(args[:2], ["opencode", "run"])
        self.assertIn("--dir", args)
        self.assertIn("--file", args)
        with self.assertRaises(models.FlowError):
            models.HarnessKind.from_executable("claude")
        self.assertEqual(harness.phase_model(models.HarnessKind.OMP, "audit", implementation_model=None, review_model="review", model="global"), "review")

    def test_completed_run_id_cannot_start_again_and_archive_is_exact_manifest(self) -> None:
        plan = self.plan()
        bin_dir = self.make_fake_omp()
        with self.with_path(bin_dir):
            flow = self.runtime(self.config(plan))
            flow.run()
            second = self.runtime(self.config(plan))
            with self.assertRaises(models.FlowError):
                second.run()
        manager = integration.IntegrationManager(
            git_workspace.GitWorkspace(self.repo, command_runner.CommandRunner(), harness_dir=Path(".harness")),
            harness_dir=Path(".harness"),
        )
        archive = self.root / "archive"
        archive.mkdir()
        (archive / "unknown.txt").write_text("bad\n", encoding="utf-8")
        with self.assertRaises(models.FlowError):
            manager.prepare_archive(archive)

    def test_conflict_context_survives_resolution_retry_cleanup(self) -> None:
        plan = self.plan()
        manager = integration.IntegrationManager(
            git_workspace.GitWorkspace(self.repo, command_runner.CommandRunner(), harness_dir=Path(".harness")),
            harness_dir=Path(".harness"),
        )
        flow = self.runtime(self.config(plan))
        flow.integration = manager
        worktree = self.root / "integration"
        context = worktree / ".harness" / "handoff" / "merge-conflict-context.md"
        context.parent.mkdir(parents=True)
        context.write_text("conflict details\n", encoding="utf-8")
        for name in ("post_conflict_audit-prompt.md", "post_conflict_audit-diagnostics.log"):
            (context.parent / name).write_text("stale\n", encoding="utf-8")
        flow._remove_phase_outputs(worktree, "conflict_resolution")
        self.assertEqual(context.read_text(encoding="utf-8"), "conflict details\n")
        self.assertFalse((context.parent / "post_conflict_audit-prompt.md").exists())
        self.assertFalse((context.parent / "post_conflict_audit-diagnostics.log").exists())
    def test_post_conflict_audit_retry_removes_stale_summary(self) -> None:
        manager = integration.IntegrationManager(
            git_workspace.GitWorkspace(self.repo, command_runner.CommandRunner(), harness_dir=Path(".harness")),
            harness_dir=Path(".harness"),
        )
        worktree = self.root / "integration"
        handoff = worktree / ".harness" / "handoff"
        handoff.mkdir(parents=True)
        for name in (
            "post-conflict-audit-summary.md",
            "post_conflict_audit-prompt.md",
            "post_conflict_audit-diagnostics.log",
        ):
            (handoff / name).write_text("stale\n", encoding="utf-8")
        manager.remove_phase_outputs(worktree, phase="post_conflict_audit")
        self.assertEqual(list(handoff.iterdir()), [])
    def test_archive_handoff_removes_stale_allowlisted_outputs(self) -> None:
        plan = self.plan()
        manager = integration.IntegrationManager(
            git_workspace.GitWorkspace(self.repo, command_runner.CommandRunner(), harness_dir=Path(".harness")),
            harness_dir=Path(".harness"),
        )
        source = self.root / "source"
        source_handoff = source / ".harness" / "handoff"
        source_handoff.mkdir(parents=True)
        (source_handoff / "implementation-summary.md").write_text("# Implementation\n", encoding="utf-8")
        archive = self.root / "archive"
        archive.mkdir()
        (archive / "audit-summary.md").write_text("stale\n", encoding="utf-8")
        manager.archive_handoff(source, archive, plan)
        self.assertFalse((archive / "audit-summary.md").exists())
        self.assertTrue((archive / "implementation-summary.md").exists())
        self.assertEqual((archive / "plan.md").read_bytes(), plan.read_bytes())

    def test_preview_uses_executable_basename_for_adapter_selection(self) -> None:
        plan = self.plan()
        flow = self.runtime(self.config(plan, harness_name="/usr/bin/opencode"))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            flow.preview()
        rendered = output.getvalue()
        self.assertIn("/usr/bin/opencode run", rendered)
        self.assertNotIn("--no-session", rendered)


    def test_full_local_git_smoke(self) -> None:
        plan = self.plan("Local Git Smoke")
        bin_dir = self.make_fake_omp()
        with self.with_path(bin_dir):
            flow = self.runtime(self.config(plan, merge_mode="squash"))
            flow.run()
        self.assertEqual(run_git(self.repo, "branch", "--show-current"), "main")
        self.assertTrue((self.repo / "implemented.txt").exists())
        self.assertTrue(any(path.name == paths.WORKFLOW_STATE_FILENAME for path in (self.root / "state").rglob("*")))


class CommandAndStateTests(unittest.TestCase):
    def test_positive_timeout_and_parser(self) -> None:
        self.assertEqual(cli.positive_seconds("1.5"), 1.5)
        with self.assertRaises(cli.argparse.ArgumentTypeError):
            cli.positive_seconds("0")

    def test_command_failure_format_excludes_output(self) -> None:
        result = command_runner.CommandResult(("tool", "--arg"), Path("/tmp/worktree"), 2, "SECRET", "SECRET")
        text = command_runner.format_command_failure(result)
        self.assertNotIn("SECRET", text)
        self.assertIn("exit code 2", text)

    def test_transition_graph_rejects_skips(self) -> None:
        with self.assertRaises(models.FlowError):
            state.require_transition(models.WorkflowStage.FEATURE_ALLOCATED, models.WorkflowStage.COMPLETE)
        self.assertTrue(state.allowed_transition(models.WorkflowStage.FEATURE_ALLOCATED, models.WorkflowStage.FEATURE_WORKTREE_CREATED))

    def test_state_reader_rejects_duplicate_keys_and_nonstandard_numbers(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            git_dir = repo / ".git"
            git_dir.mkdir()
            store = state.WorkflowStateStore(root / "state", repo_root=repo, git_common_dir=git_dir)
            payload = {
                "schema_version": 2,
                "run_id": "20260802-120000-approved-plan",
                "slug": "approved-plan",
                "repo_root": str(repo),
                "git_common_dir": str(git_dir),
                "base_branch": "main",
                "feature_base_commit": "a" * 40,
                "plan_title": "Approved Plan",
                "plan_path": str(root / "plan.md"),
                "plan_sha256": "b" * 64,
                "feature_branch": "feature/approved-plan",
                "feature_worktree": str(root / "feature"),
                "harness": "omp",
                "harness_kind": "omp",
                "harness_dir": ".harness",
                "implementation_model": "@default",
                "review_model": "@slow",
                "merge_mode": "squash",
                "keep_worktrees": False,
                "command_timeout_seconds": None,
                "stage": "feature_allocated",
                "implementation_head": None,
                "audit_start_head": None,
                "audit_head": None,
                "integration_branch": None,
                "integration_worktree": None,
                "integration_base_commit": None,
                "integration_feature_commit": None,
                "integration_worktree_fingerprint": None,
                "integration_commit": None,
                "archive_dir": None,
                "archive_commit": None,
                "final_state_commit": None,
            }
            candidate = root / "archive" / "workflow-state.json"
            candidate.parent.mkdir()
            candidate.write_text(json.dumps(payload)[:-1] + ',"run_id":"duplicate"}', encoding="utf-8")
            with self.assertRaises(models.FlowError):
                store.read_candidate_state(candidate)
            candidate.write_text(json.dumps(payload).replace('"command_timeout_seconds": null', '"command_timeout_seconds": NaN'), encoding="utf-8")
            with self.assertRaises(models.FlowError):
                store.read_candidate_state(candidate)
            candidate.unlink()
            outside = root / "outside.json"
            outside.write_text("{}", encoding="utf-8")
            candidate.symlink_to(outside)
            with self.assertRaises(models.FlowError):
                store.read_candidate_state(candidate)

def run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {result.stderr}")
    return result.stdout.strip()


def snapshot_tree(root: Path) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    for path in root.rglob("*"):
        if path.is_file() and "__pycache__" not in path.parts:
            result[str(path.relative_to(root))] = path.read_bytes()
    return result


def make_state(
    flow: workflow.HarnessWorktreeFlow,
    run_id: str,
    plan: Path,
    base_commit: str,
    *,
    names: models.Names | None = None,
    stage: models.WorkflowStage = models.WorkflowStage.FEATURE_ALLOCATED,
) -> models.WorkflowState:
    assert flow.git is not None
    selected = names or models.Names("approved-plan", "feature/approved-plan", flow.repo.parent / f"{flow.repo.name}-approved-plan", run_id)
    return models.WorkflowState(
        schema_version=2,
        run_id=run_id,
        slug=selected.slug,
        repo_root=str(flow.repo),
        git_common_dir=str(flow.git.git_common_dir(flow.repo)),
        base_branch="main",
        feature_base_commit=base_commit,
        plan_title="Approved Plan",
        plan_path=str(plan.resolve()),
        plan_sha256=paths.sha256_file(plan),
        feature_branch=selected.feature_branch,
        feature_worktree=str(selected.feature_worktree.resolve()),
        harness="omp",
        harness_kind="omp",
        harness_dir=".harness",
        implementation_model="@default",
        review_model="@slow",
        merge_mode="squash",
        keep_worktrees=False,
        command_timeout_seconds=None,
        stage=stage,
    )


if __name__ == "__main__":
    unittest.main()
