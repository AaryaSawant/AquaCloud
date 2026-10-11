"""
Unit tests for AquaCloud water-flow processing and leak detection.

Run from project root:
    python -m unittest discover -s tests -v
"""

import os
import sys
import unittest

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "lambda",
        "ingest",
    ),
)

from processing import (  # noqa: E402
    compute_baseline,
    detect_leak,
    process_reading,
    validate_reading,
)


def reading(**overrides):
    """Create a valid default water-flow reading."""
    base = {
        "building_id": "LAB-1",
        "sensor_id": "WTR-LAB-1-01",
        "flow_lpm": 15.0,
    }
    base.update(overrides)
    return base


class TestValidation(unittest.TestCase):

    def test_valid_reading(self):
        clean, errors = validate_reading(reading())

        self.assertEqual(errors, [])
        self.assertEqual(clean["building_id"], "LAB-1")
        self.assertEqual(clean["flow_lpm"], 15.0)

    def test_unknown_building(self):
        _, errors = validate_reading(
            reading(building_id="MOON-BASE")
        )

        self.assertTrue(
            any("Unknown building_id" in e for e in errors)
        )

    def test_sensor_not_registered_to_building(self):
        _, errors = validate_reading(
            reading(sensor_id="WTR-LIB-01")
        )

        self.assertTrue(
            any("not registered" in e for e in errors)
        )

    def test_flow_out_of_range(self):
        _, errors = validate_reading(
            reading(flow_lpm=250)
        )

        self.assertTrue(
            any("flow_lpm" in e for e in errors)
        )

    def test_non_numeric_flow(self):
        _, errors = validate_reading(
            reading(flow_lpm="lots")
        )

        self.assertTrue(
            any("flow_lpm must be a number" in e for e in errors)
        )

    def test_boolean_rejected(self):
        _, errors = validate_reading(
            reading(flow_lpm=True)
        )

        self.assertTrue(errors)

    def test_non_object_body(self):
        _, errors = validate_reading(
            ["not", "a", "dict"]
        )

        self.assertEqual(
            errors,
            ["Body must be a JSON object"],
        )


class TestBaseline(unittest.TestCase):

    def test_baseline_average(self):
        flows = [15.0, 15.5, 14.5, 15.0, 16.0]

        self.assertEqual(
            compute_baseline(flows),
            15.2,
        )

    def test_baseline_requires_minimum_samples(self):
        flows = [15.0, 15.0, 15.0]

        self.assertIsNone(
            compute_baseline(flows)
        )

    def test_baseline_uses_recent_window(self):
        flows = [
            15.0,
            15.0,
            15.0,
            15.0,
            15.0,
            15.0,
            15.0,
            15.0,
            15.0,
            15.0,
            100.0,
        ]

        self.assertEqual(
            compute_baseline(flows),
            15.0,
        )


class TestLeakDetection(unittest.TestCase):

    NORMAL_HISTORY = [
        15.0,
        15.5,
        14.5,
        15.0,
        16.0,
        14.0,
    ]

    def test_normal_reading(self):
        result = detect_leak(
            "LAB-1",
            16.0,
            self.NORMAL_HISTORY,
        )

        self.assertEqual(
            result["status"],
            "NORMAL",
        )

    def test_rule1_threshold(self):
        # LAB-1 limit is 35 L/min.
        result = detect_leak(
            "LAB-1",
            40.0,
            [],
        )

        self.assertEqual(
            result["status"],
            "LEAK DETECTED",
        )

        self.assertTrue(
            result["reasons"][0].startswith("THRESHOLD")
        )

    def test_rule2_baseline_deviation(self):
        # Baseline is approximately 15 L/min.
        # 25 L/min is > 1.5 x baseline.
        result = detect_leak(
            "LAB-1",
            25.0,
            self.NORMAL_HISTORY,
        )

        self.assertEqual(
            result["status"],
            "LEAK DETECTED",
        )

        self.assertTrue(
            any(
                reason.startswith("DEVIATION")
                for reason in result["reasons"]
            )
        )

    def test_rule2_needs_min_samples(self):
        # Only 3 readings means no baseline yet.
        result = detect_leak(
            "LAB-1",
            25.0,
            [15.0, 15.0, 15.0],
        )

        self.assertEqual(
            result["status"],
            "NORMAL",
        )

    def test_both_rules(self):
        # 50 L/min exceeds the 35 L/min threshold
        # and is also >1.5x the normal baseline.
        result = detect_leak(
            "LAB-1",
            50.0,
            self.NORMAL_HISTORY,
        )

        self.assertEqual(
            result["status"],
            "LEAK DETECTED",
        )

        self.assertEqual(
            len(result["reasons"]),
            2,
        )


class TestFullPipeline(unittest.TestCase):

    NORMAL_HISTORY = [
        15.0,
        15.5,
        14.5,
        15.0,
        16.0,
        14.0,
    ]

    def test_normal_pipeline(self):
        record, errors = process_reading(
            reading(flow_lpm=16.0),
            self.NORMAL_HISTORY,
        )

        self.assertEqual(errors, [])

        self.assertEqual(
            record["status"],
            "NORMAL",
        )

        self.assertEqual(
            record["flow_lpm"],
            16.0,
        )

    def test_leak_pipeline(self):
        record, errors = process_reading(
            reading(flow_lpm=50.0),
            self.NORMAL_HISTORY,
        )

        self.assertEqual(errors, [])

        self.assertEqual(
            record["status"],
            "LEAK DETECTED",
        )

        self.assertTrue(record["reasons"])


if __name__ == "__main__":
    unittest.main()