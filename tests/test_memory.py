#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MEMORY = ROOT / "scripts" / "a9_memory.py"


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


class MemoryAdapterTests(unittest.TestCase):
    @unittest.skipUnless(middleware_available(), "middleware is not running")
    def test_add_search_get_all(self):
        phrase = "A9 test memory uses mem0 shape for scoped retrieval"
        add = subprocess.run(
            [
                str(MEMORY),
                "add",
                phrase,
                "--memory-type",
                "test",
                "--agent-id",
                "unittest",
                "--metadata",
                "suite=memory",
            ],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        self.assertEqual(add.returncode, 0, add.stdout)

        search = subprocess.run(
            [str(MEMORY), "search", "scoped", "--limit", "5"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        self.assertEqual(search.returncode, 0, search.stdout)
        self.assertIn("mem0", search.stdout)

        get_all = subprocess.run(
            [str(MEMORY), "get-all", "--limit", "5"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        self.assertEqual(get_all.returncode, 0, get_all.stdout)
        self.assertIn("scoped retrieval", get_all.stdout)


if __name__ == "__main__":
    unittest.main()
