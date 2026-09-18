import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { createServer } from 'node:http'
import { readFile, readdir, writeFile } from 'node:fs/promises'
import { resolve, extname } from 'node:path'
import { fileURLToPath } from 'node:url'

const repo = fileURLToPath(new URL('../..', import.meta.url))
const output = resolve(repo, 'output/layout-20260911')
const require = createRequire(resolve(repo, 'frontend/package.json'))
const { chromium } = require('playwright')
const dist = resolve(repo, 'frontend/dist')
const finalOnly = process.argv.includes('--final')
// 将本轮已构建资产读入内存，避免并行构建改变本轮证据。
const assets = new Map([['/index.html', await readFile(resolve(dist, 'index.html'))]])
for (const file of await readdir(resolve(dist, 'assets'))) {
  assets.set(`/assets/${file}`, await readFile(resolve(dist, 'assets', file)))
}
const result = { startedAt: new Date().toISOString(), fixtures: [], blockedRequests: [], blockedWebSockets: [], pageErrors: [], cases: [] }
const server = createServer((request, response) => {
  const path = new URL(request.url, 'http://localhost').pathname
  const asset = path === '/dataset' || path === '/' ? '/index.html' : path
  const body = assets.get(asset)
  if (!body) { response.writeHead(404).end(); return }
  response.writeHead(200, { 'content-type': ({ '.js': 'text/javascript', '.css': 'text/css', '.html': 'text/html' })[extname(asset)] ?? 'application/octet-stream' })
  response.end(body)
})
await new Promise(accept => server.listen(0, '127.0.0.1', accept))
const base = `http://127.0.0.1:${server.address().port}`
const image = `data:image/svg+xml,${encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="640" height="480"><rect width="640" height="480" fill="#274c68"/><text x="24" y="54" fill="white" font-size="24">Isolated dataset fixture</text></svg>')}`
const summaryEpisode = { id: 'episode_000001', name: 'Episode 1', task: 'layout fixture', status: 'review', quality: 92, frames: 12, fps: 30, durationS: 0.4, createdAt: 1500, warnings: [], samples: [] }
const detailEpisode = { ...summaryEpisode, samples: [
  { frame: 0, leftJoints: [1, 2, 3, 4, 5, 6], rightJoints: [7, 8, 9, 10, 11, 12], forceLeft: [1, 0, 0, 0, 0, 0], forceRight: [2, 0, 0, 0, 0, 0], images: { global: image, wrist_left: image, wrist_right: image } },
] }
const dataset = { id: 'layout_fixture', name: 'Layout Fixture', status: 'local', root: 'isolated-fixture', fps: 30, format: 'lerobot-v3-native', episodes: [summaryEpisode] }
let browser
try {
  browser = await chromium.launch({ headless: true, channel: 'msedge' })
  const context = await browser.newContext({ viewport: { width: 800, height: 1000 }, serviceWorkers: 'block' })
  await context.route('**/*', route => {
    const url = new URL(route.request().url())
    // 所有接口均先拦截；只有数据集两个只读接口由内存夹具应答。
    if (url.pathname.startsWith('/api/')) {
      const data = url.pathname === '/api/datasets' ? { datasets: [dataset] }
        : url.pathname === '/api/datasets/layout_fixture/episodes/episode_000001' ? { episode: detailEpisode } : null
      if (data) {
        result.fixtures.push(url.pathname)
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, data, ts: Date.now() }) })
      }
      result.blockedRequests.push(url.href)
      return route.fulfill({ status: 503, contentType: 'application/json', body: '{"detail":"isolated layout check"}' })
    }
    if (url.origin === base && (url.pathname.startsWith('/assets/') || url.pathname === '/dataset' || url.pathname === '/')) return route.continue()
    result.blockedRequests.push(url.href)
    return route.abort()
  })
  await context.routeWebSocket('**/*', socket => {
    result.blockedWebSockets.push(socket.url())
    socket.close()
  })
  const page = await context.newPage()
  page.on('pageerror', error => result.pageErrors.push(error.message))
  await page.goto(`${base}/dataset`, { waitUntil: 'networkidle' })
  await page.locator('.episode-row-button').filter({ hasText: 'Episode 1' }).waitFor()
  await page.locator('.dataset-video-image').last().waitFor()
  assert.equal(await page.locator('.dataset-video-pane').count(), 3)
  async function measure(phase, width) {
    await page.setViewportSize({ width, height: 1000 })
    await page.locator('.dataset-quality-workbench').scrollIntoViewIfNeeded()
    const measurement = await page.evaluate(() => {
      const bounds = element => {
        const r = element.getBoundingClientRect()
        return { x: r.x, right: r.right, y: r.y, bottom: r.bottom, width: r.width, height: r.height, clientWidth: element.clientWidth, scrollWidth: element.scrollWidth }
      }
      const main = document.querySelector('.main-content')
      const panel = document.querySelector('.dataset-quality-workbench')
      const grid = document.querySelector('.dataset-video-grid')
      const videos = [...grid.querySelectorAll('.dataset-video-pane')].map(bounds)
      const gridBox = bounds(grid)
      const mainBox = bounds(main)
      const panelBox = bounds(panel)
      return { main: mainBox, panel: panelBox, grid: gridBox, columns: getComputedStyle(grid).gridTemplateColumns, videos,
        gridOverflowPanel: Math.max(0, gridBox.right - panelBox.right),
        clippedWidthByMain: Math.max(0, gridBox.right - mainBox.right),
        mainHorizontalOverflow: mainBox.scrollWidth - mainBox.clientWidth,
        videoOverflow: Math.max(0, ...videos.map(video => video.right - gridBox.right)),
        bodyOverflow: document.documentElement.scrollWidth - innerWidth,
      }
    })
    result.cases.push({ phase, width, ...measurement })
    if (width === 800) await page.locator('.dataset-quality-workbench').screenshot({ path: resolve(output, `dataset-${phase}-800.png`) })
  }
  for (const width of [800, 900, 1024, 760]) await measure(finalOnly ? 'final' : 'current', width)
  // 只注入当前隔离页面，验证移除网格硬下限能否解决；不改源码或全局 CSS。
  if (!finalOnly) {
    result.proposedCss = '@media (min-width: 761px) and (max-width: 1200px) { .dataset-video-grid { grid-template-columns: minmax(0, 1.2fr) repeat(2, minmax(0, 0.8fr)); } }'
    await page.addStyleTag({ content: result.proposedCss })
    for (const width of [800, 900, 1024, 760]) await measure('candidate', width)
  }
  assert.ok(result.fixtures.includes('/api/datasets/layout_fixture/episodes/episode_000001'))
  assert.equal(result.pageErrors.length, 0)
  if (finalOnly) {
    for (const measurement of result.cases) {
      assert.equal(measurement.mainHorizontalOverflow, 0, `main overflow at ${measurement.width}px`)
      assert.equal(measurement.gridOverflowPanel, 0, `grid overflow at ${measurement.width}px`)
      assert.equal(measurement.clippedWidthByMain, 0, `video clipped at ${measurement.width}px`)
    }
  }
  await writeFile(resolve(output, finalOnly ? 'dataset-final.json' : 'dataset-check.json'), JSON.stringify(result, null, 2))
  console.log(JSON.stringify(result, null, 2))
} finally {
  if (browser) await browser.close()
  await new Promise(accept => server.close(accept))
}
