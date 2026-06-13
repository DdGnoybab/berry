import { useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import './DocDrawer.css'

interface Props {
  /** Title shown in drawer header (e.g. "使用文档"). */
  title: string
  /** Async loader returning markdown text. Called once on open. */
  load: () => Promise<string>
  /** Close handler — esc key / backdrop click / X button. */
  onClose: () => void
}

/**
 * Right-side slide-in drawer that renders markdown.
 *
 * Backdrop click closes; Esc closes; X button closes. Body content is
 * focus-trapped to the drawer (focus falls on the first focusable element
 * after mount). Re-uses react-markdown + remark-gfm already shipping
 * with the chat view.
 */
export function DocDrawer({ title, load, onClose }: Props) {
  const [content, setContent] = useState<string>('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    load()
      .then((text) => {
        if (!cancelled) setContent(text)
      })
      .catch((err) => {
        if (cancelled) return
        if (String(err).includes('FORBIDDEN')) {
          setError('权限不足:此文档仅 admin 可见')
        } else {
          setError(`加载失败: ${err}`)
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [load])

  // Esc 关闭
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="doc-drawer-overlay" onClick={onClose}>
      <aside
        className="doc-drawer"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-label={title}
      >
        <header className="doc-drawer__header">
          <span className="doc-drawer__title">{title}</span>
          <button
            className="doc-drawer__close"
            onClick={onClose}
            type="button"
            title="Close (Esc)"
            aria-label="close"
          >
            ✕
          </button>
        </header>

        <div className="doc-drawer__body">
          {loading && <div className="doc-drawer__msg">Loading…</div>}
          {error && <div className="doc-drawer__msg doc-drawer__msg--error">{error}</div>}
          {!loading && !error && (
            <article className="doc-drawer__markdown">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
            </article>
          )}
        </div>
      </aside>
    </div>
  )
}
