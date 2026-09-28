import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// The built app is served by the gateway (frontend/serve.py) on the user side at
// /user/chat, so assets must resolve under that prefix. In `npm run dev`, API calls
// (/svc, /api) are proxied to the gateway's user side (RAILSENSE_USER_PORT, default 3000).
export default defineConfig({
  base: '/user/chat/',
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/svc': `http://localhost:${process.env.RAILSENSE_USER_PORT || 3000}`,
      '/api': `http://localhost:${process.env.RAILSENSE_USER_PORT || 3000}`,
    },
  },
})
