import unittest
from uuid import UUID

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.auth import AuthContext, get_current_user, require_record_owner


OWNER = UUID("00000000-0000-4000-8000-000000000001")
OTHER = UUID("00000000-0000-4000-8000-000000000002")


class AuthOwnershipTest(unittest.TestCase):
    def setUp(self):
        # Probe routes and overrides exist only on this isolated test app.
        self.app = FastAPI()

        @self.app.post("/probe")
        def probe(user: AuthContext = Depends(get_current_user)):
            require_record_owner(owner_sub=OWNER, current_user=user)
            return {"ok": True}

        self.client = TestClient(self.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.addCleanup(self.app.dependency_overrides.clear)

    def test_missing_authentication(self):
        response = self.client.post("/probe")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"detail": "Authentication required"})
        self.assertEqual(response.headers["www-authenticate"], "Bearer")

    def test_unverified_headers_body_and_query_cannot_authenticate(self):
        response = self.client.post(
            f"/probe?sub={OWNER}",
            headers={"Authorization": "Bearer synthetic-token", "X-User-ID": str(OWNER)},
            json={"sub": str(OWNER), "user_id": str(OWNER)},
        )
        self.assertEqual(response.status_code, 401)

    def test_same_owner_passes_with_dependency_override(self):
        self.app.dependency_overrides[get_current_user] = lambda: AuthContext(sub=OWNER)
        response = self.client.post("/probe", json={"user_id": str(OTHER)})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})

    def test_different_owner_rejected_without_sensitive_response_or_logs(self):
        self.app.dependency_overrides[get_current_user] = lambda: AuthContext(sub=OTHER)
        private = "SYNTHETIC_PRIVATE_VALUE"
        with self.assertLogs(level="DEBUG") as captured:
            response = self.client.post("/probe", json={
                "user_id": str(OWNER), "owner_id": str(OWNER),
                "name": private, "grace_reflection": private, "signature": private,
            })
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {"detail": "Access denied"})
        for value in (str(OWNER), str(OTHER), private):
            self.assertNotIn(value, response.text)
            self.assertNotIn(value, "\n".join(captured.output))

    def test_context_is_immutable_and_repr_hides_subject(self):
        user = AuthContext(sub=str(OWNER))
        self.assertEqual(user.sub, OWNER)
        self.assertNotIn(str(OWNER), repr(user))
        with self.assertRaises(ValidationError):
            user.sub = OTHER

    def test_context_rejects_missing_invalid_and_extra_claims(self):
        for data in ({}, {"sub": "SYNTHETIC_INVALID_SUB"}, {"sub": None},
                     {"sub": OWNER, "name": "SYNTHETIC_PRIVATE_VALUE"}):
            with self.subTest(keys=list(data)), self.assertRaises(ValidationError) as caught:
                AuthContext(**data)
            self.assertNotIn("SYNTHETIC_INVALID_SUB", str(caught.exception))
            self.assertNotIn("SYNTHETIC_PRIVATE_VALUE", str(caught.exception))
