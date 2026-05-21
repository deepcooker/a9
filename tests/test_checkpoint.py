#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHECKPOINT = ROOT / "scripts" / "a9_checkpoint.py"


def middleware_available() -> bool:
    redis = subprocess.run(
        ["docker", "exec", "a9-redis", "redis-cli", "PING"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    mysql = subprocess.run(
        [
            "docker",
            "exec",
            "a9-mysql",
            "mysql",
            "-h127.0.0.1",
            "-ua9",
            "-pa9_dev_password",
            "a9",
            "-NBe",
            "select 1;",
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return redis.returncode == 0 and "PONG" in redis.stdout and mysql.returncode == 0


class CheckpointTests(unittest.TestCase):
    @unittest.skipUnless(middleware_available(), "middleware is not running")
    def test_put_list_lineage(self):
        session_id = "checkpoint-unittest"
        first = subprocess.run(
            [
                str(CHECKPOINT),
                "put",
                session_id,
                "--checkpoint-id",
                f"{session_id}:1",
                "--parent-checkpoint-id",
                "",
                "--channels",
                json.dumps({"task": ["e1"], "messages": ["m1"]}),
                "--updated-channel",
                "task",
                "--source",
                "test",
            ],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        self.assertEqual(first.returncode, 0, first.stdout)

        second = subprocess.run(
            [
                str(CHECKPOINT),
                "put",
                session_id,
                "--checkpoint-id",
                f"{session_id}:2",
                "--parent-checkpoint-id",
                f"{session_id}:1",
                "--channels",
                json.dumps({"task": ["e1"], "messages": ["m2"], "checks": ["c1"]}),
                "--updated-channel",
                "messages",
                "--updated-channel",
                "checks",
                "--source",
                "test",
            ],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        self.assertEqual(second.returncode, 0, second.stdout)

        listing = subprocess.run(
            [str(CHECKPOINT), "list", session_id, "--limit", "2"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        self.assertEqual(listing.returncode, 0, listing.stdout)
        self.assertIn(f"{session_id}:2", listing.stdout)

        lineage = subprocess.run(
            [str(CHECKPOINT), "lineage", f"{session_id}:2"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        self.assertEqual(lineage.returncode, 0, lineage.stdout)
        self.assertIn(f"{session_id}:1", lineage.stdout)
        self.assertIn(f"{session_id}:2", lineage.stdout)

        history = subprocess.run(
            [
                str(CHECKPOINT),
                "channel-history",
                f"{session_id}:2",
                "--channel",
                "messages",
            ],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        self.assertEqual(history.returncode, 0, history.stdout)
        payload = json.loads(history.stdout)
        self.assertEqual(payload["seed"]["value"], ["m1"])
        self.assertEqual(payload["writes"][0]["value"], ["m2"])


if __name__ == "__main__":
    unittest.main()
