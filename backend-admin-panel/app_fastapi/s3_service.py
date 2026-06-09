import os
import boto3
from botocore.exceptions import ClientError

class S3Service:
    def __init__(self):
        # Initialize S3 client using environment or shared AWS credentials
        self.bucket_name = os.getenv("BUCKET_NAME", "local-test-csv-bucket")
        region = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
        aws_access_key = os.getenv("AWS_ACCESS_KEY_ID")
        aws_secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")

        if aws_access_key and aws_secret_key:
            self.s3_client = boto3.client(
                's3',
                region_name=region,
                aws_access_key_id=aws_access_key,
                aws_secret_access_key=aws_secret_key
            )
        else:
            # Let boto3 fallback to standard credential resolution (env, profile, IAM role)
            self.s3_client = boto3.client('s3', region_name=region)


    def generate_presigned_upload_url(self, object_name: str, expiration=3600, content_type: str = None) -> str:
        """Generates a secure link for React to upload files directly to S3.

        When `content_type` is provided the generated presigned URL will require
        the PUT request to include a matching `Content-Type` header.
        """
        try:
            params = {'Bucket': self.bucket_name, 'Key': object_name}
            if content_type:
                params['ContentType'] = content_type
            response = self.s3_client.generate_presigned_url(
                'put_object',
                Params=params,
                ExpiresIn=expiration
            )
            return response
        except ClientError as e:
            print(f"Error generating presigned URL: {e}")
            return None

    def generate_presigned_download_url(self, object_name: str, expiration=3600, filename: str = None) -> str:
        """Generates a secure link for users to fetch/download files.

        If `filename` is provided, the presigned URL will request S3 to
        set a Content-Disposition header so browsers can download with a
        friendly filename.
        """
        try:
            params = {'Bucket': self.bucket_name, 'Key': object_name}
            if filename:
                # Ask S3 to include a Content-Disposition header on the response
                params['ResponseContentDisposition'] = f'attachment; filename="{filename}"'
            response = self.s3_client.generate_presigned_url(
                'get_object',
                Params=params,
                ExpiresIn=expiration
            )
            return response
        except ClientError as e:
            print(f"Error generating download URL: {e}")
            return None

    def delete_s3_object(self, object_name: str) -> bool:
        """Removes the file content from AWS storage assets"""
        try:
            self.s3_client.delete_object(Bucket=self.bucket_name, Key=object_name)
            return True
        except ClientError:
            # Log the failure for diagnostics and return False so callers
            # can decide whether to proceed (e.g. avoid deleting DB records)
            try:
                import traceback
                traceback.print_exc()
            except Exception:
                pass
            return False

    def head_object(self, object_name: str):
        """Retrieve metadata for an object (size, ETag, etc.) or None if missing."""
        try:
            return self.s3_client.head_object(Bucket=self.bucket_name, Key=object_name)
        except ClientError:
            return None
