import React, { useState } from 'react';
import { Box, Typography, Button, IconButton, CircularProgress, Alert, LinearProgress, Dialog, DialogTitle, DialogContent, DialogActions, FormControlLabel, Checkbox } from '@mui/material';
import { DataGrid } from '@mui/x-data-grid';
import type { GridColDef, GridRenderCellParams, GridValueFormatterParams } from '@mui/x-data-grid';
import DeleteIcon from '@mui/icons-material/Delete';
import CloudUploadIcon from '@mui/icons-material/CloudUpload';
import GetAppIcon from '@mui/icons-material/GetApp';
import { useCSVData } from '../hooks/useCSVData';
import type { CSVFileRecord } from '../hooks/useCSVData';
import { authenticatedFetch } from '../utils/apiFetch';

function CSVTable() {
  const { fileList, loading, uploading, uploadProgress, errorMessage, handleFileUpload, handleDeleteFile, retryDeleteFile, refresh } = useCSVData();

  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<{ id: number; filename: string } | null>(null);
  const [deleteFromS3, setDeleteFromS3] = useState(false);
  const [summaryDialogOpen, setSummaryDialogOpen] = useState(false);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [summaryData, setSummaryData] = useState<any>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [summaryTarget, setSummaryTarget] = useState<{ id: number; filename: string } | null>(null);

  const onFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    handleFileUpload(file);
  };

  const tableColumns: GridColDef<CSVFileRecord>[] = [
    { field: 'id', headerName: 'ID', width: 70 },
    {
      field: 'filename',
      headerName: 'File Name',
      width: 230,
      renderCell: (params: GridRenderCellParams<CSVFileRecord>) => (
        <Button variant="text" onClick={(e: React.MouseEvent<HTMLButtonElement>) => { (e.currentTarget as HTMLElement).blur(); openSummary(params.row); }}>
          {params.value}
        </Button>
      )
    },
    {
      field: 'file_size_bytes',
      headerName: 'Size',
      width: 130,
      valueFormatter: (params: GridValueFormatterParams) => {
        const val = params.value;
        if (val == null) return '0 KB';
        const bytes = Number(val);
        if (isNaN(bytes)) return '';
        if (bytes < 1024) return `${bytes} B`;
        if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(2)} KB`;
        return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
      }
    },
    { field: 'mime_type', headerName: 'File Type', width: 160 },
    {
      field: 'status',
      headerName: 'Status',
      width: 180,
      renderCell: (params: GridRenderCellParams<CSVFileRecord>) => {
        if (params.value === 'pending') return <CircularProgress size={18} />;
        const verified = params.row.verified;
        if (params.value === 'uploaded' && verified === false) {
          return <Typography>Uploaded (verification pending)</Typography>;
        }
        return <Typography>{params.value || ''}</Typography>;
      }
    },
    {
      field: 'delete_requested_at',
      headerName: 'Delete Requested',
      width: 180,
      valueFormatter: (params: GridValueFormatterParams) => {
        const v = params.value;
        if (!v) return '';
        const d = new Date(v as string);
        if (isNaN(d.getTime())) return String(v);
        return d.toLocaleString();
      }
    },
    {
      field: 'delete_attempts',
      headerName: 'Delete Attempts',
      width: 120,
      valueFormatter: (params: GridValueFormatterParams) => {
        const v = params.value;
        if (v == null) return '';
        return String(v);
      }
    },
    {
      field: 'delete_last_error',
      headerName: 'Delete Error',
      width: 240,
      renderCell: (params: GridRenderCellParams<CSVFileRecord>) => (
        <Typography sx={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 220 }} title={params.value || ''}>
          {params.value || ''}
        </Typography>
      )
    },
    {
      field: 'delete_completed_at',
      headerName: 'Deleted At',
      width: 180,
      valueFormatter: (params: GridValueFormatterParams) => {
        const v = params.value;
        if (!v) return '';
        const d = new Date(v as string);
        if (isNaN(d.getTime())) return String(v);
        return d.toLocaleString();
      }
    },
    {
      field: 'created_at',
      headerName: 'Registration Timestamp',
      width: 200,
      valueFormatter: (params: GridValueFormatterParams) => {
        const v = params.value;
        if (!v) return '';
        const d = new Date(v as string);
        if (isNaN(d.getTime())) return String(v);
        return d.toLocaleString();
      }
    },
    {
      field: 'actions',
      headerName: 'Actions',
      width: 100,
      sortable: false,
      renderCell: (params: GridRenderCellParams<CSVFileRecord>) => (
        <>
          <IconButton color="primary" onClick={async (e: React.MouseEvent<HTMLButtonElement>) => {
            (e.currentTarget as HTMLElement).blur();
            try {
              const apiBase = (import.meta.env.VITE_API_BASE_URL as string) || 'http://localhost:8000/api/v1';
              const base = apiBase.replace(/\/$/, '');
              const streamUrl = `${base}/files/${params.row.id}/download-stream`;

              // Quick HEAD probe to see if backend can stream the object.
              let okToStream = false;
              try {
                const head = await fetch(streamUrl, { method: 'HEAD' });
                okToStream = head.ok;
              } catch (err) {
                okToStream = false;
              }

              if (okToStream) {
                const a = document.createElement('a');
                a.href = streamUrl;
                a.target = '_blank';
                a.rel = 'noopener noreferrer';
                document.body.appendChild(a);
                a.click();
                a.remove();
                return;
              }

              // Fallback: request presigned download URL from backend and open it.
              try {
                const resp = await authenticatedFetch(`/files/${params.row.id}/download`);
                if (!resp.ok) throw new Error('Could not get download link');
                const { download_url } = await resp.json();
                const a2 = document.createElement('a');
                a2.href = download_url;
                a2.target = '_blank';
                a2.rel = 'noopener noreferrer';
                a2.download = params.row.filename;
                document.body.appendChild(a2);
                a2.click();
                a2.remove();
                return;
              } catch (err) {
                console.error('Fallback download failed', err);
                throw err;
              }
            } catch (err) {
              console.error('Download failed', err);
            }
          }}>
            <GetAppIcon />
          </IconButton>
          <IconButton color="error" onClick={(e: React.MouseEvent<HTMLButtonElement>) => { (e.currentTarget as HTMLElement).blur(); setDeleteTarget({ id: params.row.id, filename: params.row.filename }); setDeleteDialogOpen(true); }}>
            <DeleteIcon />
          </IconButton>
          {params.row.status === 'delete_failed' && (
            <Button variant="outlined" size="small" onClick={() => { (document.activeElement as HTMLElement)?.blur(); handleRetryDelete(params.row.id); }} sx={{ ml: 1 }}>
              Retry Delete
            </Button>
          )}
        </>
      )
    }
  ];

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    try {
      const resp = await authenticatedFetch(`/files/${deleteTarget.id}?delete_s3=${deleteFromS3}`, { method: 'DELETE' });
      if (!resp.ok) throw new Error('Delete failed');
      setDeleteDialogOpen(false);
      setDeleteTarget(null);
      setDeleteFromS3(false);
      await refresh();
    } catch (err) {
      console.error('Delete failed', err);
    }
  };

  const handleRetryDelete = async (id: number) => {
    try {
      await retryDeleteFile(id);
      await refresh();
    } catch (err) {
      console.error('retry delete failed', err);
    }
  }

  const openSummary = async (row: CSVFileRecord) => {
    setSummaryTarget({ id: row.id, filename: row.filename });
    setSummaryDialogOpen(true);
    setSummaryLoading(true);
    setSummaryError(null);
    setSummaryData(null);

    try {
      const resp = await authenticatedFetch(`/files/${row.id}/summary`);
      if (!resp.ok) {
        const txt = await resp.text();
        throw new Error(txt || 'Failed to fetch summary status');
      }
      const body = await resp.json();
      if (body.exists) {
        // fetch the presigned summary JSON
        const r = await fetch(body.summary_url);
        if (!r.ok) throw new Error('Failed to download summary JSON');
        const json = await r.json();
        setSummaryData(json);
        setSummaryLoading(false);
        return;
      }

      // If summary does not exist, trigger parse and poll
      const trigger = await authenticatedFetch(`/files/${row.id}/trigger-parse`, { method: 'POST' });
      if (!trigger.ok) {
        const txt = await trigger.text();
        throw new Error(txt || 'Failed to trigger parse');
      }
      // If the server is not configured to invoke the parser lambda it will
      // return { invoked: false, reason: '...' }. Respect that and show a
      // friendly message instead of continuously polling.
      let triggerBody: any = null;
      try { triggerBody = await trigger.json(); } catch (e) { triggerBody = null; }
      if (triggerBody && triggerBody.invoked === false) {
        setSummaryError(triggerBody.reason || 'Server is not configured to parse files automatically.');
        setSummaryLoading(false);
        return;
      }

      // Poll for the summary to appear
      const maxAttempts = 15;
      const delayMs = 2000;
      let found = false;
      for (let attempt = 0; attempt < maxAttempts; attempt++) {
        await new Promise((res) => setTimeout(res, delayMs));
        const p = await authenticatedFetch(`/files/${row.id}/summary`);
        if (!p.ok) continue;
        const pb = await p.json();
        if (pb.exists) {
          const r2 = await fetch(pb.summary_url);
          if (!r2.ok) throw new Error('Failed to download summary JSON');
          const json2 = await r2.json();
          setSummaryData(json2);
          found = true;
          break;
        }
      }

      if (!found) {
        setSummaryError('Summary not yet available. Try again later.');
      }
    } catch (err: any) {
      setSummaryError(err?.message || 'Error fetching summary');
    } finally {
      setSummaryLoading(false);
    }
  };

  const closeSummary = () => {
    setSummaryDialogOpen(false);
    setSummaryTarget(null);
    setSummaryData(null);
    setSummaryError(null);
    setSummaryLoading(false);
  };

  return (
    <Box sx={{ p: 4, bgcolor: 'white', borderRadius: 2, boxShadow: 2 }}>
      {errorMessage && (
        <Alert severity="error" sx={{ mb: 3 }}>{errorMessage}</Alert>
      )}

      <Box sx={{ display: 'flex', flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Typography variant="h5" sx={{ fontWeight: 'bold', color: '#1976d2' }}>
          Database CSV Records
        </Typography>
        <Button
          variant="contained"
          component="label"
          startIcon={uploading ? <CircularProgress size={20} color="inherit" /> : <CloudUploadIcon />}
          disabled={uploading}
        >
          {uploading ? 'Uploading...' : 'Upload CSV'}
          <input type="file" accept=".csv" hidden onChange={onFileChange} />
        </Button>
        {uploading && uploadProgress > 0 && (
          <Box sx={{ width: 200, ml: 2 }}>
            <LinearProgress variant="determinate" value={uploadProgress} />
          </Box>
        )}
      </Box>

      <Dialog open={deleteDialogOpen} onClose={() => setDeleteDialogOpen(false)}>
        <DialogTitle>Confirm deletion</DialogTitle>
        <DialogContent>
          <Typography>Are you sure you want to delete {deleteTarget?.filename}?</Typography>
          <FormControlLabel
            control={<Checkbox checked={deleteFromS3} onChange={(e) => setDeleteFromS3(e.target.checked)} />}
            label="Also delete the file from cloud storage (S3)"
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteDialogOpen(false)}>Cancel</Button>
          <Button color="error" onClick={confirmDelete}>Delete</Button>
        </DialogActions>
      </Dialog>

      <Dialog open={summaryDialogOpen} onClose={closeSummary} fullWidth maxWidth="md">
        <DialogTitle>{summaryTarget?.filename || 'Summary'}</DialogTitle>
        <DialogContent>
          {summaryLoading && (
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
              <CircularProgress />
              <Typography>Processing file and waiting for summary...</Typography>
            </Box>
          )}

          {summaryError && (
            <Alert severity="warning" sx={{ mb: 2 }}>{summaryError}</Alert>
          )}

          {summaryData && (
            <Box sx={{ mt: 1 }}>
              <Typography variant="subtitle2">Summary JSON</Typography>
              <Box component="pre" sx={{ bgcolor: '#f5f5f5', p: 2, borderRadius: 1, maxHeight: 400, overflow: 'auto' }}>
                {JSON.stringify(summaryData, null, 2)}
              </Box>
            </Box>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => {
            if (summaryTarget) openSummary({ id: summaryTarget.id, filename: summaryTarget.filename } as any);
          }}>Refresh</Button>
          <Button onClick={closeSummary}>Close</Button>
        </DialogActions>
      </Dialog>

      <Box sx={{ height: 400, width: '100%' }}>
        <DataGrid
          rows={fileList}
          columns={tableColumns}
          loading={loading}
          pageSizeOptions={[]}
          initialState={{ pagination: { paginationModel: { page: 0, pageSize: 5 } } }}
        />
      </Box>
    </Box>
  );
}

export default CSVTable;