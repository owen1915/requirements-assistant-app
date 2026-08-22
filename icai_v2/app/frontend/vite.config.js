import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 3002 / 8010 so the Studio and the UI prototype (3001 / 8000) can run together —
// comparing what the pipeline induces against what the evaluator does with it is
// the normal working loop.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 3002,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://localhost:8010',
        changeOrigin: true,
      },
    },
  },
})
