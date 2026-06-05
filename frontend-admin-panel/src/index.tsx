import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './index.css';
import { Amplify } from 'aws-amplify';
import { logger } from './utils/apiFetch';

const userPoolId = process.env.REACT_APP_COGNITO_USER_POOL_ID;
const userPoolClientId = process.env.REACT_APP_COGNITO_CLIENT_ID;

if (!userPoolId || !userPoolClientId) {
  logger.error('CRITICAL: AWS Cognito environment infrastructure strings missing inside .env context configurations!');
}

Amplify.configure({
  Auth: {
    Cognito: {
      userPoolId: userPoolId || '',
      userPoolClientId: userPoolClientId || '',
    }
  }
});

const rootElement = document.getElementById('root');
if (!rootElement) {
  throw new Error('Fatal: Failed to target system root node layout entry handle DOM element.');
}

const root = ReactDOM.createRoot(rootElement);
root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);