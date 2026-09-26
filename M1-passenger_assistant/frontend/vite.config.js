import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// The built app is served by the gateway (frontend/serve.py) at
// http://localhost:3000/user/chat, so assets must resolve under that prefix.
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
  },
})
