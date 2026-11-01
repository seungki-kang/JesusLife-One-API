"""Reusable observable contract. No DB engine, private state or constructor patches.

Harness supplies service: RealSyncRepository, clock, a/b contexts, command and
opens generation 3 in setUp. Future authorized MySQL harness can inherit this
mixin. Scripted SQL unit tests MUST NOT be counted as this MySQL contract.
"""
from uuid import UUID

from app.modules.neorang_narang.real_sync_repository import (
    IdempotencyKeyReused, InvalidCandidateInput, OperationRetired,
    UnsupportedCandidatePath,
)
from app.modules.neorang_narang.real_sync_schemas import RealCompletionCreate
from tests.test_nn_real_sync_dto import candidate

STAMP = "2024-02-29T12:34:56.123400Z"
CANARY = "SYNTHETIC_PRIVATE_CANARY"


class RealSyncContract:
    def test_initial_minimal_ack(self):
        ack = self.service.create(self.a, self.command)
        self.assertEqual(ack.model_dump(mode="json"), {
            "operation_id": candidate()["operation_id"],
            "sync_id": candidate()["metadata"]["sync_id"],
            "applied_revision": 1, "current_revision": 1,
            "replayed": False, "received_at": STAMP,
        })

    def test_retry_after_lost_response_and_repeated_replay(self):
        first = self.service.create(self.a, self.command)
        self.clock.side_effect = RuntimeError(CANARY)
        for _ in range(3):
            ack = self.service.create(self.a, self.command)
            self.assertTrue(ack.replayed)
            self.assertEqual(ack.model_dump(exclude={"replayed"}),
                             first.model_dump(exclude={"replayed"}))
        self.clock.assert_called_once_with()

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

    def test_each_valid_command_field_change_conflicts(self):
        self.service.create(self.a, self.command)
        changes = (("policy_version", CANARY),
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
        # base_revision has only one valid value; bypass changes must be rejected.
        with self.assertRaises(InvalidCandidateInput):
            self.service.create(self.a, self.command.model_copy(update={"base_revision": 1}))

    def test_other_operation_same_sync_is_unsupported_even_if_content_changes(self):
        self.service.create(self.a, self.command)
        for course in (1, 2):
            data = candidate()
            data["operation_id"] = UUID(int=40)
            data["metadata"]["course_number"] = course
            with self.assertRaisesRegex(UnsupportedCandidatePath,
                                        "^unsupported_candidate_path$"):
                self.service.create(self.a, RealCompletionCreate.model_validate(data))
        self.clock.assert_called_once_with()

    def test_account_isolation_same_uuids_and_different_content(self):
        self.service.create(self.a, self.command)
        data = candidate()
        data["policy_version"] = CANARY
        other = RealCompletionCreate.model_validate(data)
        self.assertFalse(self.service.create(self.b, other).replayed)
        self.assertTrue(self.service.create(self.b, other).replayed)
        self.assertTrue(self.service.create(self.a, self.command).replayed)
        with self.assertRaises(IdempotencyKeyReused):
            self.service.create(self.a, other)
        self.assertTrue(self.service.create(self.b, other).replayed)

    def test_same_date_course_distinct_ids_never_merge(self):
        self.service.create(self.a, self.command)
        data = candidate()
        data["operation_id"] = UUID(int=50)
        data["metadata"]["sync_id"] = UUID(int=51)
        other = RealCompletionCreate.model_validate(data)
        self.assertFalse(self.service.create(self.a, other).replayed)
        self.assertTrue(self.service.create(self.a, self.command).replayed)
        self.assertTrue(self.service.create(self.a, other).replayed)

    def test_contract_retire_precedes_conflict_and_blocks_new_operation(self):
        self.service.create(self.a, self.command)
        self.service.retire(self.a, self.command.metadata.sync_id)
        for command in (self.command, self.command.model_copy(update={"policy_version": "changed"}),
                        self.command.model_copy(update={"operation_id": UUID(int=800)})):
            with self.assertRaises(OperationRetired):
                self.service.create(self.a, command)
        self.assertFalse(self.service.create(self.b, self.command).replayed)

    def test_contract_generation_close_before_open_and_monotonicity(self):
        self.service.close_generation(self.a, 5)
        for generation in (3, 4, 5):
            with self.assertRaises(OperationRetired):
                self.service.open_generation(self.a, generation)
        self.service.open_generation(self.a, 6)
        self.service.close_generation(self.a, 4)
        data = candidate()
        data["consent_generation"] = 6
        command = RealCompletionCreate.model_validate(data)
        self.assertFalse(self.service.create(self.a, command).replayed)
        self.assertTrue(self.service.create(self.a, command).replayed)
        self.assertFalse(self.service.create(self.b, self.command).replayed)

    def test_contract_absent_retire_is_permanent_across_generations(self):
        self.service.retire(self.a, self.command.metadata.sync_id)
        self.service.close_generation(self.a, 3)
        self.service.open_generation(self.a, 4)
        with self.assertRaises(OperationRetired):
            self.service.create(self.a, self.command.model_copy(update={"consent_generation": 4}))
