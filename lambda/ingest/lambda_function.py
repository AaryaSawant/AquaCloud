"""
AquaCloud - Cloud-Based Campus Water Leak Detection System

Routes:
  POST /readings   sensor reading -> validate -> leak detection -> DynamoDB
  GET  /dashboard  latest readings, leaks and summary for dashboard
  POST /export     recent readings -> JSON + CSV report in S3

AWS services:
  - API Gateway
  - AWS Lambda
  - Amazon DynamoDB
  - Amazon S3
  - Amazon CloudWatch Logs

Configuration:
  TABLE_NAME
  BUCKET_NAME
"""

import csv
import io
import json
import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

from processing import BUILDINGS, process_reading, validate_reading


# ------------------------------------------------------------------
# AWS CONFIGURATION
# ------------------------------------------------------------------

TABLE_NAME = os.environ.get(
    "TABLE_NAME",
    "AquaCloudReadings"
)

BUCKET_NAME = os.environ.get(
    "BUCKET_NAME",
    ""
)

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)

s3 = boto3.client("s3")


# ------------------------------------------------------------------
# HTTP / CORS
# ------------------------------------------------------------------

CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,x-api-key",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
}


def respond(status, body):
    """
    Standard API Gateway response.
    """
    return {
        "statusCode": status,
        "headers": CORS_HEADERS,
        "body": json.dumps(body),
    }


# ------------------------------------------------------------------
# DYNAMODB -> JSON HELPERS
# ------------------------------------------------------------------

def to_plain(item):
    """
    Convert a DynamoDB item into a JSON-friendly AquaCloud reading.

    DynamoDB stores numbers as Decimal, so they are converted to float
    before returning them through API Gateway.
    """

    def num(key):
        value = item.get(key)

        if value is None:
            return None

        return float(value)

    status = item.get("status", "NORMAL")

    reasons = item.get("reasons")

    if reasons is None:
        reasons = []

    return {
        "building_id": item.get("building_id"),
        "sensor_id": item.get("sensor_id"),
        "ts": item.get("received_at") or item.get("ts"),
        "sensor_ts": item.get("sensor_ts"),

        "flow_lpm": num("flow_lpm"),

        "status": status,
        "reasons": list(reasons),

        "baseline_lpm": num("baseline_lpm"),
    }


# ------------------------------------------------------------------
# DATABASE QUERIES
# ------------------------------------------------------------------

def recent_readings(building_id, limit=10):
    """
    Get newest readings for one building.

    DynamoDB design:

        Partition key: building_id
        Sort key:      ts

    Newest readings are returned first.
    """

    result = table.query(
        KeyConditionExpression=Key("building_id").eq(building_id),
        ScanIndexForward=False,
        Limit=limit,
    )

    return [
        to_plain(item)
        for item in result.get("Items", [])
    ]


# ------------------------------------------------------------------
# POST /readings
# ------------------------------------------------------------------

