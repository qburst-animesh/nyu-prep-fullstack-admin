#!/usr/bin/env bash
set -euo pipefail

# deployment_script.sh
# Packages Lambda handlers into a single zip artifact, uploads to S3,
# and deploys the CloudFormation stack. Designed to be idempotent and
# configurable via CLI args or environment variables.

usage() {
  cat <<'USAGE'
Usage: deployment_script.sh --artifact-bucket BUCKET --artifact-key KEY --bucket-name CSV_BUCKET \
  --backend-verify-url URL --verify-secret SECRET --cognito-user-pool-id POOL_ID --cognito-client-id CLIENT_ID [options]

Required:
  --artifact-bucket        S3 bucket where the lambda zip will be uploaded
  --artifact-key           S3 key (object name) for the uploaded zip (e.g. lambda_package.zip)
  --bucket-name            The CSV uploads bucket name (CF parameter `BucketName`)
  --backend-verify-url     Full URL to your backend verify endpoint (e.g. https://api.example.com/api/v1/files/verify)
  --verify-secret          Secret token passed as X-Verify-Token to your backend
  --cognito-user-pool-id   Cognito User Pool Id (for API GW JWT authorizer)
  --cognito-client-id      Cognito App Client ID used as JWT audience

Options:
  --stack-name             CloudFormation stack name (default: csv-processor-stack)
  --lambda-function-name   Lambda function base name (default: csv-processor-lambda)
  --delete-lambda-name     Lambda name for deletes (default: csv-delete-lambda)
  --backend-base-url       Base URL of backend used by delete lambda callbacks (e.g. https://api.example.com)
  --max-rows               MAX_ROWS_TO_VALIDATE (default: 1000)
  --validate-full          Validate full file: true|false (default: false)
  --create-bucket          true|false (create S3 bucket via CF) (default: false)
  --enable-realtime       true|false (create realtime infra: SQS, API GW, WebSocket) (default: false)
  --summary-bucket-name    Name of the summary S3 bucket to create/use (default: csv-json-summary)
  -h, --help               Show this help
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
CREATE_BUCKET="false"
ENABLE_REALTIME="false"
SUMMARY_BUCKET_NAME="csv-json-summary"
CREATE_SUMMARY_BUCKET="false"

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
    --cognito-user-pool-id)
      COGNITO_USER_POOL_ID="$2"; shift 2;;
    --cognito-client-id)
      COGNITO_CLIENT_ID="$2"; shift 2;;
    --create-bucket)
      CREATE_BUCKET="$2"; shift 2;;
      --create-summary-bucket)
        CREATE_SUMMARY_BUCKET="$2"; shift 2;;
    --summary-bucket-name)
      SUMMARY_BUCKET_NAME="$2"; shift 2;;
    --enable-realtime)
      ENABLE_REALTIME="$2"; shift 2;;
    -h|--help)
      usage;;
    *)
      echo "Unknown option: $1"; usage;;
  esac
done

# Basic validation
if [[ -z "${ARTIFACT_BUCKET:-}" || -z "${CSV_BUCKET:-}" || -z "${BACKEND_VERIFY_URL:-}" || -z "${VERIFY_SECRET:-}" ]]; then
  echo "Missing required parameters." >&2
  usage
fi

# If realtime infra is enabled, ensure Cognito parameters are provided
if [[ "${ENABLE_REALTIME}" == "true" ]]; then
  if [[ -z "${COGNITO_USER_POOL_ID:-}" || -z "${COGNITO_CLIENT_ID:-}" ]]; then
    echo "Realtime infra enabled; missing Cognito parameters." >&2
    usage
  fi
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if ! command -v zip >/dev/null 2>&1; then
  echo "zip is required but not found. Install zip and retry." >&2
  exit 2
fi

# Prepare temporary artifact path
TMP_ZIP="/tmp/${ARTIFACT_KEY}_$$.zip"

# Files to include in the lambda package (all handlers live at this directory)
LAMBDA_FILES=(s3_processor_lambda.py s3_delete_lambda.py websocket_connect.py websocket_disconnect.py)

