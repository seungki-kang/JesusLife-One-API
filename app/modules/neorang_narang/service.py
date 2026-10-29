"""Owner-scoped metadata operations; no identity or sensitive content in errors."""
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from app.core.auth import AuthContext, require_record_owner
from .schemas import CompletionRecordMetadata, CompletionResult
from .store import CompletionStore, StoredCompletion


def fail(status: int, detail: str):
    raise HTTPException(status_code=status, detail=detail)


class CompletionService:
    def __init__(self, store: CompletionStore, user: AuthContext):
        self.store, self.user = store, user

    def _get(self, record_id: UUID, *, active: bool = True) -> StoredCompletion:
        record = self.store.get(self.user.sub, record_id)
        if record is None or (active and record.metadata.deleted_at is not None):
            fail(404, 'Not Found')
        # Retain the common guard without exposing its 403 on record endpoints.
        try:
            require_record_owner(owner_sub=record.owner_sub, current_user=self.user)
        except HTTPException:
            fail(404, 'Not Found')
        return record

    @staticmethod
    def result(record: StoredCompletion, replayed: bool = False) -> CompletionResult:
        return CompletionResult(metadata=record.metadata, updated_at=record.updated_at,
                                applied_revision=record.metadata.revision,
                                current_revision=record.metadata.revision, replayed=replayed)

    def create(self, metadata: CompletionRecordMetadata) -> tuple[CompletionResult, bool]:
        with self.store.transaction(self.user.sub):
            if metadata.deleted_at is not None:
                fail(422, 'Invalid command')
            if metadata.revision != 1:
                fail(409, 'Revision conflict')
            existing = self.store.get(self.user.sub, metadata.id)
            if existing is not None:
                if existing.metadata.deleted_at is None and existing.metadata == metadata:
                    return self.result(existing, True), False
                fail(409, 'Record conflict')
            record = StoredCompletion(self.user.sub, metadata, datetime.now(timezone.utc))
            self.store.save(record)
            return self.result(record), True

    def get(self, record_id: UUID) -> CompletionRecordMetadata:
        with self.store.transaction(self.user.sub):
            return self._get(record_id).metadata

    def list(self, limit: int) -> list[CompletionRecordMetadata]:
        with self.store.transaction(self.user.sub):
            records = [r.metadata for r in self.store.list_for_owner(self.user.sub)
                       if r.metadata.deleted_at is None]
            records.sort(key=lambda r: r.id.int)
            records.sort(key=lambda r: r.completed_at, reverse=True)
            return records[:limit]

    def update(self, record_id: UUID, base: int, metadata: CompletionRecordMetadata) -> CompletionResult:
        with self.store.transaction(self.user.sub):
            current = self._get(record_id)
            if metadata.id != record_id or metadata.deleted_at is not None or metadata.completed_at != current.metadata.completed_at:
                fail(422, 'Invalid command')
            if base != current.metadata.revision or metadata.revision != base + 1:
                fail(409, 'Revision conflict')
            record = StoredCompletion(self.user.sub, metadata, datetime.now(timezone.utc))
            self.store.save(record)
            return self.result(record)

    def delete(self, record_id: UUID, base: int, revision: int) -> CompletionResult:
        with self.store.transaction(self.user.sub):
            current = self._get(record_id, active=False)
            if current.metadata.deleted_at is not None:
                if current.delete_base == base and current.metadata.revision == revision:
                    return self.result(current, True)
                fail(409, 'Revision conflict')
            if base != current.metadata.revision or revision != base + 1:
                fail(409, 'Revision conflict')
            now = datetime.now(timezone.utc)
            metadata = current.metadata.model_copy(update={'revision': revision, 'deleted_at': now})
            record = StoredCompletion(self.user.sub, metadata, now, base)
            self.store.save(record)
            return self.result(record)
