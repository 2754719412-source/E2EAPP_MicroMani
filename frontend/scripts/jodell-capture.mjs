import { open } from 'node:fs/promises'
import { basename, dirname } from 'node:path'

const header = 'time,pos,speed,torque,temperatures,vol,state'
const dayPattern = /^saveData_(\d{4})_(\d{1,2})_(\d{1,2})$/
const filePattern = /^EPG_saveData_(\d{1,2})_(\d{1,2})_(\d{1,2})\.csv$/i
const timePattern = /^(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d\.\d{3}$/

// 厂商持续追加文件，只读一个有界尾部。首尾切断的半行均不能作为真实样本。
export async function readJodellCapture(filePath, previousTag) {
  // 文件本身不含串口号。只读现场绑定的这一条采集，不扫描其他夹爪的新文件。
  const day = basename(dirname(filePath))
  const file = basename(filePath)
  if (!dayPattern.test(day) || !filePattern.test(file)) throw new Error('format')
  const handle = await open(filePath, 'r')
  try {
    const { size, mtimeMs } = await handle.stat()
    const tag = '"' + [day, file, size, mtimeMs].join('-') + '"'
    if (tag === previousTag) return { tag }
    const start = Math.max(0, size - 128 * 1024)
    const buffer = Buffer.alloc(size - start)
    const { bytesRead } = await handle.read(buffer, 0, buffer.length, start)
    const lines = buffer.toString('utf8', 0, bytesRead).split('\n')
    lines.pop()
    let first = lines.shift() ?? ''
    if (start) {
      const prefix = Buffer.alloc(256)
      const n = await handle.read(prefix, 0, prefix.length, 0)
      first = prefix.toString('utf8', 0, n.bytesRead).split('\n')[0]
    }
    if (first && first.trim() !== header) throw new Error('format')
    const samples = []
    for (const line of lines.slice(-2048)) {
      const [time, pos, speed, torque, ...other] = line.trimEnd().split(',')
      if (!timePattern.test(time) || other.length !== 3) continue
      const fields = [pos, torque, speed]
      if (fields.some((v) => !/^\d{1,3}$/.test(v) || Number(v) > 255)) continue
      samples.push([time, ...fields.map(Number)])
    }
    const [, year, month, date] = day.match(dayPattern)
    const [, hour, minute, second] = file.match(filePattern)
    const sessionStart = new Date(+year, +month - 1, +date, +hour, +minute, +second)
    let sampledAt = null
    if (samples.length) {
      const [h, m, s, ms] = samples.at(-1)[0].split(/[:.]/).map(Number)
      const stamp = new Date(+year, +month - 1, +date, h, m, s, ms)
      if (stamp < sessionStart) stamp.setDate(stamp.getDate() + 1)
      sampledAt = stamp.getTime()
    }
    return { tag, file, sampledAt, samples }
  } finally {
    await handle.close()
  }
}
