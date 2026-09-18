import { createRequire } from 'node:module'
import { createServer } from 'node:http'
import { readFile, writeFile } from 'node:fs/promises'
import { resolve, extname } from 'node:path'
import { fileURLToPath } from 'node:url'

const repo = fileURLToPath(new URL('../..', import.meta.url))
const output = resolve(repo, 'output/layout-20260911')
const require = createRequire(resolve(repo, 'frontend/package.json'))
const { chromium } = require('playwright')
const phase = process.argv[2] ?? 'after'
const results = []
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
  const context = await browser.newContext()
  // 仅访问独立静态页面，API、设备请求和 WebSocket 均在发送前拦截。
  await context.route('**/*', route => route.request().url().startsWith(`${base}/`) ? route.continue() : route.abort())
  await context.routeWebSocket('**/*', socket => socket.close())
  const page = await context.newPage()
  const pageErrors = []
  page.on('pageerror', error => pageErrors.push(error.message))
  for (const width of (process.argv[3] ?? '2560,1920,1440,1201,1024,800,390').split(',').map(Number)) {
    await page.setViewportSize({ width, height: 1000 })
    await page.goto(`${base}/settings`, { waitUntil: 'networkidle' })
    for (const target of ['系统连接', '安全与力觉', '运动控制', '遥操作', '视觉', '/', '/record', '/dataset', '/model', '/fine-tune', '/auto']) {
      if (target.startsWith('/')) await page.goto(`${base}${target}`, { waitUntil: 'networkidle' })
      else await page.getByRole('tab', { name: target, exact: true }).click()
      const measurement = await page.evaluate(() => {
        const describe = el => `${el.tagName.toLowerCase()}${el.id ? `#${el.id}` : ''}.${String(el.className).split(' ').join('.')}`
        const inputs = [...document.querySelectorAll('.ui-input, .ui-select, .ui-range, .ui-textarea')].filter(el => el.getClientRects().length)
        const overflow = inputs.flatMap(el => {
          const rect = el.getBoundingClientRect()
          const parent = el.parentElement
          const container = parent.getBoundingClientRect()
          if (rect.left >= container.left - 2 && rect.right <= container.right + 2) return []
          return [{ element: describe(el), parent: describe(parent), card: el.closest('.hardware-config-card')?.id, label: el.getAttribute('aria-label') ?? el.closest('.ui-field')?.querySelector('.ui-field-label')?.textContent, width: rect.width, parentWidth: container.width, excess: Math.round(rect.right - container.right) }]
        })
        const main = document.querySelector('.main-content')
        const cameraRows = [...document.querySelectorAll('.camera-tuning-control-row')].map(el => ({ columns: getComputedStyle(el).gridTemplateColumns, width: el.getBoundingClientRect().width, inputWidth: el.querySelector('.ui-input').getBoundingClientRect().width }))
        const wideElements = main && main.scrollWidth > main.clientWidth + 2 ? [...main.querySelectorAll('*')].filter(el => el.getBoundingClientRect().right > main.getBoundingClientRect().right + 2).slice(0, 24).map(el => ({ element: describe(el), width: Math.round(el.getBoundingClientRect().width), text: el.textContent.slice(0, 80) })) : []
        const emergency = document.querySelector('button[aria-label="全局急停"]')?.getBoundingClientRect()
        return { inputCount: inputs.length, overflow, mainOverflow: main ? main.scrollWidth - main.clientWidth : 0, bodyOverflow: document.documentElement.scrollWidth - innerWidth, cameraRows, wideElements, emergencyFits: Boolean(emergency && emergency.left >= 0 && emergency.right <= innerWidth && emergency.bottom <= innerHeight) }
      })
      results.push({ width, target, ...measurement })
      if (target === '视觉' && [1440, 390].includes(width)) {
        await page.locator('.camera-tuning-panel').first().screenshot({ path: resolve(output, `${phase}-camera-${width}.png`) })
      }
      if (target === '遥操作' && width === 1440) await page.locator('.teleop-switch-row').first().screenshot({ path: resolve(output, `${phase}-teleop.png`) })
      if (target === '/record' && width === 1920) await page.locator('.record-kalman-groups').screenshot({ path: resolve(output, `${phase}-kalman.png`) })
    }
  }
  await writeFile(resolve(output, `${phase}.json`), JSON.stringify({ results, pageErrors }, null, 2))
  console.log(JSON.stringify({ pageErrors, cases: results.length, issues: results.filter(x => x.overflow.length || x.mainOverflow > 2 || x.bodyOverflow > 2).map(({ width, target, overflow, mainOverflow, bodyOverflow }) => ({ width, target, overflow, mainOverflow, bodyOverflow })) }, null, 2))
} finally {
  if (browser) await browser.close()
  await new Promise(resolve => server.close(resolve))
}
