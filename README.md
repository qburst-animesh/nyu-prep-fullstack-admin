# CSV Admin Panel — Fullstack Project

This repository contains a small fullstack application for uploading, processing, and managing CSV files using a FastAPI backend, a React + Vite admin frontend, S3 object storage, and optional AWS Lambda processors for background parsing and asynchronous deletes.


Table of contents
- Project overview
- Repo structure (quick)
- Architecture diagram
- End-to-end flows
  - Upload (metadata-first, presigned PUT)
  - Verification & parsing (Lambda callback)
  - Download (streaming fallback + presigned GET)
  - Delete (sync and async + callback + retry)
- Auth & tokens (frontend -> backend, lambdas -> backend)
- Important environment variables
- How to run locally (quick start)
- Deploying Lambdas (packaging + CloudFormation)
- Developer notes & troubleshooting
- Where to look in the code

---

## Project overview

Purpose: provide a small admin UI to register and upload CSV files directly to S3 (presigned uploads), verify them, produce a per-file JSON summary (via background processor), and allow robust delete semantics (async deletes via a delete Lambda with backend audit). The system is designed to work both locally (developer mode) and in AWS.

Key design principles:
- Metadata-first registration so the UI can show a pending record immediately
- Direct browser -> S3 uploads using presigned URLs for large-file performance and progress reporting
- Backend verification of S3 presence (head_object) and optional Lambda-based parsing for heavier processing
- Streaming download proxy in the backend when presigned GETs fail in a dev environment
- Asynchronous, auditable delete flow handled by a dedicated delete Lambda which callbacks the backend

---

## Repo structure (quick)

- `backend-admin-panel/` — FastAPI backend, DB models, S3 wrapper, CloudFormation deploy helpers and lambda sources
  - `app_fastapi/` — FastAPI app sources (`main.py`, `s3_service.py`, `models.py`, `schemas.py`, `database.py`)
  - `aws_lambda/` — Lambda sources (`s3_processor_lambda.py`, `s3_delete_lambda.py`), `cloudformation_template.yml`, `deploy_lambda.sh`
  - `add_columns.py` — DB migration helper to add new columns (delete-tracking, etc.)
- `frontend-admin-panel/` — React + TypeScript Vite admin UI
  - `src/hooks/useCSVData.ts` — upload/delete hooks and API wiring
  - `src/components/CSVTable.tsx` — DataGrid UI showing records, actions and retry UI
- `run_services.sh` — convenience script to start frontend + backend locally (writes logs + PIDs)

---

## Architecture diagram

```mermaid
flowchart LR
  Frontend[Frontend (React + Vite)] -- "API calls (Auth token)" --> Backend[Backend (FastAPI)]
  Frontend -- "Presigned PUT (upload_url)" --> S3[(S3 Bucket)]
  Backend -- "Generate presigned URLs / Stream" --> S3
  S3 -- "ObjectCreated (optional)" --> ProcessorLambda[s3_processor_lambda]
  ProcessorLambda -- "Writes summary JSON" --> S3
  ProcessorLambda -- "POST verify -> /api/v1/files/verify" --> Backend
  Backend -- "Invoke parser" --> ProcessorLambda
  Backend -- "Invoke delete lambda" --> DeleteLambda[s3_delete_lambda]
  DeleteLambda -- "Delete object & POST /delete-complete" --> Backend
  DeleteLambda -- "Delete object" --> S3
  Frontend -- "HEAD /download-stream probe" --> Backend
  Frontend -- "open presigned GET" --> S3
```

This diagram shows the main interactions and where asynchronous processing occurs.

---

## End-to-end flows

Below are the most important runtime flows with exact API endpoints and expected behavior.

### 1) Upload (metadata-first, presigned PUT)

1. Frontend requests: POST `/api/v1/files/upload-url` with JSON { filename, file_size_bytes, mime_type }.
   - Backend checks for duplicate (same filename + size) in DB; returns 409 if duplicate.
   - Backend generates a unique `s3_key` (e.g. `csv_uploads/<uuid>_<filename>`) and a presigned PUT URL using `S3Service.generate_presigned_upload_url`.
   - Response: `{ "upload_url": "https://...", "s3_key": "csv_uploads/..." }`.

2. Frontend registers metadata: POST `/api/v1/files` with JSON { filename, file_size_bytes, mime_type, s3_key }.
   - Backend creates a DB record (status pending) and returns the created record (id).

