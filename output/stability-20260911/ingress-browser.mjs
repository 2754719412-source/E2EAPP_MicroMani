import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { createServer } from 'node:http'
import { readFile, writeFile } from 'node:fs/promises'
import { resolve, extname } from 'node:path'
import { fileURLToPath } from 'node:url'

const repo = fileURLToPath(new URL('../..', import.meta.url))
const output = resolve(repo, 'output/stability-20260911')
const require = createRequire(resolve(repo, 'frontend/package.json'))
const { chromium } = require('playwright')
const result = { pageErrors: [], blockedRequests: [] }
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
  await context.route('**/*', route => {
    const url = route.request().url()
    if (url.startsWith(`${base}/`) && !new URL(url).pathname.startsWith('/api/')) return route.continue()
    result.blockedRequests.push(url)
    return route.abort()
  })
  let socket
  await context.routeWebSocket('**/*', route => { socket = route })
  const page = await context.newPage()
  page.on('pageerror', error => result.pageErrors.push(error.message))
  await page.goto(base, { waitUntil: 'networkidle' })
  await page.getByRole('button', { name: '全局急停', exact: true }).waitFor()
  assert.ok(socket)
  const frame = {
    timestamp: Date.now(), elapsedSec: 1, jointPositions: Array(12).fill(0), gripperPositions: [-1, -1],
    motionEnabled: { left: null, right: null }, motionAxisEnabled: { left: Array(6).fill(null), right: Array(6).fill(null) },
    forceLeft: Array(6).fill(0), forceRight: Array(6).fill(0), forceStatus: { safety: { latched: false, canAcknowledge: false } },
    dangerIndex: 0.2, recording: false, episodeCount: 1, frameCount: 42, halOk: true, wsOk: true,
    cameras: [], teleopHands: [], queueDepth: { left: 0, right: 0 },
    resource: { uiFps: 60, wsHz: 30, cpuPct: 0, memMb: 0 }, processStatus: [],
  }
  const emit = (type, data) => socket.send(JSON.stringify({ type, data }))
  emit('telemetry', frame)
  await page.getByText('Safety 0.20', { exact: true }).first().waitFor()
  emit('telemetry', { ...frame, resource: null })
  await page.getByText('WS 不可用', { exact: true }).first().waitFor()
  assert.equal(await page.getByText('页面暂时无法显示', { exact: true }).count(), 0)
  result.invalidFrameDoesNotUnmount = true
  emit('telemetry', { ...frame, timestamp: Date.now(), frameCount: 43 })
  await page.getByText('Safety 0.20', { exact: true }).first().waitFor()
  result.validFrameRecovers = true
  await page.getByRole('button', { name: 'Log Panel', exact: true }).click()
  emit('log', null)
  emit('log', { id: 999999, ts: Date.now(), level: 'INFO', channel: '[BACKEND]', msg: '隔离测试：正常日志仍送达' })
  await page.getByText('隔离测试：正常日志仍送达', { exact: true }).waitFor()
  result.invalidLogDoesNotBreakPanel = true
  emit('telemetry', { ...frame, cameras: null, forceStatus: { safety: { latched: true } } })
  await page.getByText('Safety LOCK', { exact: true }).first().waitFor()
  result.latchSurvivesInvalidFrame = true
  const emergency = page.getByRole('button', { name: '全局急停', exact: true })
  await emergency.click()
  await page.getByRole('alert').filter({ hasText: '请使用实体急停' }).waitFor()
  assert.ok(result.blockedRequests.some(url => url.endsWith('/api/motion/emergency_stop')))
  result.emergencyStillDispatches = true
  await page.screenshot({ path: resolve(output, 'ingress-fault-isolated.png') })
  assert.deepEqual(result.pageErrors, [])
  await writeFile(resolve(output, 'ingress-browser.json'), JSON.stringify(result, null, 2))
  console.log(JSON.stringify(result, null, 2))
} finally {
  if (browser) await browser.close()
  await new Promise(resolve => server.close(resolve))
}
