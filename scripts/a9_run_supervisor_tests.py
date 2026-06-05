#!/usr/bin/env python3
"""Run supervisor tests while stopping the live A9 daemon claimer.

The supervisor test suite uses the real `.a9/tasks` directories in several
legacy coverage paths. If the live daemon is also running, it can claim those
selftest tasks and make the test evidence nondeterministic. This wrapper keeps
the tmux daemon stopped for the duration of the command and restarts it on exit
if it was present.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


DEFAULT_COMMAND = [sys.executable, "-m", "unittest", "tests.test_supervisor"]
DEFAULT_DAEMON_SESSION = "a9-supervisor-loop"
DEFAULT_DAEMON_COMMAND = (
    "cd /root/a9 && A9_IDLE_GOAL_CONTINUATION=0 "
    "python3 scripts/a9_supervisor.py run-loop --keep-going-on-error --sleep-seconds 15"
)


def tmux_session_exists(session: str) -> bool:
    result = subprocess.run(
        ["tmux", "has-session", "-t", session],
        cwd=ROOT,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def stop_daemon_session(session: str) -> bool:
    if not tmux_session_exists(session):
        return False
    subprocess.run(["tmux", "send-keys", "-t", session, "C-c"], cwd=ROOT, check=False)
    return True


def start_daemon_session(session: str, command: str) -> None:
    if tmux_session_exists(session):
        return
    subprocess.run(["tmux", "new-session", "-d", "-s", session, command], cwd=ROOT, check=False)


def run_guarded(command: list[str], *, session: str, restart_command: str) -> int:
    daemon_was_running = stop_daemon_session(session)
    try:
        return subprocess.run(command, cwd=ROOT, check=False).returncode
    finally:
        if daemon_was_running:
            start_daemon_session(session, restart_command)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Stop the live A9 tmux daemon while running supervisor tests."
    )
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="Optional command after --. Defaults to python -m unittest tests.test_supervisor.",
    )
    parser.add_argument(
        "--daemon-session",
        default=DEFAULT_DAEMON_SESSION,
        help="tmux session name for the live supervisor daemon.",
    )
    parser.add_argument(
        "--restart-command",
        default=DEFAULT_DAEMON_COMMAND,
        help="Command used to restart the daemon if it was running before tests.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(list(argv or sys.argv[1:]))
    command = list(args.command or DEFAULT_COMMAND)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        command = DEFAULT_COMMAND
    return run_guarded(
        command,
        session=str(args.daemon_session),
        restart_command=str(args.restart_command),
    )


if __name__ == "__main__":
    raise SystemExit(main())
