import { useCallback, useEffect, useRef, useState } from 'react'
import { api, type LlmStatus } from '../api'
import { IconBriefing } from './icons'

type SpeechRec = {
  lang: string; interimResults: boolean; continuous: boolean
  onresult: (e: { results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal: boolean }> }) => void
  onend: () => void; onerror: () => void; start: () => void; stop: () => void
}
const SpeechRecognitionCtor: (new () => SpeechRec) | undefined =
  (window as unknown as { SpeechRecognition?: new () => SpeechRec; webkitSpeechRecognition?: new () => SpeechRec })
    .SpeechRecognition ?? (window as unknown as { webkitSpeechRecognition?: new () => SpeechRec }).webkitSpeechRecognition

interface Entry { q: string | null; text: string; engine: string; latency?: number; ts: number; facts?: string }

/** AI 상황 브리핑 / 자연어 질의.
 *  - 로컬 LLM(Ollama 등) 연결 시 토큰 스트리밍, 미연결 시 규칙 기반 엔진으로 자동 폴백
 *  - 답변 근거(사실 목록) 열람, 자동 주기 브리핑, 음성 질의(브라우저 STT)
 */
export default function BriefingPanel() {
  const [q, setQ] = useState('')
  const [status, setStatus] = useState<LlmStatus | null>(null)
  const [useLlm, setUseLlm] = useState(true)
  const [cur, setCur] = useState<Entry | null>(null)
  const [hist, setHist] = useState<Entry[]>([])
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState<string | null>(null)
  const [showFacts, setShowFacts] = useState(false)
  const [auto, setAuto] = useState(0)
  const [listening, setListening] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const recRef = useRef<SpeechRec | null>(null)

  const refreshStatus = useCallback((force = false) => api.llmStatus(force).then(setStatus).catch(() => setStatus(null)), [])
  useEffect(() => {
    refreshStatus(true)
    const t = setInterval(() => refreshStatus(), 20000)
    return () => clearInterval(t)
  }, [refreshStatus])

  const run = useCallback(async (question?: string) => {
    abortRef.current?.abort()
    const ac = new AbortController()
    abortRef.current = ac
    setQ('')
    setBusy(true); setNote(null)
    const entry: Entry = { q: question ?? null, text: '', engine: '…', ts: Date.now() }
    setCur(entry)
    try {
      for await (const ev of api.briefStream(question, useLlm, ac.signal)) {
        if (ev.type === 'meta') {
          entry.engine = ev.engine; entry.facts = ev.facts
          if (ev.reason) setNote(`규칙 기반 엔진 사용 (${ev.reason})`)
        } else if (ev.type === 'token') {
          entry.text += ev.text
        } else if (ev.type === 'done') {
          entry.text = ev.text; entry.latency = ev.latency
        } else if (ev.type === 'error') {
          setNote(ev.message); entry.text = ''
        }
        setCur({ ...entry })
      }
      setHist((h) => [entry, ...h].slice(0, 6))
    } catch (e) {
      if ((e as Error).name !== 'AbortError') setNote(`브리핑 서버 오류: ${(e as Error).message}`)
    } finally {
      setBusy(false)
    }
  }, [useLlm])

  useEffect(() => {
    if (!auto) return
    const t = setInterval(() => run(), auto * 60_000)
    return () => clearInterval(t)
  }, [auto, run])

  const toggleMic = () => {
    if (!SpeechRecognitionCtor) return
    if (listening) { recRef.current?.stop(); return }
    const rec = new SpeechRecognitionCtor()
    rec.lang = 'ko-KR'; rec.interimResults = true; rec.continuous = false
    rec.onresult = (e) => {
      const res = e.results[e.results.length - 1]
      setQ(res[0].transcript)
      if (res.isFinal) { rec.stop(); run(res[0].transcript) }
    }
    rec.onend = () => setListening(false)
    rec.onerror = () => setListening(false)
    recRef.current = rec
    setListening(true)
    rec.start()
  }

  const llmOn = !!status?.available && useLlm
  return (
    <div className="flex max-h-[46%] shrink-0 flex-col border-t border-prisma-border bg-prisma-panel">
      <div className="panel-title !normal-case tracking-[0.14em]">
        <span className="inline-flex items-center gap-1.5 uppercase">
          <IconBriefing size={11} className="text-prisma-accent" />
          AI Brief
        </span>
        <span
          title={status?.error ?? status?.url ?? ''}
          className={`prisma-chip !normal-case tracking-normal ${llmOn ? 'prisma-chip-on' : ''}`}
        >
          {llmOn ? `LLM · ${status?.model}` : status?.available ? 'Rules (LLM off)' : 'Rules (no LLM)'}
        </span>
        <span className="ml-auto flex items-center gap-2 text-[10px] font-normal normal-case tracking-normal text-prisma-dim">
          <select
            value={auto}
            onChange={(e) => setAuto(Number(e.target.value))}
            className="prisma-input !w-auto !py-0.5 !text-[10px]"
            title="자동 주기 브리핑"
          >
            <option value={0}>Auto off</option>
            <option value={1}>1m</option>
            <option value={3}>3m</option>
            <option value={5}>5m</option>
          </select>
        </span>
      </div>

      <div className="flex min-h-0 flex-col gap-2 px-2 pb-2 pt-2">
        <div className="flex gap-1">
          {busy ? (
            <button type="button" onClick={() => abortRef.current?.abort()} className="prisma-btn prisma-btn-danger">중지</button>
          ) : (
            <button type="button" onClick={() => run()} className="prisma-btn prisma-btn-primary">브리핑</button>
          )}
          <form className="flex flex-1 gap-1" onSubmit={(e) => { e.preventDefault(); if (q.trim()) run(q.trim()) }}>
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="질의: 3분대 상태? / 가장 가까운 적? / 명령 수신 현황?"
              className="prisma-input min-w-0 flex-1"
            />
            {SpeechRecognitionCtor && (
              <button
                type="button"
                onClick={toggleMic}
                title="음성 질의"
                className={`prisma-btn ${listening ? 'prisma-btn-danger animate-pulse' : ''}`}
              >
                {listening ? '●' : (
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="9" y="2" width="6" height="12" rx="3" /><path d="M5 10a7 7 0 0 0 14 0M12 17v5" /></svg>
                )}
              </button>
            )}
          </form>
        </div>

        {cur && (
          <div className="prisma-card min-h-0 overflow-y-auto p-2 text-xs leading-relaxed text-prisma-fg">
            {cur.q && <div className="mb-1 text-[11px] text-prisma-accent">Q. {cur.q}</div>}
            <div className="whitespace-pre-wrap">{cur.text || (busy ? '생성 중…' : '')}{busy && <span className="animate-pulse">▍</span>}</div>
            <div className="mt-1.5 flex items-center gap-2 font-mono text-[10px] text-prisma-dim">
              <span>{cur.engine}{cur.latency ? ` · ${cur.latency}s` : ''}</span>
              {cur.facts && (
                <button type="button" className="hover:text-prisma-fg" onClick={() => setShowFacts(!showFacts)}>
                  {showFacts ? '근거 닫기' : '근거 보기'}
                </button>
              )}
            </div>
            {showFacts && cur.facts && (
              <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap bg-prisma-void p-1.5 text-[10px] leading-snug text-prisma-muted">{cur.facts}</pre>
            )}
          </div>
        )}
        {note && <div className="text-[10px] text-prisma-warn">{note}</div>}

        <div className="flex items-center gap-2 text-[10px] text-prisma-dim">
          {status?.available ? (
            <>
              <label className="flex items-center gap-1">
                <input type="checkbox" checked={useLlm} onChange={(e) => setUseLlm(e.target.checked)} className="accent-prisma-accent" />
                LLM
              </label>
              <select
                value={status.model ?? ''}
                onChange={(e) => api.setModel(e.target.value).then(setStatus)}
                className="prisma-input max-w-[150px] !py-0.5 !text-[10px]"
              >
                {status.models.map((m) => <option key={m} value={m}>{m}</option>)}
              </select>
            </>
          ) : (
            <span title="Ollama 설치 후: ollama pull exaone3.5:2.4b">로컬 LLM 미연결</span>
          )}
          <button type="button" className="hover:text-prisma-fg" onClick={() => refreshStatus(true)}>재탐지</button>
          {hist.length > 1 && (
            <select
              className="prisma-input ml-auto max-w-[120px] !py-0.5 !text-[10px]"
              value=""
              onChange={(e) => { const h = hist[Number(e.target.value)]; if (h) setCur(h) }}
            >
              <option value="">이전 {hist.length - 1}건</option>
              {hist.slice(1).map((h, i) => (
                <option key={h.ts} value={i + 1}>{new Date(h.ts).toLocaleTimeString('ko-KR', { hour12: false })} {h.q ?? '브리핑'}</option>
              ))}
            </select>
          )}
        </div>
      </div>
    </div>
  )
}