# Ensure files exist
for f in "${LAMBDA_FILES[@]}"; do
  if [[ ! -f "$f" ]]; then
    echo "Expected lambda file $f not found in $SCRIPT_DIR" >&2
    exit 3
  fi
done

echo "Packaging lambda handlers into $TMP_ZIP"
# Zip handlers at root of archive so Lambda can reference handlers by module name
rm -f "$TMP_ZIP"
zip -j "$TMP_ZIP" "${LAMBDA_FILES[@]}" >/dev/null

# Upload to S3
echo "Uploading artifact to s3://${ARTIFACT_BUCKET}/${ARTIFACT_KEY}"
aws s3 cp "$TMP_ZIP" "s3://${ARTIFACT_BUCKET}/${ARTIFACT_KEY}"

# Deploy CloudFormation stacks
if [[ -f cloudformation_core.yml && -f cloudformation_realtime.yml ]]; then
  CORE_STACK_NAME="${STACK_NAME}-core"
  REALTIME_STACK_NAME="${STACK_NAME}-realtime"

  echo "Detected split templates; deploying core stack: ${CORE_STACK_NAME}"
  CORE_PARAMS=(
    --stack-name "$CORE_STACK_NAME"
    --template-file cloudformation_core.yml
    --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM
    --parameter-overrides
    BucketName="${CSV_BUCKET}"
    LambdaS3CodeBucket="${ARTIFACT_BUCKET}"
    LambdaS3CodeKey="${ARTIFACT_KEY}"
    BackendVerifyUrl="${BACKEND_VERIFY_URL}"
    VerifySecret="${VERIFY_SECRET}"
    BackendBaseUrl="${BACKEND_BASE_URL}"
    LambdaFunctionName="${LAMBDA_FUNCTION_NAME}"
    DeleteLambdaFunctionName="${DELETE_LAMBDA_NAME}"
    MaxRowsToValidate="${MAX_ROWS_TO_VALIDATE}"
    ValidateFullFile="${VALIDATE_FULL_FILE}"
    CreateBucket="${CREATE_BUCKET}"
    SummaryBucketName="${SUMMARY_BUCKET_NAME}"
      CreateSummaryBucket="${CREATE_SUMMARY_BUCKET}"
  )

  aws cloudformation deploy "${CORE_PARAMS[@]}"

  if [[ "${ENABLE_REALTIME}" == "true" ]]; then
    echo "Deploying realtime stack: ${REALTIME_STACK_NAME}"
    REALTIME_PARAMS=(
      --stack-name "$REALTIME_STACK_NAME"
      --template-file cloudformation_realtime.yml
      --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM
      --parameter-overrides
      CoreStackName="$CORE_STACK_NAME"
      LambdaS3CodeBucket="${ARTIFACT_BUCKET}"
      LambdaS3CodeKey="${ARTIFACT_KEY}"
      BackendBaseUrl="${BACKEND_BASE_URL}"
      LambdaFunctionName="${LAMBDA_FUNCTION_NAME}"
    )
    REALTIME_PARAMS+=( CognitoUserPoolId="${COGNITO_USER_POOL_ID}" CognitoClientId="${COGNITO_CLIENT_ID}" )

    aws cloudformation deploy "${REALTIME_PARAMS[@]}"
    STACK_FOR_OUTPUTS="$REALTIME_STACK_NAME"
  else
    STACK_FOR_OUTPUTS="$CORE_STACK_NAME"
  fi