3. Frontend uploads content: Browser PUTs the file to `upload_url` (the presigned S3 URL).
   - The React hook uses an `XMLHttpRequest` to PUT so it can observe `upload.onprogress` for progress UI.

4. After successful PUT, frontend notifies backend: PATCH `/api/v1/files/{id}/status` with `{ "status": "uploaded" }`.
   - Backend attempts to confirm the S3 object with `s3.head_object()` (with a few retries/backoff). If found, `verified=true` and `status=uploaded`. Otherwise sets `verified=false` and increments `verification_attempts`.

Notes:
- The presigned PUT is unauthenticated at S3 (the URL encodes temporary credentials). The browser does not need AWS credentials.

### 2) Verification & parsing (Lambda + summary JSON)

- Option A: S3 ObjectCreated triggers `s3_processor_lambda` (deployed via CloudFormation). The lambda reads the CSV, writes a summary JSON to `<s3_key>.summary.json` in the same bucket, and calls the backend `POST /api/v1/files/verify` with JSON `{ s3_key: "..." }` and header `X-Verify-Token: <VERIFY_SECRET>`.
- Option B: The frontend or an operator can call `POST /api/v1/files/{id}/trigger-parse` and the backend will invoke the parser lambda (if `LAMBDA_FUNCTION_NAME` is configured). If the backend lacks `LAMBDA_FUNCTION_NAME` it returns `{ invoked: false, reason: '...' }` so UI can show a friendly message.

Once the summary object exists, the frontend fetches `/api/v1/files/{id}/summary` which either:
- Returns `{ exists: False }` if the summary JSON isn't present yet, or
- Returns `{ exists: True, summary_url: "<presigned-get>" }` when available.

### 3) Download (streaming fallback + presigned GET)

Behavior in UI:
1. Frontend tries a `HEAD /api/v1/files/{id}/download-stream` to check whether the backend can directly read the S3 object. This is helpful during local dev when presigned GETs may be region/credential-dependent.
2. If HEAD returns 200 the frontend opens `GET /api/v1/files/{id}/download-stream` which streams the object from S3 through the FastAPI app using `StreamingResponse` and correct `Content-Disposition` so the browser downloads with a friendly filename.
3. If HEAD fails, the frontend falls back to `GET /api/v1/files/{id}/download` which returns `{ download_url: "<presigned-get>" }`. The frontend then opens the presigned GET URL directly (browser -> S3).

### 4) Delete (sync and async + callback + retry)

- Synchronous delete: `DELETE /api/v1/files/{id}?delete_s3=true` will attempt to delete the S3 object synchronously using `S3Service.delete_s3_object`. If that `delete_object` fails, the backend returns 500 and preserves the DB record so the operator can inspect and retry.

- Asynchronous delete (recommended for least-privilege backend): if `DELETE_LAMBDA_FUNCTION` is configured, the backend will invoke the delete lambda asynchronously and return HTTP `202 Accepted`. The DB record is updated with `status = 'deleting'`, `delete_requested_at`, `delete_attempts` set to 0, and `delete_last_error` cleared.

- Delete lambda behavior: the delete lambda deletes the S3 object, then calls back the backend `POST /api/v1/files/{id}/delete-complete` with JSON `{ "deleted": true }` on success or `{ "deleted": false, "message": "..." }` on failure. The lambda includes `X-Verify-Token: <VERIFY_SECRET>` header to authenticate the callback.

- Backend callback handling: `delete-complete` will remove the DB record on `deleted: true`, or set `status = 'delete_failed'` and increment `delete_attempts` and save `delete_last_error` when `deleted: false`.

- Retry: there's a new endpoint `POST /api/v1/files/{id}/retry-delete` which re-invokes the delete lambda (if configured) or attempts synchronous delete when no lambda is configured. The frontend exposes a `Retry Delete` action when a row has `status === 'delete_failed'`.

---

## Auth & tokens — what talks to whom, and how

1. Frontend user authentication (Cognito):
   - The frontend imports `fetchAuthSession` (from `aws-amplify/auth`) and obtains Cognito tokens.
   - `frontend-admin-panel/src/utils/apiFetch.ts` contains `authenticatedFetch()` which appends `Authorization: Bearer <access_token>` when a session exists. This header is used for UI -> backend API calls.
   - Note: the current FastAPI app does not enforce JWT validation for every endpoint (the `X-Verify-Token` header is used only for trusted callbacks). If you need stricter auth, add a JWT verification middleware or place API behind API Gateway with a Cognito Authorizer.

