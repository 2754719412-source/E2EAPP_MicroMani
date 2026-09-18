import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { createServer } from 'node:http'
import { readFile, readdir, writeFile } from 'node:fs/promises'
import { resolve, extname } from 'node:path'
import { fileURLToPath } from 'node:url'

const repo = fileURLToPath(new URL('../..', import.meta.url))
const require = createRequire(resolve(repo, 'frontend/package.json'))
const { chromium } = require('playwright')
const output = resolve(repo, 'output/resilience-20260911')
const dist = resolve(repo, 'frontend/dist')
const assets = new Map([['/index.html', await readFile(resolve(dist, 'index.html'))]])
for (const file of await readdir(resolve(dist, 'assets'))) assets.set(`/assets/${file}`, await readFile(resolve(dist, 'assets', file)))
const server = createServer((request, response) => {
  const path = new URL(request.url, 'http://isolated.local').pathname
  const key = path.startsWith('/assets/') ? path : '/index.html'
  const body = assets.get(key)
  if (!body) { response.writeHead(404).end(); return }
  response.writeHead(200, { 'content-type': ({ '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css' })[extname(key)] ?? 'application/octet-stream' }).end(body)
})
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
const base = `http://127.0.0.1:${server.address().port}`
const delay = ms => new Promise(resolve => setTimeout(resolve, ms))
async function until(test, timeout = 6000) {
  const end = performance.now() + timeout
  while (!test()) { if (performance.now() > end) throw new Error('等待离线协议状态超时'); await delay(20) }
}
const results = { boundary: '仅验证生产前端与 Node 协议替身，未运行或连接真实 backend/HAL；停止时间是替身的独立过期检测，不是实机停止时间。', scenarios: [], blockedHttp: [] }
let browser

