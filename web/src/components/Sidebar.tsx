import type { Session } from '../types'

interface Props {
  sessions: Session[]
  activeId: string | null
  onSelect: (id: string) => void
  onNew: () => void
  onReset: () => void
  open: boolean
  onToggle: () => void
}

export function Sidebar({ sessions, activeId, onSelect, onNew, onReset, open, onToggle }: Props) {
  return (
    <>
      {!open && (
        <button className="sidebar-reopen" onClick={onToggle} title="Open sidebar">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <line x1="3" y1="6" x2="21" y2="6" />
            <line x1="3" y1="12" x2="21" y2="12" />
            <line x1="3" y1="18" x2="21" y2="18" />
          </svg>
        </button>
      )}
      <aside className={`sidebar ${open ? 'open' : 'closed'}`}>
        <div className="sidebar-top">
          <button className="new-chat-btn" onClick={onNew}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="12" y1="5" x2="12" y2="19" />
              <line x1="5" y1="12" x2="19" y2="12" />
            </svg>
            New chat
          </button>
          <button className="sidebar-close-btn" onClick={onToggle}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <rect x="3" y="3" width="18" height="18" rx="2" />
              <line x1="9" y1="3" x2="9" y2="21" />
            </svg>
          </button>
        </div>

        <div className="sidebar-sessions">
          {sessions.length === 0 ? (
            <div className="sidebar-empty">No conversations yet</div>
          ) : (
            sessions.map((s) => (
              <button
                key={s.id}
                className={`session-item ${s.id === activeId ? 'active' : ''}`}
                onClick={() => onSelect(s.id)}
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" opacity="0.6">
                  <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
                </svg>
                <span className="session-label">
                  {s.title || s.id.slice(0, 8)}
                </span>
              </button>
            ))
          )}
        </div>

        <div className="sidebar-bottom">
          <button className="reset-btn" onClick={onReset} title="Clear all learning data and start fresh">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <polyline points="1 4 1 10 7 10" />
              <path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10" />
            </svg>
            重新开始
          </button>
        </div>
      </aside>
    </>
  )
}
