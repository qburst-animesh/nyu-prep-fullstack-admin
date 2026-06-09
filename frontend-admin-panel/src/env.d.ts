/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_COGNITO_USER_POOL_ID?: string;
  readonly VITE_COGNITO_CLIENT_ID?: string;
  readonly VITE_LOG_LEVEL?: string;
  // add additional VITE_ variables here as needed
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

// Allow importing CSS and common asset types as side-effect modules
declare module '*.css';
declare module '*.scss';
declare module '*.svg';
declare module '*.png';
declare module '*.jpg';
declare module '*.jpeg';
declare module '*.gif';
