import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 3000
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) return;
          if (id.includes('@aws-amplify/ui-react')) return 'amplify-react-ui';
          if (id.includes('@aws-amplify/ui')) return 'amplify-ui-core';
          if (id.includes('aws-amplify') || id.includes('@aws-amplify')) return 'amplify-core';
          if (id.includes('@mui/x-data-grid')) return 'mui-grid';
          if (id.includes('@mui/material') || id.includes('@mui/icons-material') || id.includes('@emotion')) return 'mui-core';
          return;
        },
      },
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/App.test.tsx', // using the test file or a setup file to extend matchers
  },
});