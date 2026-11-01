"""Unconnected synthetic candidate. NEVER use for real collection.

No authentication, consent/policy approval or distributed withdrawal fences,
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


# Re-export established imports for compatibility.
from .real_sync_repository import (
    CandidatePreparationFailed, GenerationNotOpen, IdempotencyKeyReused,
    InvalidCandidateInput, OperationRetired, SyntheticAccountContext,
    UnsupportedCandidatePath, _command, _generation, _owner,
)


@dataclass(frozen=True, repr=False)
class _Record:
    command_json: str
    revision: int
    generation: int


@dataclass(frozen=True, repr=False)
class _Receipt:
    command_json: str
    sync_id: UUID
    applied_revision: int
    received_at: str
    generation: int


@dataclass(frozen=True, repr=False)
class _ErasedReceipt:
    """Only the owner/operation dict key and this state marker survive."""


class SyntheticMemoryStore:
    """Private snapshots; no public record/receipt/dict references escape.

    Preparing copies then swapping one state reference prevents partial writes
    on preparation failure. This is NOT a durable DB transaction, crash recovery
    mechanism, or thread/process lock. Only the candidate service writes here.
    """

    def __init__(self):
        # records, receipts, permanent sync barriers, open g, retired-through.
        self.__state: tuple[dict, dict, frozenset, dict, dict] = (
            {}, {}, frozenset(), {}, {},
        )

    def counts(self, context: SyntheticAccountContext) -> tuple[int, int]:
        owner = _owner(context)
        # Receipt count includes erased markers; barriers are not counted.
        records, receipts, _, _, _ = self.__state
        return (sum(key[0] == owner for key in records),
                sum(key[0] == owner for key in receipts))

    def _apply(self, owner: UUID, command: RealCompletionCreate,
               clock: Callable[[], str]) -> RealCompletionAck:
        records, receipts, barriers, opened, retired = self.__state
        operation_key = (owner, command.operation_id)
        record_key = (owner, command.metadata.sync_id)
        receipt = receipts.get(operation_key)
        if isinstance(receipt, _ErasedReceipt):
            raise OperationRetired()
        if record_key in barriers:
            raise OperationRetired()
        generation = command.consent_generation
        if generation <= retired.get(owner, 0):
            raise OperationRetired()
        if opened.get(owner) != generation:
            raise GenerationNotOpen()
        snapshot = command.model_dump_json()
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
        next_records[record_key] = _Record(snapshot, 1, generation)
        next_receipts[operation_key] = _Receipt(
            snapshot, command.metadata.sync_id, 1, ack.received_at, generation,
        )
        self.__state = (next_records, next_receipts, barriers, opened, retired)
        return ack

    def _retire(self, owner: UUID, sync_id: UUID) -> None:
        records, receipts, barriers, opened, retired = self.__state
        record_key = (owner, sync_id)
        next_records = records.copy()
        next_receipts = receipts.copy()
        next_barriers = barriers | {record_key}
        next_records.pop(record_key, None)
        for key, receipt in receipts.items():
            if (key[0] == owner and isinstance(receipt, _Receipt)
                    and receipt.sync_id == sync_id):
                next_receipts[key] = _ErasedReceipt()
        # No fallible preparation after publication; no revision/HTTP meaning.
        self.__state = (next_records, next_receipts, next_barriers, opened, retired)

    def _open(self, owner: UUID, generation: int) -> None:
        records, receipts, barriers, opened, retired = self.__state
        if generation <= retired.get(owner, 0):
            raise OperationRetired()
        current = opened.get(owner)
        if current == generation:
            return
        if current is not None:
            raise UnsupportedCandidatePath()
        next_opened = opened.copy()
        next_opened[owner] = generation
        self.__state = (records, receipts, barriers, next_opened, retired)

    def _close(self, owner: UUID, generation: int) -> None:
        records, receipts, barriers, opened, retired = self.__state
        boundary = max(generation, retired.get(owner, 0))
        next_records = records.copy()
        next_receipts = receipts.copy()
        next_barriers = barriers
        next_opened = opened.copy()
        next_retired = retired.copy()
        next_retired[owner] = boundary
        if opened.get(owner, boundary + 1) <= boundary:
            next_opened.pop(owner, None)
        for key, record in records.items():
            if key[0] == owner and record.generation <= boundary:
                del next_records[key]
                next_barriers = next_barriers | {key}
        for key, receipt in receipts.items():
            if (key[0] == owner and isinstance(receipt, _Receipt)
                    and receipt.generation <= boundary):
                next_barriers = next_barriers | {(owner, receipt.sync_id)}
                next_receipts[key] = _ErasedReceipt()
        # Boundary, cleanup and barriers publish together; no clock or ACK.
        self.__state = (next_records, next_receipts, next_barriers,
                        next_opened, next_retired)


class RealSyncCandidateService:
    """Synthetic create/replay/retire only; real collection BLOCKED.

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
        validated = _command(command)
        try:
            return self.__store._apply(owner, validated, self.__clock)
        except (IdempotencyKeyReused, UnsupportedCandidatePath, OperationRetired,
                GenerationNotOpen):
            raise
        except Exception:
            # Clock/ACK errors may contain inputs; do not expose their messages.
            raise CandidatePreparationFailed() from None

    def open_generation(self, context: SyntheticAccountContext, generation: int) -> None:
        """Explicit synthetic gate only; NOT consent or policy approval."""
        owner = _owner(context)
        generation = _generation(generation)
        try:
            self.__store._open(owner, generation)
        except (OperationRetired, UnsupportedCandidatePath):
            raise
        except Exception:
            raise CandidatePreparationFailed() from None

    def close_generation(self, context: SyntheticAccountContext, generation: int) -> None:
        """Synthetic gate/cleanup only; NOT Core A/F/D or full withdrawal."""
        owner = _owner(context)
        generation = _generation(generation)
        try:
            self.__store._close(owner, generation)
        except Exception:
            raise CandidatePreparationFailed() from None

    def retire(self, context: SyntheticAccountContext, sync_id: UUID) -> None:
        """Internal synthetic transition, NOT authorized user deletion.

        No default authority grant, delete operation/base/revision or HTTP ACK.
        Removes owned live references, not physical memory or caller snapshots.
        """
        owner = _owner(context)
        if type(sync_id) is not UUID:
            raise InvalidCandidateInput()
        try:
            self.__store._retire(owner, sync_id)
        except Exception:
            raise CandidatePreparationFailed() from None
