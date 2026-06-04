import React from 'react';
import { Authenticator } from '@aws-amplify/ui-react';
import '@aws-amplify/ui-react/styles.css';
import { AppBar, Toolbar, Typography, Button, Container, Box } from '@mui/material';
import CSVTable from './CSVTable'; // Ensure exact case sensitivity

// Explicitly defining the sign-up fields to match your Cognito schema requirement
const customFormFields = {
  signUp: {
    // This tells Amplify to map the text box value specifically to the "emails" key
    email: {
      order: 1,
      isRequired: true,
      label: 'Email Address',
      placeholder: 'Enter your email',
      name: 'email' // FIXED: Changed 'emails' to 'email' to match Cognito standards
    },
    username: { order: 2 },
    password: { order: 3 },
    confirm_password: { order: 4 }
  }
};

export default function App() {
  return (
    <Authenticator formFields={customFormFields}>
      {({ signOut, user }) => (
        <Box sx={{ bgcolor: '#f4f6f8', minHeight: '100vh' }}>
          <AppBar position="static" color="primary">
            <Toolbar>
              <Typography variant="h6" sx={{ flexGrow: 1, fontWeight: 'bold' }}>
                Admin Panel Dashboard
              </Typography>
              <Typography variant="body1" sx={{ mr: 3 }}>
                User: <strong>{user?.username}</strong>
              </Typography>
              <Button variant="contained" color="error" onClick={signOut}>
                Sign Out
              </Button>
            </Toolbar>
          </AppBar>
          <Container maxWidth="lg" sx={{ mt: 6 }}>
            <CSVTable />
          </Container>
        </Box>
      )}
    </Authenticator>
  );
}