else
  echo "Deploying CloudFormation stack: ${STACK_NAME}"

  # Build parameter overrides array so we can conditionally include Cognito values
  CF_PARAMS=(
    --stack-name "$STACK_NAME"
    --template-file cloudformation_template.yml
    --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM
    --parameter-overrides
    BucketName="${CSV_BUCKET}"
    LambdaS3CodeBucket="${ARTIFACT_BUCKET}"
    LambdaS3CodeKey="${ARTIFACT_KEY}"
    BackendVerifyUrl="${BACKEND_VERIFY_URL}"
    VerifySecret="${VERIFY_SECRET}"
    BackendBaseUrl="${BACKEND_BASE_URL}"
    LambdaFunctionName="${LAMBDA_FUNCTION_NAME}"
    DeleteLambdaFunctionName="${DELETE_LAMBDA_NAME}"
    MaxRowsToValidate="${MAX_ROWS_TO_VALIDATE}"
    ValidateFullFile="${VALIDATE_FULL_FILE}"
    CreateBucket="${CREATE_BUCKET}"
    EnableRealtime="${ENABLE_REALTIME}"
    SummaryBucketName="${SUMMARY_BUCKET_NAME}"
  )

  # If realtime enabled, ensure Cognito overrides are passed
  if [[ "${ENABLE_REALTIME}" == "true" ]]; then
    CF_PARAMS+=( CognitoUserPoolId="${COGNITO_USER_POOL_ID}" CognitoClientId="${COGNITO_CLIENT_ID}" )
  fi

  aws cloudformation deploy "${CF_PARAMS[@]}"
  STACK_FOR_OUTPUTS="$STACK_NAME"
fi

# Read outputs to capture deployed outputs
echo "Fetching deployed outputs"
OUTPUTS_JSON=$(aws cloudformation describe-stacks --stack-name "$STACK_FOR_OUTPUTS" --query "Stacks[0].Outputs" --output json || echo '[]')

# Extract values
API_ENDPOINT=$(echo "$OUTPUTS_JSON" | python3 -c "import sys, json; o=json.load(sys.stdin); print(next((x['OutputValue'] for x in o if x['OutputKey']=='ApiGatewayEndpoint'), ''))")
DELETE_LAMBDA_ARN=$(echo "$OUTPUTS_JSON" | python3 -c "import sys,json; o=json.load(sys.stdin); print(next((x['OutputValue'] for x in o if x['OutputKey']=='DeleteLambdaFunctionArn'), ''))")

if [[ -n "$API_ENDPOINT" ]]; then
  echo "API endpoint: $API_ENDPOINT"
fi

if [[ -n "$DELETE_LAMBDA_ARN" ]]; then
  echo "Delete Lambda ARN: $DELETE_LAMBDA_ARN"
  # Optionally write into backend .env for local testing
  BACKEND_ENV_FILE="$SCRIPT_DIR/../.env"
  if [[ -f "$BACKEND_ENV_FILE" ]]; then
    if grep -q '^DELETE_LAMBDA_FUNCTION=' "$BACKEND_ENV_FILE"; then
      sed -i "s|^DELETE_LAMBDA_FUNCTION=.*|DELETE_LAMBDA_FUNCTION='${DELETE_LAMBDA_ARN}'|" "$BACKEND_ENV_FILE"
    else
      echo "DELETE_LAMBDA_FUNCTION='${DELETE_LAMBDA_ARN}'" >> "$BACKEND_ENV_FILE"
    fi
      # Write summary bucket into backend .env for local testing
      if grep -q '^SUMMARY_BUCKET_NAME=' "$BACKEND_ENV_FILE"; then
        sed -i "s|^SUMMARY_BUCKET_NAME=.*|SUMMARY_BUCKET_NAME='${SUMMARY_BUCKET_NAME}'|" "$BACKEND_ENV_FILE"
      else
        echo "SUMMARY_BUCKET_NAME='${SUMMARY_BUCKET_NAME}'" >> "$BACKEND_ENV_FILE"
      fi
    echo "Wrote DELETE_LAMBDA_FUNCTION to $BACKEND_ENV_FILE"
  else
    echo "Warning: backend .env not found at $BACKEND_ENV_FILE; skipping write"
  fi
fi

# Clean up
rm -f "$TMP_ZIP"

echo "Deployment finished. If you need to update only Lambda code in the future, upload a new zip to s3://${ARTIFACT_BUCKET}/${ARTIFACT_KEY} and use 'aws lambda update-function-code' or re-run this script."
