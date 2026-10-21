"""Authorization for API Gateway REST proxy events.

Only Gateway-verified claims are trusted. Restrict Lambda invocation to the
intended API/stage; never expose a Function URL or accept claims from the body.
"""
import json
import os
import time


def authorize(event, action):
    claims = (event.get("requestContext", {}).get("authorizer") or {}).get("claims")
    if not isinstance(claims, dict):
        return 401
    issuer = os.environ.get("COGNITO_ISSUER", "")
    client = os.environ.get("COGNITO_CLIENT_ID", "")
    if not issuer or not client:
        return 503
    try:
        valid = (claims.get("iss") == issuer
                 and claims.get("client_id") == client
                 and claims.get("token_use") == "access"
                 and float(claims.get("exp", 0)) > time.time()
                 and bool(claims.get("sub")))
    except (TypeError, ValueError):
        valid = False
    if not valid:
        return 401
    if f"aquacloud/{action}" not in str(claims.get("scope", "")).split():
        return 403
    groups = claims.get("cognito:groups", [])
    if isinstance(groups, str):
        # REST authorizers can serialize array claims as comma-delimited strings.
        if groups.startswith("["):
            try:
                groups = json.loads(groups)
            except ValueError:
                return 403
        else:
            groups = groups.split(",")
    if not isinstance(groups, list) or not all(isinstance(g, str) for g in groups):
        return 403
    permitted = {"Viewer", "Operator", "Admin"} if action == "read" else {"Operator", "Admin"}
    return None if permitted.intersection(g.strip() for g in groups) else 403
