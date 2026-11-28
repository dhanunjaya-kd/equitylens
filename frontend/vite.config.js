import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Build output goes straight into backend/static so `python run.py` serves it.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: '../backend/static',
    emptyOutDir: true,
    rollupOptions: {
      output: {
        // React in its own small file. (The old object form let React land inside the charts file, so every
        // app open had to download and parse ~750 KB of chart code before the first screen.)
        manualChunks(id) {
          if (!id.includes('node_modules')) return undefined
          if (/node_modules\/(react|react-dom|scheduler)\//.test(id)) return 'react-vendor'
          if (id.includes('lightweight-charts') || id.includes('fancy-canvas')) return 'tvcharts'
          if (/node_modules\/(recharts|d3-|victory-vendor|internmap|decimal\.js-light|recharts-scale|react-smooth|lodash|eventemitter3|tiny-invariant|clsx|react-is|prop-types|fast-equals|dom-helpers|react-transition-group)/.test(id)) return 'charts'
          if (id.includes('/marked/')) return 'markdown'
          return undefined
        },
      },
    },
  },
  server: { port: 5174, proxy: { '/api': 'http://localhost:8600' } },
})
