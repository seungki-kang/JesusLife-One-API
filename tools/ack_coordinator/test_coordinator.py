"""Deterministic synthetic tests, including an intentionally unsafe control."""

from dataclasses import replace
import unittest

from coordinator import AckCoordinator


class NoEpochControl(AckCoordinator):
    """TEST ONLY: same acceptance rule with the epoch comparison omitted."""

    def accept_ack(self, request):
        if (
            self._account is None
            or request.account != self._account
            or request not in self._pending
        ):
            return False
        self._pending.remove(request)
        self._effects.append(request)
        return True


class AckCoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.coordinator = AckCoordinator()
        self.coordinator.replace_session("synthetic-A")
        self.request = self.coordinator.start_request()

    def assert_rejected_unchanged(self, request):
        before = self.coordinator.snapshot()
        self.assertFalse(self.coordinator.accept_ack(request))
        self.assertEqual(self.coordinator.snapshot(), before)

    def test_current_session_acceptance(self):
        self.assertEqual(self.request.account, "synthetic-A")
        self.assertEqual(self.request.epoch, 1)
        self.assertEqual(self.request.operation, 1)
        self.assertTrue(self.coordinator.accept_ack(self.request))
        state = self.coordinator.snapshot()
        self.assertEqual(state.pending, frozenset())
        self.assertEqual(state.effects, (self.request,))

    def test_a_to_b_rejects_old_a(self):
        self.coordinator.replace_session("synthetic-B")
        self.assert_rejected_unchanged(self.request)
        current = self.coordinator.start_request()
        self.assertTrue(self.coordinator.accept_ack(current))

    def test_a_to_b_to_a_rejects_first_a(self):
        self.coordinator.replace_session("synthetic-B")
        self.coordinator.replace_session("synthetic-A")
        self.assertEqual(self.coordinator.snapshot().epoch, 3)
        self.assert_rejected_unchanged(self.request)
        current = self.coordinator.start_request()
        self.assertTrue(self.coordinator.accept_ack(current))

    def test_same_account_replacement_advances_epoch(self):
        self.coordinator.replace_session("synthetic-A")
        self.assertEqual(self.coordinator.snapshot().epoch, 2)
        self.assert_rejected_unchanged(self.request)

    def test_logout_rejects_outstanding_ack(self):
        self.coordinator.logout()
        self.assertEqual(self.coordinator.snapshot().epoch, 2)
        self.assert_rejected_unchanged(self.request)
        with self.assertRaises(ValueError):
            self.coordinator.start_request()
        self.coordinator.logout()
        self.assertEqual(self.coordinator.snapshot().epoch, 3)
        self.coordinator.replace_session("synthetic-A")
        self.assert_rejected_unchanged(self.request)

    def test_unknown_or_mismatched_operation(self):
        other = self.coordinator.start_request()
        for forged in (
            replace(self.request, operation=999),
            replace(self.request, account="synthetic-B"),
            replace(self.request, epoch=0),
        ):
            with self.subTest(forged=forged):
                self.assert_rejected_unchanged(forged)
        self.assertTrue(self.coordinator.accept_ack(other))
        self.assertEqual(self.coordinator.snapshot().pending, {self.request})
        self.assertTrue(self.coordinator.accept_ack(self.request))

    def test_duplicate_does_not_apply_effect_twice(self):
        self.assertTrue(self.coordinator.accept_ack(self.request))
        self.assert_rejected_unchanged(self.request)
        self.assertEqual(self.coordinator.snapshot().effects, (self.request,))

    def test_negative_control_exposes_a_to_b_to_a_failure(self):
        for coordinator_type, expected in (
            (AckCoordinator, False),
            (NoEpochControl, True),
        ):
            with self.subTest(coordinator=coordinator_type.__name__):
                coordinator = coordinator_type()
                coordinator.replace_session("synthetic-A")
                old = coordinator.start_request()
                coordinator.replace_session("synthetic-B")
                coordinator.replace_session("synthetic-A")
                self.assertNotEqual(old.epoch, coordinator.snapshot().epoch)
                self.assertEqual(coordinator.accept_ack(old), expected)
                self.assertEqual(
                    coordinator.snapshot().effects, (old,) if expected else ()
                )


if __name__ == "__main__":
    unittest.main()
