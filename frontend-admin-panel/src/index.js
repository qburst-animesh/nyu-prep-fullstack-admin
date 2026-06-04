import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './index.css'; // Global styles if you have them
// Import the AWS Amplify library
import { Amplify } from 'aws-amplify';

// Configure Amplify with your AWS Cognito details
Amplify.configure({
  Auth: {
    Cognito: {
      userPoolId: process.env.REACT_APP_COGNITO_USER_POOL_ID,      
      userPoolClientId: process.env.REACT_APP_COGNITO_CLIENT_ID, 
    }
  }
});

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
