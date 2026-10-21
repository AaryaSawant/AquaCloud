# AquaCloud API contract

Base URL: `https://t2813qa1jl.execute-api.ap-south-1.amazonaws.com/prod`.

Security status: the repository stages the authenticated contract below. Production dashboard/export authorization and Lambda RBAC still require deployment and live verification. See [implementation record](SECURITY-IMPLEMENTATION.md).

## POST /readings

Existing simulator route, with `Content-Type: application/json` and `x-api-key` required by API Gateway. Cognito tokens do not replace the sensor key.

```json
{"building_id":"LAB-1","sensor_id":"WTR-LAB-1-01","flow_lpm":15.2,"sensor_ts":"2026-10-22T00:00:00Z"}
```

The building and sensor must be registered together. Flow is a finite number from 0 to 200 litres/minute. Boolean flow values and malformed building IDs are rejected. Lambda adds its own received timestamp and a collision-resistant sort key.

- 200: `{"message":"stored","reading":{...}}`
- 400: `{"errors":["..."]}` with no stored item
- 403 at Gateway: missing/invalid API key

## GET /dashboard

After rollout, use `Authorization: Bearer <access-token>` with scope `aquacloud/read` and Viewer, Operator, or Admin group.

```json
{
  "generated_at":"ISO-8601",
  "summary":{"total_buildings":5,"active_sensors":5,"total_flow_lpm":72.5,"leak_count":1,"readings_count":30},
  "buildings":[{"building_id":"LAB-1","name":"Computer Lab 1","sensor_id":"WTR-LAB-1-01","normal_min_lpm":8,"normal_max_lpm":20,"max_flow_lpm":35,"latest":null}],
  "recent_readings":[],
  "leaks":[]
}
```

The handler queries up to 50 records per building. It returns the 20 newest readings and up to 20 recent leak records. `leak_count` describes the bounded queried history, not all-time leaks or currently active leaks.

Reading fields: `building_id`, `sensor_id`, `ts`, `sensor_ts`, `flow_lpm`, `status` (`NORMAL` or `LEAK DETECTED`), `reasons`, and nullable `baseline_lpm`.

## POST /export

After rollout, use an access token with scope `aquacloud/export` and Operator or Admin group. Body: `{}`.

- 200: `{"project":"AquaCloud","bucket":"...","json_key":"reports/....json","csv_key":"reports/....csv","records":30}`
- The handler queries up to 200 recent records per building and writes JSON and CSV objects. This is a bounded export, not the complete table history.
- The response contains S3 keys. It does not grant public download access.

## Authorization and failure behavior

- Gateway authenticates scoped Cognito access tokens. ID tokens must not authorize these methods.
- Lambda verifies issuer/client/token type/expiration/subject/scope/groups using Gateway-verified claims.
- 401: missing or invalid identity; 403: missing required role/scope; 503: missing backend auth configuration; 500: internal backend failure.
- OPTIONS is unauthenticated CORS preflight. It must permit Content-Type and Authorization for the configured frontend origin. POST /readings retains its existing key handling.
- Responses use `Cache-Control: no-store`. Errors must not return credentials, tokens, or internal stack traces.

## Detection rules

1. Flow exceeds the configured building hard limit.
2. At least five recent NORMAL samples exist and flow exceeds 1.5 times the mean of up to ten samples. A positive flow above a zero-flow baseline is flagged without dividing by zero.

Both rules may add reasons to the same reading. Neither rule proves a physical leak without investigation.
