import React from 'react';
import { Authenticator } from '@aws-amplify/ui-react';
import '@aws-amplify/ui-react/styles.css';
import { AppBar, Toolbar, Typography, Button, Container, Box } from '@mui/material';
import CSVTable from './components/CSVTable';

const customFormFields = {
  signUp: {
    email: {
      order: 1,
      isRequired: true,
      label: 'Email Address',
      placeholder: 'Enter your email',
      name: 'email'
    },
    username: { order: 2 },
    password: { order: 3 },
    confirm_password: { order: 4 }
  }
};

interface AuthChildrenProps {
  signOut?: () => void;
  user?: Record<string, any>;
}

export default function App() {
  return (
    <Authenticator formFields={customFormFields}>
      {({ signOut, user }: AuthChildrenProps) => (
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