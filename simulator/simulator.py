"""
AquaCloud - Smart Water Flow Sensor Simulator

Simulates campus water-flow sensors and sends readings to AquaCloud.

Modes:
    stream  -> continuously generate normal readings
    spike   -> generate normal readings followed by a leak
    load    -> generate many readings for testing

Cloud environment variables:
    AQUACLOUD_API_URL
    AQUACLOUD_API_KEY

Use --dry-run to test everything locally without AWS.
"""

import argparse
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------
# Import shared processing logic
# ---------------------------------------------------------

ROOT = Path(__file__).resolve().parents[1]
LAMBDA_PATH = ROOT / "lambda" / "ingest"

if str(LAMBDA_PATH) not in sys.path:
    sys.path.insert(0, str(LAMBDA_PATH))

from processing import BUILDINGS, process_reading


# ---------------------------------------------------------
# Local history
# ---------------------------------------------------------

# Stores recent NORMAL flow readings for each building.
# This is used only during local simulation.
local_history = {
    building_id: []
    for building_id in BUILDINGS
}


# ---------------------------------------------------------
# Utility
# ---------------------------------------------------------

def utc_now():
    """Return the current UTC timestamp."""

    return datetime.now(timezone.utc).isoformat(
        timespec="seconds"
    )


def get_building(building_id):
    """Return building configuration."""

    if building_id not in BUILDINGS:
        raise ValueError(
            f"Unknown building: {building_id}"
        )

    return BUILDINGS[building_id]


# ---------------------------------------------------------
# Reading generation
# ---------------------------------------------------------

def make_reading(building_id, leak=False):
    """
    Generate a simulated water-flow sensor reading.

    Normal:
        Generates flow inside the expected operating range.

    Leak:
        Generates unusually high flow above the hard limit.
    """

    cfg = get_building(building_id)

    normal_min = cfg["normal_min_lpm"]
    normal_max = cfg["normal_max_lpm"]
    max_flow = cfg["max_flow_lpm"]

    if leak:

        # Deliberately generate abnormal water flow.
        flow_lpm = (
            max_flow
            * random.uniform(1.30, 1.60)
        )

    else:

        # Normal flow fluctuates around the middle
        # of the building's expected range.
        midpoint = (
            normal_min + normal_max
        ) / 2

        flow_lpm = (
            midpoint
            * random.uniform(0.85, 1.15)
        )

        # Keep normal values inside the configured band.
        flow_lpm = max(
            normal_min,
            min(flow_lpm, normal_max)
        )

    return {
        "building_id": building_id,
        "sensor_id": cfg["sensor_id"],
        "flow_lpm": round(flow_lpm, 2),
        "sensor_ts": utc_now(),
    }


# ---------------------------------------------------------
# Local processing
# ---------------------------------------------------------

def process_local(reading):
    """
    Process one reading using the SAME processing.py
    used by the AWS Lambda.

    process_reading() returns:

        (record, errors)
    """

    building_id = reading["building_id"]

    history = local_history[building_id]

    record, errors = process_reading(
        reading,
        history,
    )

    return record, errors


def display_result(reading, record, errors):
    """Display one processed reading."""

    if errors:

        print(
            f"[ERROR] "
            f"{reading['building_id']} | "
            f"{reading['flow_lpm']:.2f} L/min"
        )

        for error in errors:
            print(
                f"    -> {error}"
            )

        return

    print(
        f"[{reading['sensor_ts']}] "
        f"{reading['building_id']} | "
        f"{reading['sensor_id']} | "
        f"{reading['flow_lpm']:.2f} L/min | "
        f"{record['status']}"
    )

    if record.get("baseline_lpm") is not None:

        print(
            f"    -> Baseline: "
            f"{record['baseline_lpm']:.2f} L/min"
        )

    for reason in record.get(
        "reasons",
        []
    ):

        print(
            f"    -> {reason}"
        )


def update_history(reading, record):
    """
    Add a reading to the baseline history only when
    the reading is NORMAL.
    """

    if not record:
        return

    if record.get("status") != "NORMAL":
        return

    building_id = reading["building_id"]

    local_history[building_id].append(
        reading["flow_lpm"]
    )

    # Keep only the most recent 10 normal readings.
    local_history[building_id] = (
        local_history[building_id][-10:]
    )