2. Backend credentials and AWS SDK usage:
   - Backend uses `boto3` to generate presigned URLs, to `get_object` for streaming, and to `invoke` Lambdas. The backend `boto3` client obtains credentials from environment variables (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`) or from the running environment (EC2/Container IAM role).
   - Required permissions for backend identity (if backend does the streaming or invokes lambda):
     - `s3:GetObject`, `s3:HeadObject` (for streaming and verification)
     - `lambda:InvokeFunction` (to trigger parser/delete lambdas)

3. Lambda -> Backend callbacks: `VERIFY_SECRET` and `X-Verify-Token`
   - The parser and delete lambdas call back trusted endpoints on the backend. Those callbacks must include the header `X-Verify-Token` with the shared `VERIFY_SECRET` value.
   - Backend endpoints that accept these callbacks (`/api/v1/files/verify` and `/api/v1/files/{id}/delete-complete`) validate the header and return 401 if missing or mismatched.

Security note: keep `VERIFY_SECRET` secret and use HTTPS for the backend endpoints.

---

## Important environment variables

Backend (`backend-admin-panel`):

- `BUCKET_NAME` — S3 bucket to store CSVs (default `local-test-csv-bucket`)
- `AWS_DEFAULT_REGION` — e.g. `us-east-1`
- `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` — optional; if omitted boto3 uses IAM role or profile
- `LAMBDA_FUNCTION_NAME` — optional: name/ARN for parser lambda invoked by `trigger-parse`
- `DELETE_LAMBDA_FUNCTION` — optional: name/ARN for delete lambda; when set, delete requests become asynchronous
- `VERIFY_SECRET` — shared secret for lambda -> backend callbacks in `X-Verify-Token` header
- `CORS_ORIGINS` — comma separated origins allowed for CORS (default includes local dev ports)

Frontend (`frontend-admin-panel`):

- `VITE_API_BASE_URL` — base URL for backend API (e.g. `http://localhost:8000/api/v1`)
- Cognito config (if used) — configure Amplify properly to obtain auth tokens

CloudFormation deploy script parameters (see `backend-admin-panel/aws_lambda/deploy_lambda.sh`):
- `--artifact-bucket` — S3 bucket to upload lambda zip
- `--artifact-key` — S3 key for the lambda zip
- `--bucket-name` — the CSV bucket name
- `--backend-verify-url` — full URL to backend verify endpoint (used by CFN lambda env)
- `--backend-base-url` — backend base URL (for delete lambda callback env)
- `--verify-secret` — VERIFY_SECRET value
- `--lambda-function-name` / `--delete-lambda-name` — override default lambda names

When the deploy script completes it will attempt to write the `DeleteLambdaFunctionArn` into your backend `.env` as `DELETE_LAMBDA_FUNCTION` (if the `.env` file exists in `backend-admin-panel/.env`). This automates wiring the async delete behavior locally after deploy.

---

## How to run locally (quick start)

Requirements: Python 3.8+, Node 18+/npm, AWS CLI configured if you plan to deploy Lambdas.

1. Backend

```bash
cd backend-admin-panel
# optionally create .env with the variables above
python3 -m pip install -r requirements.txt  # if a requirements.txt exists
uvicorn app_fastapi.main:app --reload --host 0.0.0.0 --port 8000
```

2. Frontend

```bash
cd frontend-admin-panel
npm install
npm run dev
```

3. Convenience: start both with the included script

```bash
chmod +x run_services.sh
./run_services.sh
```

Logs are written to `backend.log` and `frontend.log` at the repo root when using `run_services.sh`.

---

## Deploying Lambdas and CloudFormation

1. Edit `backend-admin-panel/aws_lambda/deploy_lambda.sh` params and ensure:
   - You have an artifact S3 bucket to host the lambda zip
   - Your AWS CLI default profile has permissions to create IAM roles and CloudFormation stacks

2. Run the deploy script (example):

```bash
cd backend-admin-panel/aws_lambda
./deploy_lambda.sh \
  --artifact-bucket my-artifact-bucket \
  --artifact-key lambda_package.zip \
  --bucket-name my-csv-bucket \
  --backend-verify-url https://api.example.com/api/v1/files/verify \
  --verify-secret "SOME_STRONG_TOKEN" \
  --backend-base-url https://api.example.com
```

The script packages `s3_processor_lambda.py` and `s3_delete_lambda.py`, uploads them to S3, deploys `cloudformation_template.yml`, and then tries to write `DELETE_LAMBDA_FUNCTION='<arn>'` into `backend-admin-panel/.env` for local convenience.

Important IAM perms for lambdas/roles:
- Parser lambda: `s3:GetObject`, `s3:PutObject` (to write summary), CloudWatch Logs permissions
- Delete lambda: `s3:DeleteObject`, `s3:GetObject`, CloudWatch Logs
- Backend/Invoker: `lambda:InvokeFunction` if backend will invoke the lambdas

Network: delete lambda must be able to reach your backend callback URL (public or via VPC peering depending on setup).

---

## Developer notes & troubleshooting

- Duplicate uploads: the backend enforces a duplicate check in `/files/upload-url` (filename + size). If a duplicate is detected you will get `409` and a payload describing the existing file.
- `403` when accessing presigned GET: ensure `BUCKET_NAME` and `AWS_DEFAULT_REGION` are correct and the presigned URL was generated with credentials for the correct region.
- `AccessDenied` on synchronous delete: very common when backend credentials do not have `s3:DeleteObject`. Use the delete-lambda approach (give the lambda `s3:DeleteObject`) to remove privilege from the backend.
- Streaming HEAD probe returns 404: the backend could not `head_object` the S3 object — verify `BUCKET_NAME` and backend AWS credentials/permissions.
- DB migration: if code expects `delete_requested_at`, `delete_attempts`, `delete_last_error`, `delete_completed_at`, run `python3 add_columns.py` in `backend-admin-panel` to add columns safely.

Useful cURL examples

- Request upload URL
```bash
curl -sS -X POST http://localhost:8000/api/v1/files/upload-url \
  -H 'Content-Type: application/json' \
  -d '{"filename":"test.csv","file_size_bytes":1234,"mime_type":"text/csv"}' | jq
```

- Register metadata (replace `s3_key` with value returned above)
```bash
curl -sS -X POST http://localhost:8000/api/v1/files \
  -H 'Content-Type: application/json' \
  -d '{"filename":"test.csv","file_size_bytes":1234,"mime_type":"text/csv","s3_key":"csv_uploads/xxx_test.csv"}' | jq
```

- Upload file (direct to presigned URL)
```bash
curl -X PUT "<upload_url>" --upload-file test.csv -H "Content-Type: text/csv"
```

- Mark uploaded
```bash
curl -X PATCH http://localhost:8000/api/v1/files/123/status -H 'Content-Type: application/json' -d '{"status":"uploaded"}'
```

- Trigger parse (backend will invoke lambda if configured)
```bash
curl -X POST http://localhost:8000/api/v1/files/123/trigger-parse
```

- Simulate delete lambda callback (local testing)
```bash
curl -X POST http://localhost:8000/api/v1/files/123/delete-complete \
  -H "X-Verify-Token: SOME_STRONG_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"deleted": false, "message": "S3 delete AccessDenied"}'
```

---

## Where to look in the code

- Backend API: `backend-admin-panel/app_fastapi/main.py`
- S3 helper: `backend-admin-panel/app_fastapi/s3_service.py`
- DB models and schemas: `backend-admin-panel/app_fastapi/models.py`, `backend-admin-panel/app_fastapi/schemas.py`
- Lambda sources: `backend-admin-panel/aws_lambda/s3_processor_lambda.py`, `backend-admin-panel/aws_lambda/s3_delete_lambda.py`
- CloudFormation + deploy: `backend-admin-panel/aws_lambda/cloudformation_template.yml`, `backend-admin-panel/aws_lambda/deploy_lambda.sh`
- Frontend hook: `frontend-admin-panel/src/hooks/useCSVData.ts`
- Frontend DataGrid: `frontend-admin-panel/src/components/CSVTable.tsx`

---

## Recommended next steps

- Add JWT validation middleware or place the FastAPI behind API Gateway with Cognito authorizer for production.
- Harden permissions: give only the delete Lambda `s3:DeleteObject` rather than giving delete rights to backend service credentials.
- Add monitoring: CloudWatch logs and alarms for Lambda errors and S3 processing failures.
- Improve UI messaging on persistent failures (e.g., when both streaming and presigned download fail).

---

If you want, I can:
- run the deploy script for you (I will need artifact S3 bucket, the bucket name for CSVs, backend base URL, and the verify secret), or
- add a small health-check endpoint, or
- implement JWT validation on the backend.

Enjoy! The `README.md` is intentionally comprehensive — open issues or ask for clarifications and I will update it further.
# CSV Admin Panel — Fullstack Project

This repository implements an admin application for uploading, verifying, processing, downloading, and deleting CSV files.

It is intentionally designed to work seamlessly in local development and in AWS production:
- Direct browser -> S3 uploads using presigned PUT URLs (large-file friendly, progress events available in the browser).
- Backend verification using boto3 (head_object), an optional parser Lambda that writes summary JSONs, and an async delete Lambda with callback to the backend.

This README is written to be a single, easy-to-follow "cake slice" of the system. Read top-to-bottom to get a complete understanding of how data and tokens flow between components, how to run locally, and how to deploy the Lambdas.

Contents
- Project overview
- Repo layout
- High-level architecture
- Detailed runtime flows (step-by-step)
  - Upload (presigned PUT)
  - Verification & parsing (Lambda)
  - Download (streaming fallback + presigned GET)
  - Delete (sync + async + retry)
- Authentication & token handling (Cognito, VERIFY_SECRET, AWS creds, presigned URLs)
- Environment variables
- Running locally
- Deploying the Lambdas (packaging + CloudFormation)
- Troubleshooting & common errors
- Where to look in code

---

## Project overview

Purpose: provide an admin UI to register CSV files (metadata-first), upload large CSV files directly to S3, verify their presence, optionally parse them in background to produce per-file JSON summaries, and provide robust delete semantics with auditability.

Primary components
- Frontend: React + TypeScript (Vite) in `frontend-admin-panel`.
- Backend: FastAPI with SQLAlchemy and Pydantic in `backend-admin-panel/app_fastapi`.
- Storage: AWS S3 (bucket holds CSVs + summary JSONs).
- Background: AWS Lambda functions for parsing (`s3_processor_lambda.py`) and deleting (`s3_delete_lambda.py`) objects.

Design goals
- Avoid shipping AWS credentials to the browser: use presigned URLs for client-side S3 access.
- Make uploads robust: metadata-first so the UI shows pending records immediately, and background PUT uses XHR progress.
- Make deletes auditable and resilient via asynchronous delete lambda + callback.

---

## Repo layout (important files)

- [backend-admin-panel/app_fastapi/main.py](backend-admin-panel/app_fastapi/main.py) — all HTTP endpoints, streaming download, delete callbacks, retry endpoint.
- [backend-admin-panel/app_fastapi/s3_service.py](backend-admin-panel/app_fastapi/s3_service.py) — S3 helper: presigned URLs, head_object, delete.
- [backend-admin-panel/app_fastapi/models.py](backend-admin-panel/app_fastapi/models.py) — DB model `CSVFile` and audit/delete fields.
- [backend-admin-panel/app_fastapi/schemas.py](backend-admin-panel/app_fastapi/schemas.py) — Pydantic schemas used by endpoints.
- [backend-admin-panel/add_columns.py](backend-admin-panel/add_columns.py) — DB migration helper to add delete-tracking columns.
- [backend-admin-panel/aws_lambda/s3_processor_lambda.py](backend-admin-panel/aws_lambda/s3_processor_lambda.py) — parser lambda (S3 trigger) that writes `<s3_key>.summary.json` and calls backend verify.
- [backend-admin-panel/aws_lambda/s3_delete_lambda.py](backend-admin-panel/aws_lambda/s3_delete_lambda.py) — delete lambda that removes the object and callbacks the backend.
- [backend-admin-panel/aws_lambda/cloudformation_template.yml](backend-admin-panel/aws_lambda/cloudformation_template.yml) — CFN for lambdas & IAM.
- [backend-admin-panel/aws_lambda/deploy_lambda.sh](backend-admin-panel/aws_lambda/deploy_lambda.sh) — packaging & deploy helper; writes `DELETE_LAMBDA_FUNCTION` into `backend-admin-panel/.env` when available.
- [frontend-admin-panel/src/hooks/useCSVData.ts](frontend-admin-panel/src/hooks/useCSVData.ts) — upload/delete logic, with `retryDeleteFile`.
- [frontend-admin-panel/src/components/CSVTable.tsx](frontend-admin-panel/src/components/CSVTable.tsx) — DataGrid UI and retry button for failed deletes.
- `run_services.sh` — convenience script to start frontend & backend in dev (writes logs + PIDs).

---

## High-level architecture

```mermaid
flowchart LR
  subgraph Browser
    F[Frontend (React, Vite)]
  end
  subgraph Backend
    B[FastAPI Backend]
  end
  subgraph AWS
    S3[(S3 Bucket)]
    ProcLambda[s3_processor_lambda]
    DelLambda[s3_delete_lambda]
  end

  F -- Authenticated API calls (Authorization: Bearer <Cognito token>) --> B
  F -- Request presigned PUT & direct upload --> S3
  B -- Generates presigned PUT/GET using boto3 --> S3
  S3 -- Optional ObjectCreated event --> ProcLambda
  ProcLambda -- Writes summary JSON (.summary.json) --> S3
  ProcLambda -- Calls back (X-Verify-Token) --> B
  B -- Invokes ProcLambda / DelLambda (lambda:InvokeFunction) --> ProcLambda & DelLambda
  DelLambda -- Deletes object & POST /delete-complete (X-Verify-Token) --> B
  F -- Attempts HEAD /download-stream --> B
  F -- If HEAD ok -> GET /download-stream -> B streams S3 object
  F -- Else -> GET /download (backend returns presigned GET -> F opens S3 URL)
```

---

## Detailed runtime flows

These sections explain which services call which endpoints, what headers and payloads they use, and how tokens are managed.

### Upload flow (metadata-first, presigned PUT)

1. Frontend asks for an upload slot:

  - Request: `POST /api/v1/files/upload-url`
    - Headers: `Authorization: Bearer <access_token>` (if user is authenticated via Cognito)
    - Body: `{ "filename": "foo.csv", "file_size_bytes": 12345, "mime_type": "text/csv" }`

  - Backend actions:
    - Validate filename & mimetype.
    - Check for duplicates (same filename + size) in DB. If duplicate -> `409` with existing file info.
    - Create a unique S3 key: `csv_uploads/<uuid>_<filename>`.
    - Call `S3Service.generate_presigned_upload_url(key, content_type)` which uses boto3 to create a presigned PUT URL (temporary, signed by backend credentials).

  - Response: `{ "upload_url": "https://...signed...", "s3_key": "csv_uploads/..." }`

2. Frontend creates DB metadata record:

  - Request: `POST /api/v1/files` with `{ filename, file_size_bytes, mime_type, s3_key }`.
  - Backend inserts a `CSVFile` record (status: pending) and returns the created record (with `id`).

3. Browser uploads file directly to S3:

  - Client performs `PUT <upload_url>` using `XMLHttpRequest` so it can track `xhr.upload.onprogress` events.
  - The upload URL encodes signature & expiry; no AWS credentials are used in the browser.

4. After successful PUT, frontend marks the status:

  - Request: `PATCH /api/v1/files/{id}/status` with `{ "status": "uploaded" }`.
  - Backend calls `s3.head_object()` (with its boto3 client) to confirm object presence. If found the backend sets `verified=True`; otherwise `verified=False` and increments `verification_attempts`.

Notes about presigned URLs and tokens:

  - Browser never sees AWS credentials. It uses presigned URLs signed by backend's boto3 using its credentials/role.
  - The `Authorization` header (Cognito token) is used for frontend->backend authorization; its validation is optional in current code but the token is attached if present.

### Verification & parsing (Lambda)

Two ways the parsing/summary flow can occur:

1. S3-triggered Processor Lambda

  - When an object is created in S3, the `s3_processor_lambda` (if deployed) can be triggered and will:
    - Download or stream the CSV, compute summary JSON (stats, sample rows, column info), and write `<s3_key>.summary.json` to the same bucket.
    - POST to backend `/api/v1/files/verify` with JSON `{ "s3_key": "..." }` and header `X-Verify-Token: <VERIFY_SECRET>` (shared secret). The backend validates the header and updates DB record accordingly.

2. Backend-invoked parser (manual trigger)

  - Endpoint: `POST /api/v1/files/{id}/trigger-parse` — if `LAMBDA_FUNCTION_NAME` configured, backend will invoke the parser Lambda asynchronously (InvocationType='Event'). If not configured it returns `{invoked:false, reason: '...'}`.

Frontend summary retrieval:

  - `GET /api/v1/files/{id}/summary` returns `{ exists: boolean }` and, when present, `summary_url` (presigned GET to the JSON summary).

### Download flow (streaming fallback and presigned GET)

Frontend tries to open the object in a friendly way:

1. HEAD probe: `HEAD /api/v1/files/{id}/download-stream` — backend performs `s3.head_object` and returns 200 with content headers if backend can read the object. Use this to decide whether to stream through backend or use presigned GET.

2. If HEAD is OK: frontend opens `GET /api/v1/files/{id}/download-stream` — backend calls `s3.get_object`, and returns a `StreamingResponse` with `Content-Disposition: attachment; filename="<filename>"` and correct `Content-Type`.

3. If HEAD fails: frontend requests `GET /api/v1/files/{id}/download` — backend returns `{ download_url: "<presigned-get>" }` and the frontend navigates to that presigned URL (browser -> S3 download).

### Delete flow (synchronous and asynchronous)

There are two ways to delete S3 objects + DB records:

1. Synchronous delete (backend attempts immediately)

  - `DELETE /api/v1/files/{id}?delete_s3=true` — backend calls `S3Service.delete_s3_object(key)` which attempts `s3.delete_object` using backend credentials. If deletion fails, the backend returns 500 and preserves the DB record so the operator can retry.

2. Asynchronous delete (recommended; uses Delete Lambda)

  - If `DELETE_LAMBDA_FUNCTION` is configured, the backend will:
    - Mark DB record `status='deleting'`, `delete_requested_at=now`, `delete_attempts=0`, `delete_last_error=null`.
    - Invoke Delete Lambda asynchronously with payload `{ "file_id": id, "s3_key": key }`.
    - Return `202 Accepted` to the caller.

  - Delete Lambda duties:
    - Attempt to `delete_object` in S3 (must have `s3:DeleteObject`).
    - POST back to backend `POST /api/v1/files/{id}/delete-complete` with `{ "deleted": true }` on success or `{ "deleted": false, "message": "..." }` on failure. Include header `X-Verify-Token: <VERIFY_SECRET>`.

  - Backend callback handling (`delete-complete`):
    - If `deleted: true`, set `delete_completed_at` and remove DB record.
    - If `deleted: false`, set `status='delete_failed'`, increment `delete_attempts`, store `delete_last_error`.

3. Retry endpoint

  - `POST /api/v1/files/{id}/retry-delete` — backend will re-invoke Delete Lambda (if configured) and return 202, or attempt a synchronous delete if no lambda is configured.

  - The frontend displays a `Retry Delete` button for rows with `status === 'delete_failed'`. The hook `retryDeleteFile` calls this endpoint.

---

## Authentication & token handling (detailed)

1. Frontend (Cognito) -> Backend

  - Frontend uses Amplify/Cognito to authenticate users. Use `fetchAuthSession()` to obtain tokens.
  - `frontend-admin-panel/src/utils/apiFetch.ts` implements `authenticatedFetch()` which appends `Authorization: Bearer <access_token>` when a session exists.
  - Backend endpoints currently accept requests with or without this header. For production, add JWT validation middleware or put backend behind API Gateway with Cognito Authorizer.

2. Backend -> AWS (boto3 credentials)

  - Backend uses `boto3` for presigned URLs, head/get/delete, and for invoking lambdas. boto3 obtains credentials from environment variables (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`) or the instance/container IAM role.
  - Presigned URLs contain time-limited signatures that allow a browser to PUT/GET directly to S3 without AWS credentials.

3. Lambda callback verification (shared secret)

  - To authenticate callbacks from Lambdas (parser/delete) to the backend, a shared `VERIFY_SECRET` is used.
  - Lambdas include header `X-Verify-Token: <VERIFY_SECRET>` when calling `/api/v1/files/verify` or `/api/v1/files/{id}/delete-complete`.
  - Backend validates this header before trusting the callback.

Security notes
- Never check `VERIFY_SECRET` or AWS keys into source control. Use secure store (Secrets Manager / Parameter Store) in production.
- Minimum IAM permissions: give lambdas only the permissions they need. For deletes, give `s3:DeleteObject` to the delete-lambda role, not to your general backend role if possible.

---

## Environment variables (important)

Backend (`backend-admin-panel`)
- `BUCKET_NAME` (default: `local-test-csv-bucket`)
- `AWS_DEFAULT_REGION` (e.g. `us-east-1`)
- `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` (optional; rely on IAM role otherwise)
- `DATABASE_URL` (SQLAlchemy database URL)
- `LAMBDA_FUNCTION_NAME` (optional: parser lambda name)
- `DELETE_LAMBDA_FUNCTION` (optional: delete lambda name or ARN)
- `VERIFY_SECRET` (shared secret for Lambda callbacks)
- `CORS_ORIGINS` (comma separated; default includes local dev origins)

Frontend (`frontend-admin-panel`)
- `VITE_API_BASE_URL` (e.g. `http://localhost:8000/api/v1`)
- Amplify/Cognito config if using Cognito

Deploy script parameters (`deploy_lambda.sh`)
- `--artifact-bucket`, `--artifact-key`, `--bucket-name`, `--backend-verify-url`, `--backend-base-url`, `--verify-secret`, `--lambda-function-name`, `--delete-lambda-name`.

---

## Running locally (quickstart)

Prereqs: Python 3.8+, Node 18+/npm, AWS CLI (only if deploying lambdas)

1) Backend

```bash
cd backend-admin-panel
# create virtualenv and install deps if provided
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt || true
uvicorn app_fastapi.main:app --reload --host 0.0.0.0 --port 8000
```

2) Frontend

