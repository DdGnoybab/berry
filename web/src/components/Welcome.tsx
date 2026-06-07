import { useEffect, useState } from 'react'

interface Props {
  hasProjects: boolean
  onCreateProject: () => void
}

const BOOT_LINES_FRESH = [
  '> BERRY OS v0.1 :: COLD BOOT',
  '> LOADING AGENT ENGINE ............ OK',
  '> LOADING SKILL REGISTRY .......... OK',
  '> SCANNING WORKSPACES ............. 0 FOUND',
  '> SYSTEM STATUS: IDLE',
  '> AWAITING TOPIC INITIALIZATION ...',
]

const BOOT_LINES_RETURNING = [
  '> BERRY OS v0.1 :: WARM BOOT',
  '> RESTORING SESSION CACHE ......... OK',
  '> SKILL REGISTRY .................. OK',
  '> SYSTEM STATUS: ONLINE',
  '> SELECT A TOPIC TO RESUME, OR    ',
  '> INITIALIZE A NEW TOPIC TO BEGIN.',
]

/**
 * Terminal-style welcome with progressive boot-log reveal.
 *
 * Lines appear one at a time, character-by-character, with a blinking
 * cursor parked at the end. After all lines render the cursor stays
 * blinking on the last line. Total reveal ~2.5s.
 */
function useTypewriterLines(lines: string[], charDelay = 18, lineDelay = 220) {
  const [revealed, setRevealed] = useState<string[]>([])
  const [doneAll, setDoneAll] = useState(false)

  useEffect(() => {
    if (charDelay === 0) {
      setRevealed([...lines])
      setDoneAll(true)
      return
    }
    let cancelled = false
    setRevealed([])
    setDoneAll(false)

    async function run() {
      for (let i = 0; i < lines.length; i++) {
        const line = lines[i]
        for (let c = 0; c <= line.length; c++) {
          if (cancelled) return
          await new Promise((r) => setTimeout(r, charDelay))
          setRevealed((prev) => {
            const next = [...prev]
            next[i] = line.slice(0, c)
            return next
          })
        }
        await new Promise((r) => setTimeout(r, lineDelay))
        if (cancelled) return
      }
      setDoneAll(true)
    }
    run()
    return () => {
      cancelled = true
    }
  }, [lines, charDelay, lineDelay])

  return { revealed, doneAll }
}

export function Welcome({ hasProjects, onCreateProject }: Props) {
  const lines = hasProjects ? BOOT_LINES_RETURNING : BOOT_LINES_FRESH
  const { revealed, doneAll } = useTypewriterLines(
    lines,
    0,
    0,
  )

  return (
    <div className="boot-screen">
      {/* corner brackets — matches Sidebar's industrial vibe */}
      <span className="boot-corner boot-corner--tl" aria-hidden="true" />
      <span className="boot-corner boot-corner--tr" aria-hidden="true" />
      <span className="boot-corner boot-corner--bl" aria-hidden="true" />
      <span className="boot-corner boot-corner--br" aria-hidden="true" />

      <div className="boot-frame">
        {/* nested scan boxes (B) */}
        <div className="scan-box scan-box--outer" aria-hidden="true">
          <div className="scan-box__corner scan-box__corner--tl" />
          <div className="scan-box__corner scan-box__corner--tr" />
          <div className="scan-box__corner scan-box__corner--bl" />
          <div className="scan-box__corner scan-box__corner--br" />
        </div>
        <div className="scan-box scan-box--inner" aria-hidden="true">
          <div className="scan-box__corner scan-box__corner--tl" />
          <div className="scan-box__corner scan-box__corner--tr" />
          <div className="scan-box__corner scan-box__corner--bl" />
          <div className="scan-box__corner scan-box__corner--br" />
        </div>

        {/* moving scan line (top→bottom) */}
        <div className="scan-line" aria-hidden="true" />

        {/* crosshair */}
        <div className="crosshair" aria-hidden="true">
          <span className="crosshair__h" />
          <span className="crosshair__v" />
          <span className="crosshair__dot" />
        </div>

        <div className="boot-content">
          <div className="boot-version">vs.001</div>

          <h1 className="boot-title">
            <span>B</span>
            <span>E</span>
            <span>R</span>
            <span>R</span>
            <span>Y</span>
          </h1>
          <div className="boot-subtitle">AI · LEARNING · ENGINE</div>

          <div className="boot-divider" />

          {/* boot-log (A) */}
          <div className="boot-log">
            {lines.map((_, i) => (
              <div
                key={i}
                className={`boot-log__line ${
                  revealed[i] !== undefined ? 'boot-log__line--shown' : ''
                }`}
              >
                {revealed[i] ?? ''}
                {/* cursor sits at the end of the last revealed line */}
                {i === lines.length - 1 && doneAll && (
                  <span className="boot-cursor">█</span>
                )}
                {revealed[i] !== undefined &&
                  revealed[i].length < lines[i].length && (
                    <span className="boot-cursor">█</span>
                  )}
              </div>
            ))}
          </div>

          <div className="boot-divider" />

          <button
            className={`boot-cta ${doneAll ? 'boot-cta--ready' : ''}`}
            onClick={onCreateProject}
            disabled={!doneAll}
          >
            <span className="boot-cta__bracket">[</span>
            <span className="boot-cta__icon">+</span>
            <span className="boot-cta__label">INITIALIZE TOPIC</span>
            <span className="boot-cta__bracket">]</span>
          </button>

          <div className="boot-footer">
            <span>SYS://BERRY</span>
            <span className="boot-footer__sep">·</span>
            <span>{hasProjects ? 'WAITING_FOR_INPUT' : 'COLD_BOOT_COMPLETE'}</span>
            <span className="boot-footer__sep">·</span>
            <span className="boot-footer__pulse">●</span>
          </div>
        </div>
      </div>
    </div>
  )
}
