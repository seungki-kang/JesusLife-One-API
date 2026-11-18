"""Exercise the backup seam through the existing offline Android auth fixture."""
from unittest import TestCase
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.life_diary_login import PREFIX, install_life_diary
from app.modules.life_diary.backup_rehearsal import rehearsal_router
from tests import test_life_diary_login


class BackupSessionWiringTest(TestCase):
    def test_uses_life_diary_session_and_separate_backup_opt_in(self):
        fixture = test_life_diary_login.LifeDiaryLoginTest()
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        fixture.enable()
        enabled_accounts = set()
        app = FastAPI()
        install_life_diary(
            app,
            lambda: fixture.runtime,
            backup_router_factory=lambda owner: rehearsal_router(
                owner, enabled_accounts.__contains__,
            ),
        )

        with TestClient(app) as client:
            fixture.client = client
            path = f'{PREFIX}/backup/entries/{uuid4()}'
            payload = {'format_version': 1, 'ciphertext': 'AQIDBA=='}
            self.assertEqual(client.put(path, json=payload).status_code, 401)

            login = client.post(PREFIX + '/session-exchange', json=fixture.ld_start())
            self.assertEqual(login.status_code, 200)
            session = login.json()
            headers = {'Authorization': 'Bearer ' + session['access_token']}
            self.assertEqual(client.put(path, headers=headers, json=payload).status_code, 403)
            enabled_accounts.add(UUID(session['sub']))
            self.assertEqual(client.put(path, headers=headers, json=payload).status_code, 201)
            self.assertEqual(client.get(path, headers=headers).json(), payload)
            self.assertEqual(client.post(PREFIX + '/logout', headers=headers).status_code, 204)
            self.assertEqual(client.get(path, headers=headers).status_code, 401)