```bash
cd frontend-admin-panel
npm install
npm run dev
```

3) Convenience: start both

```bash
chmod +x run_services.sh
./run_services.sh
```

Logs will be written to `backend.log` and `frontend.log` when using `run_services.sh` (PIDs in `backend.pid` / `frontend.pid`).

---

## Deploying the Lambdas (packaging & CloudFormation)

1. Prepare artifact S3 bucket and ensure AWS CLI profile has CloudFormation/IAM privileges.

2. Run the deploy script from `backend-admin-panel/aws_lambda`:

```bash
cd backend-admin-panel/aws_lambda
./deploy_lambda.sh \
  --artifact-bucket my-artifact-bucket \
  --artifact-key lambda_package.zip \
  --bucket-name my-csv-bucket \
  --backend-verify-url https://api.example.com/api/v1/files/verify \
  --verify-secret "YOUR_VERIFY_SECRET" \
  --backend-base-url https://api.example.com
```

Notes:
- The script zips `s3_processor_lambda.py` and `s3_delete_lambda.py`, uploads them, deploys `cloudformation_template.yml`, and then queries the CloudFormation outputs for `DeleteLambdaFunctionArn` and writes it into `backend-admin-panel/.env` as `DELETE_LAMBDA_FUNCTION` if that file exists.
- Ensure Lambda IAM roles have `s3:GetObject`, `s3:PutObject` (parser), `s3:DeleteObject` (delete lambda), and `logs:CreateLogGroup/PutLogEvents`.

