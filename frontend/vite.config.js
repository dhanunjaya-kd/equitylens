import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Build output goes straight into backend/static so `python run.py` serves it.
export default defineConfig({
  plugins: [react()],
  build: { outDir: '../backend/static', emptyOutDir: true },
  server: { port: 5174, proxy: { '/api': 'http://localhost:8600' } },
})
