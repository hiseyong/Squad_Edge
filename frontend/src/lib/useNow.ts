import { useEffect, useState } from 'react'
import { serverNow } from '../store'

/** 1초마다 갱신되는 서버 기준 현재 시각 [s]. 탭 복귀 시 즉시 재개. */
export function useNow(interval = 1000) {
  const [now, setNow] = useState(serverNow())
  useEffect(() => {
    const tick = () => setNow(serverNow())
    const t = setInterval(tick, interval)
    const onVis = () => {
      if (document.visibilityState === 'visible') tick()
    }
    document.addEventListener('visibilitychange', onVis)
    return () => {
      clearInterval(t)
      document.removeEventListener('visibilitychange', onVis)
    }
  }, [interval])
  return now
}
