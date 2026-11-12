"""ChurchOS HTTP/RLS rehearsal invoked only in the isolated PostgreSQL worker."""
from unittest import TestCase
from unittest.mock import Mock, patch
from uuid import UUID

from fastapi.testclient import TestClient
from psycopg.errors import InsufficientPrivilege

from app.core.auth0_poc import AppSession, VerifiedAccess
from app.core.postgres import PostgresConnectionError
from app.core.postgres_settings import RUNTIME_DSN
from scripts.churchos_pc_settings import ENABLED, membership_connector
from tests.test_postgres_rls import A, B, C, X, Y

SCOPE = 'churchos:membership:read'


def verify_membership_read(port, database):
    # The PC app factory also has a configured module entry point. Keep it
    # independent of local settings files and credentials during import.
    with patch('dotenv.dotenv_values', return_value={}):
        from app.auth0_pc import PcRuntime, create_app

    check = TestCase()
    identity = ('https://synthetic.invalid/', 'synthetic-sub', 'synthetic-client')
    provider, store = Mock(), Mock()
    runtime = PcRuntime(None, provider=provider, store=store, clock=lambda: 100)

    def bind(account, scopes):
        provider.verify_access.return_value = VerifiedAccess(
            *identity, fingerprint=b'synthetic', expires_at=200, scopes=frozenset(scopes),
        )
        store.lookup.return_value = AppSession(UUID(int=100), UUID(account), *identity, 200)

    connect = membership_connector({
        ENABLED: '1',
        RUNTIME_DSN: f'postgresql://jl_api_runtime:synthetic_only@127.0.0.1:{port}/{database}',
    })

    path = f'/api/v1/churches/{X}/membership'
    headers = {'Authorization': 'Bearer synthetic'}
    with TestClient(create_app(runtime)) as client:
        check.assertEqual(client.get(path, headers=headers).status_code, 404)

    observed_connect = Mock(wraps=connect)
    with TestClient(create_app(runtime, church_membership_connect=observed_connect)) as client:
        check.assertEqual(client.get(path).status_code, 401)
        bind(A, ())
        check.assertEqual(client.get(path, headers=headers).status_code, 403)
        observed_connect.assert_not_called()
        bind(A, (SCOPE,))
        response = client.get(path, headers=headers, params={'account_id': B})
        check.assertEqual((response.status_code, response.json()), (
            200, {'church_id': X, 'permissions': ['memberships:manage']},
        ))
        response = client.get(f'/api/v1/churches/{Y}/membership', headers=headers)
        check.assertEqual((response.status_code, response.json()), (
            200, {'church_id': Y, 'permissions': []},
        ))
        for account in (B, C):
            bind(account, (SCOPE,))
            check.assertEqual(client.get(path, headers=headers).status_code, 403)

    with check.assertRaises(InsufficientPrivilege), connect() as db:
        db.execute('UPDATE jl_churchos.memberships SET revoked_at=NULL')

    bind(A, (SCOPE,))
    unavailable = Mock(side_effect=PostgresConnectionError('synthetic unavailable'))
    with TestClient(create_app(runtime, church_membership_connect=unavailable)) as client:
        response = client.get(path, headers=headers)
        check.assertEqual((response.status_code, response.json()), (
            503, {'detail': 'Church membership unavailable'},
        ))
    print('PASS: ChurchOS membership HTTP contract + PostgreSQL runtime RLS')
