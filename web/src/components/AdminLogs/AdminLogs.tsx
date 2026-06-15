import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  downloadLogUrl,
  fetchLogsGuide,
  queryLogs,
  streamLogs,
  type LogQueryParams,
  type LogRecord,
} from '../../api'
import { DocDrawer } from '../DocDrawer/DocDrawer'
import { LogLine } from './LogLine'
import './AdminLogs.css'

interface Props {
  onBack: () => void
}

const LEVELS = ['ERROR', 'WARN', 'INFO', 'DEBUG'] as const
type Level = (typeof LEVELS)[number]

const LIMIT = 200

// 日志面板统一按北京时间(Asia/Shanghai)显示与筛选,
// 跟用户「我刚才几点发的请求」心智模型对齐。
// 后端 / 落盘文件保留 UTC,这里只在展示和发请求边界做转换。

const TZ = 'Asia/Shanghai'
const TZ_OFFSET_MIN = 8 * 60  // 北京固定 UTC+8,无夏令时

function todayInBeijing(): string {
  // 拿"现在的北京日期"作为 YYYY-MM-DD(默认筛选今天)
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: TZ,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(new Date())
  const m: Record<string, string> = {}
  for (const p of parts) m[p.type] = p.value
  return `${m.year}-${m.month}-${m.day}`
}

function isoFromBeijing(date: string, time: string): string {
  // 用户输入 "2026-06-15" + "14:30" 含义是「北京时间 14:30」。
  // 转 UTC ISO 发后端: 北京 14:30 = UTC 06:30。
  // 实现:把 "2026-06-15T14:30:00" 视为北京 wall time → 减 8h → toISOString()
  const utcMs = Date.parse(`${date}T${time}:00Z`) - TZ_OFFSET_MIN * 60 * 1000
  return new Date(utcMs).toISOString()
}

