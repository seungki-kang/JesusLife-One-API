"""Unconnected, synthetic MySQL repository. Real collection BLOCKED.

connector MUST return a fresh, exclusively owned, non-pooled connection with
autocommit disabled, no pending transaction, and a dictionary cursor. It must
target only the separately reviewed product schema. Connection.close MUST
physically discard the connection, including on rollback/commit failure; a pool
return masquerading as close is unsupported. The caller owns configuration,
schema/privilege/durability verification and any eventual authorization gate.
This module never imports configuration, creates schema or retries commands.

Each command takes one connection, starts one READ COMMITTED transaction and
locks gate -> receipts(binary operation order) -> records(binary sync order)
-> barriers(binary sync order). Conservatively locks the owner's whole bounded
set, including for create/retire. At most MAX_OWNER_ROWS rows per table are
supported; barriers plus active sync IDs reserve future erasure space within
that same limit. Overflow rolls back, never chunks/commits partial close. This is a
candidate limit, not a measured production capacity or Core A/F/D protocol.
"""

from collections.abc import Callable
from datetime import datetime, timezone
from uuid import UUID

from .real_sync_repository import (
    CandidatePreparationFailed, CleanupFailed, GenerationNotOpen,
    IdempotencyKeyReused, InvalidCandidateInput, OperationRetired,
    StorageFailed, StorageIntegrityFailed, StorageRetryable,
    SyntheticAccountContext, TransactionOutcomeUnknown, UnsupportedCandidatePath,
    _command, _generation, _owner,
)
from .real_sync_schemas import RealCompletionAck, RealCompletionCreate, RealCompletionMetadata


MAX_BIGINT = 9223372036854775807
MAX_OWNER_ROWS = 10000
_DOMAIN = (OperationRetired, GenerationNotOpen, IdempotencyKeyReused,
           UnsupportedCandidatePath, StorageIntegrityFailed,
           CandidatePreparationFailed, StorageFailed)


def _integer(value, minimum=1):
    if type(value) is not int or not minimum <= value <= MAX_BIGINT:
        raise StorageIntegrityFailed()
    return value


def _policy(value):
    if type(value) is not str:
        raise InvalidCandidateInput()
    try:
        encoded = value.encode('utf-8', errors='strict')
    except Exception:
        raise InvalidCandidateInput() from None
    if not 1 <= len(encoded) <= 256:
        raise InvalidCandidateInput()
    return encoded


def _input_generation(value):
    value = _generation(value)
    if value > MAX_BIGINT:
        raise InvalidCandidateInput()
    return value


