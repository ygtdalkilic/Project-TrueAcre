import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// In development the API runs on its own port; the proxy keeps the browser on one origin, so
// cookies and the same-origin check behave exactly as in production. Set API_PORT to override.
const apiPort = process.env.API_PORT ?? '8000'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { '/api': `http://localhost:${apiPort}` },
  },
})
