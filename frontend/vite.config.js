import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    open: true,
    proxy: {
      // Proxy all /api and /avatars requests to the FastAPI backend.
      // This makes the browser see a single origin (localhost:3000) so
      // httpOnly cookies work without cross-origin complications in dev.
      '/api': {
        target: 'http://localhost:8001',
        changeOrigin: true,
        ws: true,  // also proxy WebSocket upgrade requests on /api/*
      },
      '/avatars': {
        target: 'http://localhost:8001',
        changeOrigin: true,
      },
    },
  },
})