def _stamp(value):
    # The driver must return DATETIME(6) as a naive datetime. Interpret as UTC;
    # never let a machine/session timezone change receipt meaning.
    if type(value) is not datetime or value.tzinfo is not None or value.year < 1000:
        raise StorageIntegrityFailed()
    return value.replace(tzinfo=timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def _clock_value(clock, command):
    try:
        raw = clock()
        # Reuse existing wire/calendar validation before issuing a DB timestamp.
        RealCompletionAck(operation_id=command.operation_id,
                          sync_id=command.metadata.sync_id, applied_revision=1,
                          current_revision=1, replayed=False, received_at=raw)
        utc = datetime.fromisoformat(raw)
        value = utc.astimezone(timezone.utc).replace(tzinfo=None)
        return value, _stamp(value)
    except Exception:
        raise CandidatePreparationFailed() from None


class MySQLRealSyncRepository:
    def __init__(self, connector: Callable, clock: Callable[[], str]):
        self.__connector = connector
        self.__clock = clock

    def _transaction(self, owner, action):
        connection = cursor = None
        error = result = None
        committed = committing = False
        rolled_back = cleanup_failed = False
        try:
            connection = self.__connector()
            cursor = connection.cursor()
            cursor.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
            connection.begin()
            cursor.execute('SELECT version FROM nn_real_schema_version ORDER BY version')
            versions = cursor.fetchmany(2)
            if (versions != [{'version': 1}]
                    or type(versions[0]['version']) is not int):
                raise StorageIntegrityFailed()
            cursor.execute(
                'INSERT INTO nn_real_gates(owner,open_generation,retired_through) '
                'VALUES (%s,NULL,0) ON DUPLICATE KEY UPDATE owner=owner', (owner,))
            cursor.execute('SELECT owner,open_generation,retired_through FROM nn_real_gates '
                           'WHERE owner=%s FOR UPDATE', (owner,))
            gate = cursor.fetchone()
            self._gate(gate, owner)
            result = action(cursor, gate)
            # Cursor cleanup is pre-commit, so its failure cannot create success.
            try:
                cursor.close()
            except Exception:
                cleanup_failed = True
                raise
            cursor = None
            committing = True
            connection.commit()
            committed = True
        except Exception as caught:
            if committing:
                error = TransactionOutcomeUnknown()
            elif isinstance(caught, _DOMAIN):
                error = type(caught)()
            elif (type(getattr(caught, 'args', None)) is tuple and caught.args
                  and type(caught.args[0]) is int and caught.args[0] in (1205, 1213, 1062)):
                # Full rollback below, then caller may retry SAME command with
                # bounded backoff. Unexpected duplicate is never an ACK.
                error = StorageRetryable()
            else:
                error = StorageFailed()
        finally:
            if connection is not None and not committed:
                try:
                    connection.rollback()
                    rolled_back = True
                except Exception:
                    cleanup_failed = True
                    error = TransactionOutcomeUnknown()
            if cursor is not None:
                try:
                    cursor.close()
                except Exception:
                    cleanup_failed = True
                    # Pre-commit error already blocks success; keep its fixed
                    # classification. Connection must still be discarded.
                    if error is None:
                        error = StorageFailed()
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    cleanup_failed = True
                    if committed:
                        error = CleanupFailed()
                    elif error is None:
                        error = StorageFailed()
        if error is not None:
            error.outcome = ('committed' if committed else
                             'unknown' if committing or isinstance(error, TransactionOutcomeUnknown) else
                             'rolled_back' if rolled_back else 'not_started')
            error.cleanup_failed = cleanup_failed
            raise error from None
        return result

    @staticmethod
    def _gate(row, owner):
        if (type(row) is not dict
                or set(row) != {'owner', 'open_generation', 'retired_through'}
                or row['owner'] != owner or type(row['owner']) is not bytes):
            raise StorageIntegrityFailed()
        boundary = _integer(row['retired_through'], 0)
        opened = row['open_generation']
        if opened is not None and _integer(opened) <= boundary:
            raise StorageIntegrityFailed()

    @staticmethod
    def _rows(cursor, table, columns, order, owner):
        # table/columns/order are module constants only; all values are bound.
        cursor.execute(f'SELECT {columns} FROM {table} WHERE owner=%s '
                       f'ORDER BY {order} LIMIT %s FOR UPDATE', (owner, MAX_OWNER_ROWS + 1))
        rows = cursor.fetchmany(MAX_OWNER_ROWS + 1)
        if len(rows) > MAX_OWNER_ROWS:
            raise StorageFailed()
        return rows

    def _locked(self, cursor, owner):
        receipts = self._rows(cursor, 'nn_real_receipts',
                              'owner,operation_id,state,sync_id,applied_revision,received_at_utc',
                              'operation_id', owner)
        records = self._rows(cursor, 'nn_real_records',
                             'owner,sync_id,generation,policy_version,course_number,completed_on,revision',
                             'sync_id', owner)
        barriers = self._rows(cursor, 'nn_real_sync_barriers', 'owner,sync_id', 'sync_id', owner)
        try:
            p = self._index(receipts, owner, 'operation_id', {
                'owner', 'operation_id', 'state', 'sync_id', 'applied_revision', 'received_at_utc'})
            r = self._index(records, owner, 'sync_id', {
                'owner', 'sync_id', 'generation', 'policy_version', 'course_number', 'completed_on', 'revision'})
            b = self._index(barriers, owner, 'sync_id', {'owner', 'sync_id'})
            for row in p.values():
                if type(row['state']) is not int or row['state'] not in (0, 1):
                    raise StorageIntegrityFailed()
                if row['state'] == 1:
                    if any(row[k] is not None for k in ('sync_id', 'applied_revision', 'received_at_utc')):
                        raise StorageIntegrityFailed()
                else:
                    self._binary_id(row['sync_id'])
                    _integer(row['applied_revision'])
                    _stamp(row['received_at_utc'])
            for row in r.values():
                _integer(row['generation'])
                _integer(row['revision'])
                if type(row['policy_version']) is not bytes:
                    raise StorageIntegrityFailed()
                if _policy(row['policy_version'].decode('utf-8', errors='strict')) != row['policy_version']:
                    raise StorageIntegrityFailed()
                RealCompletionMetadata(sync_id=UUID(bytes=row['sync_id']),
                                       course_number=row['course_number'], completed_on=row['completed_on'])
        except Exception:
            raise StorageIntegrityFailed() from None
        return p, r, b

    @staticmethod
    def _binary_id(value):
        if type(value) is not bytes or len(value) != 16:
            raise StorageIntegrityFailed()

    @classmethod
    def _index(cls, rows, owner, key, fields):
        result = {}
        previous = None
        for row in rows:
            if type(row) is not dict or set(row) != fields or row['owner'] != owner:
                raise StorageIntegrityFailed()
            cls._binary_id(row['owner'])
            value = row[key]
            cls._binary_id(value)
            if previous is not None and value <= previous:
                raise StorageIntegrityFailed()
            previous = value
            result[value] = row
        return result

    @staticmethod
    def _integrity(gate, receipts, records, barriers):
        # An active sync reserves the permanent barrier needed to erase it.
        if len(set(barriers) | set(records)) > MAX_OWNER_ROWS:
            raise StorageIntegrityFailed()
        linked = set()
        for receipt in receipts.values():
            if receipt['state'] == 0:
                record = records.get(receipt['sync_id'])
                if record is None or receipt['applied_revision'] > record['revision']:
                    raise StorageIntegrityFailed()
                linked.add(receipt['sync_id'])
        for key, record in records.items():
            if (key in barriers or key not in linked
                    or record['generation'] <= gate['retired_through']
                    or record['generation'] != gate['open_generation']):
                raise StorageIntegrityFailed()

    def create(self, context: SyntheticAccountContext,
               command: RealCompletionCreate) -> RealCompletionAck:
        owner = _owner(context).bytes
        command = _command(command)
        _input_generation(command.consent_generation)
        policy = _policy(command.policy_version)
        sync = command.metadata.sync_id.bytes
        operation = command.operation_id.bytes

        def apply(cursor, gate):
            receipts, records, barriers = self._locked(cursor, owner)
            receipt = receipts.get(operation)
            # Denial fences precede active comparison, clock and ACK construction.
            if receipt is not None and receipt['state'] == 1:
                raise OperationRetired()
            if sync in barriers or command.consent_generation <= gate['retired_through']:
                raise OperationRetired()
            if command.consent_generation != gate['open_generation']:
                raise GenerationNotOpen()
            self._integrity(gate, receipts, records, barriers)
            if receipt is not None:
                record = records[receipt['sync_id']]
                if (receipt['sync_id'], record['generation'], record['policy_version'],
                    record['course_number'], record['completed_on']) != (
                        sync, command.consent_generation, policy,
                        command.metadata.course_number, command.metadata.completed_on):
                    raise IdempotencyKeyReused()
                return RealCompletionAck(
                    operation_id=command.operation_id, sync_id=UUID(bytes=receipt['sync_id']),
                    applied_revision=receipt['applied_revision'], current_revision=record['revision'],
                    replayed=True, received_at=_stamp(receipt['received_at_utc']))
            if sync in records:
                raise UnsupportedCandidatePath()
            if (len(records) >= MAX_OWNER_ROWS or len(receipts) >= MAX_OWNER_ROWS
                    or len(set(barriers) | set(records) | {sync}) > MAX_OWNER_ROWS):
                raise StorageFailed()
            timestamp, stamp = _clock_value(self.__clock, command)
            ack = RealCompletionAck(operation_id=command.operation_id,
                                    sync_id=command.metadata.sync_id, applied_revision=1,
                                    current_revision=1, replayed=False, received_at=stamp)
            cursor.execute('INSERT INTO nn_real_records '
                           '(owner,sync_id,generation,policy_version,course_number,completed_on,revision) '
                           'VALUES (%s,%s,%s,%s,%s,%s,1)',
                           (owner, sync, command.consent_generation, policy,
                            command.metadata.course_number, command.metadata.completed_on))
            cursor.execute('INSERT INTO nn_real_receipts '
                           '(owner,operation_id,state,sync_id,applied_revision,received_at_utc) '
                           'VALUES (%s,%s,0,%s,1,%s)', (owner, operation, sync, timestamp))
            return ack

        return self._transaction(owner, apply)

    def open_generation(self, context: SyntheticAccountContext, generation: int) -> None:
        owner = _owner(context).bytes
        generation = _input_generation(generation)

        def apply(cursor, gate):
            if generation <= gate['retired_through']:
                raise OperationRetired()
            if gate['open_generation'] not in (None, generation):
                raise UnsupportedCandidatePath()
            self._integrity(gate, *self._locked(cursor, owner))
            if gate['open_generation'] is None:
                cursor.execute('UPDATE nn_real_gates SET open_generation=%s WHERE owner=%s',
                               (generation, owner))

        return self._transaction(owner, apply)

    def _erase(self, cursor, owner, targets, records, barriers):
        # Active targets already own reservations; only absent syncs add space.
        # Check the whole union before any barrier/receipt/record mutation.
        if len(set(barriers) | set(records) | targets) > MAX_OWNER_ROWS:
            raise StorageFailed()
        # All locks already held, ordered writes; no per-row/chunk commit.
        for sync in sorted(targets):
            if sync not in barriers:
                cursor.execute('INSERT INTO nn_real_sync_barriers(owner,sync_id) VALUES (%s,%s)',
                               (owner, sync))
            cursor.execute('UPDATE nn_real_receipts SET state=1,sync_id=NULL,'
                           'applied_revision=NULL,received_at_utc=NULL '
                           'WHERE owner=%s AND state=0 AND sync_id=%s', (owner, sync))
            cursor.execute('DELETE FROM nn_real_records WHERE owner=%s AND sync_id=%s', (owner, sync))

    def retire(self, context: SyntheticAccountContext, sync_id: UUID) -> None:
        owner = _owner(context).bytes
        if type(sync_id) is not UUID:
            raise InvalidCandidateInput()

        def apply(cursor, gate):
            receipts, records, barriers = self._locked(cursor, owner)
            self._integrity(gate, receipts, records, barriers)
            self._erase(cursor, owner, {sync_id.bytes}, records, barriers)

        return self._transaction(owner, apply)

    def close_generation(self, context: SyntheticAccountContext, generation: int) -> None:
        owner = _owner(context).bytes
        generation = _input_generation(generation)

        def apply(cursor, gate):
            receipts, records, barriers = self._locked(cursor, owner)
            self._integrity(gate, receipts, records, barriers)
            boundary = max(generation, gate['retired_through'])
            targets = {key for key, row in records.items() if row['generation'] <= boundary}
            self._erase(cursor, owner, targets, records, barriers)
            cursor.execute('UPDATE nn_real_gates SET retired_through=%s,'
                           'open_generation=CASE WHEN open_generation<=%s THEN NULL '
                           'ELSE open_generation END WHERE owner=%s', (boundary, boundary, owner))

        return self._transaction(owner, apply)
