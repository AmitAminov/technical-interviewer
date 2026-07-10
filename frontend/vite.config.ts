import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

// Dev server proxies REST + WebSocket traffic to the FastAPI backend on 8011
// (DESIGN.md §0). Production build lands in dist/ and is served by the backend.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8011',
      '/ws': { target: 'ws://127.0.0.1:8011', ws: true },
    },
  },
  build: { outDir: 'dist' },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/__tests__/setupTests.ts'],
    css: false,
    globals: false,
    // CI/Windows jsdom startup is slow; user-event driven page tests need headroom.
    testTimeout: 30000,
    hookTimeout: 30000,
  },
});
