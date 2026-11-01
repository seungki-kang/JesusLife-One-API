"""Sequential synthetic memory tests, not HTTP/consent/deletion safety tests."""

from copy import deepcopy
from dataclasses import replace
import unittest
from unittest.mock import Mock, patch
from uuid import UUID

from app.modules.neorang_narang.real_sync_candidate import (
    CandidatePreparationFailed, IdempotencyKeyReused, InvalidCandidateInput,
    RealSyncCandidateService, SyntheticAccountContext, SyntheticMemoryStore,
    UnsupportedCandidatePath, OperationRetired, GenerationNotOpen,
)
from app.modules.neorang_narang.real_sync_schemas import RealCompletionCreate
from tests.nn_real_sync_contract import RealSyncContract
from tests.test_nn_real_sync_dto import candidate


STAMP = "2024-02-29T12:34:56.123400Z"
CANARY = "SYNTHETIC_PRIVATE_CANARY"


class RealSyncCandidateTests(RealSyncContract, unittest.TestCase):
    def setUp(self):
        self.a = SyntheticAccountContext(UUID(int=10))
        self.b = SyntheticAccountContext(UUID(int=11))
        self.store = SyntheticMemoryStore()
        self.clock = Mock(return_value=STAMP)
        self.service = RealSyncCandidateService(self.store, self.clock)
        self.command = RealCompletionCreate.model_validate(candidate())
        self.service.open_generation(self.a, 3)
        self.service.open_generation(self.b, 3)

    def state(self):
        # White-box copies for failure invariants only; no public mutable views.
        return deepcopy(self.store._SyntheticMemoryStore__state)

    def command_for(self, generation=3, operation=100, sync=101):
        data = candidate()
        data.update(consent_generation=generation, operation_id=UUID(int=operation))
        data["metadata"]["sync_id"] = UUID(int=sync)
        return RealCompletionCreate.model_validate(data)

    def test_initial_closed_and_unopened_future_reject_without_mutation(self):
        store = SyntheticMemoryStore()
        service = RealSyncCandidateService(store, self.clock)
        before = deepcopy(store._SyntheticMemoryStore__state)
        with self.assertRaisesRegex(GenerationNotOpen, "^generation_not_open$"):
            service.create(self.a, self.command)
        self.assertEqual(before, store._SyntheticMemoryStore__state)
        service.open_generation(self.a, 3)
        before = deepcopy(store._SyntheticMemoryStore__state)
        for generation in (1, 2, 4):
            with self.assertRaises(GenerationNotOpen):
                service.create(self.a, self.command_for(generation))
            self.assertEqual(before, store._SyntheticMemoryStore__state)
        self.clock.assert_not_called()
        self.assertFalse(service.create(self.a, self.command).replayed)
        self.assertTrue(service.create(self.a, self.command).replayed)

    def test_close_blocks_ack_comparison_absent_requests_and_new_generation_reuse(self):
        ack = self.service.create(self.a, self.command)
        self.service.close_generation(self.a, 3)
        before = self.state()
        for command in (self.command,
                        self.command.model_copy(update={"policy_version": CANARY}),
                        self.command_for(3), self.command_for(2)):
            with self.assertRaisesRegex(OperationRetired, "^operation_retired$"):
                self.service.create(self.a, command)
            self.assertEqual(before, self.state())
        self.assertEqual(ack.received_at, STAMP)  # caller ACK cannot reopen gate
        self.service.open_generation(self.a, 4)
        before = self.state()
        changed = self.command.model_copy(update={"consent_generation": 4})
        # Erased operation wins even with a new sync ID or unopened generation.
        for generation in (4, 5):
            data = candidate()
            data["consent_generation"] = generation
            data["metadata"]["sync_id"] = UUID(int=102)
            with self.assertRaises(OperationRetired):
                self.service.create(self.a, RealCompletionCreate.model_validate(data))
        for command in (changed, self.command_for(4, 103, self.command.metadata.sync_id.int)):
            with self.assertRaises(OperationRetired):
                self.service.create(self.a, command)
        self.assertEqual(before, self.state())
        self.assertFalse(self.service.create(self.a, self.command_for(4)).replayed)
        with self.assertRaises(OperationRetired):
            self.service.create(self.a, self.command_for(3, 104, 105))
        self.assertEqual(self.clock.call_count, 2)

    def test_open_close_ordering_monotonicity_and_no_automatic_replacement(self):
        absent = SyntheticAccountContext(UUID(int=12))
        self.service.close_generation(absent, 8)
        for generation in (1, 8):
            before = self.state()
            with self.assertRaises(OperationRetired):
                self.service.create(absent, self.command_for(generation))
            with self.assertRaises(OperationRetired):
                self.service.open_generation(absent, generation)
            self.assertEqual(before, self.state())
        before = self.state()
        self.service.open_generation(self.a, 3)
        self.assertEqual(before, self.state())
        for generation in (1, 2, 4, 9):
            with self.assertRaisesRegex(UnsupportedCandidatePath, "^unsupported_candidate_path$"):
                self.service.open_generation(self.a, generation)
            self.assertEqual(before, self.state())
        self.service.close_generation(self.a, 2)
        self.assertEqual(self.state()[3][self.a.owner], 3)
        for generation in (2, 1, 2):
            before = self.state()
            self.service.close_generation(self.a, generation)
            self.assertEqual(before, self.state())
            with self.assertRaises(OperationRetired):
                self.service.open_generation(self.a, generation)
        self.service.close_generation(self.a, 5)
        self.assertNotIn(self.a.owner, self.state()[3])
        self.assertEqual(self.state()[4][self.a.owner], 5)
        for generation in (3, 4, 5):
            with self.assertRaises(OperationRetired):
                self.service.open_generation(self.a, generation)
        self.service.open_generation(self.a, 6)
        before = self.state()
        self.service.close_generation(self.a, 4)
        self.assertEqual(before, self.state())

    def test_close_minimizes_all_old_payloads_and_preserves_high_generation_and_accounts(self):
        self.service.create(self.a, self.command)
        self.service.create(self.b, self.command)
        self.service.retire(self.a, UUID(int=110))
        records, receipts, _, _, _ = self.store._SyntheticMemoryStore__state
        original = (self.a.owner, self.command.operation_id)
        receipts[(self.a.owner, UUID(int=111))] = replace(receipts[original])
        before_b = {key: value for key, value in receipts.items() if key[0] == self.b.owner}
        self.service.close_generation(self.a, 2)
        self.assertTrue(self.service.create(self.a, self.command).replayed)
        self.service.close_generation(self.a, 3)
        records, receipts, barriers, opened, retired = self.state()
        self.assertFalse(any(key[0] == self.a.owner for key in records))
        for key, receipt in receipts.items():
            if key[0] == self.a.owner:
                self.assertEqual(type(receipt).__name__, "_ErasedReceipt")
                self.assertEqual(vars(receipt), {})
            else:
                self.assertEqual(receipt, before_b[key])
        self.assertIn((self.a.owner, UUID(int=110)), barriers)
        self.assertIn((self.a.owner, self.command.metadata.sync_id), barriers)
        self.assertEqual(opened, {self.b.owner: 3})
        self.assertEqual(retired, {self.a.owner: 3})
        self.service.open_generation(self.a, 5)
        high = self.command_for(5)
        self.service.create(self.a, high)
        before = self.state()
        self.service.close_generation(self.a, 4)
        after = self.state()
        self.assertEqual(before[:4], after[:4])
        self.assertTrue(self.service.create(self.a, high).replayed)
        self.assertTrue(self.service.create(self.b, self.command).replayed)
        # Single-record barrier persists across close/open too.
        with self.assertRaises(OperationRetired):
            self.service.create(self.a, self.command_for(5, 112, 110))

    def test_close_preparation_failure_preserves_single_state_reference_then_retries(self):
        self.service.create(self.a, self.command)
        self.service.create(self.a, self.command_for())
        self.service.create(self.b, self.command)
        before = self.state()
        reference = self.store._SyntheticMemoryStore__state
        with self.assertNoLogs(level="DEBUG"):
            with patch("app.modules.neorang_narang.real_sync_candidate._ErasedReceipt",
                       side_effect=[object(), ValueError(CANARY)]):
                with self.assertRaisesRegex(CandidatePreparationFailed,
                                            "^candidate_preparation_failed$") as caught:
                    self.service.close_generation(self.a, 3)
                self.assertNotIn(CANARY, repr(caught.exception))
        self.assertIs(reference, self.store._SyntheticMemoryStore__state)
        self.assertEqual(before, self.state())
        self.assertTrue(self.service.create(self.a, self.command).replayed)
        self.service.close_generation(self.a, 3)
        records, receipts, _, _, _ = self.state()
        self.assertNotIn((self.a.owner, self.command.metadata.sync_id), records)
        self.assertEqual(vars(receipts[(self.a.owner, self.command.operation_id)]), {})
        # A-only state has no payload, command, timestamp, generation receipt link.
        self.service.close_generation(self.b, 3)
        self.assertNotIn(STAMP, repr(self.state()))
        self.assertNotIn(self.command.model_dump_json(), repr(self.state()))

    def test_strict_internal_generation_and_context_validation(self):
        before = self.state()
        with self.assertNoLogs(level="DEBUG"):
            for value in (True, False, "3", CANARY, 3.0, 0, -1, None):
                for action in (self.service.open_generation, self.service.close_generation):
                    with self.assertRaisesRegex(InvalidCandidateInput, "^invalid_candidate_input$"):
                        action(self.a, value)
                with self.assertRaises(InvalidCandidateInput):
                    self.service.create(self.a, self.command.model_copy(
                        update={"consent_generation": value}))
                self.assertEqual(before, self.state())
            for context in (None, {"owner": CANARY}, SyntheticAccountContext(CANARY)):
                for action in (self.service.open_generation, self.service.close_generation):
                    with self.assertRaises(InvalidCandidateInput):
                        action(context, 3)
                    self.assertEqual(before, self.state())
        self.clock.assert_not_called()


    def test_memory_replay_and_conflicts_preserve_private_snapshot(self):
        self.service.create(self.a, self.command)
        before = self.state()
        for _ in range(3):
            self.service.create(self.a, self.command)
            self.assertEqual(before, self.state())
        for changes, error in (({"policy_version": CANARY}, IdempotencyKeyReused),
                               ({"operation_id": UUID(int=40)}, UnsupportedCandidatePath)):
            with self.assertRaises(error):
                self.service.create(self.a, self.command.model_copy(update=changes))
            self.assertEqual(before, self.state())
        self.assertEqual(self.store.counts(self.a), (1, 1))

    def test_memory_private_counts_for_normalization_accounts_and_distinct_ids(self):
        self.service.create(self.a, self.command)
        normalized = RealCompletionCreate.model_validate_json(self.command.model_dump_json())
        self.service.create(self.a, normalized)
        self.assertEqual(self.store.counts(self.a), (1, 1))
        self.service.create(self.b, self.command)
        self.assertEqual(self.store.counts(self.b), (1, 1))
        self.service.create(self.a, self.command_for())
        self.assertEqual(self.store.counts(self.a), (2, 2))
        self.assertEqual(self.store.counts(self.b), (1, 1))

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
        records, _, _, _, _ = self.store._SyntheticMemoryStore__state
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
        records, receipts, _, _, _ = self.store._SyntheticMemoryStore__state
        # Create only supports one receipt per record. Simulate another historical
        # create receipt to prove minimization scans all matching operations.
        key = (self.a.owner, self.command.operation_id)
        receipts[(self.a.owner, UUID(int=82))] = replace(receipts[key])
        command_json = records[(self.a.owner, self.command.metadata.sync_id)].command_json
        self.service.retire(self.a, self.command.metadata.sync_id)
        records, receipts, barriers, _, _ = self.state()
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
