import { defineConfig } from '@playwright/test'

/**
 * Drives the real built frontend served by the FastAPI backend — the same
 * arrangement Render runs — so the browser-only failure modes (missing request
 * headers, downloads, client-side routing) are actually exercised.
 *
 * Start the backend before running:
 *   cd backend && python -m uvicorn main:app --port 8153
 */
export default defineConfig({
  testDir: './e2e',
  timeout: 180000,
  expect: { timeout: 20000 },
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: process.env.E2E_BASE_URL || 'http://127.0.0.1:8153',
    headless: true,
    acceptDownloads: true,
    screenshot: 'only-on-failure',
  },
})