export function AdminLogs({ onBack }: Props) {
  // ── filter state ──
  const [date, setDate] = useState<string>(todayInBeijing())
  const [timeFrom, setTimeFrom] = useState<string>('00:00')
  const [timeTo, setTimeTo] = useState<string>('23:59')
  const [activeLevels, setActiveLevels] = useState<Set<Level>>(new Set())
  const [keyword, setKeyword] = useState<string>('')
  const [debouncedKw, setDebouncedKw] = useState<string>('')

  // ── data state ──
  const [lines, setLines] = useState<LogRecord[]>([])
  const [loading, setLoading] = useState(false)
  const [totalMatched, setTotalMatched] = useState(0)
  const [nextCursor, setNextCursor] = useState<number | null>(null)

  // ── live tail state ──
  const [follow, setFollow] = useState(true)
  const [tailing, setTailing] = useState(false)
  const [pendingNew, setPendingNew] = useState(0)
  const consoleRef = useRef<HTMLDivElement>(null)
  const closeStreamRef = useRef<(() => void) | null>(null)

  // ── docs drawer ──
  const [showDocs, setShowDocs] = useState(false)

  // debounce keyword
  useEffect(() => {
    const t = window.setTimeout(() => setDebouncedKw(keyword), 300)
    return () => window.clearTimeout(t)
  }, [keyword])

  // is "today + full day + no level filter + no keyword" — i.e. live mode is meaningful
  const isLiveScope = useMemo(() => {
    return (
      date === todayInBeijing() &&
      timeFrom === '00:00' &&
      timeTo === '23:59' &&
      activeLevels.size === 0 &&
      debouncedKw === ''
    )
  }, [date, timeFrom, timeTo, activeLevels, debouncedKw])

  const queryParams: LogQueryParams = useMemo(() => {
    const params: LogQueryParams = {
      date_from: isoFromBeijing(date, timeFrom),
      date_to: isoFromBeijing(date, timeTo === '23:59' ? '23:59' : timeTo),
      limit: LIMIT,
      cursor: 0,
    }
    if (activeLevels.size > 0) params.level = Array.from(activeLevels)
    if (debouncedKw) params.q = debouncedKw
    return params
  }, [date, timeFrom, timeTo, activeLevels, debouncedKw])

  // load initial / on filter change
  useEffect(() => {
    let cancelled = false
    setLoading(true)
    queryLogs(queryParams)
      .then((r) => {
        if (cancelled) return
        // server returns newest-first; we want oldest-at-top, newest-at-bottom (console feel)
        setLines([...r.lines].reverse())
        setTotalMatched(r.total_matched)
        setNextCursor(r.next_cursor)
      })
      .catch((err) => {
        if (cancelled) return
        if (String(err).includes('FORBIDDEN')) {
          // shouldn't happen — App-level guard checked role — but tolerate
          onBack()
          return
        }
        console.error('queryLogs error:', err)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [queryParams, onBack])

  // load older (older = larger cursor, server returns newest-first by ts)
  const loadMore = useCallback(async () => {
    if (nextCursor == null) return
    setLoading(true)
    try {
      const r = await queryLogs({ ...queryParams, cursor: nextCursor })
      // older entries go to the TOP of the console (since we display oldest-at-top)
      setLines((prev) => [...[...r.lines].reverse(), ...prev])
      setNextCursor(r.next_cursor)
    } catch (err) {
      console.error('loadMore error:', err)
    } finally {
      setLoading(false)
    }
  }, [nextCursor, queryParams])

  // live tail: only when filters allow it AND user pressed "follow"
  useEffect(() => {
    if (!follow || !isLiveScope) {
      // tear down any existing stream
      closeStreamRef.current?.()
      closeStreamRef.current = null
      setTailing(false)
      return
    }
    setTailing(true)
    const close = streamLogs({
      onLine: (rec) => {
        setLines((prev) => {
          // append, cap at 5000 to keep browser snappy
          const next = [...prev, rec]
          if (next.length > 5000) next.splice(0, next.length - 5000)
          return next
        })
        // bump pending counter; will be cleared by auto-scroll effect below
        setPendingNew((n) => n + 1)
      },
      onError: (err) => {
        console.error('streamLogs error:', err)
      },
    })
    closeStreamRef.current = close
    return () => {
      close()
      closeStreamRef.current = null
      setTailing(false)
    }
  }, [follow, isLiveScope])

  // auto-scroll to bottom when in follow mode and a new line arrives
  useEffect(() => {
    if (!follow) return
    const el = consoleRef.current
    if (!el) return
    el.scrollTop = el.scrollHeight
    setPendingNew(0)
  }, [lines, follow])

  // user manually scrolling up while following → pause follow
  const onConsoleScroll = useCallback(() => {
    const el = consoleRef.current
    if (!el) return
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 30
    if (!atBottom && follow) {
      setFollow(false)
    }
  }, [follow])

  const toggleLevel = useCallback((lv: Level) => {
    setActiveLevels((prev) => {
      const next = new Set(prev)
      if (next.has(lv)) next.delete(lv)
      else next.add(lv)
      return next
    })
  }, [])

  const onJumpDown = useCallback(() => {
    setFollow(true)
    const el = consoleRef.current
    if (el) el.scrollTop = el.scrollHeight
    setPendingNew(0)
  }, [])

  const onClear = useCallback(() => {
    setLines([])
    setPendingNew(0)
  }, [])

  return (
    <div className="admin-logs">
      <div className="admin-logs__header">
        <button className="admin-logs__back" onClick={onBack} type="button">
          ← Back
        </button>
        <span className="admin-logs__title">
          Berry <span className="admin-logs__sep">/</span>
          Admin <span className="admin-logs__sep">/</span>
          <span className="admin-logs__title-strong">Logs</span>
        </span>
        <span className="admin-logs__tz" title="所有时间按北京时间显示;后端落盘是 UTC">
          CST
        </span>
        <span className={`admin-logs__live ${tailing ? '' : 'admin-logs__live--off'}`}>
          {tailing ? 'live' : 'idle'}
        </span>
        <button
          className="admin-logs__help"
          onClick={() => setShowDocs(true)}
          type="button"
          title="使用文档"
          aria-label="open docs"
        >
          ?
        </button>
      </div>

      <div className="admin-logs__toolbar">
        <label className="admin-logs__field">
          Date
          <input
            className="admin-logs__input"
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
          />
        </label>
        <label className="admin-logs__field">
          From
          <input
            className="admin-logs__input"
            type="time"
            value={timeFrom}
            onChange={(e) => setTimeFrom(e.target.value)}
          />
        </label>
        <label className="admin-logs__field">
          To
          <input
            className="admin-logs__input"
            type="time"
            value={timeTo}
            onChange={(e) => setTimeTo(e.target.value)}
          />
        </label>

        <div className="admin-logs__levels">
          {LEVELS.map((lv) => (
            <button
              key={lv}
              className={[
                'admin-logs__btn',
                activeLevels.has(lv) ? 'admin-logs__btn--active' : '',
              ].join(' ')}
              onClick={() => toggleLevel(lv)}
              type="button"
            >
              {lv}
            </button>
          ))}
        </div>

        <input
          className="admin-logs__input admin-logs__input--search"
          type="text"
          placeholder="🔍 search…"
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
        />

        <button
          className={[
            'admin-logs__btn',
            follow ? 'admin-logs__btn--active' : '',
          ].join(' ')}
          onClick={() => setFollow((x) => !x)}
          disabled={!isLiveScope}
          title={isLiveScope ? 'Toggle live tail' : 'Live tail only available for today / full day / no filter'}
          type="button"
        >
          Follow
        </button>
        <button className="admin-logs__btn" onClick={onClear} type="button">
          Clear
        </button>
        <a
          className="admin-logs__btn"
          href={downloadLogUrl(date)}
          download
          type="button"
        >
          Download
        </a>

        <div className="admin-logs__spacer" />
        <span className="admin-logs__counts">
          {lines.length} shown · {totalMatched} matched
        </span>
      </div>

      <div className="admin-logs__console" ref={consoleRef} onScroll={onConsoleScroll}>
        {nextCursor != null && (
          <div className="admin-logs__loadmore">
            <button
              className="admin-logs__loadmore-btn"
              onClick={loadMore}
              disabled={loading}
              type="button"
            >
              {loading ? 'Loading…' : `Load older (${totalMatched - lines.length} more)`}
            </button>
          </div>
        )}

        {lines.length === 0 && !loading && (
          <div className="admin-logs__empty">No logs in selected range</div>
        )}
        {loading && lines.length === 0 && (
          <div className="admin-logs__loading">Loading…</div>
        )}

        {lines.map((rec, i) => (
          <LogLine key={i} rec={rec} keyword={debouncedKw} />
        ))}

        {!follow && pendingNew > 0 && (
          <button className="admin-logs__jumpdown" onClick={onJumpDown} type="button">
            ↓ {pendingNew} new
          </button>
        )}
      </div>

      {showDocs && (
        <DocDrawer
          title="Admin · 日志使用指南"
          load={fetchLogsGuide}
          onClose={() => setShowDocs(false)}
        />
      )}
    </div>
  )
}
