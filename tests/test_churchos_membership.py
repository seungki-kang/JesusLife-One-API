from unittest import TestCase
from unittest.mock import MagicMock
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.auth import AuthContext
from app.core.postgres import PostgresConnectionError
from app.modules.churchos.router import create_membership_router


class ChurchMembershipTest(TestCase):
    def test_membership_response_and_failure_contract(self):
        account, church = UUID(int=1), UUID(int=2)
        connect = MagicMock()
        db = connect.return_value.__enter__.return_value
        app = FastAPI()

        def authenticate():
            return AuthContext(sub=account)

        app.include_router(create_membership_router(authenticate, connect))
        path = f'/api/v1/churches/{church}/membership'
        with TestClient(app) as client:
            for row, status, permissions in (
                ((True,), 200, ['memberships:manage']),
                ((False,), 200, []),
                (None, 403, None),
            ):
                with self.subTest(row=row):
                    db.execute.reset_mock()
                    db.execute.return_value.fetchone.return_value = row
                    response = client.get(path, params={'account_id': str(UUID(int=3))})
                    self.assertEqual(response.status_code, status)
                    if permissions is not None:
                        self.assertEqual(response.json(), {
                            'church_id': str(church), 'permissions': permissions,
                        })
                    self.assertEqual(db.execute.call_args.args[1], (account, church))

            connect.side_effect = PostgresConnectionError('synthetic unavailable')
            response = client.get(path)
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json(), {'detail': 'Church membership unavailable'})
