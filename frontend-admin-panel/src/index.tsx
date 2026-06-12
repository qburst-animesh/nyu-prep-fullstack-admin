import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './index.css';
import { Amplify } from 'aws-amplify';
import { logger } from './utils/apiFetch';

const userPoolId = import.meta.env.VITE_COGNITO_USER_POOL_ID as string | undefined;
const userPoolClientId = import.meta.env.VITE_COGNITO_CLIENT_ID as string | undefined;

const authEnabled = Boolean(userPoolId && userPoolClientId);

if (!authEnabled) {
  logger.warn('AWS Cognito env vars missing — running without authentication (local dev).');
} else {
  Amplify.configure({
    Auth: {
      Cognito: {
        userPoolId: userPoolId || '',
        userPoolClientId: userPoolClientId || ''
      }
    }
  });
}

const rootElement = document.getElementById('root');
if (!rootElement) {
  throw new Error('Fatal: Failed to target system root node layout entry handle DOM element.');
}

const root = ReactDOM.createRoot(rootElement);
root.render(
  <React.StrictMode>
    <App authEnabled={authEnabled} />
  </React.StrictMode>
);