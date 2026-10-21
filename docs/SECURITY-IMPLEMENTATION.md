# AquaCloud security implementation and deployment record

## Scope and status

This change adds the requested Cognito dashboard login and role enforcement to the existing three-route application. It does not introduce new product capabilities. Local code is tested. AWS rollout is **not complete**: the production API and Lambda authorization have not yet been changed by this task.

The real hosted login successfully returned to the dashboard before the saved browser permission blocked further AWS actions. That established the frontend login flow only. Because the API was still public, that successful data load is not proof of Gateway token enforcement or backend RBAC.

## Identifiers observed in AWS

- Region: `ap-south-1`
- REST API: `AquaCloudAPI`, ID `t2813qa1jl`, stage `prod`
- Resource IDs: dashboard `d8nxl5`, export `b45rcf`, readings `dftqem`
- Lambda: `AquaCloudBackend`, handler `lambda_function.lambda_handler`
- Execution role: `AquaCloudBackend-role-pn5ghlbu`
- DynamoDB table: `AquaCloudReadings`
- Export bucket: `aquacloud-reports-aarya.sawant15`
- Cognito user pool: `ap-south-1_q8OaAp14C`
- Public app client: `t59l9j6o55uhlq7e03pcis35m`, no client secret
- Hosted domain: `https://ap-south-1q8oaap14c.auth.ap-south-1.amazoncognito.com`
- Local callback and logout URL: `http://localhost:8000/`
- Scopes: `openid aquacloud/read aquacloud/export`

These are public deployment identifiers, not credentials. No password, API key, AWS access key, or token belongs in the repository.

## Code changes

- `frontend/auth.js`: authorization-code flow with S256 PKCE, cryptographically random state/verifier, ten-minute one-use transaction, state checking, token exchange, logout, and expiration handling. Access tokens stay in memory. The PKCE transaction alone uses sessionStorage. Refreshing the page requires a fresh sign-in, usually using the hosted login session.
- `frontend/auth-config.js`: public deployment identifiers. Tokens can only be sent to the configured API URL; arbitrary URLs entered in connection settings cannot receive credentials.
- `frontend/app.js`: authenticated API calls, no-store fetches, role-aware export button, cleared data on sign-out/expiry, and a check preventing a late response from repainting data after sign-out.
- `frontend/index.html` and CSS: account controls, correct hidden-state handling, callback referrer privacy, and functioning Cancel action in connection settings.
- `lambda/ingest/security.py`: deny-by-default authorization from API Gateway-verified claims. Checks configured issuer, app client, token type, expiration, subject, scope, and groups. Missing configuration fails closed with 503.
- Lambda handler: authorizes dashboard/export **before** DynamoDB or S3 side effects. The readings route continues through its existing ingestion path and depends on API Gateway's API-key requirement.
- CORS: explicit configured frontend origin, Authorization header, no-store responses. API Gateway's OPTIONS and error responses must be configured consistently during rollout.
- Processing fixes: malformed building IDs return validation errors, and a zero-flow baseline no longer divides by zero.

The frontend's decoded group claims only control its presentation. API Gateway validates the JWT signature; Lambda enforces authorization. Do not expose a Function URL or broaden direct Lambda invocation. A forged body/header must never become trusted authorizer context.

## Exact intended permissions

| Route | Gateway | Lambda |
|---|---|---|
| GET /dashboard | Cognito authorizer plus `aquacloud/read` scope | Viewer, Operator, or Admin |
| POST /export | Cognito authorizer plus `aquacloud/export` scope | Operator or Admin |
| POST /readings | Existing API key required and usage plan | Existing validation/ingestion path |
| OPTIONS | Unauthenticated CORS preflight | No data access |

All users may request the two API scopes through the public SPA client. The backend's group check is what prevents Viewer exports. Scopes alone do not differentiate these groups.

## Rollout sequence still required

