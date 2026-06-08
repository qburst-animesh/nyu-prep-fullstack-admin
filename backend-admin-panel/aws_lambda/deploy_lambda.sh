#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: deploy_lambda.sh --artifact-bucket BUCKET --artifact-key KEY --bucket-name CSV_BUCKET --stack-name STACK_NAME --backend-verify-url URL --verify-secret SECRET [options]

Required:
  --artifact-bucket    S3 bucket where the lambda zip will be uploaded
  --artifact-key       S3 key (object name) for the uploaded zip (e.g. lambda_package.zip)
  --bucket-name        The CSV uploads bucket name (CF parameter `BucketName`)
  --backend-verify-url Full URL to your backend verify endpoint (e.g. https://api.example.com/api/v1/files/verify)
  --verify-secret      Secret token passed as X-Verify-Token to your backend

Options:
  --stack-name         CloudFormation stack name (default: csv-processor-stack)
  --lambda-function-name Lambda function name (default: csv-processor-lambda)
  --delete-lambda-name Lambda function name for async deletes (default: csv-delete-lambda)
  --backend-base-url   Base URL of backend used by delete lambda callbacks (e.g. https://api.example.com)
  --max-rows           MAX_ROWS_TO_VALIDATE (default: 1000)
  --validate-full      Validate full file: true|false (default: false)
  -h, --help           Show this help
USAGE
  exit 1
}

# Defaults
ARTIFACT_KEY="lambda_package.zip"
STACK_NAME="csv-processor-stack"
LAMBDA_FUNCTION_NAME="csv-processor-lambda"
DELETE_LAMBDA_NAME="csv-delete-lambda"
BACKEND_BASE_URL=""
MAX_ROWS_TO_VALIDATE="1000"
VALIDATE_FULL_FILE="false"

# Parse args
while [[ $# -gt 0 ]]; do
  case "$1" in
    --artifact-bucket)
      ARTIFACT_BUCKET="$2"; shift 2;;
    --artifact-key)
      ARTIFACT_KEY="$2"; shift 2;;
    --bucket-name)
      CSV_BUCKET="$2"; shift 2;;
    --stack-name)
      STACK_NAME="$2"; shift 2;;
    --backend-verify-url)
      BACKEND_VERIFY_URL="$2"; shift 2;;
    --backend-base-url)
      BACKEND_BASE_URL="$2"; shift 2;;
    --delete-lambda-name)
      DELETE_LAMBDA_NAME="$2"; shift 2;;
    --verify-secret)
      VERIFY_SECRET="$2"; shift 2;;
    --lambda-function-name)
      LAMBDA_FUNCTION_NAME="$2"; shift 2;;
    --max-rows)
      MAX_ROWS_TO_VALIDATE="$2"; shift 2;;
    --validate-full)
      VALIDATE_FULL_FILE="$2"; shift 2;;
    -h|--help)
      usage;;
    *)
      echo "Unknown option: $1"; usage;;
  esac
done

# Basic validation
if [[ -z "${ARTIFACT_BUCKET:-}" || -z "${CSV_BUCKET:-}" || -z "${BACKEND_VERIFY_URL:-}" || -z "${VERIFY_SECRET:-}" || -z "${BACKEND_BASE_URL:-}" ]]; then
  echo "Missing required parameters." >&2
  usage
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if ! command -v zip >/dev/null 2>&1; then
  echo "zip is required but not found. Install zip and retry." >&2
  exit 2
fi

TMP_ZIP="/tmp/${ARTIFACT_KEY}_$$.zip"
echo "Packaging lambda into $TMP_ZIP"
zip -j "$TMP_ZIP" s3_processor_lambda.py s3_delete_lambda.py

echo "Uploading artifact to s3://${ARTIFACT_BUCKET}/${ARTIFACT_KEY}"
aws s3 cp "$TMP_ZIP" "s3://${ARTIFACT_BUCKET}/${ARTIFACT_KEY}"

echo "Deploying CloudFormation stack: ${STACK_NAME}"
aws cloudformation deploy \
  --stack-name "$STACK_NAME" \
  --template-file cloudformation_template.yml \
  --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    BucketName="${CSV_BUCKET}" \
    LambdaS3CodeBucket="${ARTIFACT_BUCKET}" \
    LambdaS3CodeKey="${ARTIFACT_KEY}" \
    BackendVerifyUrl="${BACKEND_VERIFY_URL}" \
    VerifySecret="${VERIFY_SECRET}" \
    BackendBaseUrl="${BACKEND_BASE_URL}" \
    LambdaFunctionName="${LAMBDA_FUNCTION_NAME}" \
    DeleteLambdaFunctionName="${DELETE_LAMBDA_NAME}" \
    MaxRowsToValidate="${MAX_ROWS_TO_VALIDATE}" \
    ValidateFullFile="${VALIDATE_FULL_FILE}"

echo "Fetching deployed Delete Lambda ARN from CloudFormation outputs"
DELETE_LAMBDA_ARN=$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" --query "Stacks[0].Outputs[?OutputKey=='DeleteLambdaFunctionArn'].OutputValue" --output text || true)
if [[ -n "$DELETE_LAMBDA_ARN" && "$DELETE_LAMBDA_ARN" != "None" ]]; then
  echo "Updating backend .env with DELETE_LAMBDA_FUNCTION=$DELETE_LAMBDA_ARN"
  BACKEND_ENV_FILE="$SCRIPT_DIR/../.env"
  if [[ -f "$BACKEND_ENV_FILE" ]]; then
    if grep -q '^DELETE_LAMBDA_FUNCTION=' "$BACKEND_ENV_FILE"; then
      sed -i "s|^DELETE_LAMBDA_FUNCTION=.*|DELETE_LAMBDA_FUNCTION='${DELETE_LAMBDA_ARN}'|" "$BACKEND_ENV_FILE"
    else
      echo "DELETE_LAMBDA_FUNCTION='${DELETE_LAMBDA_ARN}'" >> "$BACKEND_ENV_FILE"
    fi
    echo "Wrote DELETE_LAMBDA_FUNCTION to $BACKEND_ENV_FILE"
  else
    echo "Warning: backend .env not found at $BACKEND_ENV_FILE; skipping write"
  fi
else
  echo "No DeleteLambdaFunctionArn found in stack outputs; skipping backend .env update"
fi

echo "Cleaning up temporary artifact"
rm -f "$TMP_ZIP"

echo "Deployment finished."
