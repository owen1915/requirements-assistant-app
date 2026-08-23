import { test, expect } from '@playwright/test'
import path from 'path'
import fs from 'fs'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const SAMPLES = path.resolve(__dirname, '../../samples')
const FIXTURE = path.resolve(__dirname, 'fixtures')

const ACCESS_CODE = process.env.E2E_ACCESS_CODE || '1234'

// A deliberately small requirements file — this suite tests the UI flow, not
// analysis quality, so there is no reason to pay for ten model calls per run.
const SMALL_REQS = path.join(FIXTURE, 'two_requirements.txt')

test.beforeAll(() => {
  fs.mkdirSync(FIXTURE, { recursive: true })
  fs.writeFileSync(
    SMALL_REQS,
    '[1]  (Cyber User Need)\n' +
      '  MQ-99 shall be able to complete assigned missions 90% of the time under cyber attack.\n\n' +
      '[1.1]  (Hardened)\n' +
      '  MQ-99 shall be sufficiently hardened from cyber attack.\n',
  )
})

/** Surface browser console errors and failed requests — these are invisible to curl. */
function captureProblems(page) {
  const problems = []
  page.on('console', (m) => {
    if (m.type() === 'error') problems.push(`console.error: ${m.text()}`)
  })
  page.on('pageerror', (e) => problems.push(`pageerror: ${e.message}`))
  page.on('response', (r) => {
    if (r.status() >= 400) problems.push(`HTTP ${r.status()} ${r.url()}`)
  })
  return problems
}

test('access gate rejects a wrong code and accepts the right one', async ({ page }) => {
  const problems = captureProblems(page)
  await page.goto('/')

  await expect(page.getByRole('heading', { name: /access code required/i })).toBeVisible()

  await page.getByLabel(/access code/i).fill('definitely-wrong')
  await page.getByRole('button', { name: /continue/i }).click()
  await expect(page.getByText(/incorrect access code/i)).toBeVisible()

  await page.getByLabel(/access code/i).fill(ACCESS_CODE)
  await page.getByRole('button', { name: /continue/i }).click()

  // Gate opens onto the upload form
  await expect(page.getByRole('heading', { name: /upload requirements/i })).toBeVisible()

  // The 401 from the wrong code is expected; nothing else should have failed.
  const unexpected = problems.filter((p) => !p.includes('401'))
  expect(unexpected, `unexpected browser problems:\n${unexpected.join('\n')}`).toEqual([])
})

test('full flow: upload -> review -> submit -> download both files', async ({ page }) => {
  const problems = captureProblems(page)

  // --- gate ---
  await page.goto('/')
  await page.getByLabel(/access code/i).fill(ACCESS_CODE)
  await page.getByRole('button', { name: /continue/i }).click()
  await expect(page.getByRole('heading', { name: /upload requirements/i })).toBeVisible()

  // --- upload ---
  await page.setInputFiles('#req-file', SMALL_REQS)
  await page.setInputFiles('#ctx-file', path.join(SAMPLES, 'Berserker_Context.txt'))
  await page.getByRole('button', { name: /upload & analyze/i }).click()

  // Analysis is a live model call; give it room.
  await expect(page.getByRole('button', { name: /review solo/i })).toBeVisible({ timeout: 180000 })
  await page.getByRole('button', { name: /review solo/i }).click()

  // --- review ---
  await expect(page.getByRole('heading', { name: /review requirements/i })).toBeVisible()
  const sessionId = (await page.getByText(/Session:/).innerText()).match(/Session:\s*(\w+)/)[1]

  // Accept every violation so the submit button has something to send.
  const acceptButtons = page.locator('button.action-btn.accept')
  const count = await acceptButtons.count()
  expect(count, 'expected at least one violation to review').toBeGreaterThan(0)
  for (let i = 0; i < count; i++) await acceptButtons.nth(i).click()

  // The counter should show everything reviewed. FeedbackControls renders
  // twice (above and below the list), so scope to the first.
  await expect(page.getByText(/100%/).first()).toBeVisible()

  // --- submit ---
  await page.getByRole('button', { name: /submit all feedback/i }).first().click()

  // --- download page ---
  await expect(page.getByRole('heading', { name: /analysis complete/i })).toBeVisible({ timeout: 60000 })
  expect(page.url()).toContain(`/download/${sessionId}`)

  // --- downloads: the regression that window.open() caused ---
  const [docxDownload] = await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('button', { name: /download report/i }).click(),
  ])
  const docxPath = await docxDownload.path()
  expect(docxDownload.suggestedFilename()).toMatch(/\.docx$/)
  const docxBytes = fs.readFileSync(docxPath)
  expect(docxBytes.length).toBeGreaterThan(5000)
  expect(docxBytes.subarray(0, 2).toString()).toBe('PK') // real Office file

  const [jsonDownload] = await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('button', { name: /download feedback/i }).click(),
  ])
  expect(jsonDownload.suggestedFilename()).toMatch(/\.json$/)
  const parsed = JSON.parse(fs.readFileSync(await jsonDownload.path(), 'utf-8'))
  expect(Array.isArray(parsed.requirement_feedback)).toBe(true)
  expect(parsed.requirement_feedback.length).toBeGreaterThan(0)

  expect(problems, `browser problems:\n${problems.join('\n')}`).toEqual([])
})
