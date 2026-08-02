from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "harness-init.ps1"
UPDATE_SCRIPT = ROOT / "update-loadout-repos.ps1"


def copy_scripts_to_temp_root(root: Path) -> tuple[Path, Path]:
    harness_init = root / "harness-init.ps1"
    update_loadout_repos = root / "update-loadout-repos.ps1"
    harness_init.write_text(SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    update_loadout_repos.write_text(UPDATE_SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    return harness_init, update_loadout_repos



class HarnessInitTests(unittest.TestCase):
    def setUp(self) -> None:
        if not shutil.which("pwsh"):
            self.skipTest("pwsh is not installed")

    def run_init(self, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["pwsh", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT), *args],
            cwd=cwd or ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    def make_fake_omp(
        self,
        bin_dir: Path,
        record_path: Path,
        *,
        stdout: str = "completed init\n",
        stderr: str = "",
        exit_code: int = 0,
    ) -> None:
        bin_dir.mkdir(parents=True, exist_ok=True)
        fake_omp = bin_dir / "fake_omp.py"
        fake_omp.write_text(
            "\n".join(
                [
                    "import json",
                    "import os",
                    "import sys",
                    "from pathlib import Path",
                    "",
                    f"record_path = Path({str(record_path)!r})",
                    f"stdout = {stdout!r}",
                    f"stderr = {stderr!r}",
                    f"exit_code = {exit_code!r}",
                    "prompt_arg = next((arg for arg in sys.argv[1:] if arg.startswith('@')), None)",
                    "if prompt_arg is None:",
                    "    raise SystemExit('missing @prompt argument')",
                    "prompt = Path(prompt_arg[1:]).read_text(encoding='utf-8')",
                    "record_path.write_text(",
                    "    json.dumps({'argv': sys.argv[1:], 'cwd': os.getcwd(), 'prompt': prompt}),",
                    "    encoding='utf-8',",
                    ")",
                    "sys.stdout.write(stdout)",
                    "sys.stderr.write(stderr)",
                    "raise SystemExit(exit_code)",
                ]
            ),
            encoding="utf-8",
        )
        if os.name == "nt":
            (bin_dir / "omp.cmd").write_text(
                "\n".join(["@echo off", f'"{sys.executable}" "%~dp0fake_omp.py" %*']),
                encoding="utf-8",
            )
        else:
            omp = bin_dir / "omp"
            omp.write_text(
                f'#!/bin/sh\nexec "{sys.executable}" "$(dirname "$0")/fake_omp.py" "$@"\n',
                encoding="utf-8",
            )
            omp.chmod(0o755)

    def test_harness_flag_is_required(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "target"
            target.mkdir()
            result = self.run_init("-Loadout", "worktrees", "-Target", str(target))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("-Harness is required", result.stdout)

    def test_harness_template_directory_maps_to_selected_harness(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            loadout = root / "loadouts" / "custom"
            target = root / "target"
            (loadout / ".harness" / "skills" / "demo").mkdir(parents=True)
            target.mkdir()
            (loadout / "AGENTS.md").write_text("# Instructions\n", encoding="utf-8")
            (loadout / ".harness" / "settings.txt").write_text("setting\n", encoding="utf-8")
            (loadout / ".harness" / "skills" / "demo" / "SKILL.md").write_text("# Demo\n", encoding="utf-8")

            script, _ = copy_scripts_to_temp_root(root)
            result = subprocess.run(
                ["pwsh", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-Loadout", "custom", "-Target", str(target), "-Harness", "codex"],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue((target / "AGENTS.md").exists())
            self.assertTrue((target / ".codex" / "settings.txt").exists())
            self.assertTrue((target / ".codex" / "skills" / "demo" / "SKILL.md").exists())
            self.assertFalse((target / ".harness").exists())

    def test_installed_loadout_contains_package_and_wrapper_runs_help(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            loadout = root / "loadouts" / "custom"
            target = root / "target"
            loadout.mkdir(parents=True)
            shutil.copytree(ROOT / "loadouts" / "worktrees" / ".harness", loadout / ".harness")
            target.mkdir()
            script, _ = copy_scripts_to_temp_root(root)
            result = subprocess.run(
                [
                    "pwsh",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script),
                    "-Loadout",
                    "custom",
                    "-Target",
                    str(target),
                    "-Harness",
                    "codex",
                ],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            wrapper = target / ".codex" / "scripts" / "worktree-flow.py"
            self.assertTrue(wrapper.is_file())
            self.assertTrue((target / ".codex" / "scripts" / "worktree_flow" / "cli.py").is_file())
            help_result = subprocess.run(
                [sys.executable, str(wrapper), "--help"],
                cwd=target,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(help_result.returncode, 0, help_result.stderr)
            self.assertIn("--state-dir", help_result.stdout)

    def test_generated_python_cache_files_are_not_copied(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            loadout = root / "loadouts" / "custom"
            target = root / "target"
            (loadout / ".harness" / "scripts" / "__pycache__").mkdir(parents=True)
            (loadout / ".harness" / "skills" / "demo" / "__pycache__").mkdir(parents=True)
            target.mkdir()
            (loadout / "AGENTS.md").write_text("# Instructions\n", encoding="utf-8")
            (loadout / "root.pyc").write_bytes(b"cache")
            (loadout / ".harness" / "scripts" / "tool.py").write_text("print('ok')\n", encoding="utf-8")
            (loadout / ".harness" / "scripts" / "tool.pyc").write_bytes(b"cache")
            (loadout / ".harness" / "scripts" / "__pycache__" / "tool.cpython-313.pyc").write_bytes(b"cache")
            (loadout / ".harness" / "skills" / "demo" / "SKILL.md").write_text("# Demo\n", encoding="utf-8")
            (loadout / ".harness" / "skills" / "demo" / "__pycache__" / "skill.cpython-313.pyc").write_bytes(b"cache")

            script, _ = copy_scripts_to_temp_root(root)
            result = subprocess.run(
                ["pwsh", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-Loadout", "custom", "-Target", str(target), "-Harness", "codex"],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue((target / ".codex" / "scripts" / "tool.py").exists())
            self.assertTrue((target / ".codex" / "skills" / "demo" / "SKILL.md").exists())
            self.assertFalse((target / "root.pyc").exists())
            self.assertFalse((target / ".codex" / "scripts" / "tool.pyc").exists())
            self.assertFalse((target / ".codex" / "scripts" / "__pycache__").exists())
            self.assertFalse((target / ".codex" / "skills" / "demo" / "__pycache__").exists())

    def test_records_and_upserts_repo_per_loadout(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            loadout = root / "loadouts" / "custom"
            target = root / "target"
            loadout.mkdir(parents=True)
            target.mkdir()
            (loadout / "AGENTS.md").write_text("# Instructions\n", encoding="utf-8")
            script, _ = copy_scripts_to_temp_root(root)

            command = ["pwsh", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-Loadout", "custom", "-Target", str(target), "-Harness", "codex"]
            result = subprocess.run(command, cwd=root, capture_output=True, text=True, check=False)

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            usage_path = root / "applied-repos.json"
            registry = json.loads(usage_path.read_text(encoding="utf-8"))
            data = registry["loadouts"]["custom"]
            self.assertEqual(registry["version"], 1)
            self.assertEqual(data["loadout"], "custom")
            self.assertEqual(len(data["repos"]), 1)
            self.assertEqual(data["repos"][0]["path"], str(target.resolve()))
            self.assertEqual(data["repos"][0]["harness"], "codex")
            self.assertTrue(data["repos"][0]["lastAppliedAt"])

            result = subprocess.run(command, cwd=root, capture_output=True, text=True, check=False)

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            data = json.loads(usage_path.read_text(encoding="utf-8"))["loadouts"]["custom"]
            self.assertEqual(len(data["repos"]), 1)
            self.assertEqual(data["repos"][0]["path"], str(target.resolve()))
            self.assertEqual(data["repos"][0]["harness"], "codex")

    def test_root_usage_registry_is_not_copied_to_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            loadout = root / "loadouts" / "custom"
            target = root / "target"
            loadout.mkdir(parents=True)
            target.mkdir()
            (loadout / "AGENTS.md").write_text("# Instructions\n", encoding="utf-8")
            (root / "applied-repos.json").write_text(
                json.dumps({"version": 1, "loadouts": {"custom": {"loadout": "custom", "repos": []}}}),
                encoding="utf-8",
            )
            script, _ = copy_scripts_to_temp_root(root)

            result = subprocess.run(
                ["pwsh", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-Loadout", "custom", "-Target", str(target), "-Harness", "codex"],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse((target / "applied-repos.json").exists())
            self.assertFalse((target / ".harness-loadout").exists())

    def test_force_overwrites_existing_file_without_stdin(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            loadout = root / "loadouts" / "custom"
            target = root / "target"
            (loadout / ".harness").mkdir(parents=True)
            (target / ".codex").mkdir(parents=True)
            (loadout / ".harness" / "settings.txt").write_text("new", encoding="utf-8")
            (target / ".codex" / "settings.txt").write_text("old", encoding="utf-8")
            (loadout / ".harness" / "skills" / "demo").mkdir(parents=True)
            (target / ".codex" / "skills" / "demo").mkdir(parents=True)
            (loadout / ".harness" / "skills" / "demo" / "SKILL.md").write_text("new skill", encoding="utf-8")
            (target / ".codex" / "skills" / "demo" / "SKILL.md").write_text("old skill", encoding="utf-8")
            script, _ = copy_scripts_to_temp_root(root)

            result = subprocess.run(
                ["pwsh", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-Loadout", "custom", "-Target", str(target), "-Harness", "codex", "-Force"],
                cwd=root,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                check=False,
                timeout=20,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual((target / ".codex" / "settings.txt").read_text(encoding="utf-8"), "new")
            self.assertEqual((target / ".codex" / "skills" / "demo" / "SKILL.md").read_text(encoding="utf-8"), "new skill")
            self.assertIn("[OVERWROTE] Skill 'demo'", result.stdout)
            self.assertNotIn("[EXISTS]   Skill 'demo'", result.stdout)

    def test_headless_init_prompt_invokes_omp_with_augmented_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            script, _ = copy_scripts_to_temp_root(root)
            prompt_dir = root / "init-prompts"
            prompt_dir.mkdir()
            (prompt_dir / "demo.md").write_text("# Demo Prompt\n\nOriginal body.", encoding="utf-8")
            target = root / "target"
            target.mkdir()
            fake_bin = root / "fake-bin"
            record_path = root / "omp-record.json"
            self.make_fake_omp(fake_bin, record_path)
            env = os.environ.copy()
            env["PATH"] = str(fake_bin) + os.pathsep + env.get("PATH", "")

            result = subprocess.run(
                ["pwsh", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-Target", str(target), "-InitPrompt", "demo", "-Headless"],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            record = json.loads(record_path.read_text(encoding="utf-8"))
            actual_args = list(record["argv"])
            actual_args[-1] = actual_args[-1].replace("\\", "/")
            expected_prompt_arg = f"@{target / '.omp' / 'init' / 'demo-headless-prompt.md'}".replace("\\", "/")
            self.assertEqual(
                actual_args,
                ["-p", "--no-session", "--auto-approve", "--approval-mode", "yolo", expected_prompt_arg],
            )
            self.assertEqual(Path(record["cwd"]).resolve(), target.resolve())
            self.assertEqual((target / ".omp" / "init" / "demo-headless-output.md").read_text(encoding="utf-8"), "completed init\n")
            self.assertFalse((target / ".omp" / "init" / "demo-headless-prompt.md").exists())
            expected_report_rule = (
                "Before your final response, create `.omp/init/reports/` in this repository if needed "
                "and write a timestamped Markdown report there named `yyyyMMdd-HHmmss-init-report.md`."
            )
            self.assertIn("Original body.", record["prompt"])
            self.assertIn("The repository may already satisfy some or all items", record["prompt"])
            self.assertIn("end-state checklist", record["prompt"])
            self.assertIn(expected_report_rule, record["prompt"])
            self.assertNotIn("create .omp/init/reports/", record["prompt"])
            self.assertNotIn("named yyyyMMdd-HHmmss-init-report.md", record["prompt"])
            self.assertIn("Headless init prompt 'demo' completed.", result.stdout)

    def test_failed_headless_init_preserves_prompt_and_writes_captured_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            script, _ = copy_scripts_to_temp_root(root)
            prompt_dir = root / "init-prompts"
            prompt_dir.mkdir()
            (prompt_dir / "demo.md").write_text("# Demo Prompt\n\nOriginal body.", encoding="utf-8")
            target = root / "target"
            target.mkdir()
            fake_bin = root / "fake-bin"
            record_path = root / "omp-record.json"
            self.make_fake_omp(
                fake_bin,
                record_path,
                stdout="partial init output\n",
                stderr="diagnostic failure\n",
                exit_code=17,
            )
            env = os.environ.copy()
            env["PATH"] = str(fake_bin) + os.pathsep + env.get("PATH", "")

            result = subprocess.run(
                ["pwsh", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-Target", str(target), "-InitPrompt", "demo", "-Headless"],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            init_dir = target / ".omp" / "init"
            prompt_file = init_dir / "demo-headless-prompt.md"
            self.assertEqual(result.returncode, 17, result.stdout + result.stderr)
            self.assertIn("partial init output", result.stdout)
            self.assertIn("diagnostic failure", result.stderr)
            self.assertIn("Error: Headless init prompt 'demo' failed with exit code 17.", result.stdout)
            self.assertEqual((init_dir / "demo-headless-output.md").read_text(encoding="utf-8"), "partial init output\n")
            self.assertEqual((init_dir / "demo-headless-stderr.txt").read_text(encoding="utf-8"), "diagnostic failure\n")
            self.assertTrue(prompt_file.exists())
            preserved_prompt = prompt_file.read_text(encoding="utf-8")
            self.assertIn("Original body.", preserved_prompt)
            self.assertIn("`yyyyMMdd-HHmmss-init-report.md`", preserved_prompt)

    def test_headless_init_prompt_accepts_model_option(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            script, _ = copy_scripts_to_temp_root(root)
            prompt_dir = root / "init-prompts"
            prompt_dir.mkdir()
            (prompt_dir / "demo.md").write_text("# Demo Prompt\n\nOriginal body.", encoding="utf-8")
            target = root / "target"
            target.mkdir()
            fake_bin = root / "fake-bin"
            record_path = root / "omp-record.json"
            self.make_fake_omp(fake_bin, record_path)
            env = os.environ.copy()
            env["PATH"] = str(fake_bin) + os.pathsep + env.get("PATH", "")

            result = subprocess.run(
                [
                    "pwsh",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script),
                    "-Target",
                    str(target),
                    "-InitPrompt",
                    "demo",
                    "-Headless",
                    "-Model",
                    "gpt-test",
                ],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            record = json.loads(record_path.read_text(encoding="utf-8"))
            self.assertEqual(record["argv"][-3:-1], ["--model", "gpt-test"])
            self.assertTrue(record["argv"][-1].replace("\\", "/").endswith("/target/.omp/init/demo-headless-prompt.md"))

    def test_headless_init_prompt_requires_headless_switch(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            script, _ = copy_scripts_to_temp_root(root)
            prompt_dir = root / "init-prompts"
            prompt_dir.mkdir()
            (prompt_dir / "demo.md").write_text("# Demo Prompt\n", encoding="utf-8")
            target = root / "target"
            target.mkdir()

            result = subprocess.run(
                ["pwsh", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-Target", str(target), "-InitPrompt", "demo"],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("-Headless is required when -InitPrompt is used", result.stdout)

    def test_headless_switch_requires_init_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            script, _ = copy_scripts_to_temp_root(root)
            target = root / "target"
            target.mkdir()

            result = subprocess.run(
                ["pwsh", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-Target", str(target), "-Headless"],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("-Headless requires -InitPrompt <name>", result.stdout)

    def test_headless_init_prompt_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            script, _ = copy_scripts_to_temp_root(root)
            prompt_dir = root / "init-prompts"
            prompt_dir.mkdir()
            (prompt_dir / "demo.md").write_text("# Demo Prompt\n", encoding="utf-8")
            target = root / "target"
            target.mkdir()

            result = subprocess.run(
                ["pwsh", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-Target", str(target), "-InitPrompt", "../demo", "-Headless"],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Init prompt name must be a file name under init-prompts", result.stdout)

    def test_update_loadout_repos_updates_recorded_repos_and_skips_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            loadout = root / "loadouts" / "custom"
            target1 = root / "target1"
            target2 = root / "target2"
            missing = root / "missing"
            (loadout / ".harness").mkdir(parents=True)
            target1.mkdir()
            target2.mkdir()
            (loadout / ".harness" / "settings.txt").write_text("v1", encoding="utf-8")
            (loadout / "AGENTS.md").write_text("# Instructions v1\n", encoding="utf-8")
            script, updater = copy_scripts_to_temp_root(root)

            for target in (target1, target2):
                result = subprocess.run(
                    ["pwsh", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-Loadout", "custom", "-Target", str(target), "-Harness", "codex", "-Force"],
                    cwd=root,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

            usage_path = root / "applied-repos.json"
            usage_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "loadouts": {
                            "custom": {
                                "loadout": "custom",
                                "repos": [
                                    {"path": str(target1.resolve()), "harness": "codex", "lastAppliedAt": "2026-06-24T00:00:00.0000000Z"},
                                    {"path": str(target2.resolve()), "harness": "codex", "lastAppliedAt": "2026-06-24T00:00:00.0000000Z"},
                                    {"path": str(missing.resolve()), "harness": "codex", "lastAppliedAt": "2026-06-24T00:00:00.0000000Z"},
                                ],
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            (loadout / ".harness" / "settings.txt").write_text("v2", encoding="utf-8")
            (loadout / "AGENTS.md").write_text("# Instructions v2\n", encoding="utf-8")

            result = subprocess.run(
                ["pwsh", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(updater), "-Loadout", "custom"],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual((target1 / ".codex" / "settings.txt").read_text(encoding="utf-8"), "v2")
            self.assertEqual((target2 / ".codex" / "settings.txt").read_text(encoding="utf-8"), "v2")
            self.assertEqual((target1 / "AGENTS.md").read_text(encoding="utf-8"), "# Instructions v1\n")
            self.assertEqual((target2 / "AGENTS.md").read_text(encoding="utf-8"), "# Instructions v1\n")
            self.assertIn("Skipping missing repo", result.stdout + result.stderr)
            data = json.loads(usage_path.read_text(encoding="utf-8"))
            self.assertIn(str(missing.resolve()), [repo["path"] for repo in data["loadouts"]["custom"]["repos"]])

            result = subprocess.run(
                ["pwsh", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(updater), "-Loadout", "custom", "-UpdateAgentsMd"],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("# Instructions v2\n", (target1 / "AGENTS.md").read_text(encoding="utf-8"))
            self.assertIn("# Instructions v2\n", (target2 / "AGENTS.md").read_text(encoding="utf-8"))

    def test_update_loadout_repos_whatif_does_not_change_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            loadout = root / "loadouts" / "custom"
            target = root / "target"
            (loadout / ".harness").mkdir(parents=True)
            target.mkdir()
            (loadout / ".harness" / "settings.txt").write_text("v1", encoding="utf-8")
            script, updater = copy_scripts_to_temp_root(root)

            result = subprocess.run(
                ["pwsh", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-Loadout", "custom", "-Target", str(target), "-Harness", "codex", "-Force"],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

            usage_path = root / "applied-repos.json"
            usage_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "loadouts": {
                            "custom": {
                                "loadout": "custom",
                                "repos": [
                                    {"path": str(target.resolve()), "harness": "codex", "lastAppliedAt": "2026-06-24T00:00:00.0000000Z"}
                                ],
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            (loadout / ".harness" / "settings.txt").write_text("v2", encoding="utf-8")

            result = subprocess.run(
                ["pwsh", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(updater), "-Loadout", "custom", "-WhatIf"],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual((target / ".codex" / "settings.txt").read_text(encoding="utf-8"), "v1")
            self.assertIn("Planned update for repo:", result.stdout)
            self.assertIn("[WOULD CHANGE] .codex/settings.txt", result.stdout)


if __name__ == "__main__":
    unittest.main()
