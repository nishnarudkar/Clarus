import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Dev server proxies the backend (uvicorn on :8000) so the browser uses one origin,
// exactly like production where FastAPI serves the built frontend.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
      '/ws': { target: 'ws://localhost:8000', ws: true },
    },
  },
})
