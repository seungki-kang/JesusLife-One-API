"""DB-disconnected SQL/transaction unit tests, NOT a MySQL contract harness.

Scripted result sets only: no SQL interpretation, stateful fake DB or network.
Real InnoDB contract/concurrency/durability/restart/restore remain NOT_RUN.
"""
from datetime import datetime, timezone
import traceback
import unittest
from unittest.mock import Mock, patch
from uuid import UUID

from app.modules.neorang_narang.real_sync_candidate import (
    RealSyncCandidateService, SyntheticMemoryStore,
)
from app.modules.neorang_narang.real_sync_mysql import (
    MAX_BIGINT, MAX_OWNER_ROWS, MySQLRealSyncRepository,
)
from app.modules.neorang_narang.real_sync_repository import (
    CandidatePreparationFailed, CleanupFailed, GenerationNotOpen, IdempotencyKeyReused,
    InvalidCandidateInput, OperationRetired, StorageFailed, StorageIntegrityFailed,
    StorageRetryable, SyntheticAccountContext, TransactionOutcomeUnknown,
    UnsupportedCandidatePath,
)
from app.modules.neorang_narang.real_sync_schemas import RealCompletionCreate
from tests.test_nn_real_sync_dto import candidate


STAMP = '2024-02-29T12:34:56.123400Z'
PRIVATE = 'SYNTHETIC_PRIVATE_CANARY'
OWNER = UUID(int=10).bytes
COMMAND = RealCompletionCreate.model_validate(candidate())
SYNC = COMMAND.metadata.sync_id.bytes
OP = COMMAND.operation_id.bytes
NOW = datetime(2024, 2, 29, 12, 34, 56, 123400)


def gate(opened=3, retired=0):
    return {'owner': OWNER, 'open_generation': opened, 'retired_through': retired}


def record(**changes):
    return {**dict(owner=OWNER, sync_id=SYNC, generation=3,
                   policy_version=COMMAND.policy_version.encode('utf-8'),
                   course_number=1, completed_on='2024-02-29', revision=1), **changes}


def receipt(**changes):
    return {**dict(owner=OWNER, operation_id=OP, state=0, sync_id=SYNC,
                   applied_revision=1, received_at_utc=NOW), **changes}


def erased(**changes):
    return {**receipt(state=1, sync_id=None, applied_revision=None, received_at_utc=None), **changes}


class ScriptedConnection:
    """One connection/cursor; each SELECT consumes exactly one result set."""
    def __init__(self, *, gate_row=None, receipts=(), records=(), barriers=(),
                 version=None, fail_at=None, commit_error=False, rollback_error=False,
                 close_error=False, cursor_close_error=False, driver_error=None):
        self.results = [version if version is not None else [{'version': 1}],
                        [gate_row if gate_row is not None else gate()],
                        list(receipts), list(records), list(barriers)]
        self.events = []
        self.sql = []
        self.fail_at = fail_at
        self.commit_error = commit_error
        self.rollback_error = rollback_error
        self.close_error = close_error
        self.cursor_close_error = cursor_close_error
        self.driver_error = driver_error or RuntimeError(PRIVATE)
        self.current = None

    def cursor(self):
        self.events.append('cursor')
        parent = self

        class Cursor:
            def execute(self, sql, params=()):
                parent.events.append('execute')
                parent.sql.append((sql, params))
                if len(parent.sql) == parent.fail_at:
                    raise parent.driver_error
                if sql.startswith('SELECT'):
                    parent.current = parent.results.pop(0)

            def fetchone(self):
                return parent.current[0] if parent.current else None

            def fetchmany(self, limit):
                return parent.current[:limit]

            def close(self):
                parent.events.append('cursor.close')
                if parent.cursor_close_error:
                    raise RuntimeError(PRIVATE)

        return Cursor()

    def begin(self):
        self.events.append('begin')

    def commit(self):
        self.events.append('commit')
        if self.commit_error:
            raise RuntimeError(PRIVATE)

    def rollback(self):
        self.events.append('rollback')
        if self.rollback_error:
            raise RuntimeError(PRIVATE)

    def close(self):
        self.events.append('close')
        if self.close_error:
            raise RuntimeError(PRIVATE)


