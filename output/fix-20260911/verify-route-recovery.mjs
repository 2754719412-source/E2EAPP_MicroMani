import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { createServer } from 'node:http'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { resolve, extname } from 'node:path'
import { fileURLToPath } from 'node:url'

const repo = fileURLToPath(new URL('../..', import.meta.url))
const output = resolve(repo, 'output/fix-20260911')
const require = createRequire(resolve(repo, 'frontend/package.json'))
const { chromium } = require('playwright')
const result = { blockedRequests: [], errors: [] }
await mkdir(output, { recursive: true })
const server = createServer(async (request, response) => {
  const pathname = new URL(request.url, 'http://localhost').pathname
  const asset = pathname.startsWith('/assets/') ? pathname.slice(1) : 'index.html'
  try {
    const body = await readFile(resolve(repo, 'frontend/dist', asset))
    response.writeHead(200, {
      'content-type': ({ '.js': 'text/javascript', '.css': 'text/css', '.html': 'text/html' })[extname(asset)] ?? 'application/octet-stream',
      'cache-control': 'no-store',
    })
    response.end(body)
  } catch {
    response.writeHead(404).end()
  }
})
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
const base = `http://127.0.0.1:${server.address().port}`
let browser
let failModel = true
try {
  browser = await chromium.launch({ headless: true, channel: 'msedge' })
  const context = await browser.newContext()
  // 所有设备 HTTP/WS 都在请求发出前阻断；仅允许本次静态服务器。
  await context.route('**/*', route => {
    const url = route.request().url()
    if (!url.startsWith(`${base}/`)) {
      result.blockedRequests.push(url)
      return route.abort()
    }
    if (failModel && /\/ModelView-[^/]+\.js/.test(url)) {
      return route.fulfill({ status: 404, body: 'Isolated chunk failure' })
    }
    return route.continue()
  })
  await context.routeWebSocket('**/*', socket => socket.close())
  const page = await context.newPage()
  page.on('pageerror', error => result.errors.push(error.message))
  await page.goto(base, { waitUntil: 'networkidle' })
  await page.getByRole('button', { name: '全局急停', exact: true }).waitFor()
  await page.screenshot({ path: resolve(output, 'route-before.png') })
  await page.locator('a[href="/model"]').click()
  await page.getByRole('alert').filter({ hasText: '页面暂时无法显示' }).waitFor()
  result.afterFailure = {
    rootChildren: await page.locator('#root').evaluate(root => root.childElementCount),
    emergencyButtons: await page.getByRole('button', { name: '全局急停', exact: true }).count(),
    navigationVisible: await page.getByRole('navigation', { name: '主导航' }).isVisible(),
  }
  assert.ok(result.afterFailure.rootChildren > 0)
  assert.equal(result.afterFailure.emergencyButtons, 1)
  assert.equal(result.afterFailure.navigationVisible, true)
  await page.screenshot({ path: resolve(output, 'route-error-contained.png') })

  const stopRequest = page.waitForRequest(request => request.url().endsWith('/api/motion/emergency_stop'))
  await page.getByRole('button', { name: '全局急停', exact: true }).click()
  await stopRequest
  result.emergencyDispatchBlocked = true

  await page.locator('a[href="/"]').click()
  await page.getByRole('alert').filter({ hasText: '页面暂时无法显示' }).waitFor({ state: 'detached' })
  result.navigationRecovered = true
  await page.locator('a[href="/model"]').click()
  await page.getByRole('alert').filter({ hasText: '页面暂时无法显示' }).waitFor()
  failModel = false
  await Promise.all([
    page.waitForEvent('load'),
    page.getByRole('button', { name: '重新加载页面', exact: true }).click(),
  ])
  await page.getByRole('heading', { name: '模型 Model', exact: true }).waitFor()
  assert.equal(await page.getByRole('button', { name: '全局急停', exact: true }).count(), 1)
  result.reloadRecovered = true
  await page.screenshot({ path: resolve(output, 'route-recovered.png') })
  console.log(JSON.stringify(result, null, 2))
} finally {
  await browser?.close()
  await new Promise(resolve => server.close(resolve))
  await writeFile(resolve(output, 'route-recovery.json'), JSON.stringify(result, null, 2))
}
