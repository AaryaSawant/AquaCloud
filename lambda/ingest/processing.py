"""
AquaCloud - water-flow processing and leak detection logic.

Pure Python (no AWS imports) so it can be unit-tested locally
and reused inside the ingest Lambda.

Responsibilities:
    1. Building / sensor configuration
    2. Input validation
    3. Water-flow validation
    4. Leak detection using two explainable rules
"""

# --------------------------------------------------------------------------
# 1. Campus water sensor configuration
#
# normal_min_lpm / normal_max_lpm:
#     Expected water-flow range for the building.
#
# max_flow_lpm:
#     Absolute flow threshold. A reading above this is considered
#     a possible leak.
# --------------------------------------------------------------------------

BUILDINGS = {
    "ACAD-A": {
        "name": "Academic Block A",
        "type": "Classrooms",
        "sensor_id": "WTR-ACAD-A-01",
        "normal_min_lpm": 10.0,
        "normal_max_lpm": 25.0,
        "max_flow_lpm": 40.0,
    },
    "LAB-1": {
        "name": "Computer Lab 1",
        "type": "Laboratory",
        "sensor_id": "WTR-LAB-1-01",
        "normal_min_lpm": 8.0,
        "normal_max_lpm": 20.0,
        "max_flow_lpm": 35.0,
    },
    "LIB": {
        "name": "Central Library",
        "type": "Library",
        "sensor_id": "WTR-LIB-01",
        "normal_min_lpm": 5.0,
        "normal_max_lpm": 15.0,
        "max_flow_lpm": 28.0,
    },
    "HOSTEL-A": {
        "name": "Hostel A",
        "type": "Hostel",
        "sensor_id": "WTR-HOSTEL-A-01",
        "normal_min_lpm": 20.0,
        "normal_max_lpm": 45.0,
        "max_flow_lpm": 70.0,
    },
    "ADMIN": {
        "name": "Admin Block",
        "type": "Administration",
        "sensor_id": "WTR-ADMIN-01",
        "normal_min_lpm": 5.0,
        "normal_max_lpm": 12.0,
        "max_flow_lpm": 22.0,
    },
}


# Reasonable operating range for a simulated water-flow sensor.
FLOW_MIN_LPM = 0.0
FLOW_MAX_LPM = 200.0

# Use up to the last 10 normal readings when calculating the baseline.
BASELINE_WINDOW = 10

# Require at least 5 normal readings before using the baseline rule.
BASELINE_MIN_SAMPLES = 5

# Leak is flagged when flow exceeds 1.5x the recent normal baseline.
DEVIATION_FACTOR = 1.5


# --------------------------------------------------------------------------
# 2. Validation
# --------------------------------------------------------------------------

def _is_number(value):
    """Return True for numeric values, excluding booleans."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_reading(payload):
    """
    Validate an incoming water-flow sensor reading.

    Returns:
        (clean_reading, errors)

    clean_reading is None when validation fails.
    """

    errors = []

    if not isinstance(payload, dict):
        return None, ["Body must be a JSON object"]

    building_id = payload.get("building_id")
    sensor_id = payload.get("sensor_id")
    flow_lpm = payload.get("flow_lpm")

    # Validate building and registered sensor.
    if not isinstance(building_id, str) or building_id not in BUILDINGS:
        errors.append(f"Unknown building_id: {building_id!r}")
    elif sensor_id != BUILDINGS[building_id]["sensor_id"]:
        errors.append(
            f"sensor_id {sensor_id!r} is not registered to {building_id}"
        )

    # Validate water flow.
    if not _is_number(flow_lpm):
        errors.append("flow_lpm must be a number")
    elif not (FLOW_MIN_LPM <= flow_lpm <= FLOW_MAX_LPM):
        errors.append(
            f"flow_lpm {flow_lpm} outside "
            f"{FLOW_MIN_LPM}-{FLOW_MAX_LPM} L/min"
        )

    if errors:
        return None, errors

    return {
        "building_id": building_id,
        "sensor_id": sensor_id,
        "flow_lpm": round(float(flow_lpm), 2),
        "sensor_ts": str(payload.get("sensor_ts", ""))[:40],
    }, []


# --------------------------------------------------------------------------
# 3. Baseline calculation
# --------------------------------------------------------------------------

def compute_baseline(recent_normal_flows):
    """
    Calculate the average of recent normal water-flow readings.

    Returns None until enough normal readings are available.
    """

    window = list(recent_normal_flows)[:BASELINE_WINDOW]

    if len(window) < BASELINE_MIN_SAMPLES:
        return None

    return round(sum(window) / len(window), 3)


# --------------------------------------------------------------------------
# 4. Leak detection
#
# Rule 1:
#     Absolute threshold.
#     Example: 45 L/min > building limit of 35 L/min.
#
# Rule 2:
#     Baseline deviation.
#     Example: normal baseline = 15 L/min.
#              current flow = 25 L/min.
#              25 > 1.5 × 15 -> possible leak.
#
# Both rules are deliberately explainable and easy to defend in a viva.
# --------------------------------------------------------------------------

def detect_leak(building_id, flow_lpm, recent_normal_flows):
    """
    Detect abnormal water flow.

    recent_normal_flows:
        Previous NORMAL flow readings for this building,
        newest first.

    Returns:
        {
            "status": "NORMAL" or "LEAK DETECTED",
            "reasons": [...],
            "baseline_lpm": ...
        }
    """

    reasons = []

    max_flow_lpm = BUILDINGS[building_id]["max_flow_lpm"]

    # Rule 1: absolute flow threshold.
    if flow_lpm > max_flow_lpm:
        reasons.append(
            f"THRESHOLD: {flow_lpm} L/min exceeds "
            f"limit {max_flow_lpm} L/min"
        )

    # Rule 2: deviation from recent normal baseline.
    baseline = compute_baseline(recent_normal_flows)

    if (
        baseline is not None
        and flow_lpm > DEVIATION_FACTOR * baseline
    ):
        if baseline == 0:
            reasons.append(
                f"DEVIATION: {flow_lpm} L/min exceeds zero-flow baseline"
            )
        else:
            pct = round((flow_lpm / baseline - 1) * 100)
            reasons.append(
                f"DEVIATION: {flow_lpm} L/min is {pct}% above "
                f"baseline {baseline} L/min"
            )

    return {
        "status": "LEAK DETECTED" if reasons else "NORMAL",
        "reasons": reasons,
        "baseline_lpm": baseline,
    }


# --------------------------------------------------------------------------
# 5. Full processing pipeline
# --------------------------------------------------------------------------

def process_reading(payload, recent_normal_flows):
    """
    Full water-flow processing pipeline.

    Returns:
        (record, errors)
    """

    clean, errors = validate_reading(payload)

    if errors:
        return None, errors

    clean.update(
        detect_leak(
            clean["building_id"],
            clean["flow_lpm"],
            recent_normal_flows,
        )
    )

    return clean, []