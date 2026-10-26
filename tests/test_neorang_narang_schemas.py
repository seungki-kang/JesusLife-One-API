import json
import unittest
from datetime import datetime, timezone
from uuid import UUID

from pydantic import ValidationError

from app.modules.neorang_narang.schemas import (
    CompletionRecordMetadata, CourseNumber, ParticipationMode,
)


def payload(**changes):
    return {
        "id": "d752bfee-2574-4be4-9fa5-e3475958aeb2",
        "course_number": 1,
        "participation_mode": "solo",
        "completed_at": "2026-10-26T12:00:00Z",
        "revision": 1,
        **changes,
    }


class CompletionRecordMetadataTest(unittest.TestCase):
    def test_valid_json_and_round_trip(self):
        record = CompletionRecordMetadata.model_validate_json(json.dumps(payload()))
        self.assertIsInstance(record.id, UUID)
        self.assertEqual(record.course_number, CourseNumber.CHAPTER_ONE)
        self.assertEqual(record.participation_mode, ParticipationMode.SOLO)
        self.assertIsNone(record.deleted_at)
        self.assertEqual(
            CompletionRecordMetadata.model_validate_json(record.model_dump_json()),
            record,
        )
        self.assertEqual(set(record.model_dump()), {
            "id", "course_number", "participation_mode", "completed_at",
            "revision", "deleted_at",
        })

    def test_chapter_two_together_and_deletion(self):
        record = CompletionRecordMetadata(**payload(
            course_number=2, participation_mode="together", revision=2,
            deleted_at="2026-10-27T12:00:00Z",
        ))
        self.assertEqual(record.course_number, CourseNumber.CHAPTER_TWO)
        self.assertEqual(record.participation_mode, ParticipationMode.TOGETHER)
        self.assertEqual(record.deleted_at.tzinfo, timezone.utc)

    def test_offsets_normalize_to_utc(self):
        record = CompletionRecordMetadata(**payload(
            completed_at="2026-10-26T21:00:00+09:00",
            deleted_at="2026-10-27T07:00:00-05:00",
        ))
        self.assertEqual(record.completed_at, datetime(2026, 10, 26, 12, tzinfo=timezone.utc))
        serialized = record.model_dump(mode="json")
        self.assertEqual(serialized["completed_at"], "2026-10-26T12:00:00Z")
        self.assertEqual(serialized["deleted_at"], "2026-10-27T12:00:00Z")

    def test_invalid_uuid(self):
        for value in ("1-1793000000000000", "invalid", "", 123, None):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                CompletionRecordMetadata(**payload(id=value))

    def test_invalid_chapter(self):
        for value in (0, 3, -1, True, "1", 1.0, None):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                CompletionRecordMetadata(**payload(course_number=value))

    def test_invalid_participation_mode(self):
        for value in ("unknown", "SOLO", "", 1, None):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                CompletionRecordMetadata(**payload(participation_mode=value))

    def test_invalid_revision(self):
        for value in (0, -1, True, "1", 1.0, None):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                CompletionRecordMetadata(**payload(revision=value))

    def test_timezone_required_and_invalid_timestamps_rejected(self):
        for field in ("completed_at", "deleted_at"):
            for value in ("2026-10-26T12:00:00", datetime(2026, 10, 26),
                          "2026-10-26", "invalid", 1793000000, True):
                with self.subTest(field=field, value=value), self.assertRaises(ValidationError):
                    CompletionRecordMetadata(**payload(**{field: value}))

    def test_required_fields(self):
        for field in ("id", "course_number", "participation_mode", "completed_at", "revision"):
            data = payload()
            del data[field]
            with self.subTest(field=field), self.assertRaises(ValidationError):
                CompletionRecordMetadata(**data)
        with self.assertRaises(ValidationError):
            CompletionRecordMetadata(**payload(completed_at=None))

    def test_sensitive_and_unknown_fields_forbidden(self):
        for field in (
            "myName", "my_name", "partnerName", "partner_name",
            "graceReflection", "grace_reflection", "signature_image",
            "signatureImage", "handwriting_coordinates", "signature_points",
            "mySignedAt", "partnerSignedAt", "courseTitle", "unknown",
        ):
            with self.subTest(field=field):
                with self.assertRaises(ValidationError) as caught:
                    CompletionRecordMetadata.model_validate_json(json.dumps(
                        payload(**{field: "SYNTHETIC_PRIVATE_VALUE"})
                    ))
                self.assertEqual(caught.exception.errors(include_input=False)[0]["type"], "extra_forbidden")
                self.assertNotIn("SYNTHETIC_PRIVATE_VALUE", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
