"""Unconnected synthetic repository contract; no authentication or Core grants.

Fixed public errors never contain inputs, driver errors or SQL. No automatic
retry: StorageRetryable permits caller bounded retry of the SAME command on a
fresh connection after confirmed rollback. TransactionOutcomeUnknown requires
same-command reconciliation; never issue a replacement ID. CleanupFailed means
commit was confirmed but resource disposal failed (outcome='committed').
Do not log exception traceback locals, DTOs, SQL parameters or driver objects.
MySQL errors also expose fixed outcome (not_started/rolled_back/unknown/committed)
and cleanup_failed bool, independently of the domain/storage error code.
"""
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from .real_sync_schemas import RealCompletionAck, RealCompletionCreate, RealCompletionMetadata


class InvalidCandidateInput(ValueError):
    def __init__(self):
        super().__init__("invalid_candidate_input")


class IdempotencyKeyReused(ValueError):
    def __init__(self):
        super().__init__("idempotency_key_reused")


class OperationRetired(ValueError):
    def __init__(self):
        super().__init__("operation_retired")


class UnsupportedCandidatePath(ValueError):
    def __init__(self):
        super().__init__("unsupported_candidate_path")


class CandidatePreparationFailed(ValueError):
    def __init__(self):
        super().__init__("candidate_preparation_failed")


class GenerationNotOpen(ValueError):
    def __init__(self):
        super().__init__("generation_not_open")


@dataclass(frozen=True, repr=False)
class SyntheticAccountContext:
    """Explicit test identity boundary; NOT an authentication result."""

    owner: UUID


class StorageFailed(ValueError):
    def __init__(self):
        super().__init__("storage_failed")


class StorageIntegrityFailed(ValueError):
    def __init__(self):
        super().__init__("storage_integrity_failed")


class StorageRetryable(ValueError):
    def __init__(self):
        super().__init__("storage_retryable")


class TransactionOutcomeUnknown(ValueError):
    def __init__(self):
        super().__init__("transaction_outcome_unknown")


class CleanupFailed(ValueError):
    outcome = "committed"

    def __init__(self):
        super().__init__("cleanup_failed_after_commit")


def _owner(context: SyntheticAccountContext) -> UUID:
    if type(context) is not SyntheticAccountContext or type(context.owner) is not UUID:
        raise InvalidCandidateInput()
    return context.owner


def _generation(value: int) -> int:
    # Internal PROPOSED ordering only; does not grant consent/policy authority.
    if type(value) is not int or value <= 0:
        raise InvalidCandidateInput()
    return value


def _command(command: RealCompletionCreate) -> RealCompletionCreate:
    try:
        if (type(command) is not RealCompletionCreate
                or type(command.metadata) is not RealCompletionMetadata):
            raise InvalidCandidateInput()
        raw = dict(vars(command))
        raw["metadata"] = dict(vars(command.metadata))
        if command.model_extra or command.metadata.model_extra:
            raise InvalidCandidateInput()
        validated = RealCompletionCreate.model_validate(raw)
        _generation(validated.consent_generation)
    except Exception:
        raise InvalidCandidateInput() from None
    return validated


class RealSyncRepository(Protocol):
    def create(self, context: SyntheticAccountContext,
               command: RealCompletionCreate) -> RealCompletionAck: ...
    def retire(self, context: SyntheticAccountContext, sync_id: UUID) -> None: ...
    def open_generation(self, context: SyntheticAccountContext, generation: int) -> None: ...
    def close_generation(self, context: SyntheticAccountContext, generation: int) -> None: ...