---

## Troubleshooting & common errors

- Presigned GET returns 403: ensure the presigned URL was generated for the correct region and bucket and that the object still exists. Check `BUCKET_NAME` and region.
- Backend `s3.delete_object` AccessDenied: backend credentials lack `s3:DeleteObject`. Use the delete-lambda approach and grant `s3:DeleteObject` to the lambda role.
- Streaming HEAD returns 404: backend cannot read the S3 object; check backend AWS credentials and `BUCKET_NAME`.
- Missing DB columns (e.g. delete tracking fields): run `python3 add_columns.py` in `backend-admin-panel` to add columns.
- Lambda callback failing with 401: ensure the delete/parser lambda sends `X-Verify-Token: <VERIFY_SECRET>` header and that `VERIFY_SECRET` in backend env matches.

Useful debug commands

```bash
# List records
curl -sS http://localhost:8000/api/v1/files | jq

# Request an upload URL
curl -sS -X POST http://localhost:8000/api/v1/files/upload-url -H 'Content-Type: application/json' \
  -d '{"filename":"test.csv","file_size_bytes":1234,"mime_type":"text/csv"}' | jq

# Simulate delete lambda callback (failure)
curl -X POST http://localhost:8000/api/v1/files/2/delete-complete \
  -H "X-Verify-Token: YOUR_VERIFY_SECRET" -H 'Content-Type: application/json' \
  -d '{"deleted": false, "message": "S3 delete AccessDenied"}'
```

---

## Where to look in the code (quick links)

- Backend API: [backend-admin-panel/app_fastapi/main.py](backend-admin-panel/app_fastapi/main.py)
- S3 helper: [backend-admin-panel/app_fastapi/s3_service.py](backend-admin-panel/app_fastapi/s3_service.py)
- Delete lambda: [backend-admin-panel/aws_lambda/s3_delete_lambda.py](backend-admin-panel/aws_lambda/s3_delete_lambda.py)
- Parser lambda: [backend-admin-panel/aws_lambda/s3_processor_lambda.py](backend-admin-panel/aws_lambda/s3_processor_lambda.py)
- Lambda deploy helper: [backend-admin-panel/aws_lambda/deploy_lambda.sh](backend-admin-panel/aws_lambda/deploy_lambda.sh)
- Frontend hook: [frontend-admin-panel/src/hooks/useCSVData.ts](frontend-admin-panel/src/hooks/useCSVData.ts)
- Frontend table & retry UI: [frontend-admin-panel/src/components/CSVTable.tsx](frontend-admin-panel/src/components/CSVTable.tsx)

---