# ---------------------------------------------------------
# Cloud communication
# ---------------------------------------------------------

def send_cloud(
    reading,
    api_url,
    api_key,
):
    """Send a reading to the AquaCloud API."""

    body = json.dumps(
        reading
    ).encode("utf-8")

    request = urllib.request.Request(
        api_url.rstrip("/")
        + "/readings",
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
        },
    )

    try:

        with urllib.request.urlopen(
            request,
            timeout=15,
        ) as response:

            text = response.read().decode(
                "utf-8"
            )

            try:
                data = json.loads(text)

            except json.JSONDecodeError:
                data = {
                    "raw": text
                }

            return (
                response.status,
                data,
            )

    except urllib.error.HTTPError as error:

        try:
            text = error.read().decode(
                "utf-8"
            )

            data = json.loads(text)

        except Exception:
            data = {
                "error": str(error)
            }

        return (
            error.code,
            data,
        )

    except Exception as error:

        return (
            0,
            {
                "error": str(error)
            },
        )


def get_cloud_config():

    api_url = os.getenv(
        "AQUACLOUD_API_URL"
    )

    api_key = os.getenv(
        "AQUACLOUD_API_KEY"
    )

    if not api_url:
        raise RuntimeError(
            "AQUACLOUD_API_URL is not set."
        )

    if not api_key:
        raise RuntimeError(
            "AQUACLOUD_API_KEY is not set."
        )

    return api_url, api_key


# ---------------------------------------------------------
# STREAM MODE
# ---------------------------------------------------------

def run_stream(
    building_id,
    interval,
    dry_run,
):
    """
    Continuously generate normal water-flow readings.
    """

    if not dry_run:

        api_url, api_key = (
            get_cloud_config()
        )

    print(
        "AquaCloud water-flow simulator started."
    )

    print(
        f"Building : {building_id}"
    )

    print(
        f"Interval : {interval} seconds"
    )

    print(
        f"Dry run  : {dry_run}"
    )

    print(
        "-" * 70
    )

    # Reset history for this run.
    local_history[building_id] = []

    try:

        while True:

            reading = make_reading(
                building_id,
                leak=False,
            )

            if dry_run:

                record, errors = (
                    process_local(
                        reading
                    )
                )

                display_result(
                    reading,
                    record,
                    errors,
                )

                if not errors:

                    update_history(
                        reading,
                        record,
                    )

            else:

                status, response = (
                    send_cloud(
                        reading,
                        api_url,
                        api_key,
                    )
                )

                print(
                    f"[{reading['sensor_ts']}] "
                    f"{building_id} | "
                    f"{reading['flow_lpm']:.2f} L/min | "
                    f"Cloud HTTP {status}"
                )

                if response:

                    print(
                        f"    -> {response}"
                    )

            time.sleep(
                interval
            )

    except KeyboardInterrupt:

        print(
            "\nSimulator stopped."
        )


# ---------------------------------------------------------
# SPIKE MODE
# ---------------------------------------------------------

def run_spike(
    building_id,
    dry_run,
):
    """
    Generate five normal readings followed by
    one deliberate high-flow leak reading.
    """

    if not dry_run:

        api_url, api_key = (
            get_cloud_config()
        )

    print(
        "AquaCloud leak demonstration"
    )

    print(
        f"Building: {building_id}"
    )

    print(
        "-" * 70
    )

    # Reset history.
    local_history[building_id] = []

    # -----------------------------------------------------
    # Normal readings
    # -----------------------------------------------------

    print(
        "\nGenerating normal readings...\n"
    )

    for _ in range(5):

        reading = make_reading(
            building_id,
            leak=False,
        )

        if dry_run:

            record, errors = (
                process_local(
                    reading
                )
            )

            display_result(
                reading,
                record,
                errors,
            )

            if not errors:

                update_history(
                    reading,
                    record,
                )

        else:

            status, response = (
                send_cloud(
                    reading,
                    api_url,
                    api_key,
                )
            )

            print(
                f"{reading['flow_lpm']:.2f} L/min "
                f"| Cloud HTTP {status}"
            )

            if response:
                print(
                    f"    -> {response}"
                )

        time.sleep(1)

    # -----------------------------------------------------
    # Leak reading
    # -----------------------------------------------------

    print(
        "\n" + "=" * 70
    )

    print(
        ">>> SIMULATING WATER LEAK <<<"
    )

    print(
        "=" * 70 + "\n"
    )

    leak_reading = make_reading(
        building_id,
        leak=True,
    )

    if dry_run:

        record, errors = (
            process_local(
                leak_reading
            )
        )

        display_result(
            leak_reading,
            record,
            errors,
        )

    else:

        status, response = (
            send_cloud(
                leak_reading,
                api_url,
                api_key,
            )
        )

        print(
            f"{leak_reading['flow_lpm']:.2f} L/min "
            f"| Cloud HTTP {status}"
        )

        if response:
            print(
                f"    -> {response}"
            )

    print(
        "\nLeak demonstration completed."
    )


