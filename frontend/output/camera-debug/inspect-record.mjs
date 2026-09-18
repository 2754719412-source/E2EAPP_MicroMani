/*
 * 阅读导航 08｜启动、部署与工具
 * 职责：保留的录制页面浏览器诊断脚本；用于调查相机预览，非应用启动入口。
 * 全局阅读顺序与关联文件：docs/CODE_READING_GUIDE.md；逐文件目录：docs/SOURCE_INDEX.md。
 */
import { chromium } from 'playwright';
import fs from 'node:fs';
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1592, height: 890 }, deviceScaleFactor: 1 });
const responses = [];
page.on('response', async (r) => {
  const url = r.url();
  if (url.includes('/api/cameras/')) responses.push({ url, status: r.status(), type: r.headers()['content-type'] });
});
await page.goto('http://127.0.0.1:5174/record', { waitUntil: 'domcontentloaded', timeout: 15000 });
await page.waitForTimeout(3000);
const info = await page.evaluate(async () => {
  const imgs = [...document.querySelectorAll('img.record-camera-image')];
  return imgs.map((img) => {
    const rect = img.getBoundingClientRect();
    const slot = img.closest('.record-camera-slot')?.getBoundingClientRect();
    const style = getComputedStyle(img);
    return {
      testid: img.getAttribute('data-testid'),
      src: img.src,
      complete: img.complete,
      naturalWidth: img.naturalWidth,
      naturalHeight: img.naturalHeight,
      rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
      slot: slot ? { x: slot.x, y: slot.y, width: slot.width, height: slot.height } : null,
      display: style.display,
      visibility: style.visibility,
      opacity: style.opacity,
      objectFit: style.objectFit,
    };
  });
});
await page.screenshot({ path: 'frontend/output/camera-debug/page-record-current.png', fullPage: false });
await browser.close();
console.log(JSON.stringify({ info, responses: responses.slice(-10) }, null, 2));
