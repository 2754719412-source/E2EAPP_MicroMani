import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { createServer } from 'node:http'
import { readFile, writeFile } from 'node:fs/promises'
import { resolve, extname } from 'node:path'
import { fileURLToPath } from 'node:url'

const repo = fileURLToPath(new URL('../..', import.meta.url))
const output = resolve(repo, 'output/safety-20260911')
const require = createRequire(resolve(repo, 'frontend/package.json'))
const { chromium } = require('playwright')
const result = { blockedRequests: [], pageErrors: [] }
const server = createServer(async (request, response) => {
  const pathname = new URL(request.url, 'http://localhost').pathname
  const asset = pathname.startsWith('/assets/') ? pathname.slice(1) : 'index.html'
  try {
    const body = await readFile(resolve(repo, 'frontend/dist', asset))
    response.writeHead(200, { 'content-type': ({ '.js': 'text/javascript', '.css': 'text/css', '.html': 'text/html' })[extname(asset)] ?? 'application/octet-stream' })
    response.end(body)
  } catch { response.writeHead(404).end() }
})
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
const base = `http://127.0.0.1:${server.address().port}`
let browser
try {
  browser = await chromium.launch({ headless: true, channel: 'msedge' })
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
  // 只允许此静态服务器，所有设备/API HTTP 与 WebSocket 都在发送前拦截。
  await context.route('**/*', route => {
    const url = route.request().url()
    if (!url.startsWith(`${base}/`)) {
      result.blockedRequests.push(url)
      return route.abort()
    }
    if (/\/ModelView-[^/]+\.js/.test(url)) return route.fulfill({ status: 404, body: 'Isolated chunk failure' })
    return route.continue()
  })
  await context.routeWebSocket('**/*', socket => socket.close())
  const page = await context.newPage()
  page.on('pageerror', error => result.pageErrors.push(error.message))
  await page.goto(base, { waitUntil: 'networkidle' })
  const emergency = page.getByRole('button', { name: '全局急停', exact: true })
  await emergency.waitFor()
  assert.equal(await page.getByRole('button', { name: /Safety Off|安全显示测试|模拟危险/ }).count(), 0)
  await page.locator('a[href="/model"]').click()
  await page.getByRole('alert').filter({ hasText: '页面暂时无法显示' }).waitFor()
  await emergency.click()
  await page.getByRole('alert').filter({ hasText: '请使用实体急停' }).waitFor()
  assert.match(await emergency.innerText(), /急停未确认/)
  await page.getByText('Safety LOCK', { exact: true }).first().waitFor()
  assert.equal(await emergency.isEnabled(), true)
  assert.equal(await page.getByRole('button', { name: '确认安全态', exact: true }).isDisabled(), true)
  result.failureVisible = true
  result.emergencyAvailableAfterRouteFailure = true
  await page.screenshot({ path: resolve(output, 'emergency-failed.png') })
  await page.locator('a[href="/settings"]').click()
  await page.getByRole('tab', { name: '运动控制' }).click()
  const disabledServoButtons = page.getByRole('button', { name: '断使能', exact: true })
  assert.ok(await disabledServoButtons.count() >= 2)
  assert.equal(await disabledServoButtons.first().isEnabled(), true)
  assert.equal(await page.locator('#motion-left').getByRole('button', { name: '使能全部', exact: true }).isDisabled(), true)
  result.disableAvailableOffline = true
  await page.reload({ waitUntil: 'networkidle' })
  await emergency.waitFor()
  assert.match(await emergency.innerText(), /安全锁定|急停未确认/)
  await page.getByText('Safety LOCK', { exact: true }).first().waitFor()
  result.reloadPreservesEmergencyIntent = true
  await page.screenshot({ path: resolve(output, 'emergency-after-reload.png') })
  await page.setViewportSize({ width: 800, height: 600 })
  const bounds = await emergency.boundingBox()
  assert.ok(bounds && bounds.height >= 44 && bounds.x >= 0 && bounds.x + bounds.width <= 800)
  result.emergencyFitsNarrowViewport = true
  assert.ok(result.blockedRequests.some(url => url.endsWith('/api/motion/emergency_stop')))
  await writeFile(resolve(output, 'browser-safety.json'), JSON.stringify(result, null, 2))
  console.log(JSON.stringify(result, null, 2))
} finally {
  if (browser) await browser.close()
  await new Promise(resolve => server.close(resolve))
}