def handle_ingest(event):
    """
    Receive a water-flow reading from the simulator/sensor.

    Pipeline:

        API Gateway
             |
             v
          Lambda
             |
        validation
             |
       leak detection
             |
             v
        DynamoDB
    """

    # --------------------------------------------------------------
    # Parse JSON
    # --------------------------------------------------------------

    try:
        payload = json.loads(event.get("body") or "")

    except (TypeError, ValueError):
        return respond(
            400,
            {
                "errors": [
                    "Body must be valid JSON"
                ]
            },
        )

    # --------------------------------------------------------------
    # Validate reading
    # --------------------------------------------------------------

    _, errors = validate_reading(payload)

    if errors:

        print(
            json.dumps(
                {
                    "event": "rejected",
                    "errors": errors,
                }
            )
        )

        return respond(
            400,
            {
                "errors": errors
            },
        )

    # --------------------------------------------------------------
    # Get recent NORMAL readings for baseline calculation
    # --------------------------------------------------------------

    recent = recent_readings(
        payload["building_id"],
        10,
    )

    history = [
        float(reading["flow_lpm"])
        for reading in recent
        if reading.get("status") == "NORMAL"
        and reading.get("flow_lpm") is not None
    ]

    # --------------------------------------------------------------
    # Process reading
    #
    # process_reading() returns:
    #
    #     (record, errors)
    # --------------------------------------------------------------

    record, errors = process_reading(
        payload,
        history,
    )

    if errors:

        print(
            json.dumps(
                {
                    "event": "processing_rejected",
                    "errors": errors,
                }
            )
        )

        return respond(
            400,
            {
                "errors": errors
            },
        )

    # --------------------------------------------------------------
    # Server-side timestamp
    # --------------------------------------------------------------

    received_at = (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )

    # Random suffix prevents collisions when two readings arrive
    # during the same millisecond.

    timestamp_key = (
        f"{received_at}#{uuid.uuid4().hex[:6]}"
    )

    # --------------------------------------------------------------
    # DynamoDB item
    # --------------------------------------------------------------

    item = {
        # Primary key
        "building_id": record["building_id"],
        "ts": timestamp_key,

        # Metadata
        "received_at": received_at,
        "sensor_id": record["sensor_id"],

        # Water measurement
        "flow_lpm": Decimal(
            str(record["flow_lpm"])
        ),

        # Detection result
        "status": record["status"],
        "reasons": record["reasons"],
    }

    # Baseline is optional because there may not be enough
    # historical readings during the first few readings.

    if record.get("baseline_lpm") is not None:

        item["baseline_lpm"] = Decimal(
            str(record["baseline_lpm"])
        )

    # Preserve original sensor timestamp if supplied.

    if record.get("sensor_ts"):

        item["sensor_ts"] = record["sensor_ts"]

    # --------------------------------------------------------------
    # STORE IN DYNAMODB
    # --------------------------------------------------------------

    table.put_item(
        Item=item
    )

    # --------------------------------------------------------------
    # CLOUDWATCH LOGGING
    # --------------------------------------------------------------

    log = {
        "event": "water_reading",
        "building_id": item["building_id"],
        "sensor_id": item["sensor_id"],
        "flow_lpm": record["flow_lpm"],
        "status": record["status"],
    }

    if record["status"] == "LEAK DETECTED":

        log["reasons"] = record["reasons"]

        print(
            "LEAK DETECTED "
            + json.dumps(log)
        )

    else:

        print(
            json.dumps(log)
        )

    # --------------------------------------------------------------
    # API RESPONSE
    # --------------------------------------------------------------

    return respond(
        200,
        {
            "message": "stored",
            "reading": to_plain(item),
        },
    )


# ------------------------------------------------------------------
# GET /dashboard
# ------------------------------------------------------------------

def handle_dashboard():
    """
    Build the dashboard payload.

    Returns:

      - building information
      - latest reading for every building
      - recent readings
      - detected leaks
      - summary statistics
    """

    buildings = []
    all_readings = []

    # --------------------------------------------------------------
    # Collect readings for each campus building
    # --------------------------------------------------------------

    for building_id, config in BUILDINGS.items():

        readings = recent_readings(
            building_id,
            50,
        )

        all_readings.extend(readings)

        buildings.append(
            {
                "building_id": building_id,
                **config,
                "latest": (
                    readings[0]
                    if readings
                    else None
                ),
            }
        )

    # --------------------------------------------------------------
    # Sort newest first
    # --------------------------------------------------------------

    all_readings.sort(
        key=lambda reading: reading["ts"],
        reverse=True,
    )

    # --------------------------------------------------------------
    # Find detected leaks
    # --------------------------------------------------------------

    leaks = [
        reading
        for reading in all_readings
        if reading["status"] == "LEAK DETECTED"
    ]

    # --------------------------------------------------------------
    # Calculate total current flow
    # --------------------------------------------------------------

    total_flow = sum(
        building["latest"]["flow_lpm"]
        for building in buildings
        if building["latest"]
        and building["latest"].get("flow_lpm")
        is not None
    )

    # --------------------------------------------------------------
    # Dashboard response
    # --------------------------------------------------------------

    return respond(
        200,
        {
            "generated_at": (
                datetime.now(timezone.utc)
                .isoformat(timespec="seconds")
            ),

            "summary": {

                "total_buildings": len(
                    buildings
                ),

                "active_sensors": sum(
                    1
                    for building in buildings
                    if building["latest"]
                ),

                "total_flow_lpm": round(
                    total_flow,
                    3,
                ),

                "leak_count": len(
                    leaks
                ),

                "readings_count": len(
                    all_readings
                ),
            },

            "buildings": buildings,

            "recent_readings": (
                all_readings[:20]
            ),

            "leaks": leaks[:20],
        },
    )


# ------------------------------------------------------------------
# POST /export
# ------------------------------------------------------------------

