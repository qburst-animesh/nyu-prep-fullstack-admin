# NYU Prep Fullstack Admin

This repository contains a small full-stack admin application for managing CSV file uploads. The system uses a React frontend for authentication and file management, and a FastAPI backend for metadata storage and S3 presigned URL workflows.

## Repository structure

```text
nyu-prep-fullstack-admin/
├── backend-admin-panel/
│   ├── app_fastapi/
│   │   ├── database.py
│   │   ├── main.py
│   │   ├── models.py
│   │   ├── s3_service.py
│   │   └── schemas.py
│   └── requirements.txt
├── frontend-admin-panel/
│   ├── public/
│   ├── src/
│   │   ├── components/
│   │   ├── hooks/
│   │   └── utils/
│   ├── package.json
│   └── vite.config.ts
└── README.md
```

## Architecture overview

### Frontend

The frontend lives in `frontend-admin-panel/`.

It is responsible for:
- authenticating users with AWS Cognito through Amplify
- rendering the admin dashboard
- requesting presigned upload URLs from the backend
- uploading CSV files directly to S3
- saving file metadata through backend APIs
- listing and deleting uploaded file records

Important frontend files:
- `frontend-admin-panel/src/index.tsx` - bootstraps React and configures Amplify Auth
- `frontend-admin-panel/src/App.tsx` - authenticated app shell and dashboard layout
- `frontend-admin-panel/src/components/CSVTable.tsx` - file table, upload button, delete action
- `frontend-admin-panel/src/hooks/useCSVData.ts` - main file fetch/upload/delete workflow
- `frontend-admin-panel/src/utils/apiFetch.ts` - authenticated fetch helper and logging

### Backend

The backend lives in `backend-admin-panel/`.

It is responsible for:
- exposing REST endpoints for file operations
- generating S3 presigned upload and download URLs
- persisting file metadata in PostgreSQL with SQLAlchemy
- handling deletion from both S3 and the database

Important backend files:
- `backend-admin-panel/app_fastapi/main.py` - FastAPI app, routes, and CORS setup
- `backend-admin-panel/app_fastapi/database.py` - SQLAlchemy engine, session, and base model setup
- `backend-admin-panel/app_fastapi/models.py` - database model for uploaded CSV records
- `backend-admin-panel/app_fastapi/schemas.py` - Pydantic request and response schemas
- `backend-admin-panel/app_fastapi/s3_service.py` - boto3 wrapper for S3 URL generation and deletion

## Key technologies

### Frontend
- React 18
- TypeScript
- Vite
- Vitest
- AWS Amplify
- AWS Cognito
- Pino logging
- Material UI and MUI Data Grid components in the app code

### Backend
- FastAPI
- SQLAlchemy
- Pydantic
- boto3
- PostgreSQL
- Uvicorn

## Request flow

The main upload flow works like this:

1. The frontend requests `POST /api/v1/files/upload-url`.
2. The backend generates a unique S3 key and returns a presigned upload URL.
3. The frontend uploads the file directly to S3 using the returned URL.
4. The frontend calls `POST /api/v1/files` to save metadata in PostgreSQL.
5. The dashboard refreshes by calling `GET /api/v1/files`.

Deletion works through `DELETE /api/v1/files/{file_id}`, which removes the object from S3 and the metadata row from the database.

## Backend API

Current backend routes:

- `POST /api/v1/files/upload-url`
- `POST /api/v1/files`
- `GET /api/v1/files`
- `GET /api/v1/files/{file_id}/download`
- `DELETE /api/v1/files/{file_id}`

## Environment variables

### Frontend

The current frontend code reads these environment variables:

- `REACT_APP_API_BASE_URL` - backend base URL used by `authenticatedFetch`
- `REACT_APP_COGNITO_USER_POOL_ID` - Cognito user pool ID
- `REACT_APP_COGNITO_CLIENT_ID` - Cognito app client ID
- `REACT_APP_LOG_LEVEL` - optional browser log level, defaults to `info`

> Note: the frontend uses Vite as its build tool, but the code has not been updated to use Vite's `VITE_*` environment variable naming convention. The documented names above match the code as it exists today.

### Backend

The backend expects these environment variables:

- `DATABASE_URL` - SQLAlchemy database connection string
- `CORS_ORIGINS` - comma-separated allowed frontend origins, defaults to `http://localhost:3000`
- `BUCKET_NAME` - S3 bucket name, defaults to `local-test-csv-bucket`
- `AWS_DEFAULT_REGION` - AWS region, defaults to `us-east-1`
- `AWS_ACCESS_KEY_ID` - AWS access key
- `AWS_SECRET_ACCESS_KEY` - AWS secret key

## Local development

### 1. Backend setup

```bash
cd backend-admin-panel
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app_fastapi.main:app --reload
```

By default, the FastAPI app creates tables on startup using the configured `DATABASE_URL`.

When running the frontend with `npm run dev`, Vite defaults to `http://localhost:5173`. If this port is unavailable, Vite will select an alternative port, so adjust `CORS_ORIGINS` accordingly for local development.

### 2. Frontend setup

```bash
cd frontend-admin-panel
npm install
npm run dev
```

## Frontend scripts

From `frontend-admin-panel/`:

- `npm run dev` - start the Vite dev server
- `npm run test` - run Vitest
- `npm run lint` - run ESLint
- `npm run build` - production build script currently configured in `package.json`