class MySQLRealSyncUnitTests(unittest.TestCase):
    def setUp(self):
        self.context = SyntheticAccountContext(UUID(bytes=OWNER))
        self.clock = Mock(return_value=STAMP)

    def repo(self, connection):
        self.connector = Mock(return_value=connection)
        return MySQLRealSyncRepository(self.connector, self.clock)

    def rejects(self, connection, expected=StorageIntegrityFailed, action=None):
        repo = self.repo(connection)
        with self.assertNoLogs(level='DEBUG'):
            with self.assertRaises(expected) as caught:
                (action or (lambda: repo.create(self.context, COMMAND)))()
        self.assertNotIn(PRIVATE, str(caught.exception))
        self.assertNotIn(PRIVATE, repr(caught.exception))
        self.assertNotIn(PRIVATE, ''.join(traceback.format_exception(caught.exception)))
        self.assertNotIn('commit', connection.events)
        self.assertIn('rollback', connection.events)
        self.assertEqual(connection.events[-1], 'close')
        return caught.exception

    def test_create_binding_order_single_storage_and_confirmed_commit(self):
        connection = ScriptedConnection()
        ack = self.repo(connection).create(self.context, COMMAND)
        self.assertFalse(ack.replayed)
        self.assertEqual(ack.received_at, STAMP)
        self.assertEqual(connection.events.count('begin'), 1)
        self.assertEqual(connection.events[-3:], ['cursor.close', 'commit', 'close'])
        self.assertNotIn('rollback', connection.events)
        self.connector.assert_called_once_with()
        selects = [sql for sql, _ in connection.sql if sql.startswith('SELECT')]
        self.assertIn('nn_real_gates', selects[1])
        for sql, table, order in zip(selects[2:],
                                     ('receipts', 'records', 'sync_barriers'),
                                     ('operation_id', 'sync_id', 'sync_id')):
            self.assertIn('nn_real_' + table, sql)
            self.assertIn('ORDER BY ' + order, sql)
            self.assertTrue(sql.endswith('FOR UPDATE'))
        writes = [(sql, params) for sql, params in connection.sql if sql.startswith('INSERT')]
        self.assertEqual(len(writes), 3)
        self.assertEqual(writes[-2][1], (OWNER, SYNC, 3, COMMAND.policy_version.encode(), 1, '2024-02-29'))
        self.assertEqual(writes[-1][1], (OWNER, OP, SYNC, NOW))
        self.assertNotIn('policy_version', writes[-1][0])
        for sql, params in connection.sql:
            self.assertNotIn(COMMAND.policy_version, sql)
            self.assertNotIn(str(COMMAND.operation_id), sql)
            self.assertEqual(sql.count('%s'), len(params))

    def test_replay_preserves_first_applied_time_reads_current_without_clock(self):
        connection = ScriptedConnection(receipts=[receipt(applied_revision=2)], records=[record(revision=4)])
        self.clock.side_effect = RuntimeError(PRIVATE)
        ack = self.repo(connection).create(self.context, COMMAND)
        self.assertEqual((ack.applied_revision, ack.current_revision, ack.received_at, ack.replayed),
                         (2, 4, STAMP, True))
        self.clock.assert_not_called()
        self.assertEqual(len([s for s, _ in connection.sql if s.startswith('INSERT')]), 1)
        self.assertIn('commit', connection.events)

    def test_fence_precedence_over_conflict_and_ack(self):
        changed = COMMAND.model_copy(update={'policy_version': PRIVATE})
        scenarios = (
            (dict(receipts=[erased()], gate_row=gate(None, 3)), OperationRetired),
            (dict(receipts=[receipt()], records=[record()], barriers=[{'owner': OWNER, 'sync_id': SYNC}]), OperationRetired),
            (dict(receipts=[receipt()], records=[record()], gate_row=gate(4, 3)), OperationRetired),
            (dict(receipts=[receipt()], records=[record()], gate_row=gate(4)), GenerationNotOpen),
        )
        for kwargs, error in scenarios:
            with self.subTest(error=error.__name__):
                connection = ScriptedConnection(**kwargs)
                repo = self.repo(connection)
                self.rejects(connection, error, lambda: repo.create(self.context, changed))
        self.clock.assert_not_called()

    def test_active_comparison_every_field_and_unsupported_other_operation(self):
        variants = []
        variants.extend((COMMAND.model_copy(update={'policy_version': 'v '}),
                         COMMAND.model_copy(update={'operation_id': UUID(int=500)})))
        for field, value in (('sync_id', UUID(int=2)), ('course_number', 2), ('completed_on', '0001-01-01')):
            variants.append(COMMAND.model_copy(update={
                'metadata': COMMAND.metadata.model_copy(update={field: value})}))
        for command in variants:
            connection = ScriptedConnection(receipts=[receipt()], records=[record()])
            repo = self.repo(connection)
            expected = UnsupportedCandidatePath if command.operation_id != COMMAND.operation_id else IdempotencyKeyReused
            self.rejects(connection, expected, lambda: repo.create(self.context, command))
        self.clock.assert_not_called()

    def test_retire_all_receipts_minimal_and_existing_barrier_read_only(self):
        for existing in (False, True):
            with self.subTest(existing=existing):
                barriers = [{'owner': OWNER, 'sync_id': SYNC}] if existing else []
                receipts = [] if existing else sorted([receipt(), receipt(operation_id=UUID(int=9).bytes)],
                                                      key=lambda r: r['operation_id'])
                connection = ScriptedConnection(receipts=receipts,
                                                records=[] if existing else [record()], barriers=barriers)
                self.repo(connection).retire(self.context, UUID(bytes=SYNC))
                statements = [s for s, _ in connection.sql]
                inserts = [s for s in statements if s.startswith('INSERT INTO nn_real_sync_barriers')]
                self.assertEqual(len(inserts), 0 if existing else 1)
                update = next(s for s in statements if s.startswith('UPDATE nn_real_receipts'))
                self.assertIn('state=1,sync_id=NULL,applied_revision=NULL,received_at_utc=NULL', update)
                self.assertIn('WHERE owner=%s AND state=0 AND sync_id=%s', update)
                self.assertFalse(any('INSERT IGNORE' in s or s.startswith('UPDATE nn_real_sync_barriers') for s in statements))
                self.assertEqual(connection.events.count('commit'), 1)

    def test_absent_retire_creates_barrier(self):
        connection = ScriptedConnection()
        self.repo(connection).retire(self.context, UUID(bytes=SYNC))
        self.assertIn(('INSERT INTO nn_real_sync_barriers(owner,sync_id) VALUES (%s,%s)', (OWNER, SYNC)), connection.sql)

    def test_close_one_transaction_all_targets_and_minimization(self):
        other = UUID(int=3).bytes
        connection = ScriptedConnection(
            receipts=sorted([receipt(), receipt(operation_id=UUID(int=5).bytes, sync_id=other)], key=lambda p: p['operation_id']),
            records=sorted([record(), record(sync_id=other)], key=lambda r: r['sync_id']))
        self.repo(connection).close_generation(self.context, 3)
        self.assertEqual(connection.events.count('begin'), 1)
        self.assertEqual(connection.events.count('commit'), 1)
        self.assertEqual(len([s for s, _ in connection.sql if s.startswith('DELETE')]), 2)
        self.assertEqual(connection.sql[-1][1], (3, 3, OWNER))
        self.assertIn('CASE WHEN open_generation<=%s THEN NULL', connection.sql[-1][0])
        self.clock.assert_not_called()

    def test_lower_close_preserves_higher_records_and_high_water(self):
        connection = ScriptedConnection(gate_row=gate(6, 4), receipts=[receipt()], records=[record(generation=6)])
        self.repo(connection).close_generation(self.context, 2)
        self.assertEqual(connection.sql[-1][1], (4, 4, OWNER))
        self.assertFalse(any(s.startswith('DELETE') for s, _ in connection.sql))

    def test_open_closed_same_other_and_retired(self):
        for opened, retired, expected in ((None, 0, None), (3, 0, None),
                                          (4, 0, UnsupportedCandidatePath), (None, 3, OperationRetired)):
            connection = ScriptedConnection(gate_row=gate(opened, retired))
            repo = self.repo(connection)
            if expected:
                self.rejects(connection, expected, lambda: repo.open_generation(self.context, 3))
            else:
                repo.open_generation(self.context, 3)
                self.assertEqual(len([s for s, _ in connection.sql if s.startswith('UPDATE')]), int(opened is None))

    def test_every_sql_failure_rolls_back_without_partial_ack(self):
        # Execute each command once to enumerate its SQL failure positions.
        for action in ('create', 'retire', 'open_generation', 'close_generation'):
            kwargs = dict(gate_row=gate(None)) if action == 'open_generation' else {}
            if action in ('retire', 'close_generation'):
                kwargs.update(receipts=[receipt()], records=[record()])
            connection = ScriptedConnection(**kwargs)
            arg = COMMAND if action == 'create' else UUID(bytes=SYNC) if action == 'retire' else 3
            getattr(self.repo(connection), action)(self.context, arg)
            for position in range(1, len(connection.sql) + 1):
                with self.subTest(action=action, position=position):
                    failed = ScriptedConnection(**kwargs, fail_at=position)
                    repo = self.repo(failed)
                    self.rejects(failed, StorageFailed,
                                 lambda: getattr(repo, action)(self.context, arg))

    def test_commit_unknown_never_retried_and_fresh_connection_reconciliation(self):
        lost = ScriptedConnection(commit_error=True)
        replay = ScriptedConnection(receipts=[receipt()], records=[record()])
        connector = Mock(side_effect=[lost, replay])
        repo = MySQLRealSyncRepository(connector, self.clock)
        with self.assertRaisesRegex(TransactionOutcomeUnknown, '^transaction_outcome_unknown$'):
            repo.create(self.context, COMMAND)
        self.assertEqual(connector.call_count, 1)
        self.assertEqual(lost.events[-2:], ['rollback', 'close'])
        ack = repo.create(self.context, COMMAND)
        self.assertTrue(ack.replayed)
        self.assertEqual(connector.call_count, 2)
        self.clock.assert_called_once_with()

    def test_commit_unknown_for_all_management_commands(self):
        for action, arg in (('retire', UUID(bytes=SYNC)), ('open_generation', 3), ('close_generation', 3)):
            connection = ScriptedConnection(commit_error=True)
            with self.assertRaises(TransactionOutcomeUnknown):
                getattr(self.repo(connection), action)(self.context, arg)
            self.assertEqual(connection.events.count('commit'), 1)
            self.assertEqual(connection.events[-1], 'close')

    def test_rollback_failure_is_unknown_even_for_domain_denial(self):
        connection = ScriptedConnection(gate_row=gate(None), rollback_error=True, close_error=True)
        error = self.rejects(connection, TransactionOutcomeUnknown)
        self.assertEqual(error.outcome, 'unknown')
        self.assertTrue(error.cleanup_failed)

    def test_cleanup_after_commit_is_distinct_and_not_rolled_back(self):
        connection = ScriptedConnection(close_error=True)
        with self.assertRaises(CleanupFailed) as caught:
            self.repo(connection).create(self.context, COMMAND)
        self.assertEqual(caught.exception.outcome, 'committed')
        self.assertTrue(caught.exception.cleanup_failed)
        self.assertNotIn('rollback', connection.events)
        self.assertEqual(connection.events.count('commit'), 1)

    def test_cursor_cleanup_failure_is_precommit_and_sanitized(self):
        error = self.rejects(ScriptedConnection(cursor_close_error=True), StorageFailed)
        self.assertEqual(error.outcome, 'rolled_back')
        self.assertTrue(error.cleanup_failed)

    def test_failed_close_preserves_original_denial_and_rollback_outcome(self):
        error = self.rejects(ScriptedConnection(gate_row=gate(None), close_error=True), GenerationNotOpen)
        self.assertEqual(error.outcome, 'rolled_back')
        self.assertTrue(error.cleanup_failed)

    def test_connection_setup_failures_still_discard_connection(self):
        for method in ('cursor', 'begin'):
            connection = ScriptedConnection()
            with patch.object(connection, method, side_effect=RuntimeError(PRIVATE)):
                error = self.rejects(connection, StorageFailed)
            self.assertEqual(error.outcome, 'rolled_back')

    def test_owner_binding_for_same_ids_in_independent_accounts(self):
        for owner in (OWNER, UUID(int=11).bytes):
            connection = ScriptedConnection(gate_row={**gate(), 'owner': owner},
                                            receipts=[receipt(owner=owner)], records=[record(owner=owner)])
            context = SyntheticAccountContext(UUID(bytes=owner))
            ack = self.repo(connection).create(context, COMMAND)
            self.assertTrue(ack.replayed)
            for sql, params in connection.sql:
                if 'owner=%s' in sql or sql.startswith('INSERT'):
                    self.assertEqual(params[0], owner)
            self.assertEqual(ack.sync_id, COMMAND.metadata.sync_id)
        self.clock.assert_not_called()

    def test_retryable_driver_codes_only_after_full_rollback(self):
        for code in (1062, 1205, 1213):
            connection = ScriptedConnection(fail_at=8, driver_error=RuntimeError(code, PRIVATE))
            self.rejects(connection, StorageRetryable)
            self.connector.assert_called_once_with()
        self.rejects(ScriptedConnection(fail_at=8, driver_error=RuntimeError(1213, PRIVATE), rollback_error=True),
                     TransactionOutcomeUnknown)

    def test_connector_failure_fixed_without_driver_details(self):
        connector = Mock(side_effect=RuntimeError(PRIVATE))
        with self.assertRaisesRegex(StorageFailed, '^storage_failed$'):
            MySQLRealSyncRepository(connector, self.clock).create(self.context, COMMAND)

    def test_invalid_inputs_never_acquire_connection(self):
        connector = Mock()
        repo = MySQLRealSyncRepository(connector, self.clock)
        for value in (MAX_BIGINT + 1, True, 0, '3'):
            for action in (repo.open_generation, repo.close_generation):
                with self.assertRaises(InvalidCandidateInput):
                    action(self.context, value)
            with self.assertRaises(InvalidCandidateInput):
                repo.create(self.context, COMMAND.model_copy(update={'consent_generation': value}))
        for value in ('x' * 257, '한' * 86, '\ud800'):
            with self.assertRaises(InvalidCandidateInput):
                repo.create(self.context, COMMAND.model_copy(update={'policy_version': value}))
        for value in ('2024-02-30', '2024-02-29 ', PRIVATE):
            with self.assertRaises(InvalidCandidateInput):
                repo.create(self.context, COMMAND.model_copy(update={
                    'metadata': COMMAND.metadata.model_copy(update={'completed_on': value})}))
        for context in (None, SyntheticAccountContext(PRIVATE)):
            with self.assertRaises(InvalidCandidateInput):
                repo.create(context, COMMAND)
        with self.assertRaises(InvalidCandidateInput):
            repo.retire(self.context, PRIVATE)
        with self.assertRaises(InvalidCandidateInput):
            repo.create(self.context, COMMAND.model_copy(update={'base_revision': 1}))
        connector.assert_not_called()

    def test_exact_policy_bytes_full_date_range_bigint_and_clock_profile(self):
        for policy in ('한' * 85 + 'x', ' V ', 'v', 'é', 'e\u0301', ' '):
            for day in ('0001-01-01', '9999-12-31'):
                command = COMMAND.model_copy(update={
                    'consent_generation': MAX_BIGINT, 'policy_version': policy,
                    'metadata': COMMAND.metadata.model_copy(update={'completed_on': day})})
                connection = ScriptedConnection(gate_row=gate(MAX_BIGINT))
                self.clock.return_value = '1000-01-01T00:00:00Z'
                ack = self.repo(connection).create(self.context, command)
                self.assertEqual(ack.received_at, '1000-01-01T00:00:00.000000Z')
                params = connection.sql[-2][1]
                self.assertEqual((params[2], params[3], params[5]), (MAX_BIGINT, policy.encode('utf-8'), day))

    def test_bad_clock_rolls_back_and_does_not_insert_payload(self):
        for value in ('0001-01-01T00:00:00Z', PRIVATE, None, '2024-02-29T00:00:00+09:00'):
            connection = ScriptedConnection()
            self.clock.return_value = value
            self.rejects(connection, CandidatePreparationFailed)
            self.assertFalse(any(s.startswith('INSERT INTO nn_real_records') for s, _ in connection.sql))

    def test_corrupt_gate_version_and_owner_rows_fail_closed(self):
        for row in (gate(True), gate(3, 3), gate(3, -1), gate(MAX_BIGINT + 1),
                    {**gate(), 'owner': UUID(int=11).bytes}, {**gate(), 'extra': PRIVATE}):
            self.rejects(ScriptedConnection(gate_row=row))
        for version in ([], [{'version': 2}], [{'version': True}], [{'version': 1}, {'version': 2}]):
            self.rejects(ScriptedConnection(version=version))
        for rows in ([record(owner=UUID(int=11).bytes)], [record(sync_id=b'bad')],
                     [record(), record()], [record(extra=PRIVATE)]):
            self.rejects(ScriptedConnection(records=rows))

    def test_corrupt_record_and_receipt_ranges_shapes_and_linkage(self):
        for field, value in (('generation', True), ('generation', MAX_BIGINT + 1),
                             ('revision', 0), ('revision', MAX_BIGINT + 1),
                             ('policy_version', b'\xff'), ('policy_version', b'x' * 257),
                             ('policy_version', 'text'), ('completed_on', '1900-02-29'),
                             ('completed_on', '2024-02-29 '), ('course_number', True),
                             ('generation', 4)):
            self.rejects(ScriptedConnection(receipts=[receipt()], records=[record(**{field: value})]))
        for field, value in (('state', True), ('state', 2), ('sync_id', None),
                             ('sync_id', UUID(int=500).bytes), ('applied_revision', 2),
                             ('applied_revision', MAX_BIGINT + 1),
                             ('received_at_utc', PRIVATE), ('received_at_utc', NOW.replace(tzinfo=timezone.utc)),
                             ('received_at_utc', datetime(1, 1, 1))):
            self.rejects(ScriptedConnection(receipts=[receipt(**{field: value})], records=[record()]))
        self.rejects(ScriptedConnection(receipts=[receipt()]))  # orphan active
        self.rejects(ScriptedConnection(records=[record()]))  # record without receipt
        self.rejects(ScriptedConnection(receipts=[erased(sync_id=SYNC)]))

    def test_management_rejects_orphans_and_barrier_record_coexistence(self):
        for action, arg in (('retire', UUID(bytes=SYNC)), ('close_generation', 3), ('open_generation', 3)):
            for kwargs in (dict(receipts=[receipt()]),
                           dict(receipts=[receipt()], records=[record()],
                                barriers=[{'owner': OWNER, 'sync_id': SYNC}])):
                connection = ScriptedConnection(**kwargs)
                repo = self.repo(connection)
                self.rejects(connection, action=lambda: getattr(repo, action)(self.context, arg))

    def test_owner_capacity_blocks_without_chunk_commit(self):
        rows = [receipt(operation_id=UUID(int=n).bytes, state=1, sync_id=None,
                        applied_revision=None, received_at_utc=None) for n in range(MAX_OWNER_ROWS + 1)]
        self.rejects(ScriptedConnection(receipts=rows), StorageFailed)

    def test_reserved_capacity_rejections_before_payload_writes(self):
        other = UUID(int=2).bytes
        barrier = {'owner': OWNER, 'sync_id': other}
        cases = (
            (dict(barriers=[barrier]), 'create', COMMAND, 1),
            (dict(records=[record(sync_id=other)],
                  receipts=[receipt(operation_id=other, sync_id=other)],
                  barriers=[{'owner': OWNER, 'sync_id': UUID(int=3).bytes}]),
             'create', COMMAND, 2),
            (dict(records=[record()], receipts=[receipt()], barriers=[barrier]),
             'retire', UUID(int=4), 2),
        )
        for kwargs, action, arg, limit in cases:
            with patch('app.modules.neorang_narang.real_sync_mysql.MAX_OWNER_ROWS', limit):
                with self.subTest(action=action):
                    connection = ScriptedConnection(**kwargs)
                    repo = self.repo(connection)
                    error = self.rejects(connection, StorageFailed,
                                         lambda: getattr(repo, action)(self.context, arg))
                    self.assertEqual(str(error), 'storage_failed')
                    self.assertFalse(any(s.startswith(('INSERT INTO nn_real_records',
                                                       'INSERT INTO nn_real_receipts',
                                                       'INSERT INTO nn_real_sync_barriers',
                                                       'UPDATE', 'DELETE'))
                                         for s, _ in connection.sql))
        self.clock.assert_not_called()

    def test_full_reservation_retire_and_close_convert_to_barriers(self):
        other = UUID(int=2).bytes
        barrier = {'owner': OWNER, 'sync_id': UUID(int=3).bytes}
        cases = (
            ('retire', UUID(bytes=SYNC), [record()], [receipt()], 1),
            ('close_generation', 3,
             sorted([record(), record(sync_id=other)], key=lambda r: r['sync_id']),
             sorted([receipt(), receipt(operation_id=other, sync_id=other)],
                    key=lambda r: r['operation_id']), 2),
        )
        for action, arg, records, receipts, count in cases:
            with self.subTest(action=action), patch(
                    'app.modules.neorang_narang.real_sync_mysql.MAX_OWNER_ROWS', count + 1):
                connection = ScriptedConnection(records=records, receipts=receipts, barriers=[barrier])
                getattr(self.repo(connection), action)(self.context, arg)
                self.assertEqual(connection.events.count('commit'), 1)
                self.assertNotIn('rollback', connection.events)
                inserts = [params[1] for s, params in connection.sql
                           if s.startswith('INSERT INTO nn_real_sync_barriers')]
                self.assertEqual(inserts, sorted(r['sync_id'] for r in records))
                self.assertEqual(sum(s.startswith('DELETE') for s, _ in connection.sql), count)

    def test_capacity_allows_create_and_repeated_retire(self):
        barrier = {'owner': OWNER, 'sync_id': UUID(int=2).bytes}
        # Explicit post-command result sets, not a stateful SQL engine.
        connections = [ScriptedConnection(barriers=[barrier]),
                       ScriptedConnection(records=[record()], receipts=[receipt()], barriers=[barrier]),
                       ScriptedConnection(receipts=[erased()], barriers=sorted(
                           [barrier, {'owner': OWNER, 'sync_id': SYNC}], key=lambda r: r['sync_id']))]
        repo = MySQLRealSyncRepository(Mock(side_effect=connections), self.clock)
        with patch('app.modules.neorang_narang.real_sync_mysql.MAX_OWNER_ROWS', 2):
            self.assertFalse(repo.create(self.context, COMMAND).replayed)
            repo.retire(self.context, UUID(bytes=SYNC))
            repo.retire(self.context, UUID(bytes=SYNC))
        for connection in connections:
            self.assertEqual(connection.events.count('commit'), 1)
            self.assertNotIn('rollback', connection.events)
        self.assertFalse(any(s.startswith('INSERT INTO nn_real_sync_barriers')
                             for s, _ in connections[-1].sql))

    def test_corrupt_overreserved_state_blocks_all_commands(self):
        barrier = {'owner': OWNER, 'sync_id': UUID(int=2).bytes}
        with patch('app.modules.neorang_narang.real_sync_mysql.MAX_OWNER_ROWS', 1):
            for action, arg in (('create', COMMAND), ('retire', UUID(bytes=SYNC)),
                                ('close_generation', 3), ('open_generation', 3)):
                with self.subTest(action=action):
                    connection = ScriptedConnection(records=[record()], receipts=[receipt()],
                                                    barriers=[barrier])
                    repo = self.repo(connection)
                    self.rejects(connection, StorageIntegrityFailed,
                                 lambda: getattr(repo, action)(self.context, arg))
                    self.assertFalse(any(s.startswith(('UPDATE', 'DELETE',
                                                       'INSERT INTO nn_real_sync_barriers',
                                                       'INSERT INTO nn_real_records',
                                                       'INSERT INTO nn_real_receipts'))
                                         for s, _ in connection.sql))

    def test_memory_and_dto_not_silently_narrowed_to_persistence_limits(self):
        command = COMMAND.model_copy(update={'consent_generation': MAX_BIGINT + 1,
                                             'policy_version': 'x' * 257})
        service = RealSyncCandidateService(SyntheticMemoryStore(), self.clock)
        service.open_generation(self.context, MAX_BIGINT + 1)
        self.assertFalse(service.create(self.context, command).replayed)


if __name__ == '__main__':
    unittest.main()
