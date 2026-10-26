import unittest

from fastapi.testclient import TestClient

from app.main import app


class ApiRoutesTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def assert_json_response(self, path, status_code, expected):
        response = self.client.get(path)
        self.assertEqual(response.status_code, status_code)
        self.assertEqual(response.headers["content-type"], "application/json")
        self.assertEqual(response.json(), expected)

    def test_root(self):
        self.assert_json_response(
            "/", 200, {"message": "JesusLife One API가 실행 중입니다."}
        )

    def test_health(self):
        self.assert_json_response(
            "/health", 200,
            {"status": "ok", "service": "jesuslife-one-api", "version": "0.1.0"},
        )

    def test_neorang_narang_health(self):
        self.assert_json_response(
            "/api/v1/neorang-narang/health", 200,
            {"status": "ok", "service": "neorang-narang", "version": "0.1.0"},
        )

    def test_openapi(self):
        response = self.client.get("/openapi.json")
        self.assertEqual(response.status_code, 200)
        schema = response.json()
        self.assertTrue(schema["openapi"].startswith("3."))
        self.assertEqual(schema["info"]["title"], "JesusLife One API")
        self.assertEqual(schema["info"]["version"], "0.1.0")
        self.assertEqual(
            set(schema["paths"]),
            {"/", "/health", "/api/v1/neorang-narang/health"},
        )
        for path in schema["paths"]:
            with self.subTest(path=path):
                self.assertIn("200", schema["paths"][path]["get"]["responses"])

    def test_unknown_paths(self):
        for path in ("/missing", "/api/v1/neorang-narang/missing"):
            with self.subTest(path=path):
                self.assert_json_response(path, 404, {"detail": "Not Found"})


if __name__ == "__main__":
    unittest.main()
