"""Development-only process memory; restart loses all records and tombstones."""
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from threading import RLock
from typing import Iterator, Protocol
from uuid import UUID

from .schemas import CompletionRecordMetadata


@dataclass(frozen=True)
class StoredCompletion:
    owner_sub: UUID
    metadata: CompletionRecordMetadata
    updated_at: datetime
    delete_base: int | None = None


class CompletionStore(Protocol):
    def transaction(self): ...
    def get(self, owner: UUID, record_id: UUID) -> StoredCompletion | None: ...
    def save(self, record: StoredCompletion) -> None: ...
    def list_for_owner(self, owner: UUID) -> list[StoredCompletion]: ...


class InMemoryCompletionStore:
    def __init__(self):
        self._records: dict[tuple[UUID, UUID], StoredCompletion] = {}
        self._lock = RLock()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Serialize the entire read/compare/write, including concurrent retries."""
        with self._lock:
            yield

    def get(self, owner: UUID, record_id: UUID) -> StoredCompletion | None:
        return self._records.get((owner, record_id))

    def save(self, record: StoredCompletion) -> None:
        self._records[(record.owner_sub, record.metadata.id)] = record

    def list_for_owner(self, owner: UUID) -> list[StoredCompletion]:
        return [record for (subject, _), record in self._records.items() if subject == owner]


_store = InMemoryCompletionStore()


def get_completion_store() -> CompletionStore:
    return _store
