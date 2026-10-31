import unittest
from dataclasses import replace

from explore import explore
from model import LIVE_COPIES, Effect, State, step, violations


def run(*events):
    s = State()
    for event in events:
        after, effect = step(s, event)
        errors = violations(s, event, after, effect)
        if errors:
            raise AssertionError((events, event, errors))
        s = after
    return s


class SpecificationTests(unittest.TestCase):
    def test_admission_and_fence_are_distinct(self):
        s = run("admit_old", "A", "commit_old")
        self.assertTrue(s.durable.row)
        self.assertFalse(step(s, "admit_new")[1].admitted)
        s = run("admit_old", "A", "F", "commit_old")
        self.assertFalse(s.durable.row)
        self.assertFalse(run("A", "drain").durable.drained)

    def test_D_requires_every_declared_copy(self):
        prefix = ("admit_old", "commit_old", "A", "F", "drain")
        for omitted in LIVE_COPIES:
            events = tuple("clean_" + c for c in LIVE_COPIES if c != omitted)
            self.assertFalse(run(*prefix, *events, "D").durable.done)
        s = run(*prefix, *("clean_" + c for c in LIVE_COPIES), "D")
        self.assertTrue(s.durable.done)
        self.assertFalse(s.durable.row)
        self.assertFalse(s.durable.receipts)

    def test_deleted_identity_blocks_both_operation_ids(self):
        for op in ("old", "new"):
            s = run("admit_old", "commit_old", "delete", "admit_" + op, "commit_" + op)
            self.assertFalse(s.durable.row)
            self.assertTrue(s.durable.barrier)

    def test_delete_before_create_commit(self):
        s = run("admit_old", "delete", "commit_old")
        self.assertFalse(s.durable.row)

    def test_erased_and_withdrawn_receipts_never_replay_metadata(self):
        active = run("admit_old", "commit_old")
        self.assertTrue(step(active, "replay")[1].metadata)
        for event in ("delete", "A"):
            retired, _ = step(active, event)
            self.assertFalse(step(retired, "replay")[1].metadata)

    def test_auxiliary_failure_restart_undo_retains_L(self):
        s = run("aux_fail", "L", "restart")
        self.assertTrue(s.durable.marker)
        self.assertFalse(s.durable.journal)
        self.assertFalse(s.volatile.startup_ready)
        s = run("aux_fail", "L", "restart", "reconcile", "switch_owner", "undo", "consent_on", "admit_new")
        self.assertTrue(s.durable.marker)
        self.assertTrue(s.durable.journal)
        self.assertTrue(s.durable.retired)
        self.assertFalse(s.durable.local_deleted)
        self.assertFalse(s.durable.tickets)

    def test_management_without_upload_consent(self):
        s = run("consent_off", "upload_permission_off")
        for event in ("A", "delete", "status"):
            self.assertTrue(step(s, event)[1].management)
        self.assertFalse(step(s, "admit_old")[1].admitted)
        self.assertTrue(run("consent_off", "delete").durable.barrier)

    def test_owner_and_permissions(self):
        for restriction in ("switch_other", "unverify", "management_permission_off"):
            s = run(restriction)
            for event in ("A", "delete", "status"):
                self.assertFalse(step(s, event)[1].management)
        for restriction in ("switch_other", "unverify", "upload_permission_off", "consent_off"):
            self.assertFalse(step(run(restriction), "admit_old")[1].admitted)

    def test_stale_ack(self):
        for events in (("L", "undo"), ("A",), ("delete",), ("switch_other",), ("restart",)):
            s = run("admit_old", "commit_old", *events, "ack")
            self.assertFalse(s.volatile.client_active)

    def test_checker_uses_state_deltas_without_effects(self):
        cases = [
            (run("A"), "admit_old", "A blocks new admission", "ticket"),
            (run("A", "F"), "commit_old", "F blocks retired-generation commit", "row"),
            (run("delete"), "commit_old", "deleted sync ID cannot be recreated", "row"),
            (run("switch_other"), "admit_old", "verified owner required to resume", "ticket"),
            (run("consent_off"), "admit_old", "upload requires current consent and permission", "ticket"),
            (run("restart", "switch_owner"), "admit_old", "startup reconciliation required before admission", "ticket"),
        ]
        for before, event, error, change in cases:
            with self.subTest(error=error):
                delta = {"tickets": frozenset({"old"})} if change == "ticket" else {"row": True}
                after = replace(before, durable=replace(before.durable, **delta))
                self.assertIn(error, violations(before, event, after, Effect()))
        before = run("switch_other")
        after = replace(before, durable=replace(before.durable, accepted=True))
        self.assertIn("verified owner required to resume", violations(before, "A", after, Effect()))

    def test_ack_checker_independently_checks_each_condition(self):
        active = run("admit_old", "commit_old")
        fixtures = [run("admit_old", "commit_old", e)
                    for e in ("switch_other", "unverify", "A", "delete")]
        # Epoch-only fixture: bounded model cannot reach epoch=1 without retirement.
        fixtures.append(replace(active, durable=replace(active.durable, epoch=1)))
        fixtures.append(State())
        for before in fixtures:
            after = replace(before, volatile=replace(before.volatile, client_active=True))
            self.assertIn("stale ACK requires verified owner and captured epoch",
                          violations(before, "ack", after, Effect()))
        epoch_only = fixtures[-2]
        self.assertFalse(step(epoch_only, "ack")[0].volatile.client_active)
        after, effect = step(epoch_only, "ack", test_fault="missing_ack_epoch")
        self.assertTrue(after.volatile.client_active)
        errors = violations(epoch_only, "ack", after, effect)
        print("NEGATIVE_CONTROL missing_ack_epoch: fixture=admit_old,commit_old; epoch=1,retired=False; ack", errors)
        self.assertIn("stale ACK requires verified owner and captured epoch", errors)

    def test_startup_reconciliation_gate(self):
        before = run("restart", "switch_owner")
        self.assertFalse(step(before, "admit_old")[0].durable.tickets)
        self.assertTrue(run("restart", "switch_owner", "reconcile", "admit_old").durable.tickets)

    def test_bounded_exploration(self):
        result = explore()
        self.assertFalse(result.errors, result)
        self.assertFalse(result.truncated, result)
        self.assertGreater(result.transitions, result.states)

    def test_test_only_negative_controls_shortest_counterexamples(self):
        expected = {
            "missing_startup_reconciliation": (3, "startup reconciliation required before admission"),
            "missing_fence": (4, "F blocks retired-generation commit"),
            "missing_barrier": (2, "deleted sync ID cannot be recreated"),
            "management_requires_consent": (2, "management is consent-independent and permission-restricted"),
        }
        for fault, (length, error) in expected.items():
            with self.subTest(fault=fault):
                result = explore(depth=5, state_limit=60000, test_fault=fault)
                print(f"NEGATIVE_CONTROL {fault}: {result}")
                self.assertIn(error, result.errors)
                self.assertEqual(len(result.trace), length)
                self.assertFalse(result.truncated)


if __name__ == "__main__":
    unittest.main()
