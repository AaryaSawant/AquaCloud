# AquaCloud AWS demonstration guide

Region: **Asia Pacific (Mumbai), ap-south-1**. Sign into the same AWS account before opening these links. IAM is a global service.

## Open these service dashboards

| Service | Console link | Resource and what to show |
|---|---|---|
| API Gateway | [AquaCloudAPI resources](https://ap-south-1.console.aws.amazon.com/apigateway/main/apis/t2813qa1jl/resources?region=ap-south-1&api=t2813qa1jl) | `POST /readings`, `GET /dashboard`, `POST /export`, and their Lambda integrations. Open Stages → prod to show the deployed stage. |
| Lambda | [AquaCloudBackend](https://ap-south-1.console.aws.amazon.com/lambda/home?region=ap-south-1#/functions/AquaCloudBackend) | Code, environment variables, execution role, and Monitor. Python 3.13, arm64. |
| DynamoDB | [DynamoDB console](https://ap-south-1.console.aws.amazon.com/dynamodbv2/home?region=ap-south-1) | Tables → `AquaCloudReadings` → Explore table items. Show `building_id` partition key and `ts` sort key, then the LAB-1 readings and leak reasons. |
| S3 | [S3 console](https://ap-south-1.console.aws.amazon.com/s3/home?region=ap-south-1) | Open `aquacloud-reports-aarya.sawant15`, then `reports/`. Show JSON/CSV export objects. Under Permissions, demonstrate Block Public Access and Object Ownership after confirming their current settings. |
| Cognito | [AquaCloud user pool](https://ap-south-1.console.aws.amazon.com/cognito/v2/idp/user-pools/ap-south-1_q8OaAp14C/overview?region=ap-south-1) | App client `AquaCloud Dashboard`, hosted login configuration, Users, and Viewer/Operator/Admin groups. |
| IAM | [IAM console](https://console.aws.amazon.com/iam/home?region=ap-south-1#/roles) | Open `AquaCloudBackend-role-pn5ghlbu`. Show the actual resource-scoped data policy and logging permissions after review. App roles and IAM roles serve different purposes. |
| CloudWatch | [CloudWatch console](https://ap-south-1.console.aws.amazon.com/cloudwatch/home?region=ap-south-1) | Logs → Log groups → `/aws/lambda/AquaCloudBackend`. Open the latest stream and show `water_reading`, `LEAK DETECTED`, `export`, and authorization-denial events after generating them. Also show Lambda invocation, error, and duration metrics. |

The API Gateway, Lambda, and Cognito links use resource identifiers observed in the console. The DynamoDB, S3, IAM, and CloudWatch links open their service consoles; use the resource names above. Their current privacy and monitoring settings still need a final live audit.

## Explain the flow in this order

1. **Simulator:** “The Python simulator represents water sensors. It sends a building ID, sensor ID, and flow in litres per minute.” The hardware is simulated.
2. **API Gateway:** “POST /readings requires the sensor API key and uses the existing usage plan. Gateway routes accepted requests to Lambda.” Keep the key hidden during the presentation.
3. **Lambda:** “Lambda validates the registered building/sensor pair and checks a hard flow threshold and recent normal-flow baseline.” A leak is a rule result, not a machine-learning prediction.
4. **DynamoDB:** “Lambda stores each result with a server timestamp. The dashboard queries recent history by building.” Show a NORMAL and a LEAK DETECTED record.
5. **Dashboard login:** “Cognito signs dashboard users in. The browser exchanges a short-lived authorization code using PKCE.” Demonstrate this only as far as the verified deployment supports it.
6. **Authorization:** “Gateway verifies the token. Lambda checks scope and group before it reads dashboard data or creates a report.” **This enforcement is staged locally and must not be described as deployed until the final live tests pass.**
7. **S3 export:** “An Operator or Admin requests an export. Lambda queries recent readings and writes JSON and CSV reports under reports/.” The response contains object keys, not public download links.
8. **CloudWatch and IAM:** “CloudWatch records execution and failures. IAM limits which AWS resources the backend can access.” Show actual configured permissions rather than claiming least privilege from the README.

## Role matrix for the completed security deployment

| Caller | GET /dashboard | POST /export | POST /readings |
|---|---|---|---|
| Anonymous | Deny | Deny | Deny without valid sensor API key |
| Viewer | Allow | Deny | User token alone does not authorize sensors |
| Operator | Allow | Allow | User token alone does not authorize sensors |
| Admin | Allow | Allow | User token alone does not authorize sensors |
| Valid sensor API key | No user access | No user access | Allow subject to input validation and usage plan |

Admin is an application group. This project does **not** add an administration screen, a user-management API, or AWS console permissions for dashboard users. AWS-authorized maintainers manage memberships in Cognito.

## Demonstration checklist

- Select Mumbai in the top-right AWS region selector.
- Keep the local frontend server running and open `http://localhost:8000/`.
- Use the simulator's existing `--dry-run` option if live sensor authorization is unavailable.
- For a live demonstration, provide `AQUACLOUD_API_URL` and `AQUACLOUD_API_KEY` through your local environment. Do not paste the key into slides, Git, screenshots, or chat.
- Show one normal reading, one deliberate leak, the matching DynamoDB result, the dashboard refresh, and the latest CloudWatch stream.
- Once RBAC is deployed and tested, show Viewer export denial, then Operator/Admin export success and the two S3 objects.
- API Gateway changes require deployment to `prod`; saving a method alone does not change that stage.
- Group changes require a new sign-in/token. An existing access token retains its old group claims until it expires.

## Verified status as of 22 October 2026

- Local source checks: 28 Python tests and 5 JavaScript authentication tests pass.
- Simulator dry run: normal readings followed by a LAB-1 leak pass.
- Original deployed Lambda and processing files matched the local baseline before changes.
- Cognito directory, public SPA client, custom scopes, and three groups were created. Public self-registration is disabled.
- First real PKCE login returned successfully to the dashboard. That user had no group assigned at that point.
- `POST /readings` was observed with API key required.
- Production authorization, Lambda RBAC deployment, role membership, IAM/S3/CloudWatch audit, and final live positive/negative tests remain pending. Browser access was blocked by a saved permission before these actions finished.

Do not use the previous ENERCloud/Sydney documentation as evidence for AquaCloud's deployment.
