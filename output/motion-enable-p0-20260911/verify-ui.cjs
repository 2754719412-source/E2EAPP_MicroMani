const { chromium } = require('../../frontend/node_modules/playwright')
const assert = require('node:assert/strict')
const path = require('node:path')

async function expectButtonEnabled(locator) {
  await locator.evaluate((button) => {
    if (button.disabled) throw new Error(`button disabled: ${button.textContent}`)
  })
}

;(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true })
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
    const errors = []
    page.on('pageerror', (error) => errors.push(error.message))
    // 本次验证只加载隔离的 test-mode 前端；阻止所有外部 HTTP，并替换后端 WS。
    await page.route('**/*', (route) => {
      if (new URL(route.request().url()).origin === 'http://127.0.0.1:5192') return route.continue()
      return route.fulfill({ status: 204, body: '' })
    })
    await page.addInitScript(() => {
      // 隔离验证：所有后端 WS 一律替换为可控 mock，避免连到本不存在的后端。
      window.WebSocket = class {
        static OPEN = 1
        constructor() {
          this.readyState = 1
          window.__motionSocket = this
          setTimeout(() => this.onopen?.(new Event('open')), 0)
        }
        send() {}
        close() { this.readyState = 3; this.onclose?.({ code: 1000 }) }
      }
    })
    await page.goto('http://127.0.0.1:5192/settings#manual')
    await page.getByRole('heading', { name: '右臂手动控制' }).waitFor()
    await page.evaluate(async () => {
      const { useTelemetryStore } = await import('/src/stores/telemetry.ts')
      window.__p0Store = useTelemetryStore
      useTelemetryStore.getState().stopMock()
      useTelemetryStore.getState().stopBackend()
      useTelemetryStore.getState().startBackend()
      await new Promise((resolve) => setTimeout(resolve, 50))
      if (!window.__motionSocket) throw new Error('mock websocket not installed')
      window.__p0Axes = Array(6).fill(false)
      window.__p0Emit = setInterval(() => {
        const frame = useTelemetryStore.getState().frame
        window.__motionSocket.onmessage?.({ data: JSON.stringify({ type: 'telemetry', data: {
          ...frame, timestamp: Date.now(), halOk: true, wsOk: true,
          motionEnabled: { left: window.__p0Axes.every((value) => value === true), right: null },
          motionAxisEnabled: { left: window.__p0Axes, right: Array(6).fill(null) },
        } }) })
      }, 80)
    })
    const card = page.locator('#motion-right')
    const manual = page.locator('.manual-arm-card').filter({ has: page.getByRole('heading', { name: '右臂手动控制' }) })
    const cardProgress = page.getByRole('status', { name: '右臂运动控制卡使能进度' })
    const manualProgress = page.getByRole('status', { name: '右臂手动控制使能进度' })
    // P0：live 遥测未建立时使能按钮禁用；先等链路可用再点击。
    await page.waitForFunction(() => {
      const store = window.__p0Store
      if (!store) return false
      const { telemetryLink, frame } = store.getState()
      return telemetryLink.state === 'live'
        && frame.halOk && frame.wsOk
        && telemetryLink.lastFrameReceivedAt !== null
        && Date.now() - telemetryLink.lastFrameReceivedAt <= 2000
    }, undefined, { timeout: 5000 })
    await card.getByRole('button', { name: '使能全部' }).waitFor({ state: 'visible' })
    await expectButtonEnabled(card.getByRole('button', { name: '使能全部' }))
    await card.getByRole('button', { name: '使能全部' }).click()
    await page.waitForFunction(() => window.__p0Store.getState().motionCommand.left.phase === 'waitingConfirm')
    assert.equal(await cardProgress.textContent(), await manualProgress.textContent())
    assert.equal(await manual.getByText('已使能', { exact: true }).count(), 0)

    await page.evaluate(() => { window.__p0Axes = Array(6).fill(true) })
    await page.waitForFunction(() => window.__p0Store.getState().motionCommand.left.phase === 'confirmed')
    assert.equal(await manual.getByText('已使能', { exact: true }).count(), 1)
    await manual.screenshot({ path: path.join(__dirname, 'manual-confirmed.png') })
    await manual.getByRole('button', { name: '断使能', exact: true }).click()
    await page.evaluate(() => { window.__p0Axes = Array(6).fill(null) })
    await page.waitForFunction(() => window.__p0Store.getState().motionCommand.left.phase === 'timeout', { timeout: 7000 })
    assert.equal(await cardProgress.textContent(), '未获得执行确认')
    assert.equal(await manualProgress.textContent(), '未获得执行确认')
    assert.equal(await manual.getByText('使能状态未知', { exact: true }).count(), 1)
    await manual.screenshot({ path: path.join(__dirname, 'manual-timeout.png') })
    await card.locator('.hardware-config-card-head').screenshot({ path: path.join(__dirname, 'motion-card-timeout.png') })
    await page.evaluate(() => {
      clearInterval(window.__p0Emit)
      window.__motionSocket.onerror?.()
    })
    await page.waitForFunction(() => window.__p0Store.getState().telemetryLink.state === 'offline')
    assert.equal(await manual.getByRole('button', { name: '使能', exact: true }).isDisabled(), true)
    assert.deepEqual(errors, [])
    console.log(JSON.stringify({ result: 'passed', viewport: '1440x1000', scenarios: ['API accepted without feedback', 'shared confirmation', 'unknown feedback timeout', 'disconnect'], screenshots: 3 }))
  } finally {
    await browser.close()
  }
})().catch((error) => { console.error(error); process.exitCode = 1 })
