import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Kept separate from vite.config.js on purpose: Vitest prefers vitest.config.js
// over vite.config.js, so the dev-server proxy config stays out of the test run
// (tests never hit a real backend — every fetch is stubbed).
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./vitest.setup.js'],
    include: ['src/**/*.{test,spec}.{js,jsx}'],
    restoreMocks: true,
    unstubEnvs: true,
    unstubGlobals: true,
  },
});
