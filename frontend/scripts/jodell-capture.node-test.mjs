import assert from 'node:assert/strict'
import { appendFile, mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { test } from 'node:test'
import { readJodellCapture } from './jodell-capture.mjs'

test('读取官方列，等待完整末行，不串入其他夹爪新建的文件', async (t) => {
  const root = await mkdtemp(join(tmpdir(), 'jodell-csv-'))
  t.after(() => rm(root, { recursive: true, force: true }))
  const folder = join(root, 'saveData_2026_11_26')
  await mkdir(folder)
  const first = join(folder, 'EPG_saveData_16_36_57.csv')
  const header = 'time,pos,speed,torque,temperatures,vol,state\r\n'
  await writeFile(first, header + '16:36:59.975,242,0,116,28,24,0x3d\r\n16:37:00.038,165,7,')
  let result = await readJodellCapture(first)
  assert.deepEqual(result.samples, [['16:36:59.975', 242, 116, 0]])
  await appendFile(first, '103,28,24,0x3d\r\n')
  result = await readJodellCapture(first)
  assert.deepEqual(result.samples.at(-1), ['16:37:00.038', 165, 103, 7])
  const next = 'EPG_saveData_17_00_00.csv'
  await writeFile(join(folder, next), header)
  assert.equal((await readJodellCapture(first, result.tag)).tag, result.tag)
  assert.deepEqual((await readJodellCapture(first)).samples, result.samples)
  assert.deepEqual((await readJodellCapture(join(folder, next))).samples, [])
})
