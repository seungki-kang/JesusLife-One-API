"""Sequential synthetic memory tests, not HTTP/consent/deletion safety tests."""

from copy import deepcopy
from dataclasses import replace
import unittest
from unittest.mock import Mock, patch
from uuid import UUID

from app.modules.neorang_narang.real_sync_candidate import (
    CandidatePreparationFailed, IdempotencyKeyReused, InvalidCandidateInput,
    RealSyncCandidateService, SyntheticAccountContext, SyntheticMemoryStore,
    UnsupportedCandidatePath, OperationRetired,
)
from app.modules.neorang_narang.real_sync_schemas import RealCompletionCreate
from tests.test_nn_real_sync_dto import candidate


STAMP = "2024-02-29T12:34:56.123400Z"
CANARY = "SYNTHETIC_PRIVATE_CANARY"


class RealSyncCandidateTests(unittest.TestCase):
    def setUp(self):
        self.a = SyntheticAccountContext(UUID(int=10))
        self.b = SyntheticAccountContext(UUID(int=11))
        self.store = SyntheticMemoryStore()
        self.clock = Mock(return_value=STAMP)
        self.service = RealSyncCandidateService(self.store, self.clock)
        self.command = RealCompletionCreate.model_validate(candidate())

    def state(self):
        # White-box copies for failure invariants only; no public mutable views.
        return deepcopy(self.store._SyntheticMemoryStore__state)

    def test_initial_minimal_ack(self):
        ack = self.service.create(self.a, self.command)
        self.assertEqual(self.store.counts(self.a), (1, 1))
        self.assertEqual(ack.model_dump(mode="json"), {
            "operation_id": candidate()["operation_id"],
            "sync_id": candidate()["metadata"]["sync_id"],
            "applied_revision": 1, "current_revision": 1,
            "replayed": False, "received_at": STAMP,
        })

    def test_retry_after_lost_response_and_repeated_replay(self):
        first = self.service.create(self.a, self.command)
        before = self.state()
        self.clock.side_effect = RuntimeError(CANARY)
        for _ in range(3):
            ack = self.service.create(self.a, self.command)
            self.assertTrue(ack.replayed)
            self.assertEqual(ack.model_dump(exclude={"replayed"}),
                             first.model_dump(exclude={"replayed"}))
        self.clock.assert_called_once_with()
        self.assertEqual(before, self.state())
        self.assertEqual(self.store.counts(self.a), (1, 1))

    def test_uuid_normalization_replays(self):
        data = candidate()
        value = "abcdefab-cdef-1abc-8abc-abcdefabcdef"
        data["operation_id"] = data["metadata"]["sync_id"] = value
        first = self.service.create(self.a, RealCompletionCreate.model_validate(data))
        for form in (value.upper(), value.replace("-", ""), UUID(value)):
            data["operation_id"] = data["metadata"]["sync_id"] = form
            ack = self.service.create(self.a, RealCompletionCreate.model_validate(data))
            self.assertTrue(ack.replayed)
            self.assertEqual(first.operation_id, ack.operation_id)
        self.assertEqual(self.store.counts(self.a), (1, 1))

    def test_each_valid_command_field_change_conflicts(self):
        self.service.create(self.a, self.command)
        before = self.state()
        changes = (("consent_generation", 4), ("policy_version", CANARY),
                   ("sync_id", UUID(int=30)), ("course_number", 2),
                   ("completed_on", "2024-03-01"))
        for field, value in changes:
            with self.subTest(field=field):
                data = candidate()
                target = data["metadata"] if field in data["metadata"] else data
                target[field] = value
                with self.assertRaisesRegex(IdempotencyKeyReused,
                                            "^idempotency_key_reused$"):
                    self.service.create(self.a, RealCompletionCreate.model_validate(data))
                self.assertEqual(before, self.state())
        # base_revision has only one valid value; bypass changes must be rejected.
        with self.assertRaises(InvalidCandidateInput):
            self.service.create(self.a, self.command.model_copy(update={"base_revision": 1}))
        self.assertEqual(before, self.state())

    def test_other_operation_same_sync_is_unsupported_even_if_content_changes(self):
        self.service.create(self.a, self.command)
        before = self.state()
        for course in (1, 2):
            data = candidate()
            data["operation_id"] = UUID(int=40)
            data["metadata"]["course_number"] = course
            with self.assertRaisesRegex(UnsupportedCandidatePath,
                                        "^unsupported_candidate_path$"):
                self.service.create(self.a, RealCompletionCreate.model_validate(data))
            self.assertEqual(before, self.state())
        self.clock.assert_called_once_with()

    def test_account_isolation_same_uuids_and_different_content(self):
        self.service.create(self.a, self.command)
        data = candidate()
        data["policy_version"] = CANARY
        other = RealCompletionCreate.model_validate(data)
        self.assertFalse(self.service.create(self.b, other).replayed)
        self.assertTrue(self.service.create(self.b, other).replayed)
        self.assertTrue(self.service.create(self.a, self.command).replayed)
        self.assertEqual(self.store.counts(self.a), (1, 1))
        self.assertEqual(self.store.counts(self.b), (1, 1))
        with self.assertRaises(IdempotencyKeyReused):
            self.service.create(self.a, other)
        self.assertTrue(self.service.create(self.b, other).replayed)

    def test_same_date_course_distinct_ids_never_merge(self):
        self.service.create(self.a, self.command)
        data = candidate()
        data["operation_id"] = UUID(int=50)
        data["metadata"]["sync_id"] = UUID(int=51)
        self.assertFalse(self.service.create(self.a, RealCompletionCreate.model_validate(data)).replayed)
        self.assertEqual(self.store.counts(self.a), (2, 2))

    def test_bad_clock_and_ack_construction_leave_no_partial_state(self):
        for value in (CANARY, None, 123, "2024-02-30T00:00:00Z"):
            with self.subTest(value=value):
                self.clock.return_value = value
                with self.assertRaisesRegex(CandidatePreparationFailed,
                                            "^candidate_preparation_failed$"):
                    self.service.create(self.a, self.command)
                self.assertEqual(self.store.counts(self.a), (0, 0))
        self.clock.side_effect = RuntimeError(CANARY)
        with self.assertRaises(CandidatePreparationFailed):
            self.service.create(self.a, self.command)
        self.assertEqual(self.store.counts(self.a), (0, 0))
        self.clock.side_effect = None
        self.clock.return_value = STAMP
        with patch("app.modules.neorang_narang.real_sync_candidate.RealCompletionAck",
                   side_effect=ValueError(CANARY)):
            with self.assertRaises(CandidatePreparationFailed):
                self.service.create(self.a, self.command)
        self.assertEqual(self.store.counts(self.a), (0, 0))
        self.assertFalse(self.service.create(self.a, self.command).replayed)

    def test_invalid_bypass_inputs_are_revalidated_without_state_changes(self):
        invalid = [self.command.model_copy(update={"consent_generation": True}),
                   self.command.model_copy(update={"policy_version": CANARY, "base_revision": 9}),
                   self.command.model_copy(update={"extra": CANARY}),
                   RealCompletionCreate.model_construct(**candidate()),
                   self.command.model_copy(update={"metadata":
                       self.command.metadata.model_copy(update={"completed_on": CANARY})})]
        for command in invalid:
            with self.subTest():
                with self.assertRaisesRegex(InvalidCandidateInput, "^invalid_candidate_input$"):
                    self.service.create(self.a, command)
                self.assertEqual(self.store.counts(self.a), (0, 0))
        self.clock.assert_not_called()

    def test_input_and_response_mutations_do_not_change_snapshots(self):
        original = RealCompletionCreate.model_validate(candidate())
        ack = self.service.create(self.a, self.command)
        before = self.state()
        # Deliberately bypass frozen safeguards, mimicking hostile local mutation.
        self.command.metadata.__dict__["course_number"] = 2
        self.command.__dict__["policy_version"] = CANARY
        ack.__dict__["received_at"] = CANARY
        ack.__dict__["operation_id"] = UUID(int=99)
        self.assertEqual(before, self.state())
        replay = self.service.create(self.a, original)
        self.assertEqual(replay.received_at, STAMP)
        self.assertEqual(replay.operation_id, original.operation_id)
        with self.assertRaises(IdempotencyKeyReused):
            self.service.create(self.a, self.command)
        self.assertEqual(before, self.state())

    def test_current_revision_is_read_from_record_not_receipt(self):
        self.service.create(self.a, self.command)
        # No update API is implemented. White-box simulate a later record state.
        records, _, _ = self.store._SyntheticMemoryStore__state
        key = (self.a.owner, self.command.metadata.sync_id)
        records[key] = replace(records[key], revision=4)
        ack = self.service.create(self.a, self.command)
        self.assertEqual((ack.applied_revision, ack.current_revision), (1, 4))
        self.assertEqual(ack.received_at, STAMP)

    def test_explicit_context_required_and_no_canary_in_errors_or_logs(self):
        with self.assertNoLogs(level="DEBUG"):
            for context in (None, {"owner": CANARY}, SyntheticAccountContext(CANARY)):
                with self.assertRaises(InvalidCandidateInput) as caught:
                    self.service.create(context, self.command)
                self.assertEqual(str(caught.exception), "invalid_candidate_input")
                self.assertNotIn(CANARY, repr(caught.exception))
            self.clock.side_effect = RuntimeError(CANARY)
            with self.assertRaises(CandidatePreparationFailed) as caught:
                self.service.create(self.a, self.command)
            self.assertEqual(str(caught.exception), "candidate_preparation_failed")
            self.assertNotIn(CANARY, repr(caught.exception))
            self.clock.side_effect = None
            self.service.create(self.a, self.command)
            changed = self.command.model_copy(update={"policy_version": CANARY})
            with self.assertRaises(IdempotencyKeyReused) as caught:
                self.service.create(self.a, changed)
            self.assertEqual(str(caught.exception), "idempotency_key_reused")

    def test_retired_operation_rejects_original_and_valid_changes_before_comparison(self):
        self.service.create(self.a, self.command)
        self.assertIsNone(self.service.retire(self.a, self.command.metadata.sync_id))
        before = self.state()
        changes = ({}, {"consent_generation": 4}, {"policy_version": CANARY},
                   {"metadata": {**candidate()["metadata"], "sync_id": str(UUID(int=80))}},
                   {"metadata": {**candidate()["metadata"], "course_number": 2}},
                   {"metadata": {**candidate()["metadata"], "completed_on": "2024-03-01"}})
        with self.assertNoLogs(level="DEBUG"):
            for change in changes:
                command = RealCompletionCreate.model_validate({**candidate(), **change})
                with self.assertRaisesRegex(OperationRetired, "^operation_retired$") as caught:
                    self.service.create(self.a, command)
                self.assertNotIn(CANARY, repr(caught.exception))
                self.assertEqual(before, self.state())
        self.clock.assert_called_once_with()

    def test_barrier_blocks_new_operation_and_absent_id_late_create(self):
        for present in (False, True):
            with self.subTest(present=present):
                self.setUp()
                if present:
                    self.service.create(self.a, self.command)
                self.service.retire(self.a, self.command.metadata.sync_id)
                before = self.state()
                data = candidate()
                data["operation_id"] = UUID(int=81)
                with self.assertRaisesRegex(OperationRetired, "^operation_retired$"):
                    self.service.create(self.a, RealCompletionCreate.model_validate(data))
                self.assertEqual(before, self.state())
                self.assertEqual(self.clock.call_count, int(present))

    def test_retire_minimizes_all_receipts_and_repeat_preserves_whole_state(self):
        first = self.service.create(self.a, self.command)
        records, receipts, _ = self.store._SyntheticMemoryStore__state
        # Create only supports one receipt per record. Simulate another historical
        # create receipt to prove minimization scans all matching operations.
        key = (self.a.owner, self.command.operation_id)
        receipts[(self.a.owner, UUID(int=82))] = replace(receipts[key])
        command_json = records[(self.a.owner, self.command.metadata.sync_id)].command_json
        self.service.retire(self.a, self.command.metadata.sync_id)
        records, receipts, barriers = self.state()
        self.assertEqual(records, {})
        self.assertEqual(barriers, {(self.a.owner, self.command.metadata.sync_id)})
        self.assertEqual(set(receipts), {key, (self.a.owner, UUID(int=82))})
        for receipt in receipts.values():
            self.assertEqual(type(receipt).__name__, "_ErasedReceipt")
            self.assertEqual(vars(receipt), {})
        self.assertNotIn(command_json, repr(self.state()))
        self.assertNotIn(STAMP, repr(self.state()))
        self.assertEqual(self.store.counts(self.a), (0, 2))
        before = self.state()
        for _ in range(3):
            self.service.retire(self.a, self.command.metadata.sync_id)
            self.assertEqual(before, self.state())
        # Previously returned ACK/input remain caller-owned; no physical erasure.
        self.assertEqual(first.received_at, STAMP)
        self.assertEqual(self.command.metadata.completed_on, candidate()["metadata"]["completed_on"])

    def test_retire_isolates_accounts_and_unrelated_records(self):
        self.service.create(self.a, self.command)
        self.service.create(self.b, self.command)
        data = candidate()
        data["operation_id"] = UUID(int=83)
        data["metadata"]["sync_id"] = UUID(int=84)
        unrelated = RealCompletionCreate.model_validate(data)
        self.service.create(self.a, unrelated)
        before = self.state()
        self.service.retire(self.a, self.command.metadata.sync_id)
        after = self.state()
        for index in (0, 1):
            for key, value in before[index].items():
                if key[0] == self.b.owner or key[1] in (UUID(int=83), UUID(int=84)):
                    self.assertEqual(after[index][key], value)
        self.assertTrue(self.service.create(self.b, self.command).replayed)
        self.assertTrue(self.service.create(self.a, unrelated).replayed)
        absent = UUID(int=85)
        self.service.retire(self.a, absent)
        data["operation_id"] = UUID(int=86)
        data["metadata"]["sync_id"] = absent
        self.assertFalse(self.service.create(self.b, RealCompletionCreate.model_validate(data)).replayed)
        self.assertEqual(self.store.counts(self.b), (2, 2))

    def test_retire_preparation_failure_preserves_whole_state_then_recovers(self):
        self.service.create(self.a, self.command)
        self.service.create(self.b, self.command)
        before = self.state()
        with self.assertNoLogs(level="DEBUG"):
            with patch("app.modules.neorang_narang.real_sync_candidate._ErasedReceipt",
                       side_effect=ValueError(CANARY)):
                with self.assertRaisesRegex(CandidatePreparationFailed,
                                            "^candidate_preparation_failed$") as caught:
                    self.service.retire(self.a, self.command.metadata.sync_id)
                self.assertNotIn(CANARY, repr(caught.exception))
        self.assertEqual(before, self.state())
        self.service.retire(self.a, self.command.metadata.sync_id)
        with self.assertRaises(OperationRetired):
            self.service.create(self.a, self.command)

    def test_retire_invalid_identifiers_preserve_whole_state(self):
        self.service.create(self.a, self.command)
        before = self.state()
        with self.assertNoLogs(level="DEBUG"):
            for context, sync_id in (
                (None, self.command.metadata.sync_id),
                ({"owner": CANARY}, self.command.metadata.sync_id),
                (SyntheticAccountContext(CANARY), self.command.metadata.sync_id),
                (self.a, str(self.command.metadata.sync_id)),
                (self.a, CANARY), (self.a, None), (self.a, 1), (self.a, True),
            ):
                with self.assertRaisesRegex(InvalidCandidateInput,
                                            "^invalid_candidate_input$") as caught:
                    self.service.retire(context, sync_id)
                self.assertNotIn(CANARY, repr(caught.exception))
                self.assertEqual(before, self.state())


if __name__ == "__main__":
    unittest.main()
