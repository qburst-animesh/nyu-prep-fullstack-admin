from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class CSVFileBase(BaseModel):
    filename: str
    file_size_bytes: int
    mime_type: Optional[str] = "text/csv"
    status: Optional[str] = "pending"

class CSVFileCreate(CSVFileBase):
    s3_key: str
    uploaded_by: Optional[str] = None


class CSVFileStatusUpdate(BaseModel):
    status: str

class CSVFileResponse(CSVFileBase):
    id: int
    s3_key: str
    uploaded_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    verified: Optional[bool] = None
    # Async delete tracking and audit
    delete_requested_at: Optional[datetime] = None
    delete_attempts: Optional[int] = 0
    delete_last_error: Optional[str] = None
    delete_completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True
