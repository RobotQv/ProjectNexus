// 布局回归：连接以 VITE_DEFAULT_MODE=demo 启动的 Vite，不调用模型或业务后端。
// node tests/evaluation/check_responsive_layout.mjs <playwright模块路径> [本地URL]
import { createRequire } from 'node:module'
import fs from 'node:fs/promises'
import path from 'node:path'
import assert from 'node:assert/strict'

const { chromium } = createRequire(import.meta.url)(process.argv[2])
const base = process.argv[3] || 'http://127.0.0.1:18766'
assert.ok(['127.0.0.1', 'localhost'].includes(new URL(base).hostname))
const output = path.resolve('artifacts/ui_layout_fix')
await fs.mkdir(output, { recursive: true })
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
const errors = []
const results = []
page.on('pageerror', error => errors.push(error.message))
const rect = locator => locator.evaluate(element => {
  const { top, bottom, left, right, height } = element.getBoundingClientRect()
  return { top, bottom, left, right, height }
})
async function checkAssistant(width, populated) {
  await page.setViewportSize({ width, height: 844 })
  // 跨过抽屉断点时等待现有滑入/滑出过渡，避免截到动画中间态。
  await page.waitForTimeout(250)
  const facts = await rect(page.locator('.assistant-evidence'))
  const chat = await rect(page.locator('.assistant-conversation'))
  if (width <= 1080) assert.ok(facts.bottom <= chat.top, '窄屏事实依据应完整位于对话框上方')
  else {
    assert.ok(chat.right <= facts.left, '桌面对话左侧、事实右侧')
    assert.ok(Math.abs(chat.top - facts.top) < 1, '桌面双栏顶部对齐')
  }
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), '不能横向溢出')
  if (width <= 820) assert.ok((await rect(page.locator('.sidebar'))).right <= 1, '未打开的抽屉不能遮挡页面')
  results.push({ page: 'assistant', width, populated, facts, chat })
}
try {
  await page.goto(`${base}/#/assistant`, { waitUntil: 'networkidle' })
  await page.locator('.assistant-layout').waitFor()
  for (const width of [390, 768, 1024, 1440]) await checkAssistant(width, false)
  await page.locator('.composer input').fill('支付那块进度怎样，为什么卡住？')
  await page.getByRole('button', { name: '发送', exact: true }).click()
  await page.locator('.msg.ai').waitFor()
  for (const width of [1440, 1024, 768, 390]) await checkAssistant(width, true)
  await page.screenshot({ path: path.join(output, 'assistant-mobile.png'), fullPage: true })
  // 窄屏导航仍作为一屏高的抽屉，不被整页侧栏背景规则撑长。
  await page.getByRole('button', { name: '菜单', exact: true }).click()
  await page.waitForTimeout(250)
  const drawer = await rect(page.locator('.sidebar'))
  assert.equal(drawer.top, 0)
  assert.equal(drawer.height, 844)
  await page.locator('a[href="#/suggestions"]').click()
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.locator('.sg').first().waitFor()
  const sidebar = await rect(page.locator('.sidebar'))
  const app = await rect(page.locator('.app'))
  assert.ok(app.height > 900, '验收页应为超过一屏的真实建议列表')
  assert.equal(sidebar.height, app.height, '深色背景必须随整页延伸')
  await page.screenshot({ path: path.join(output, 'suggestions-desktop.png'), fullPage: true })
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight))
  const sticky = await rect(page.locator('.sidebar-inner'))
  assert.ok(Math.abs(sticky.top) < 1)
  assert.equal(sticky.height, 900)
  assert.equal(await page.evaluate(() => getComputedStyle(document.elementFromPoint(4, innerHeight - 4).closest('.sidebar')).backgroundColor), 'rgb(22, 35, 47)')
  await page.screenshot({ path: path.join(output, 'suggestions-scrolled.png') })
  results.push({ page: 'suggestions', sidebar, app, sticky, bottomBackground: 'covered' })
  assert.deepEqual(errors, [])
  await fs.writeFile(path.join(output, 'results.json'), JSON.stringify({ status: 'passed', results, errors }, null, 2))
  console.log('PASS: empty/populated assistant at four widths; mobile drawer; long-page sidebar and scrolled navigation')
} finally {
  await browser.close()
}