async function scenario(kind) {
  const context = await browser.newContext({ serviceWorkers: 'block', viewport: { width: 1440, height: 1000 } })
  await context.route('**/*', route => {
    const request = route.request()
    const url = new URL(request.url())
    if (url.origin === base && request.method() === 'GET' && (url.pathname === '/' || assets.has(url.pathname))) return route.continue()
    results.blockedHttp.push({ method: request.method(), path: url.pathname })
    return route.abort('failed')
  })
  const events = []
  let socketCount = 0
  let heartbeats = 0
  let stopped = false
  let stopAt = null
  let closed = false
  const timers = new Set()
  const later = (fn, ms) => { const timer = setTimeout(fn, ms); timers.add(timer); return timer }
  const stop = reason => {
    if (stopped) return
    stopped = true; stopAt = performance.now()
    events.push({ event: 'fake-backend-stop', at: stopAt, reason })
  }
  await context.routeWebSocket('**/*', socket => {
    if (++socketCount > 1) { socket.close(); return }
    const sessionId = `${kind}-session`
    let sequence = 0
    let pending = null
    let lastResponseAt = performance.now()
    const emit = (type, data) => { if (!closed) socket.send(JSON.stringify({ type, data })) }
    const challenge = () => {
      if (closed || stopped) return
      pending = { challengeId: `nonce-${++sequence}`, deadline: performance.now() + 2000 }
      events.push({ event: 'challenge', at: performance.now(), challengeId: pending.challengeId })
      emit('safety_challenge', { sessionId, challengeId: pending.challengeId, ttlMs: 2000 })
      later(() => {
        if (pending && performance.now() >= pending.deadline && !closed) {
          stop('challenge expired')
          emit('control_lease', { sessionId, challengeId: pending.challengeId, status: 'expired', ttlMs: 2500 })
        }
      }, 2010)
    }
    socket.onMessage(raw => {
      const message = JSON.parse(String(raw))
      events.push({ event: 'response-received', at: performance.now(), data: message.data })
      if (stopped || !pending || performance.now() >= pending.deadline || message.type !== 'safety_heartbeat'
        || message.data.sessionId !== sessionId || message.data.challengeId !== pending.challengeId) {
        events.push({ event: 'response-rejected', at: performance.now() }); return
      }
      heartbeats += 1
      lastResponseAt = performance.now()
      const challengeId = pending.challengeId
      pending = null
      emit('control_lease', { sessionId, challengeId, status: 'active', ttlMs: 2500 })
      events.push({ event: 'fake-hal-lease-confirmed', at: performance.now(), challengeId })
      later(challenge, 500)
    })
    socket.onClose(() => { closed = true; stop('socket closed') })
    // 与实际后端一致：从最后有效答复起算，不能再额外等下一挑战的 500ms 间隔。
    const watchdog = setInterval(() => {
      if (!closed && !stopped && performance.now() - lastResponseAt >= 2000) {
        stop('last valid response expired')
        emit('control_lease', { sessionId, challengeId: pending?.challengeId ?? '', status: 'expired', ttlMs: 2500 })
      }
    }, 50)
    timers.add(watchdog)
    challenge()
    const frames = setInterval(() => emit('telemetry', {
      timestamp: Date.now(), elapsedSec: 1, jointPositions: Array(12).fill(0), gripperPositions: [0, 0],
      motionEnabled: { left: true, right: true }, motionAxisEnabled: { left: Array(6).fill(true), right: Array(6).fill(true) },
      forceLeft: Array(6).fill(0), forceRight: Array(6).fill(0), forceStatus: { safety: { latched: false, canAcknowledge: true } },
      dangerIndex: 0, recording: false, episodeCount: 0, frameCount: 0, halOk: true, wsOk: true,
      cameras: [], teleopHands: [], queueDepth: { left: 0, right: 0 },
      resource: { uiFps: 60, wsHz: 30, cpuPct: 0, memMb: 0 }, processStatus: [],
    }), 100)
    timers.add(frames)
  })
  const page = await context.newPage()
  const pageErrors = []
  page.on('pageerror', error => pageErrors.push(error.message))
  try {
    await page.goto(base, { waitUntil: 'networkidle' })
    await until(() => heartbeats >= 2)
    await page.getByText('Safety 0.00', { exact: true }).first().waitFor()
    const cdp = await context.newCDPSession(page)
    const before = heartbeats
    const faultAt = performance.now()
    if (kind === 'main-thread-paused') {
      await cdp.send('Debugger.enable')
      const paused = new Promise(resolve => cdp.once('Debugger.paused', resolve))
      await cdp.send('Debugger.pause')
      await paused
      events.push({ event: 'actual-renderer-main-thread-paused', at: performance.now() })
      await delay(2800)
      assert.equal(heartbeats, before, '暂停时不能由 Worker 或其他计时器代答')
      assert.equal(stopped, true, '独立替身应在页面暂停期间检测过期')
      await cdp.send('Debugger.resume')
      events.push({ event: 'renderer-resumed', at: performance.now() })
      await page.getByRole('status', { name: '控制安全租约', exact: true }).waitFor()
      await until(() => closed)
      assert.equal(heartbeats, before, '恢复后积压挑战不能续旧会话')
      const acknowledge = page.getByRole('button', { name: '确认安全态', exact: true })
      assert.equal(await acknowledge.count() > 0 && await acknowledge.isEnabled(), false)
      assert.equal(await page.getByRole('button', { name: '全局急停', exact: true }).isVisible(), true)
      await page.screenshot({ path: resolve(output, 'main-thread-resumed.png') })
    } else if (kind === 'renderer-crashed') {
      const crash = new Promise(resolve => page.once('crash', resolve))
      void cdp.send('Page.crash').catch(() => undefined)
      await crash
      events.push({ event: 'actual-renderer-crashed', at: performance.now() })
      await until(() => stopped)
      assert.equal(heartbeats, before, 'renderer 崩溃后不能继续续租')
    } else {
      await page.evaluate(() => { void Promise.reject(new Error('隔离测试：全局未处理拒绝')) })
      await until(() => closed)
      await page.getByRole('status', { name: '控制安全租约', exact: true }).waitFor()
      assert.equal(heartbeats, before, '未处理拒绝后不能继续续租')
      assert.match(await page.getByRole('status', { name: '控制安全租约', exact: true }).textContent(), /页面异步异常/)
    }
    assert.ok(stopAt - faultAt <= 3000)
    results.scenarios.push({ kind, actualRendererFault: true, acceptedBeforeFault: before, acceptedAfterFault: heartbeats,
      fakeBackendStopAfterFaultMs: Math.round(stopAt - faultAt), oldSessionNotRenewed: heartbeats === before, pageErrors, events })
  } finally {
    for (const timer of timers) clearTimeout(timer)
    await context.close()
  }
}

try {
  browser = await chromium.launch({ headless: true, channel: 'msedge' })
  await scenario('main-thread-paused')
  await scenario('renderer-crashed')
  await scenario('unhandled-rejection')
  await writeFile(resolve(output, 'browser-main-thread.json'), JSON.stringify(results, null, 2))
  console.log(JSON.stringify({ scenarios: results.scenarios.map(({ kind, acceptedBeforeFault, acceptedAfterFault, fakeBackendStopAfterFaultMs, oldSessionNotRenewed }) => ({ kind, acceptedBeforeFault, acceptedAfterFault, fakeBackendStopAfterFaultMs, oldSessionNotRenewed })), interceptedHttp: results.blockedHttp.length }))
} finally {
  await browser?.close()
  await new Promise(resolve => server.close(resolve))
}
