#!/usr/bin/env python3
"""
Cursor stop hook: after an agent turn finishes, commit all repo changes and push
to the current branch's upstream remote.

Fails open (exit 0) so push/commit errors do not block the agent.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path.cwd()
LOCK = ROOT / ".cursor" / "hooks" / ".auto_push.lock"


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def has_changes() -> bool:
    proc = run("git", "status", "--porcelain")
    return proc.returncode == 0 and bool(proc.stdout.strip())


def current_branch() -> str:
    proc = run("git", "rev-parse", "--abbrev-ref", "HEAD")
    if proc.returncode != 0:
        return "main"
    return proc.stdout.strip() or "main"


def main() -> int:
    try:
        raw = sys.stdin.read()
        hook_input = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        hook_input = {}

    if not (ROOT / ".git").is_dir():
        return 0

    if LOCK.exists():
        return 0

    if not has_changes():
        return 0

    LOCK.parent.mkdir(parents=True, exist_ok=True)
    LOCK.write_text(str(datetime.now(timezone.utc).isoformat()), encoding="utf-8")

    try:
        add = run("git", "add", "-A")
        if add.returncode != 0:
            print(add.stderr, file=sys.stderr)
            return 0

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        status = run("git", "status", "--porcelain")
        file_count = len([ln for ln in status.stdout.splitlines() if ln.strip()])
        msg = f"chore: auto-commit after agent ({file_count} files) [{ts}]"

        commit = run("git", "commit", "-m", msg)
        if commit.returncode != 0:
            # nothing staged / hook-only noise
            if "nothing to commit" not in (commit.stdout + commit.stderr).lower():
                print(commit.stderr, file=sys.stderr)
            return 0

        branch = current_branch()
        push = run("git", "push", "origin", branch)
        if push.returncode != 0:
            print(push.stderr, file=sys.stderr)
            # try set upstream on first push of a new branch
            push_u = run("git", "push", "-u", "origin", branch)
            if push_u.returncode != 0:
                print(push_u.stderr, file=sys.stderr)

        # Optional debug for Hooks output channel
        if hook_input:
            print(json.dumps({"auto_commit": msg, "branch": branch}, ensure_ascii=False))
        return 0
    finally:
        if LOCK.exists():
            LOCK.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
