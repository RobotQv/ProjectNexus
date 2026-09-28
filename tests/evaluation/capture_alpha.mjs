// 本机真实 UI 验证。Playwright 模块路径由命令行传入，不上传截图或本地凭证。
import { createRequire } from 'node:module'
import fs from 'node:fs/promises'
import path from 'node:path'
import assert from 'node:assert/strict'

const require = createRequire(import.meta.url)
const { chromium } = require(process.argv[2])
const output = path.resolve('artifacts/alpha_handoff/screenshots')
await fs.mkdir(output, { recursive: true })
const credentials = JSON.parse(await fs.readFile('data/alpha-demo/local-credentials.json', 'utf8'))
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
const errors = []
page.on('pageerror', error => errors.push(error.message))
const results = []
let completed = false
try {
  await page.goto('http://127.0.0.1:18765', { waitUntil: 'networkidle' })
  await page.locator('input[type=text]').fill('demo1')
  await page.locator('input[type=password]').fill(credentials.password)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await page.locator('.badge-live').waitFor({ timeout: 15000 })
  for (const name of ['overview', 'tasks', 'documents', 'assistant', 'suggestions', 'dependencies']) {
    await page.locator(`a[href="#/${name}"]`).click()
    await page.waitForTimeout(700)
    assert.equal(await page.locator('.title').count() > 0, true)
    await page.screenshot({ path: path.join(output, `${name}-desktop.png`), fullPage: true })
    results.push({ page: name, viewport: 'desktop', status: 'rendered' })
  }
  await page.locator('a[href="#/assistant"]').click()
  await page.locator('.composer input').fill('TASK-3 现在进度怎样？请依据当前正式记录回答。')
  await page.getByRole('button', { name: '发送', exact: true }).click()
  await page.getByRole('status').waitFor({ timeout: 15000 })
  await page.screenshot({ path: path.join(output, 'assistant-progress.png'), fullPage: true })
  await Promise.race([
    page.locator('.msg.ai').waitFor({ timeout: 150000 }),
    page.getByText('再次发送会创建新请求。', { exact: false }).waitFor({ timeout: 150000 }).then(async () => {
      await page.screenshot({ path: path.join(output, 'assistant-failure.png'), fullPage: true })
      throw new Error('Actual assistant request failed; failure screenshot retained')
    }),
  ])
  await page.screenshot({ path: path.join(output, 'assistant-answer.png'), fullPage: true })
  await page.getByRole('button', { name: '查看版本历史' }).first().click()
  await page.getByText('字段变化与完整快照').first().waitFor({ timeout: 10000 })
  await page.getByText('字段变化与完整快照').first().click()
  await page.screenshot({ path: path.join(output, 'assistant-history.png'), fullPage: true })
  await page.keyboard.press('Escape')
  // 弹窗可能没有 Escape 行为，关闭按钮若仍存在则正常点击。
  const close = page.getByRole('button', { name: '关闭', exact: true })
  if (await close.count()) await close.last().click()
  await page.setViewportSize({ width: 390, height: 844 })
  await page.waitForTimeout(400)
  const dimensions = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth }))
  assert.ok(dimensions.scroll <= dimensions.client + 1, JSON.stringify(dimensions))
  await page.screenshot({ path: path.join(output, 'assistant-mobile.png'), fullPage: true })
  results.push({ page: 'assistant', viewport: '390x844', horizontalOverflow: false })
  assert.deepEqual(errors, [])
  completed = true
  console.log('Browser checks passed: six desktop pages, actual progress, answer/history and mobile width')
} catch (error) {
  results.push({ stage: 'failure', message: error.message })
  await page.screenshot({ path: path.join(output, 'browser-failure.png'), fullPage: true })
  throw error
} finally {
  await fs.writeFile(path.join(output, 'browser-results.json'), JSON.stringify({ status: completed ? 'passed' : 'failed', results, errors }, null, 2))
  await browser.close()
}
