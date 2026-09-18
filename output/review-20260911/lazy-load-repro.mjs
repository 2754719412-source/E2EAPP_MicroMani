import { createRequire } from 'node:module'
import { createServer } from 'node:http'
import { readFile, writeFile } from 'node:fs/promises'
import { resolve, extname } from 'node:path'
import { fileURLToPath } from 'node:url'

const repo = resolve(fileURLToPath(new URL('../..', import.meta.url)))
const require = createRequire(resolve(repo, 'frontend/package.json'))
const { chromium } = require('playwright')
const dist = resolve(repo, 'frontend/dist')
const result = { blockedRequests: [], errors: [] }
const server = createServer(async (request, response) => {
  const pathname = new URL(request.url, 'http://localhost').pathname
  const asset = pathname.startsWith('/assets/') ? pathname.slice(1) : 'index.html'
  try {
    const body = await readFile(resolve(dist, asset))
    response.writeHead(200, { 'content-type': ({ '.js': 'text/javascript', '.css': 'text/css', '.html': 'text/html' })[extname(asset)] ?? 'application/octet-stream' })
    response.end(body)
  } catch {
    response.writeHead(404).end()
  }
})
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
const base = `http://127.0.0.1:${server.address().port}`
let browser
try {
  browser = await chromium.launch({ headless: true, channel: 'msedge' })
  const context = await browser.newContext()
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
  page.on('pageerror', error => result.errors.push(error.message))
  await page.goto(base, { waitUntil: 'networkidle' })
  await page.getByRole('button', { name: '全局急停', exact: true }).waitFor()
  result.before = { rootChildren: await page.locator('#root').evaluate(root => root.childElementCount), emergencyButtons: await page.getByRole('button', { name: '全局急停', exact: true }).count() }
  await page.screenshot({ path: resolve(repo, 'output/review-20260911/lazy-before.png') })
  result.links = await page.getByRole('link').evaluateAll(links => links.map(link => ({ text: link.textContent, href: link.getAttribute('href') })))
  await page.locator('a[href="/model"]').click()
  await page.waitForFunction(() => document.querySelector('#root')?.childElementCount === 0, { timeout: 5000 })
  result.after = { rootChildren: await page.locator('#root').evaluate(root => root.childElementCount), emergencyButtons: await page.getByRole('button', { name: '全局急停', exact: true }).count() }
  await page.screenshot({ path: resolve(repo, 'output/review-20260911/lazy-after.png') })
  console.log(JSON.stringify(result, null, 2))
} finally {
  await browser?.close()
  await new Promise(resolve => server.close(resolve))
  await writeFile(resolve(repo, 'output/review-20260911/lazy-load-repro.json'), JSON.stringify(result, null, 2))
}
