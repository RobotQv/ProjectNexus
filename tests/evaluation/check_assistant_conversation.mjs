// UI回归使用拦截的合成HTTP响应，不调用模型或读取业务库。
// node tests/evaluation/check_assistant_conversation.mjs <playwright模块路径> [Vite URL]
import { createRequire } from 'node:module'
import fs from 'node:fs/promises'
import path from 'node:path'
import assert from 'node:assert/strict'

const { chromium } = createRequire(import.meta.url)(process.argv[2])
const base = process.argv[3] || 'http://127.0.0.1:18769'
assert.ok(['127.0.0.1', 'localhost'].includes(new URL(base).hostname))
const output = path.resolve('artifacts/assistant_conversation')
await fs.mkdir(output, { recursive: true })
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const results = []
const errors = []
const longAnswer = Array.from({ length: 50 }, (_, i) => `第${i + 1}条：这是用于滚动验收的合成回答，不代表真实模型输出。`).join('\n')

async function eventually(check, message) {
  const deadline = Date.now() + 10000
  while (Date.now() < deadline) {
    if (await check()) return
    await new Promise(resolve => setTimeout(resolve, 50))
  }
  throw new Error(message)
}

async function scenario(width, task = false) {
  const page = await browser.newPage({ viewport: { width, height: 844 } })
  page.on('pageerror', error => errors.push(error.message))
  let run = null
  let release
  let runCount = 0
  await page.route('**/api/v1/**', async route => {
    const request = route.request()
    const url = new URL(request.url())
    const reply = (body, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
    if (url.pathname.endsWith('/assistant/messages')) {
      const body = request.postDataJSON()
      run = { key: body.request_key, id: ++runCount, events: 24, status: 'running' }
      await new Promise(resolve => { release = resolve })
      if (run.status === 'failed') return reply({ error: { code: 'llm_timeout', message: '合成超时' } }, 504)
      run.status = 'succeeded'
      return reply({ answer: longAnswer, outcome: 'answered', facts: [], evidence: [], routes: [], suggestions: [], model_id: 'ui-test' })
    }
    if (url.pathname.endsWith('/assistant/progress')) {
      if (!run || run.key !== url.searchParams.get('request_key')) return reply({ error: { code: 'not_found' } }, 404)
      return reply({ run_id: run.id, status: run.status, terminal: run.status !== 'running', elapsed_ms: 3600,
        error: run.status === 'failed' ? '合成超时' : null,
        events: Array.from({ length: run.events }, (_, i) => ({ seq: i + 1, message: `合成执行阶段 ${i + 1}`, state: run.status === 'failed' ? 'failed' : run.status === 'running' ? 'running' : 'completed', elapsed_ms: i * 100 })) })
    }
    return reply({ items: [], total: 0, limit: 200, offset: 0 })
  })
  await page.goto(`${base}/#/${task ? 'tasks' : 'assistant'}`, { waitUntil: 'networkidle' })
  await page.evaluate(async () => {
    const { session } = await import('/src/stores/session.js')
    session.mode = 'live'; session.token = 'synthetic-ui-token'; session.projectId = 1
  })
  // 切换数据源会按项目key重建路由组件，要在新工作区加载后再打开任务弹窗。
  await page.waitForFunction(async () => (await import('/src/stores/workspace.js')).workspace.loaded)
  if (task) await page.getByRole('button', { name: '✦ AI 助理', exact: true }).click()
  const shell = page.locator('.assistant-shell')
  const viewport = page.locator('.assistant-scroll')
  const height = await shell.evaluate(e => e.getBoundingClientRect().height)
  assert.ok(height >= (task ? 500 : 440), '空对话需提供充分的初始空间')
  const bottomGap = () => viewport.evaluate(e => e.scrollHeight - e.clientHeight - e.scrollTop)
  const stableHeight = async () => assert.ok(Math.abs(await shell.evaluate(e => e.getBoundingClientRect().height) - height) < 1, '内容不能撑大视窗')
  const send = async value => {
    await page.locator('.composer input').fill(value)
    await page.getByRole('button', { name: '发送', exact: true }).click()
    await eventually(() => page.locator('.assistant-progress li').count().then(n => n >= 24), '执行阶段应出现')
  }
  await send('合成问题一')
  await eventually(() => bottomGap().then(g => g < 3), '阶段输出应自动跟随到底部')
  assert.equal(await page.locator('.assistant-progress details').evaluate(e => e.open), true)
  await stableHeight()
  await page.locator('.assistant-progress summary').click()
  run.events = 40
  await eventually(() => page.locator('.assistant-progress li').count().then(n => n === 40), '新阶段应更新')
  assert.equal(await page.locator('.assistant-progress details').evaluate(e => e.open), false, '轮询不能覆盖手动折叠状态')
  await page.locator('.assistant-progress summary').click()
  if (await page.locator('.latest-message').isVisible()) await page.locator('.latest-message').click()
  await eventually(() => bottomGap().then(g => g < 3), '长阶段列表仍跟随底部')
  await viewport.evaluate(e => { e.scrollTop = 0 })
  await page.locator('.latest-message').waitFor()
  run.events = 45
  await eventually(() => page.locator('.assistant-progress li').count().then(n => n === 45), '阶段仍在后台更新')
  assert.ok(await viewport.evaluate(e => e.scrollTop) < 3, '手动查看历史时不抢滚动位置')
  await page.locator('.latest-message').click()
  await eventually(() => bottomGap().then(g => g < 3), '回到最新按钮有效')
  release()
  await page.locator('.msg.ai').waitFor()
  await eventually(() => page.locator('.assistant-progress details').evaluate(e => !e.open), '回答出现后折叠阶段')
  await eventually(() => bottomGap().then(g => g < 3), '正式长回答仍定位底部')
  await stableHeight()
  await page.locator('.assistant-progress summary').click()
  assert.equal(await page.locator('.assistant-progress details').evaluate(e => e.open), true, '完成后仍可手动展开')
  await page.locator('.assistant-progress summary').click()
  if (!task && width <= 1080) {
    const evidenceBottom = await page.locator('.assistant-evidence').evaluate(e => e.getBoundingClientRect().bottom)
    const conversationTop = await page.locator('.assistant-conversation').evaluate(e => e.getBoundingClientRect().top)
    assert.ok(evidenceBottom <= conversationTop, '窄屏保留依据在上、对话在下')
  }
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), '无横向溢出')
  await page.screenshot({ path: path.join(output, `${task ? 'task' : 'project'}-${width}.png`), fullPage: true })
  // 第二轮重新展开，失败保留错误和原输入，不误当成正式回答折叠。
  await send('合成失败问题')
  assert.equal(await page.locator('.assistant-progress details').evaluate(e => e.open), true)
  run.status = 'failed'; release()
  await eventually(() => page.locator('.composer input').inputValue().then(v => v === '合成失败问题'), '失败应恢复输入')
  assert.equal(await page.locator('.assistant-progress details').evaluate(e => e.open), true)
  await stableHeight()
  if (task) {
    const bounds = await page.locator('.modal').boundingBox()
    assert.ok(bounds.y >= 0 && bounds.y + bounds.height <= 844, '任务弹窗不超出视口')
    assert.equal(await page.locator('.modal-body').evaluate(e => e.scrollTop), 0, '仅对话内容滚动')
  }
  results.push({ width, task, height, passed: true })
  await page.close()
}

try {
  for (const width of [1440, 390]) {
    await scenario(width)
    await scenario(width, true)
  }
  assert.deepEqual(errors, [])
  await fs.writeFile(path.join(output, 'results.json'), JSON.stringify({ results, errors }, null, 2))
  console.log('PASS: both assistants desktop/mobile, fixed height, progress follow, history scrolling, answer collapse, manual reopen, retry/failure')
} finally {
  await browser.close()
}
