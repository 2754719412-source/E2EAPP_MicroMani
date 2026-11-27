/*
 * 阅读导航 08｜启动、部署与工具
 * 职责：用本地 HTTP 服务提供构建后的 dist 文件，并处理前端路由回退。
 * 先看：safePath → sendFile。
 * 全局阅读顺序与关联文件：docs/CODE_READING_GUIDE.md；逐文件目录：docs/SOURCE_INDEX.md。
 */
import { createReadStream, existsSync, statSync } from 'node:fs'
import { parseEnv } from 'node:util'
import { readJodellCapture } from './jodell-capture.mjs'
import { readFile } from 'node:fs/promises'
import { createServer } from 'node:http'
import { extname, join, normalize, resolve } from 'node:path'

const args = new Map()
for (let index = 2; index < process.argv.length; index += 1) {
  const key = process.argv[index]
  if (key === '--' || !key.startsWith('--')) {
    continue
  }
  const value = process.argv[index + 1]
  if (value && !value.startsWith('--')) {
    args.set(key, value)
    index += 1
  } else {
    args.set(key, 'true')
  }
}

const host = args.get('--host') || '0.0.0.0'
const port = Number(args.get('--port') || 4173)
const root = resolve('dist')
const localEnv = existsSync('.env.local') ? parseEnv(await readFile('.env.local', 'utf8')) : {}
const env = { ...localEnv, ...process.env }
const jodellFile = env.APPSTATION_JODELL_CAPTURE_FILE
const jodellPort = env.APPSTATION_JODELL_CAPTURE_PORT
const jodellSlaveId = Number(env.APPSTATION_JODELL_CAPTURE_SLAVE)

const contentTypes = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.ico': 'image/x-icon',
}

if (!existsSync(join(root, 'index.html'))) {
  console.error('dist/index.html not found. Run npm run build first.')
  process.exit(1)
}

function safePath(urlPath) {
  const decoded = decodeURIComponent(urlPath.split('?')[0] || '/')
  const normalized = normalize(decoded).replace(/^(\.\.[/\\])+/, '')
  return resolve(root, normalized.slice(1))
}

function sendFile(response, filePath) {
  const type = contentTypes[extname(filePath)] || 'application/octet-stream'
  response.writeHead(200, {
    'content-type': type,
    'cache-control': 'no-store',
  })
  createReadStream(filePath).pipe(response)
}

const server = createServer(async (request, response) => {
  try {
    const requestUrl = new URL(request.url || '/', `http://${host}:${port}`)
    if (requestUrl.pathname === '/station/jodell-capture') {
      if (request.method !== 'GET') {
        response.writeHead(405, { Allow: 'GET' }).end()
        return
      }
      try {
        const capture = jodellFile && /^COM\d+$/i.test(jodellPort || '') && Number.isInteger(jodellSlaveId) && jodellSlaveId >= 1 && jodellSlaveId <= 247
          ? await readJodellCapture(jodellFile, request.headers['if-none-match'])
          : { file: null, samples: [] }
        if (capture.tag) response.setHeader('ETag', capture.tag)
        response.setHeader('Cache-Control', 'no-cache')
        if (!capture.samples) response.writeHead(304).end()
        else response.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' }).end(JSON.stringify({ ...capture, port: jodellPort, slaveId: jodellSlaveId }))
      } catch (error) {
        response.writeHead(503, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' })
        response.end(JSON.stringify({ message: error.message === 'format' ? '采集文件列名与 EPG 工具格式不符' : '暂时无法读取钧舵采集目录' }))
      }
      return
    }
    let filePath = safePath(requestUrl.pathname)
    if (!filePath.startsWith(root)) {
      response.writeHead(403)
      response.end('Forbidden')
      return
    }
    if (existsSync(filePath) && statSync(filePath).isDirectory()) {
      filePath = join(filePath, 'index.html')
    }
    if (existsSync(filePath) && statSync(filePath).isFile()) {
      sendFile(response, filePath)
      return
    }
    const html = await readFile(join(root, 'index.html'))
    response.writeHead(200, { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-cache' })
    response.end(html)
  } catch (error) {
    response.writeHead(500, { 'content-type': 'text/plain; charset=utf-8' })
    response.end(error instanceof Error ? error.message : 'Internal Server Error')
  }
})

server.listen(port, host, () => {
  console.log(`AppStation frontend served at http://${host}:${port}`)
})
