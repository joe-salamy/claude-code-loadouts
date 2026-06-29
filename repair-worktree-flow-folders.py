#!/usr/bin/env python3
"""Repair legacy .omp/worktree-flow folder names for repos using the worktrees loadout.

This is a one-off migration utility for this repository. It is intentionally not
stored in loadouts/ because target repositories do not need to receive it.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable

REGISTRY = Path("applied-repos.json")
WORKTREE_FLOW_DIR = Path(".omp") / "worktree-flow"
OLD_RUN_ID_RE = re.compile(r"^(?P<slug>.+)-(?P<stamp>\d{8}-\d{6})(?P<suffix>-\d+)?$")
NEW_RUN_ID_RE = re.compile(r"^\d{8}-\d{6}-.+")


@dataclass
class RepairStats:
    repos_seen: int = 0
    repos_missing_flow_dir: int = 0
    dirs_created: int = 0
    dirs_removed: int = 0
    dirs_renamed: int = 0
    files_copied: int = 0
    files_moved: int = 0
    files_removed: int = 0
    json_files_rewritten: int = 0
    conflicts_preserved: int = 0
    actions: list[str] = field(default_factory=list)

    def note(self, message: str) -> None:
        self.actions.append(message)


@dataclass(frozen=True)
class RunId:
    old: str
    new: str
    slug: str


def load_worktree_repos(registry: Path, loadout: str) -> list[Path]:
    data = json.loads(registry.read_text(encoding="utf-8"))
    try:
        repos = data["loadouts"][loadout]["repos"]
    except KeyError as exc:
        raise SystemExit(f"Registry {registry} has no loadout entry {loadout!r}.") from exc
    return [Path(entry["path"]) for entry in repos]


def parse_old_run_id(name: str) -> RunId | None:
    if NEW_RUN_ID_RE.match(name):
        return None
    match = OLD_RUN_ID_RE.match(name)
    if match is None:
        return None
    slug = match.group("slug")
    stamp = match.group("stamp")
    suffix = match.group("suffix") or ""
    return RunId(old=name, new=f"{stamp}-{slug}{suffix}", slug=slug)


def is_timestamp_first(name: str) -> bool:
    return NEW_RUN_ID_RE.match(name) is not None


def safe_suffix(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-") or "source"


def unique_conflict_path(dest: Path, source_label: str) -> Path:
    suffix = safe_suffix(source_label)
    candidate = dest.with_name(f"{dest.stem}.from-{suffix}{dest.suffix}")
    index = 2
    while candidate.exists():
        candidate = dest.with_name(f"{dest.stem}.from-{suffix}-{index}{dest.suffix}")
        index += 1
    return candidate


def ensure_dir(path: Path, *, dry_run: bool, stats: RepairStats) -> None:
    if path.exists():
        return
    stats.dirs_created += 1
    stats.note(f"mkdir {path}")
    if not dry_run:
        path.mkdir(parents=True, exist_ok=True)


def same_file_bytes(left: Path, right: Path) -> bool:
    return left.is_file() and right.is_file() and left.read_bytes() == right.read_bytes()


def merge_file(
    source: Path,
    dest: Path,
    *,
    source_label: str,
    copy: bool,
    dry_run: bool,
    stats: RepairStats,
) -> None:
    ensure_dir(dest.parent, dry_run=dry_run, stats=stats)
    if not dest.exists():
        if copy:
            stats.files_copied += 1
            stats.note(f"copy {source} -> {dest}")
            if not dry_run:
                shutil.copy2(source, dest)
        else:
            stats.files_moved += 1
            stats.note(f"move {source} -> {dest}")
            if not dry_run:
                shutil.move(str(source), str(dest))
        return

    if same_file_bytes(source, dest):
        if copy:
            stats.note(f"keep duplicate {source}; already present at {dest}")
        else:
            stats.files_removed += 1
            stats.note(f"remove duplicate {source}; already present at {dest}")
            if not dry_run:
                source.unlink()
        return

    conflict_dest = unique_conflict_path(dest, source_label)
    stats.conflicts_preserved += 1
    if copy:
        stats.files_copied += 1
        stats.note(f"copy conflict {source} -> {conflict_dest}")
        if not dry_run:
            shutil.copy2(source, conflict_dest)
    else:
        stats.files_moved += 1
        stats.note(f"move conflict {source} -> {conflict_dest}")
        if not dry_run:
            shutil.move(str(source), str(conflict_dest))


def merge_tree(
    source: Path,
    dest: Path,
    *,
    source_label: str,
    copy: bool,
    dry_run: bool,
    stats: RepairStats,
) -> None:
    if source.is_file():
        merge_file(
            source,
            dest,
            source_label=source_label,
            copy=copy,
            dry_run=dry_run,
            stats=stats,
        )
        return

    ensure_dir(dest, dry_run=dry_run, stats=stats)
    for item in sorted(source.iterdir(), key=lambda path: path.name.lower()):
        merge_tree(
            item,
            dest / item.name,
            source_label=source_label,
            copy=copy,
            dry_run=dry_run,
            stats=stats,
        )
    if not copy:
        remove_empty_dir(source, dry_run=dry_run, stats=stats)


def remove_empty_dir(path: Path, *, dry_run: bool, stats: RepairStats) -> None:
    if not path.exists():
        return
    try:
        next(path.iterdir())
    except StopIteration:
        stats.dirs_removed += 1
        stats.note(f"rmdir {path}")
        if not dry_run:
            path.rmdir()


def remove_tree(path: Path, *, dry_run: bool, stats: RepairStats) -> None:
    if not path.exists():
        return
    stats.dirs_removed += 1
    stats.note(f"remove tree {path}")
    if not dry_run:
        shutil.rmtree(path)


def metadata_timestamp(path: Path) -> str:
    plan = path / "plan.md"
    source = plan if plan.exists() else path
    return datetime.fromtimestamp(source.stat().st_mtime).strftime("%Y%m%d-%H%M%S")


def unique_target(flow_dir: Path, wanted_name: str) -> Path:
    target = flow_dir / wanted_name
    if not target.exists():
        return target
    for index in range(2, 1000):
        candidate = flow_dir / f"{wanted_name}-{index}"
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Could not choose unique target for {wanted_name}")


def rewrite_run_id_metadata(
    run_dir: Path,
    *,
    old_run_id: str,
    new_run_id: str,
    dry_run: bool,
    stats: RepairStats,
) -> None:
    state_path = run_dir / "workflow-state.json"
    if state_path.exists():
        data = json.loads(state_path.read_text(encoding="utf-8"))
        changed = False
        if data.get("run_id") == old_run_id:
            data["run_id"] = new_run_id
            changed = True
        plan = run_dir / "plan.md"
        if plan.exists() and data.get("plan_path"):
            data["plan_path"] = str(plan)
            changed = True
        if changed:
            stats.json_files_rewritten += 1
            stats.note(f"rewrite {state_path}: run_id {old_run_id} -> {new_run_id}")
            if not dry_run:
                state_path.write_text(
                    json.dumps(data, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                    newline="\n",
                )

    log_path = run_dir / "workflow.jsonl"
    if log_path.exists():
        changed = False
        output_lines: list[str] = []
        for line in log_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                output_lines.append(line)
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                output_lines.append(line)
                continue
            if record.get("run_id") == old_run_id:
                record["run_id"] = new_run_id
                changed = True
            output_lines.append(json.dumps(record, sort_keys=True))
        if changed:
            stats.json_files_rewritten += 1
            stats.note(f"rewrite {log_path}: run_id {old_run_id} -> {new_run_id}")
            if not dry_run:
                log_path.write_text("\n".join(output_lines) + "\n", encoding="utf-8", newline="\n")



def converted_legacy_run_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    run_id = parse_old_run_id(value)
    return run_id.new if run_id is not None else None


def authoritative_state_run_id(run_dir: Path) -> str | None:
    state_path = run_dir / "workflow-state.json"
    if not state_path.exists():
        return None
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return converted_legacy_run_id(data.get("run_id"))


def rewrite_legacy_metadata_run_ids(
    run_dir: Path, *, dry_run: bool, stats: RepairStats
) -> None:
    state_path = run_dir / "workflow-state.json"
    if state_path.exists():
        data = json.loads(state_path.read_text(encoding="utf-8"))
        converted = converted_legacy_run_id(data.get("run_id"))
        changed = False
        if converted is not None:
            stats.note(f"rewrite {state_path}: run_id {data['run_id']} -> {converted}")
            data["run_id"] = converted
            changed = True
        plan = run_dir / "plan.md"
        if plan.exists() and data.get("plan_path") != str(plan):
            data["plan_path"] = str(plan)
            changed = True
        if changed:
            stats.json_files_rewritten += 1
            if not dry_run:
                state_path.write_text(
                    json.dumps(data, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                    newline="\n",
                )

    log_path = run_dir / "workflow.jsonl"
    if log_path.exists():
        changed = False
        output_lines: list[str] = []
        for line in log_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                output_lines.append(line)
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                output_lines.append(line)
                continue
            converted = converted_legacy_run_id(record.get("run_id"))
            if converted is not None:
                record["run_id"] = converted
                changed = True
            output_lines.append(json.dumps(record, sort_keys=True))
        if changed:
            stats.json_files_rewritten += 1
            stats.note(f"rewrite {log_path}: legacy run_id values")
            if not dry_run:
                log_path.write_text(
                    "\n".join(output_lines) + "\n",
                    encoding="utf-8",
                    newline="\n",
                )


def normalize_existing_timestamp_dir(
    flow_dir: Path, run_dir: Path, *, dry_run: bool, stats: RepairStats
) -> Path:
    desired_run_id = authoritative_state_run_id(run_dir)
    if desired_run_id is not None and run_dir.name != desired_run_id:
        target = flow_dir / desired_run_id
        merge_tree(
            run_dir,
            target,
            source_label=run_dir.name,
            copy=False,
            dry_run=dry_run,
            stats=stats,
        )
        run_dir = target
    rewrite_legacy_metadata_run_ids(run_dir, dry_run=dry_run, stats=stats)
    return run_dir

def migrate_direct_run(
    flow_dir: Path,
    source: Path,
    run_id: RunId,
    *,
    dry_run: bool,
    stats: RepairStats,
) -> Path:
    target = flow_dir / run_id.new
    if not target.exists():
        stats.dirs_renamed += 1
        stats.note(f"rename {source} -> {target}")
        if not dry_run:
            source.rename(target)
    else:
        merge_tree(
            source,
            target,
            source_label=source.name,
            copy=False,
            dry_run=dry_run,
            stats=stats,
        )
    rewrite_run_id_metadata(
        target,
        old_run_id=run_id.old,
        new_run_id=run_id.new,
        dry_run=dry_run,
        stats=stats,
    )
    return target


def migrate_nested_run(
    flow_dir: Path,
    parent: Path,
    run_dir: Path,
    run_id: RunId,
    *,
    dry_run: bool,
    stats: RepairStats,
) -> Path:
    target = flow_dir / run_id.new
    for item in sorted(parent.iterdir(), key=lambda path: path.name.lower()):
        if item.name == "runs":
            continue
        merge_tree(
            item,
            target / item.name,
            source_label=parent.name,
            copy=True,
            dry_run=dry_run,
            stats=stats,
        )
    merge_tree(
        run_dir,
        target,
        source_label=run_dir.name,
        copy=False,
        dry_run=dry_run,
        stats=stats,
    )
    rewrite_run_id_metadata(
        target,
        old_run_id=run_id.old,
        new_run_id=run_id.new,
        dry_run=dry_run,
        stats=stats,
    )
    return target


def migrate_unmatched_plan_dir(
    flow_dir: Path,
    source: Path,
    *,
    dry_run: bool,
    stats: RepairStats,
) -> Path:
    wanted = f"{metadata_timestamp(source)}-{source.name}"
    target = unique_target(flow_dir, wanted)
    merge_tree(
        source,
        target,
        source_label=source.name,
        copy=False,
        dry_run=dry_run,
        stats=stats,
    )
    return target


def direct_files(path: Path) -> Iterable[Path]:
    return (item for item in path.iterdir() if item.is_file())


def repair_repo(repo: Path, *, dry_run: bool, stats: RepairStats) -> None:
    stats.repos_seen += 1
    flow_dir = repo / WORKTREE_FLOW_DIR
    if not flow_dir.exists():
        stats.repos_missing_flow_dir += 1
        stats.note(f"skip missing {flow_dir}")
        return

    children = [child for child in sorted(flow_dir.iterdir(), key=lambda path: path.name.lower()) if child.is_dir()]
    slug_targets: dict[str, list[Path]] = {}
    handled: set[Path] = set()

    for child in children:
        run_id = parse_old_run_id(child.name)
        if run_id is None:
            continue
        target = migrate_direct_run(flow_dir, child, run_id, dry_run=dry_run, stats=stats)
        slug_targets.setdefault(run_id.slug, []).append(target)
        handled.add(child)

    children = [child for child in sorted(flow_dir.iterdir(), key=lambda path: path.name.lower()) if child.is_dir()]
    for parent in children:
        if parent in handled or is_timestamp_first(parent.name):
            continue
        runs_dir = parent / "runs"
        if not runs_dir.is_dir():
            continue
        migrated_any = False
        for run_dir in sorted((path for path in runs_dir.iterdir() if path.is_dir()), key=lambda path: path.name.lower()):
            run_id = parse_old_run_id(run_dir.name)
            if run_id is None:
                if is_timestamp_first(run_dir.name):
                    run_id = RunId(old=run_dir.name, new=run_dir.name, slug=run_dir.name[16:])
                else:
                    continue
            target = migrate_nested_run(flow_dir, parent, run_dir, run_id, dry_run=dry_run, stats=stats)
            slug_targets.setdefault(parent.name, []).append(target)
            slug_targets.setdefault(run_id.slug, []).append(target)
            migrated_any = True
        remove_empty_dir(runs_dir, dry_run=dry_run, stats=stats)
        if migrated_any:
            remove_tree(parent, dry_run=dry_run, stats=stats)
            handled.add(parent)

    children = [child for child in sorted(flow_dir.iterdir(), key=lambda path: path.name.lower()) if child.is_dir()]
    for child in children:
        if child in handled or is_timestamp_first(child.name):
            continue
        if parse_old_run_id(child.name) is not None:
            continue
        targets = slug_targets.get(child.name, [])
        if targets:
            for target in targets:
                merge_tree(
                    child,
                    target,
                    source_label=child.name,
                    copy=True,
                    dry_run=dry_run,
                    stats=stats,
                )
            remove_tree(child, dry_run=dry_run, stats=stats)
        elif any(direct_files(child)):
            migrate_unmatched_plan_dir(flow_dir, child, dry_run=dry_run, stats=stats)

    for child in sorted((path for path in flow_dir.iterdir() if path.is_dir()), key=lambda path: path.name.lower()):
        if is_timestamp_first(child.name):
            normalize_existing_timestamp_dir(
                flow_dir, child, dry_run=dry_run, stats=stats
            )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=REGISTRY)
    parser.add_argument("--loadout", default="worktrees")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repos = load_worktree_repos(args.registry, args.loadout)
    stats = RepairStats()
    for repo in repos:
        repair_repo(repo, dry_run=args.dry_run, stats=stats)

    mode = "DRY RUN" if args.dry_run else "APPLIED"
    print(f"{mode}: repos={stats.repos_seen}, missing_flow_dirs={stats.repos_missing_flow_dir}")
    print(
        "changes: "
        f"renamed_dirs={stats.dirs_renamed}, created_dirs={stats.dirs_created}, "
        f"removed_dirs={stats.dirs_removed}, moved_files={stats.files_moved}, "
        f"copied_files={stats.files_copied}, removed_files={stats.files_removed}, "
        f"rewritten_json={stats.json_files_rewritten}, conflicts_preserved={stats.conflicts_preserved}"
    )
    if args.verbose:
        for action in stats.actions:
            print(action)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
