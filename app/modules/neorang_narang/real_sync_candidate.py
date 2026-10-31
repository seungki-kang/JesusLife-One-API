"""Unconnected synthetic candidate. NEVER use for real collection.

No authentication, consent/policy approval, withdrawal/deletion fences,
retention, persistence or restart recovery. One instance, sequential calls
only (including a non-reentrant injected clock); no concurrency guarantee.
Python private state is an encapsulation boundary, not a sandbox against
hostile code/reflection. No app, Core, configuration or HTTP dependencies.
"""

from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from .real_sync_schemas import (
    RealCompletionAck, RealCompletionCreate, RealCompletionMetadata,
)


class InvalidCandidateInput(ValueError):
    def __init__(self):
        super().__init__("invalid_candidate_input")


class IdempotencyKeyReused(ValueError):
    def __init__(self):
        super().__init__("idempotency_key_reused")


class UnsupportedCandidatePath(ValueError):
    def __init__(self):
        super().__init__("unsupported_candidate_path")


class CandidatePreparationFailed(ValueError):
    def __init__(self):
        super().__init__("candidate_preparation_failed")


@dataclass(frozen=True, repr=False)
class SyntheticAccountContext:
    """Explicit test identity boundary; NOT an authentication result."""

    owner: UUID


@dataclass(frozen=True, repr=False)
class _Record:
    command_json: str
    revision: int


@dataclass(frozen=True, repr=False)
class _Receipt:
    command_json: str
    sync_id: UUID
    applied_revision: int
    received_at: str


class SyntheticMemoryStore:
    """Private snapshots; no public record/receipt/dict references escape.

    Preparing copies then swapping one state reference prevents partial writes
    on preparation failure. This is NOT a durable DB transaction, crash recovery
    mechanism, or thread/process lock. Only the candidate service writes here.
    """

    def __init__(self):
        self.__state: tuple[dict, dict] = ({}, {})

    def counts(self, context: SyntheticAccountContext) -> tuple[int, int]:
        owner = _owner(context)
        records, receipts = self.__state
        return (sum(key[0] == owner for key in records),
                sum(key[0] == owner for key in receipts))

    def _apply(self, owner: UUID, command: RealCompletionCreate,
               clock: Callable[[], str]) -> RealCompletionAck:
        records, receipts = self.__state
        operation_key = (owner, command.operation_id)
        record_key = (owner, command.metadata.sync_id)
        snapshot = command.model_dump_json()
        receipt = receipts.get(operation_key)
        if receipt is not None:
            if snapshot != receipt.command_json:
                raise IdempotencyKeyReused()
            current = records[(owner, receipt.sync_id)]
            return RealCompletionAck(
                operation_id=command.operation_id, sync_id=receipt.sync_id,
                applied_revision=receipt.applied_revision,
                current_revision=current.revision, replayed=True,
                received_at=receipt.received_at,
            )
        if record_key in records:
            raise UnsupportedCandidatePath()

        # All fallible construction precedes publication. No clock on replay.
        ack = RealCompletionAck(
            operation_id=command.operation_id, sync_id=command.metadata.sync_id,
            applied_revision=1, current_revision=1, replayed=False,
            received_at=clock(),
        )
        next_records = records.copy()
        next_receipts = receipts.copy()
        next_records[record_key] = _Record(snapshot, 1)
        next_receipts[operation_key] = _Receipt(
            snapshot, command.metadata.sync_id, 1, ack.received_at,
        )
        self.__state = (next_records, next_receipts)
        return ack


def _owner(context: SyntheticAccountContext) -> UUID:
    if type(context) is not SyntheticAccountContext or type(context.owner) is not UUID:
        raise InvalidCandidateInput()
    return context.owner


class RealSyncCandidateService:
    """Synthetic create/replay only; real collection BLOCKED.

    Callers explicitly supply context, store and clock. No authority is inferred
    from generation/policy fields. DTO instances alone are not trusted: construct,
    copy(update=...) and mutable __dict__ can bypass frozen model validation.
    Rebuild exact DTO types from their raw fields and revalidate nested metadata.
    Reject subclasses/custom serializers; never serialize validation errors.
    """

    def __init__(self, store: SyntheticMemoryStore, clock: Callable[[], str]):
        self.__store = store
        self.__clock = clock

    def create(self, context: SyntheticAccountContext,
               command: RealCompletionCreate) -> RealCompletionAck:
        owner = _owner(context)
        try:
            if (type(command) is not RealCompletionCreate
                    or type(command.metadata) is not RealCompletionMetadata):
                raise InvalidCandidateInput()
            raw = dict(vars(command))
            raw["metadata"] = dict(vars(command.metadata))
            if command.model_extra or command.metadata.model_extra:
                raise InvalidCandidateInput()
            validated = RealCompletionCreate.model_validate(raw)
        except Exception:
            raise InvalidCandidateInput() from None
        try:
            return self.__store._apply(owner, validated, self.__clock)
        except (IdempotencyKeyReused, UnsupportedCandidatePath):
            raise
        except Exception:
            # Clock/ACK errors may contain inputs; do not expose their messages.
            raise CandidatePreparationFailed() from None