# ---------------------------------------------------------
# LOAD MODE
# ---------------------------------------------------------

def run_load(
    building_id,
    count,
    dry_run,
):
    """
    Generate a batch of normal readings.

    Used for basic performance/load testing.
    """

    if count <= 0:

        raise ValueError(
            "Count must be greater than 0."
        )

    if not dry_run:

        api_url, api_key = (
            get_cloud_config()
        )

    print(
        "AquaCloud load test"
    )

    print(
        f"Building : {building_id}"
    )

    print(
        f"Readings : {count}"
    )

    print(
        f"Dry run  : {dry_run}"
    )

    print(
        "-" * 70
    )

    local_history[building_id] = []

    normal_count = 0
    leak_count = 0
    error_count = 0

    start_time = time.perf_counter()

    for index in range(count):

        reading = make_reading(
            building_id,
            leak=False,
        )

        if dry_run:

            record, errors = (
                process_local(
                    reading
                )
            )

            if errors:

                error_count += 1

            elif record["status"] == "NORMAL":

                normal_count += 1

                update_history(
                    reading,
                    record,
                )

            else:

                leak_count += 1

            # Display first ten readings.
            if index < 10:

                if record:

                    print(
                        f"Reading {index + 1}: "
                        f"{reading['flow_lpm']:.2f} L/min "
                        f"-> {record['status']}"
                    )

                else:

                    print(
                        f"Reading {index + 1}: "
                        f"ERROR"
                    )

        else:

            status, response = (
                send_cloud(
                    reading,
                    api_url,
                    api_key,
                )
            )

            if 200 <= status < 300:

                normal_count += 1

            else:

                error_count += 1

                print(
                    f"Reading {index + 1} failed: "
                    f"{response}"
                )

    elapsed = (
        time.perf_counter()
        - start_time
    )

    print(
        "\n" + "-" * 70
    )

    print(
        f"Normal readings : {normal_count}"
    )

    print(
        f"Leak readings   : {leak_count}"
    )

    print(
        f"Errors          : {error_count}"
    )

    print(
        f"Total readings  : {count}"
    )

    print(
        f"Elapsed time    : {elapsed:.3f} seconds"
    )

    if elapsed > 0:

        print(
            f"Throughput      : "
            f"{count / elapsed:.2f} readings/sec"
        )


# ---------------------------------------------------------
# Command line interface
# ---------------------------------------------------------

def main():

    parser = argparse.ArgumentParser(
        description=(
            "AquaCloud smart water-flow "
            "sensor simulator"
        )
    )

    parser.add_argument(
        "mode",
        choices=[
            "stream",
            "spike",
            "load",
        ],
        help="Simulation mode",
    )

    parser.add_argument(
        "--building",
        default="LAB-1",
        choices=list(
            BUILDINGS.keys()
        ),
        help="Building to simulate",
    )

    parser.add_argument(
        "--interval",
        type=float,
        default=5,
        help=(
            "Seconds between readings "
            "in stream mode"
        ),
    )

    parser.add_argument(
        "--count",
        type=int,
        default=100,
        help=(
            "Number of readings "
            "in load mode"
        ),
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Run locally without "
            "sending data to AWS"
        ),
    )

    args = parser.parse_args()

    if args.mode == "stream":

        run_stream(
            building_id=args.building,
            interval=args.interval,
            dry_run=args.dry_run,
        )

    elif args.mode == "spike":

        run_spike(
            building_id=args.building,
            dry_run=args.dry_run,
        )

    elif args.mode == "load":

        run_load(
            building_id=args.building,
            count=args.count,
            dry_run=args.dry_run,
        )


if __name__ == "__main__":

    main()