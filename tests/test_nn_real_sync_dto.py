"""Synthetic DTO tests only; no app, configuration loader or DB imports."""

from datetime import date, datetime
import json
import unittest
from uuid import UUID

from pydantic import ValidationError

from app.modules.neorang_narang.real_sync_schemas import RealCompletionCreate


def candidate():
    return {
        "operation_id": "10000000-0000-4000-8000-000000000001",
        "consent_generation": 3,
        "policy_version": "nn-real-completion-v1-draft",
        "base_revision": 0,
        "metadata": {
            "sync_id": "20000000-0000-4000-8000-000000000001",
            "course_number": 1,
            "completed_on": "2024-02-29",
        },
    }


class RealSyncDtoTests(unittest.TestCase):
    def reject(self, data):
        with self.assertRaises(ValidationError):
            RealCompletionCreate.model_validate(data)

    def test_valid_json_roundtrip_and_exact_allowlist(self):
        for course in (1, 2):
            data = candidate()
            data["metadata"]["course_number"] = course
            dto = RealCompletionCreate.model_validate_json(json.dumps(data))
            self.assertEqual(json.loads(dto.model_dump_json()), data)
            self.assertEqual(RealCompletionCreate.model_validate_json(dto.model_dump_json()), dto)

    def test_unknown_and_sensitive_fields_at_both_levels(self):
        for nested in (False, True):
            for field in ("unknown", "owner", "owner_sub", "account_id", "user_id",
                          "name", "body", "signature", "participation_mode",
                          "completed_at", "original_hash", "renamed_secret",
                          "revision", "received_at"):
                with self.subTest(nested=nested, field=field):
                    data = candidate()
                    target = data["metadata"] if nested else data
                    target[field] = "SYNTHETIC_CANARY"
                    self.reject(data)

    def test_every_field_required_and_nonnull(self):
        for nested in (False, True):
            fields = candidate()["metadata"] if nested else candidate()
            for field in fields:
                for missing in (False, True):
                    with self.subTest(nested=nested, field=field, missing=missing):
                        data = candidate()
                        target = data["metadata"] if nested else data
                        if missing:
                            del target[field]
                        else:
                            target[field] = None
                        self.reject(data)

    def test_strict_integer_types(self):
        for field in ("course_number", "consent_generation", "base_revision"):
            for value in (True, False, "0", "1", 0.0, 1.0):
                with self.subTest(field=field, value=value):
                    data = candidate()
                    target = data["metadata"] if field == "course_number" else data
                    target[field] = value
                    self.reject(data)

    def test_course_and_base_boundaries(self):
        for field, values in (("course_number", (-1, 0, 3)),
                              ("base_revision", (-1, 1, 2))):
            for value in values:
                data = candidate()
                target = data["metadata"] if field == "course_number" else data
                target[field] = value
                self.reject(data)

    def test_generation_shape_does_not_establish_authority_or_floor(self):
        for value in (-1, 0, 1, 3):
            data = candidate()
            data["consent_generation"] = value
            self.assertEqual(RealCompletionCreate.model_validate(data).consent_generation, value)

    def test_calendar_boundaries_preserve_original_string(self):
        for value in ("0001-01-01", "2000-02-29", "2024-02-29", "9999-12-31"):
            data = candidate()
            data["metadata"]["completed_on"] = value
            self.assertEqual(RealCompletionCreate.model_validate(data).metadata.completed_on, value)

    def test_invalid_dates_and_non_string_inputs(self):
        for value in ("1900-02-29", "2023-02-29", "2024-04-31", "0000-01-01",
                      "2024-13-01", "2024-01-00", "20240229", "2024-2-29",
                      " 2024-02-29", "2024-02-29 ", "2024-02-29\n",
                      "2024-02-29T00:00:00Z", "2024-02-29+09:00",
                      "２０２４-02-29", 1709164800, True,
                      date(2024, 2, 29), datetime(2024, 2, 29)):
            data = candidate()
            data["metadata"]["completed_on"] = value
            self.reject(data)

    def test_uuid_normalization_matches_v1_without_version_restriction(self):
        for value in ("ABCDEFAB-CDEF-1ABC-8ABC-ABCDEFABCDEF",
                      "abcdefabcdef1abc8abcabcdefabcdef",
                      UUID("abcdefab-cdef-1abc-8abc-abcdefabcdef")):
            data = candidate()
            data["operation_id"] = data["metadata"]["sync_id"] = value
            result = RealCompletionCreate.model_validate(data).model_dump(mode="json")
            self.assertEqual(result["operation_id"], "abcdefab-cdef-1abc-8abc-abcdefabcdef")
            self.assertEqual(result["metadata"]["sync_id"], result["operation_id"])

    def test_invalid_uuid_at_both_locations(self):
        for nested in (False, True):
            for value in ("invalid", "", 123, True, b"abcdefabcdef1abc8abcabcdefabcdef"):
                data = candidate()
                if nested:
                    data["metadata"]["sync_id"] = value
                else:
                    data["operation_id"] = value
                self.reject(data)

    def test_policy_is_only_nonempty_str_not_supported_registry(self):
        for value in ("synthetic-unknown-policy", "nn-real-completion-v1-draft", " "):
            data = candidate()
            data["policy_version"] = value
            self.assertEqual(RealCompletionCreate.model_validate(data).policy_version, value)
        for value in ("", 1, True, 1.0, b"policy"):
            data = candidate()
            data["policy_version"] = value
            self.reject(data)

    def test_string_error_hides_values_but_structured_errors_are_unsafe(self):
        data = candidate()
        data["metadata"]["completed_on"] = "SYNTHETIC_CANARY"
        try:
            RealCompletionCreate.model_validate(data)
        except ValidationError as error:
            self.assertNotIn("SYNTHETIC_CANARY", str(error))
            self.assertIn("SYNTHETIC_CANARY", repr(error.errors()))
        else:
            self.fail("Expected shape rejection")


if __name__ == "__main__":
    unittest.main()
