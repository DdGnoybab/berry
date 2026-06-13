import { useState } from 'react'
import type { LogRecord } from '../../api'

interface Props {
  rec: LogRecord
  keyword: string
}

const KNOWN_TOP = new Set(['timestamp', 'ts', 'level', 'event', 'logger', 'raw_text'])

// 这些字段太大,不放内联 KV,折叠到展开区。
// payload: LLM 切面里的请求/响应详情。
// exception: structlog format_exc_info 输出的多行堆栈。
const HEAVY_FIELDS = new Set(['payload', 'exception'])

/** Render a single structlog JSON record as one console line + expandable detail. */
export function LogLine({ rec, keyword }: Props) {
  const [expanded, setExpanded] = useState(false)

  const ts = (rec.timestamp ?? rec.ts ?? '') as string
  const tsShort = ts.slice(11, 23) || ts // HH:MM:SS.mmm slice from ISO

  const level = String(rec.level ?? 'info').toUpperCase().padEnd(5)
  const lvlClass = `log-line__lvl log-line__lvl--${level.trim().toLowerCase()}`

  const event = String(rec.event ?? '')
  const isError = level.trim() === 'ERROR'
  const isWarn = level.trim() === 'WARN' || level.trim() === 'WARNING'

  // 把字段拆成「内联展示」和「heavy(展开才看)」两组
  const inlineKv: [string, unknown][] = []
  const heavyKv: [string, unknown][] = []
  for (const [k, v] of Object.entries(rec)) {
    if (KNOWN_TOP.has(k)) continue
    if (HEAVY_FIELDS.has(k)) {
      heavyKv.push([k, v])
    } else {
      inlineKv.push([k, v])
    }
  }

  // For unparseable lines, just dump raw_text
  if (event === '_unparsed' && typeof rec.raw_text === 'string') {
    return (
      <div className="log-line" onClick={() => setExpanded((x) => !x)}>
        <span className="log-line__ts">{tsShort}</span>
        <span className="log-line__lvl log-line__lvl--debug">RAW  </span>
        {hl(rec.raw_text, keyword)}
      </div>
    )
  }

  return (
    <>
      <div
        className={[
          'log-line',
          isError ? 'log-line--error' : '',
          isWarn ? 'log-line--warn' : '',
          expanded ? 'log-line--expanded' : '',
        ].join(' ')}
        onClick={() => setExpanded((x) => !x)}
      >
        <span className="log-line__ts">{tsShort}</span>
        <span className={lvlClass}>{level}</span>
        <span className="log-line__event">{hl(event, keyword)}</span>
        {inlineKv.map(([k, v], i) => (
          <span className="log-line__kv" key={k + i}>
            <span className="log-line__kv-key">{k}</span>
            <span className="log-line__kv-eq">=</span>
            <span className="log-line__kv-val">{hl(stringify(v), keyword)}</span>
            <span> </span>
          </span>
        ))}
        {heavyKv.map(([k]) => (
          <span className="log-line__heavy-marker" key={`marker-${k}`}>
            {expanded ? '▼' : '▶'} {k}
          </span>
        ))}
      </div>
      {expanded && (
        <div className="log-line__detail">
          {heavyKv.length > 0 ? (
            <>
              {heavyKv.map(([k, v]) => (
                <div className="log-line__heavy-section" key={k}>
                  <div className="log-line__heavy-label">{k}</div>
                  <pre className="log-line__heavy-body">
                    {prettyJson(v)}
                  </pre>
                </div>
              ))}
              <div className="log-line__heavy-section">
                <div className="log-line__heavy-label">full record</div>
                <pre className="log-line__heavy-body">{JSON.stringify(rec, null, 2)}</pre>
              </div>
            </>
          ) : (
            <pre className="log-line__heavy-body">{JSON.stringify(rec, null, 2)}</pre>
          )}
        </div>
      )}
    </>
  )
}

/** Highlight `kw` substring inside `text` (case-insensitive). */
function hl(text: string, kw: string) {
  if (!kw) return text
  const lower = text.toLowerCase()
  const klower = kw.toLowerCase()
  const idx = lower.indexOf(klower)
  if (idx < 0) return text
  return (
    <>
      {text.slice(0, idx)}
      <mark className="log-hl">{text.slice(idx, idx + kw.length)}</mark>
      {text.slice(idx + kw.length)}
    </>
  )
}

function stringify(v: unknown): string {
  if (v == null) return String(v)
  if (typeof v === 'string') return `"${v}"`
  if (typeof v === 'number' || typeof v === 'boolean') return String(v)
  try {
    return JSON.stringify(v)
  } catch {
    return String(v)
  }
}

function prettyJson(v: unknown): string {
  try {
    return JSON.stringify(v, null, 2)
  } catch {
    return String(v)
  }
}
