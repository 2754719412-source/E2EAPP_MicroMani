import { useEffect, useState } from 'react'

export type JodellRow = [time: string, position: number, torque: number, speed: number]
export interface JodellCapture {
  port: string
  slaveId: number
  file: string
  sampledAt: number
  samples: JodellRow[]
  live: boolean
}

/** 官方工具独占串口时，只读其采集文件。即使文件停止追加，界面也能从实时转为历史。 */
export function useJodellCapture(enabled: boolean) {
  const [capture, setCapture] = useState<JodellCapture | null>(null)
  useEffect(() => {
    if (!enabled) return
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout>
    let last: JodellCapture | null = null
    let tag = ''
    async function poll() {
      let readable = false
      try {
        const res = await fetch('/station/jodell-capture', { signal: controller.signal,
          headers: tag ? { 'If-None-Match': tag } : {}, cache: 'no-store' })
        if (res.status !== 304 && res.ok) {
          const data = await res.json()
          last = data.file && data.samples?.length ? data : null
          tag = res.headers.get('etag') ?? ''
        }
        readable = res.ok || res.status === 304
      } catch {
        // 文件或本地服务暂不可用时，保留带时间标记的历史图。
      }
      if (controller.signal.aborted) return
      if (last) {
        const age = Date.now() - last.sampledAt
        const live = readable && age >= 0 && age < 5000
        if (last.live !== live) last = { ...last, live }
      }
      setCapture(last)
      timer = setTimeout(poll, 350)
    }
    void poll()
    return () => { controller.abort(); clearTimeout(timer) }
  }, [enabled])
  return enabled ? capture : null
}
