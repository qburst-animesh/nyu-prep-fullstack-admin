import React, { useState } from 'react';
// Import Material-UI structural and design components
import { Box, Typography, Button, Stack, IconButton, Modal, TextField } from '@mui/material';
// Import standard MUI DataGrid for tables
import { DataGrid } from '@mui/x-data-grid';
// Import icons
import DeleteIcon from '@mui/icons-material/Delete';
import CloudUploadIcon from '@mui/icons-material/CloudUpload';
const API_BASE_URL = 'http://localhost:8000/api/v1';
export default function CSVTable() {
  // 1. STATE: This is where React stores our table data. 
  // If this array changes, React automatically updates what you see on the screen.
  const [fileList, setFileList] = useState([
    { id: 1, name: 'q1_revenue.csv', size: '1.2 MB', rows: 450 },
    { id: 2, name: 'active_users.csv', size: '420 KB', rows: 1200 }
  ]);

  // 2. STATE: Controls whether our "Add File" pop-up window is open (true) or closed (false)
  const [isModalOpen, setIsModalOpen] = useState(false);

  // 3. STATE: Holds the temporary text typed into our form fields
  const [inputName, setInputName] = useState('');
  const [inputSize, setInputSize] = useState('');

  // CRUD - DELETE: Filters out the file with the matching ID
  const handleDeleteFile = (idToDelete) => {
    const updatedList = fileList.filter(file => file.id !== idToDelete);
    setFileList(updatedList);
  };

  // CRUD - CREATE: Takes the form text and appends a new object to our state
  const handleFormSubmit = (event) => {
    event.preventDefault(); // Prevents the browser from reloading the page
    if (!inputName || !inputSize) return; // Basic validation

    const newFile = {
      id: fileList.length + 1, // Simple incremental ID generation
      name: inputName,
      size: inputSize,
      rows: Math.floor(Math.random() * 500) + 50 // Generates a random row count for fun
    };

    setFileList([...fileList, newFile]); // Adds newFile to our existing array
    setIsModalOpen(false); // Closes the pop-up window
    setInputName(''); // Clears out the form inputs
    setInputSize('');
  };

  // MUI Table Column Configuration
  const tableColumns = [
    { field: 'id', headerName: 'ID', width: 80 },
    { field: 'name', headerName: 'File Name', width: 250 },
    { field: 'size', headerName: 'File Size', width: 150 },
    { field: 'rows', headerName: 'Total Rows', type: 'number', width: 150 },
    {
      field: 'actions',
      headerName: 'Actions',
      width: 120,
      renderCell: (cellData) => (
        <IconButton color="error" onClick={() => handleDeleteFile(cellData.id)}>
          <DeleteIcon />
        </IconButton>
      )
    }
  ];

  return (
    <Box sx={{ p: 4, bgcolor: 'white', borderRadius: 2, boxShadow: 2 }}>
      
      {/* Header section with Title and Add Button */}
      <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 3 }}>
        <Typography variant="h5" sx={{ fontWeight: 'bold', color: '#1976d2', margin: 'auto' }}>
          Database CSV Records
        </Typography>
        <Button 
          variant="contained" 
          startIcon={<CloudUploadIcon />} 
          onClick={() => setIsModalOpen(true)}
        >
          Add New File
        </Button>
      </Stack>

      {/* MUI DataGrid Component */}
      <Box sx={{ height: 350, width: '100%' }}>
        <DataGrid 
          rows={fileList} 
          columns={tableColumns} 
          pageSizeOptions={[5]}
          initialState={{ pagination: { paginationModel: { page: 0, pageSize: 5 } } }}
        />
      </Box>

      {/* Pop-up Form Modal */}
      <Modal open={isModalOpen} onClose={() => setIsModalOpen(false)}>
        <Box sx={{
          position: 'absolute', top: '50%', left: '50%', transform: 'translate(-50%, -50%)',
          width: 400, bgcolor: 'background.paper', p: 4, borderRadius: 2, boxShadow: 24
        }}>
          <Typography variant="h6" sx={{ mb: 2, fontWeight: 'bold' }}>Mock Database Insert</Typography>
          
          <form onSubmit={handleFormSubmit}>
            <Stack spacing={3}>
              <TextField 
                label="File Name" 
                fullWidth 
                value={inputName} 
                onChange={(e) => setInputName(e.target.value)} 
              />
              <TextField 
                label="File Size (e.g. 2 MB)" 
                fullWidth 
                value={inputSize} 
                onChange={(e) => setInputSize(e.target.value)} 
              />
              <Button type="submit" variant="contained" color="success" fullWidth>
                Save to Table State
              </Button>
            </Stack>
          </form>
        </Box>
      </Modal>

    </Box>
  );
}