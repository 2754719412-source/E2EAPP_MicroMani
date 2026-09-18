import { createRequire } from 'node:module'
import { createServer } from 'node:http'
import { readFile, readdir, writeFile } from 'node:fs/promises'
import { extname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const repo = fileURLToPath(new URL('../..', import.meta.url))
const require = createRequire(resolve(repo, 'frontend/package.json'))
const { chromium } = require('playwright')
const dist = resolve(repo, 'frontend/dist')
const assets = new Map([['/index.html', await readFile(resolve(dist, 'index.html'))]])
for (const name of await readdir(resolve(dist, 'assets'))) {
  assets.set(`/assets/${name}`, await readFile(resolve(dist, 'assets', name)))
}
const server = createServer((request, response) => {
  const pathname = new URL(request.url, 'http://isolated.local').pathname
  const key = pathname.startsWith('/assets/') ? pathname : '/index.html'
  const body = assets.get(key)
  if (!body) { response.writeHead(404).end(); return }
  response.writeHead(200, { 'content-type': ({ '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css' })[extname(key)] ?? 'application/octet-stream' })
  response.end(body)
})
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
const base = `http://127.0.0.1:${server.address().port}`
const records = []
const pageErrors = []
const blockedRequests = []
let browser
try {
  browser = await chromium.launch({ headless: true, channel: 'msedge' })
  const context = await browser.newContext({ serviceWorkers: 'block' })
  // 只放行本次启动的内存静态资源；所有 API、媒体和 WS 都在发送前拦截。
  await context.route('**/*', route => {
    const request = route.request()
    const url = new URL(request.url())
    if (url.origin === base && request.method() === 'GET' && (['/model', '/fine-tune', '/index.html'].includes(url.pathname) || assets.has(url.pathname))) return route.continue()
    blockedRequests.push({ method: request.method(), pathname: url.pathname })
    return route.abort('failed')
  })
  await context.routeWebSocket('**/*', socket => socket.close())
  const page = await context.newPage()
  page.on('pageerror', error => pageErrors.push(error.message))
  for (const width of [2560, 1920, 1440, 1201, 1024, 800, 390]) {
    await page.setViewportSize({ width, height: 1000 })
    for (const path of ['/model', '/fine-tune']) {
      await page.goto(`${base}${path}`, { waitUntil: 'networkidle' })
      const alert = page.locator('.view-stack > [role="alert"]')
      await alert.waitFor()
      const initialError = await alert.textContent()
      await alert.getByRole('button', { name: '重试', exact: true }).click()
      await alert.waitFor()
      const retryError = await alert.textContent()
      await page.getByRole('button', { name: path === '/model' ? '导入 checkpoint' : '创建任务', exact: true }).click()
      await alert.waitFor()
      records.push({ width, path, initialError, retryError, actionError: await alert.textContent(), emergencyVisible: await page.getByRole('button', { name: '全局急停', exact: true }).isVisible() })
    }
  }
  const result = { records, pageErrors, blockedRequests }
  await writeFile(resolve(repo, 'output/stability-20260911/components-browser.json'), JSON.stringify(result, null, 2))
  console.log(JSON.stringify({ cases: records.length, pageErrors, allErrorsVisible: records.every(item => item.initialError && item.retryError && item.actionError), allEmergencyVisible: records.every(item => item.emergencyVisible), blockedRequests: blockedRequests.length }))
  if (pageErrors.length || records.some(item => !item.emergencyVisible)) process.exitCode = 1
} finally {
  await browser?.close()
  await new Promise(resolve => server.close(resolve))
}
