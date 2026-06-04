import os
import boto3
from botocore.exceptions import ClientError

class S3Service:
    def __init__(self):
        # self.s3_client = boto3.client('s3')
        # self.bucket_name = os.getenv("BUCKET_NAME", "csv-management-storage-dev")
        
        # Fetch configurations with local development safe defaults
        self.bucket_name = os.getenv("BUCKET_NAME", "local-test-csv-bucket")
        region = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
        
        # Pull environment access strings if available
        aws_access_key = os.getenv("AWS_ACCESS_KEY_ID")
        aws_secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")

        # If variables are completely empty, inject dummy placeholders to bypass errors
        if not aws_access_key or not aws_secret_key:
            aws_access_key = "local_mock_developer_key"
            aws_secret_key = "local_mock_developer_secret"

        self.s3_client = boto3.client(
            's3',
            region_name=region,
            aws_access_key_id=aws_access_key,
            aws_secret_access_key=aws_secret_key
        )


    def generate_presigned_upload_url(self, object_name: str, expiration=3600) -> str:
        """Generates a secure link for React to upload files directly to S3"""
        try:
            response = self.s3_client.generate_presigned_url(
                'put_object',
                Params={'Bucket': self.bucket_name, 'Key': object_name},
                ExpiresIn=expiration
            )
            return response
        except ClientError as e:
            print(f"Error generating presigned URL: {e}")
            return None

    def generate_presigned_download_url(self, object_name: str, expiration=3600) -> str:
        """Generates a secure link for users to fetch/download files"""
        try:
            response = self.s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': self.bucket_name, 'Key': object_name},
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
            return False
