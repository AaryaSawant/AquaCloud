# AquaCloud

Campus water-flow monitoring with simulated sensors, API Gateway, AWS Lambda, DynamoDB, S3, and CloudWatch in **Mumbai (ap-south-1)**.

The simulator sends flow readings. Lambda validates each building/sensor pair, detects unusually high flow with threshold and baseline rules, and stores the result in DynamoDB. The dashboard reads recent history and can request JSON/CSV exports to S3.

## Current security rollout

Cognito hosted login with authorization-code PKCE has completed its first real sign-in. Viewer, Operator, and Admin groups exist. The repository contains tested frontend login and backend role enforcement code.

**The security rollout is not yet complete.** This task has not changed production API authorization or uploaded the new Lambda code. Live role tests and the final IAM/S3/CloudWatch audit remain pending browser access. See [implementation record](docs/SECURITY-IMPLEMENTATION.md) for exact status and deployment steps. Do not describe the locally staged RBAC as enforced in production yet.

## Run locally

Use Python 3.10+ for the tests/simulator and Node.js for the authentication tests. Lambda supplies boto3 in AWS; no third-party dependencies are needed for local processing tests or simulator dry runs.

```powershell
python -m unittest discover -s tests -v
node --test tests/test_auth.cjs
python simulator/simulator.py --dry-run spike --building LAB-1
python -m http.server 8000 --bind 127.0.0.1 --directory frontend
```

Open [the local dashboard](http://localhost:8000/). Its public Cognito configuration is in `frontend/auth-config.js`. Keep callback URL, sign-out URL, trusted API URL, and Lambda/Gateway CORS settings aligned. Tokens live in memory, so a page reload requires another sign-in through the hosted session.

For the existing live simulator flow, set `AQUACLOUD_API_URL` and `AQUACLOUD_API_KEY` in your local environment, then use its `stream`, `spike`, or `load` command. Never put the key in the frontend, Git, slides, screenshots, or chat.

## Intended access after rollout

| Identity | Dashboard | Export |
|---|---|---|
| Viewer | Read | Denied |
| Operator | Read | Allowed |
| Admin | Read | Allowed |
| Anonymous or unassigned group | Denied | Denied |

The sensor route remains API-key controlled. Dashboard tokens do not replace that key. Admin is an application group, with no new user-management screen or AWS console privileges.

## Source layout

- `frontend/`: static dashboard, hosted-login integration, and public configuration
- `lambda/ingest/`: handler, pure processing logic, and backend authorization
- `simulator/`: simulated water sensors
- `tests/`: processing, role-boundary, and login tests
- `docs/`: [API contract](docs/api-contract.md), [security record](docs/SECURITY-IMPLEMENTATION.md), and [AWS links/demo guide](docs/AWS-DEMO-GUIDE.md)

## Validation

28 Python tests and 5 JavaScript authentication tests pass locally. The leak simulator dry run also passes. The deployed baseline Lambda and processing files matched the original local files before edits. Final live positive/negative auth tests are pending and must be recorded separately from local test results.

## Limits

This is an academic prototype with simulated sensors, explainable rules, a shared sensor API key, one Lambda role across three routes, and 30-second dashboard polling. No physical sensor integration, machine learning, automatic email/SMS alerts, new administration API, or public frontend hosting is included.