1. Restore browser access and verify the current AWS state before any changes. Confirm that no other edits occurred.
2. Finish creating the pending `AquaCloudCognito` REST authorizer with the correct user pool and `Authorization` token source. Leave identity-token audience regex empty for access-token/scoped use.
3. Obtain action-time approval before granting the named test account Viewer/Operator/Admin permissions. Test each group with a newly issued token and restore the agreed final membership.
4. Confirm login again after final app-client settings. Use a short access-token lifetime where suitable. This SPA intentionally has no persistent token storage or refresh-token handling.
5. Package `lambda_function.py`, `processing.py`, and `security.py` at the archive root. Back up the deployed archive and current environment/configuration first.
6. Set Lambda `COGNITO_ISSUER`, `COGNITO_CLIENT_ID`, and `ALLOWED_ORIGIN` alongside the existing TABLE_NAME/BUCKET_NAME. Upload the tested archive only after login works. A brief fail-closed interval may occur before Gateway is deployed; coordinate it.
7. Attach the Cognito authorizer and the appropriate scope to the two dashboard routes. Preserve POST /readings API-key-required=true, existing usage-plan association, and unauthenticated OPTIONS.
8. Ensure OPTIONS allows Authorization and Content-Type for the exact frontend origin. Configure Gateway DEFAULT_4XX/DEFAULT_5XX CORS headers without exposing sensitive response details. Disable API Gateway full request/response data tracing to avoid token leakage.
9. Deploy to `prod`, verify route behavior immediately, and retain the previous deployment ID for recovery. Do not call the rollout complete until the full matrix below passes.
10. Inspect the actual IAM role. Limit data access to Query/PutItem on the account-specific AquaCloudReadings table and PutObject under this bucket's reports/* prefix. Limit logs to the function log group. Do not add broad DynamoDB/S3 policies. The shared function necessarily shares one role across its routes.
11. Inspect S3 Block Public Access, bucket policy, disabled ACLs/Object Ownership, default encryption, and any public website settings. Do not grant public object access for the demo. Exports return object keys, not presigned download links.
12. Review CloudWatch log retention and errors. Use existing metrics to verify invocations, duration, failures, and authorization denials. Record actual settings. No alert or SNS capability is claimed.

## Validation record

| Check | Result |
|---|---|
| Python processing and backend security suite | 28 tests passed locally |
| JavaScript PKCE/state/expiry/token destination tests | 5 tests passed locally |
| JavaScript syntax and Git whitespace checks | Passed |
| Simulator normal and leak dry run | Passed |
| Original deployed archive comparison | Lambda and processing hashes matched local baseline |
| First Cognito hosted PKCE login | Returned to dashboard successfully |
| Live Viewer GET /dashboard / POST /export | Pending |
| Live Operator GET /dashboard / POST /export | Pending |
| Live Admin GET /dashboard / POST /export | Pending |
| Anonymous dashboard/export, malformed and expired JWT | Pending |
| Wrong issuer/client, ID token, missing scope, no-group token | Local claim tests passed; live Gateway tests pending |
| Readings without/with API key after rollout | Pending final regression |
| S3 privacy, exact IAM, CloudWatch audit | Pending |

Local security tests use mocked Gateway claims and storage. They do not prove deployed JWT validation, CORS, IAM, or S3 settings.

## Recovery

If the rollout fails, diagnose the failing boundary first: browser CORS, Gateway 401, backend 403, or storage 500. Keep authentication enforced while repairing code/configuration. Avoid reopening dashboard/export as a routine fix. Use the backed-up Lambda archive, environment settings, and previous Gateway deployment only as a coordinated recovery with the user, since restoring the former deployment would reopen the original public routes.

## Honest limitations

- The sensor API key is a shared secret and usage control, not per-device identity. This task preserves it.
- One Lambda function handles all routes. Per-route AWS role isolation is not implemented.
- Admin has no user-management screen/API and no AWS console permissions from Cognito group membership.
- The frontend remains a local static dashboard. A public HTTPS deployment and its callback/CORS configuration are not included.
- JWT group changes and logout do not instantly invalidate an already issued access token at API Gateway. Short token lifetime limits that interval.
- No new alarms, WAF, MFA enforcement, IoT Core, email/SMS leak alerts, or ML capabilities are claimed.

References: [AWS PKCE](https://docs.aws.amazon.com/cognito/latest/developerguide/using-pkce-in-authorization-code.html), [Cognito resource servers and scopes](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pools-define-resource-servers.html), [API Gateway Cognito integration](https://docs.aws.amazon.com/apigateway/latest/developerguide/apigateway-integrate-with-cognito.html).
