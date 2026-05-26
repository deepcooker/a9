#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIDDLEWARE_PATH = ROOT / "scripts" / "a9_middleware.py"


def load_middleware():
    spec = importlib.util.spec_from_file_location("a9_middleware", MIDDLEWARE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def redis_available() -> bool:
    redis = subprocess.run(
        ["docker", "exec", "a9-redis", "redis-cli", "PING"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return redis.returncode == 0 and "PONG" in redis.stdout


class MiddlewareFlowTests(unittest.TestCase):
    def test_transition_flow_state_requires_expected_revision(self):
        mod = load_middleware()
        state = mod.initial_flow_state("flow-1", "session_refresh")

        with self.assertRaisesRegex(ValueError, "revision_mismatch"):
            mod.transition_flow_state(
                state,
                expected_revision=1,
                next_status="running",
                actor="test",
            )

    def test_transition_flow_state_advances_revision_and_history(self):
        mod = load_middleware()
        state = mod.initial_flow_state("flow-1", "session_refresh", metadata={"source": "unit"})

        updated = mod.transition_flow_state(
            state,
            expected_revision=0,
            next_status="running",
            actor="supervisor",
            reason="lease",
            evidence_id="e1",
            now="2026-05-22T00:00:00+00:00",
        )

        self.assertEqual(updated["revision"], 1)
        self.assertEqual(updated["status"], "running")
        self.assertEqual(updated["metadata"], {"source": "unit"})
        self.assertEqual(updated["history"][0]["from_status"], "created")
        self.assertEqual(updated["history"][0]["to_status"], "running")
        self.assertEqual(updated["history"][0]["evidence_id"], "e1")

    def test_set_waiting_flow_state_records_approval_envelope(self):
        mod = load_middleware()
        state = mod.initial_flow_state("flow-1", "approval")

        updated = mod.set_waiting_flow_state(
            state,
            expected_revision=0,
            actor="supervisor",
            prompt="Approve next step?",
            approval_id="approval-1",
            resume_token="token-1",
            waiting_step="apply_patch",
            now="2026-05-22T00:00:00+00:00",
        )

        self.assertEqual(updated["revision"], 1)
        self.assertEqual(updated["status"], "waiting")
        self.assertEqual(updated["waiting"]["kind"], "approval_request")
        self.assertEqual(updated["waiting"]["approval_id"], "approval-1")
        self.assertEqual(updated["waiting"]["resume_token"], "token-1")
        self.assertEqual(updated["history"][0]["to_status"], "waiting")

    def test_resume_waiting_flow_state_requires_identity_and_resumes(self):
        mod = load_middleware()
        state = mod.set_waiting_flow_state(
            mod.initial_flow_state("flow-1", "approval"),
            expected_revision=0,
            actor="supervisor",
            prompt="Approve next step?",
            approval_id="approval-1",
            resume_token="token-1",
            now="2026-05-22T00:00:00+00:00",
        )

        with self.assertRaisesRegex(ValueError, "resume_identity_required"):
            mod.resume_waiting_flow_state(
                state,
                expected_revision=1,
                actor="operator",
                approve=True,
            )

        resumed = mod.resume_waiting_flow_state(
            state,
            expected_revision=1,
            actor="operator",
            approve=True,
            approval_id="approval-1",
            reason="ok",
            now="2026-05-22T00:00:01+00:00",
        )

        self.assertEqual(resumed["revision"], 2)
        self.assertEqual(resumed["status"], "running")
        self.assertIsNone(resumed["waiting"])
        self.assertTrue(resumed["last_approval"]["approved"])
        self.assertEqual(resumed["history"][1]["to_status"], "running")

    @unittest.skipUnless(redis_available(), "redis is not running")
    def test_redis_function_transition_flow_rejects_stale_revision(self):
        mod = load_middleware()
        mod.init_redis_runtime()
        flow_id = "middleware-flow-unittest"
        key = mod.redis_flow_key(flow_id)
        state = mod.initial_flow_state(flow_id, "unit")
        create = mod.redis(["JSON.SET", key, "$", mod.json_compact(state)])
        self.assertEqual(create.returncode, 0, create.stdout)

        first = mod.redis(
            [
                "FCALL",
                "transition_flow",
                "1",
                key,
                "0",
                "running",
                "unittest",
                "lease",
                "e1",
                "2026-05-22T00:00:00+00:00",
            ]
        )
        self.assertEqual(first.returncode, 0, first.stdout)
        self.assertIn('"revision":1', first.stdout)

        stale = mod.redis(
            [
                "FCALL",
                "transition_flow",
                "1",
                key,
                "0",
                "completed",
                "unittest",
                "done",
                "e2",
                "2026-05-22T00:00:01+00:00",
            ]
        )
        self.assertIn("revision_mismatch", stale.stdout)

    @unittest.skipUnless(redis_available(), "redis is not running")
    def test_redis_function_wait_and_resume_flow(self):
        mod = load_middleware()
        mod.init_redis_runtime()
        flow_id = "middleware-approval-unittest"
        key = mod.redis_flow_key(flow_id)
        state = mod.initial_flow_state(flow_id, "approval")
        create = mod.redis(["JSON.SET", key, "$", mod.json_compact(state)])
        self.assertEqual(create.returncode, 0, create.stdout)

        waiting = mod.redis(
            [
                "FCALL",
                "set_waiting_flow",
                "1",
                key,
                "0",
                "supervisor",
                "Approve test?",
                "approval-1",
                "token-1",
                "unit-step",
                "2026-05-22T00:00:00+00:00",
            ]
        )
        self.assertEqual(waiting.returncode, 0, waiting.stdout)
        self.assertIn('"status":"waiting"', waiting.stdout)
        self.assertIn('"revision":1', waiting.stdout)
        self.assertIn('"approval_id":"approval-1"', waiting.stdout)

        resumed = mod.redis(
            [
                "FCALL",
                "resume_flow",
                "1",
                key,
                "1",
                "operator",
                "true",
                "approval-1",
                "",
                "ok",
                "2026-05-22T00:00:01+00:00",
            ]
        )
        self.assertEqual(resumed.returncode, 0, resumed.stdout)
        self.assertIn('"status":"running"', resumed.stdout)
        self.assertIn('"revision":2', resumed.stdout)
        self.assertIn('"approved":true', resumed.stdout)

        stale = mod.redis(
            [
                "FCALL",
                "resume_flow",
                "1",
                key,
                "1",
                "operator",
                "true",
                "approval-1",
                "",
                "stale",
                "2026-05-22T00:00:02+00:00",
            ]
        )
        self.assertIn("revision_mismatch", stale.stdout)


if __name__ == "__main__":
    unittest.main()
