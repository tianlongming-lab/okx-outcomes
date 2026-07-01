import { useEffect, useRef } from 'react'

type MsgHandler = (msg: any) => void

export function useBackendWS(onMessage: MsgHandler) {
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    const scheme = location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${scheme}://${location.host}/ws`)
    wsRef.current = ws

    ws.onopen = () => {
      console.info('WS connected')
    }
    ws.onmessage = (ev) => {
      try {
        const d = JSON.parse(ev.data)
        onMessage(d)
      } catch (e) {
        console.error('WS parse error', e)
      }
    }
    ws.onclose = () => console.info('WS closed')
    ws.onerror = (e) => console.error('WS error', e)

    return () => {
      ws.close()
    }
  }, [onMessage])

  const send = (obj: any) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(obj))
    }
  }

  return { send }
}
