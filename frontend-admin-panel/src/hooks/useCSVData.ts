import { useState, useEffect, useCallback } from 'react';
import { authenticatedFetch, logger } from '../utils/apiFetch';

export interface CSVFileRecord {
  id: number;
  filename: string;
  s3_key: string;
  file_size_bytes: number;
  mime_type: string;
  created_at: string;
  updated_at: string;
}

export function useCSVData() {
  const [fileList, setFileList] = useState<CSVFileRecord[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [uploading, setUploading] = useState<boolean>(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const fetchDatabaseRecords = useCallback(async () => {
    setLoading(true);
    setErrorMessage(null);
    logger.info('Initiating database record fetch orchestration.');
    try {
      const response = await authenticatedFetch('/files');
      if (!response.ok) throw new Error(`Server returned status operational fault: ${response.status}`);
      const data: CSVFileRecord[] = await response.json();
      setFileList(data);
      logger.info({ count: data.length }, 'Successfully synchronized local state ledger.');
    } catch (err: any) {
      logger.error({ err }, 'Failed to pull infrastructure data index mapping models.');
      setErrorMessage('Failed to load database records. Please try again.');
    } finally {
      setLoading(false);
    }
  }, []);

  const handleFileUpload = async (file: File | undefined) => {
    if (!file) return;
    setUploading(true);
    setErrorMessage(null);
    logger.info({ filename: file.name, size: file.size }, 'Commencing pre-signed file payload routing workflow.');

    try {
      // Step A: Request S3 pointer allocation mapping slot
      const urlResponse = await authenticatedFetch('/files/upload-url', {
        method: 'POST',
        body: JSON.stringify({
          filename: file.name,
          file_size_bytes: file.size,
          mime_type: file.type || 'text/csv',
        }),
      });

      if (!urlResponse.ok) throw new Error('Backend failed to allocate an S3 secure link asset.');
      const { upload_url, s3_key } = await urlResponse.json();

      // Step B: Direct Binary Stream to AWS S3 Bucket
      logger.info({ s3_key }, 'Streaming binary payload chunks directly to S3 endpoint.');
      
      // 1. Convert file to ArrayBuffer to drop auto-generated headers
      const fileBinary = await file.arrayBuffer();

      // 2. Use the exact upload_url from the backend. 
      // Do not rewrite the host domain, as it invalidates the AWS Signature security hash.
      const s3PutResponse = await fetch(upload_url, {
        method: 'PUT',
        body: fileBinary,
        headers: {},
      });

      if (!s3PutResponse.ok) throw new Error('AWS S3 pipeline rejected binary file ingestion streams.');

      // Step C: Commit Metadata Record into Database Ledger
      logger.info('Registering verified cloud allocation metadata to system database ledger.');
      const confirmResponse = await authenticatedFetch('/files', {
        method: 'POST',
        body: JSON.stringify({
          filename: file.name,
          file_size_bytes: file.size,
          mime_type: file.type || 'text/csv',
          s3_key: s3_key,
        }),
      });

      if (!confirmResponse.ok) throw new Error('Database tier denied application logging schema verification.');
      await fetchDatabaseRecords();
    } catch (err: any) {
      logger.error({ err }, 'Fatal failure during distributed file upload ingestion chain.');
      setErrorMessage(err.message || 'An error occurred during file upload.');
    } finally {
      setUploading(false);
    }
  };

  const handleDeleteFile = async (idToDelete: number) => {
    logger.warn({ idToDelete }, 'Requesting system resource teardown sequence.');
    try {
      const response = await authenticatedFetch(`/files/${idToDelete}`, {
        method: 'DELETE',
      });
      if (!response.ok) throw new Error('Distributed architecture cleanup command failed.');
      setFileList((prev) => prev.filter((file) => file.id !== idToDelete));
      logger.info({ idToDelete }, 'Successfully extracted resource across all boundary entities.');
    } catch (err: any) {
      logger.error({ err, idToDelete }, 'Resource evacuation failure execution routine broken.');
      setErrorMessage('Could not remove file registration metadata context safely.');
    }
  };

  useEffect(() => {
    fetchDatabaseRecords();
  }, [fetchDatabaseRecords]);

  return { fileList, loading, uploading, errorMessage, handleFileUpload, handleDeleteFile };
}