import unittest

from receipt_ocr.firestore_writer import reservation_decision


class ReservationDecisionTest(unittest.TestCase):
    def test_stops_at_limit(self):
        decision, increment = reservation_decision({}, 20, 20)
        self.assertFalse(decision.reserved)
        self.assertEqual(decision.reason, "limit_reached")
        self.assertFalse(increment)

    def test_terminal_and_reserved_jobs_are_idempotent(self):
        for status in ("completed", "needs_review", "unknown_after_request", "vision_reserved"):
            decision, increment = reservation_decision({"status": status}, 0, 20)
            self.assertFalse(decision.reserved)
            self.assertFalse(increment)

    def test_pre_request_failure_reuses_reservation(self):
        decision, increment = reservation_decision(
            {"status": "failed", "visionAttempted": False}, 20, 20
        )
        self.assertTrue(decision.reserved)
        self.assertFalse(increment)


if __name__ == "__main__":
    unittest.main()