def handle_export():
    """
    Export recent AquaCloud readings to Amazon S3.

    Two files are created:

        reports/YYYYMMDD/aquacloud-report-TIMESTAMP.json
        reports/YYYYMMDD/aquacloud-report-TIMESTAMP.csv
    """

    if not BUCKET_NAME:

        return respond(
            500,
            {
                "error": (
                    "BUCKET_NAME environment "
                    "variable is not set"
                )
            },
        )

    # --------------------------------------------------------------
    # Collect recent readings
    # --------------------------------------------------------------

    rows = []

    for building_id in BUILDINGS:

        rows.extend(
            recent_readings(
                building_id,
                200,
            )
        )

    # Oldest -> newest for report

    rows.sort(
        key=lambda reading: reading["ts"]
    )

    # --------------------------------------------------------------
    # Report timestamp
    # --------------------------------------------------------------

    stamp = datetime.now(
        timezone.utc
    ).strftime(
        "%Y%m%dT%H%M%SZ"
    )

    base = (
        f"reports/{stamp[:8]}/"
        f"aquacloud-report-{stamp}"
    )

    # --------------------------------------------------------------
    # JSON REPORT
    # --------------------------------------------------------------

    json_report = json.dumps(
        {
            "project": "AquaCloud",
            "generated_at": stamp,
            "records": rows,
        },
        indent=2,
    )

    # --------------------------------------------------------------
    # CSV REPORT
    # --------------------------------------------------------------

    csv_buffer = io.StringIO()

    fields = [
        "ts",
        "building_id",
        "sensor_id",
        "sensor_ts",
        "flow_lpm",
        "status",
        "baseline_lpm",
        "reasons",
    ]

    writer = csv.DictWriter(
        csv_buffer,
        fieldnames=fields,
        extrasaction="ignore",
    )

    writer.writeheader()

    for reading in rows:

        writer.writerow(
            {
                **reading,

                "reasons": "; ".join(
                    reading.get(
                        "reasons",
                        []
                    )
                ),
            }
        )

    # --------------------------------------------------------------
    # UPLOAD JSON TO S3
    # --------------------------------------------------------------

    json_key = base + ".json"

    s3.put_object(
        Bucket=BUCKET_NAME,
        Key=json_key,
        Body=json_report.encode("utf-8"),
        ContentType="application/json",
    )

    # --------------------------------------------------------------
    # UPLOAD CSV TO S3
    # --------------------------------------------------------------

    csv_key = base + ".csv"

    s3.put_object(
        Bucket=BUCKET_NAME,
        Key=csv_key,
        Body=csv_buffer.getvalue().encode("utf-8"),
        ContentType="text/csv",
    )

    # --------------------------------------------------------------
    # CLOUDWATCH LOG
    # --------------------------------------------------------------

    print(
        json.dumps(
            {
                "event": "export",
                "records": len(rows),
                "json_key": json_key,
                "csv_key": csv_key,
            }
        )
    )

    # --------------------------------------------------------------
    # RESPONSE
    # --------------------------------------------------------------

    return respond(
        200,
        {
            "project": "AquaCloud",

            "bucket": BUCKET_NAME,

            "json_key": json_key,

            "csv_key": csv_key,

            "records": len(rows),
        },
    )


# ------------------------------------------------------------------
# LAMBDA ENTRY POINT
# ------------------------------------------------------------------

def lambda_handler(event, context):

    method = event.get(
        "httpMethod"
    )

    route = event.get(
        "resource"
    )

    try:

        # ----------------------------------------------------------
        # CORS preflight
        # ----------------------------------------------------------

        if method == "OPTIONS":

            return respond(
                200,
                {
                    "message": "ok"
                },
            )

        # ----------------------------------------------------------
        # POST /readings
        # ----------------------------------------------------------

        if (
            method == "POST"
            and route == "/readings"
        ):

            return handle_ingest(
                event
            )

        # ----------------------------------------------------------
        # GET /dashboard
        # ----------------------------------------------------------

        if (
            method == "GET"
            and route == "/dashboard"
        ):

            return handle_dashboard()

        # ----------------------------------------------------------
        # POST /export
        # ----------------------------------------------------------

        if (
            method == "POST"
            and route == "/export"
        ):

            return handle_export()

        # ----------------------------------------------------------
        # Unknown route
        # ----------------------------------------------------------

        return respond(
            404,
            {
                "error": (
                    f"No route for "
                    f"{method} {route}"
                )
            },
        )

    except Exception as exc:

        # Full error goes to CloudWatch.
        # Client receives only a generic message.

        print(
            json.dumps(
                {
                    "event": "error",
                    "route": route,
                    "method": method,
                    "error": repr(exc),
                }
            )
        )

        return respond(
            500,
            {
                "error": "Internal server error"
            },
        )