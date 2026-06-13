import type { Project, Session } from '../types'

interface Props {
  projects: Project[]
  sessionsByProject: Record<string, Session[]>
  activeProjectId: string | null
  activeSessionId: string | null
  onSelectProject: (projectId: string) => void
  onSelectSession: (sessionId: string) => void
  onNewSession: (projectId: string) => void
  onNewProject: () => void
  onResetProject: (projectId: string) => void
  onDeleteProject: (projectId: string) => void
  onDeleteSession: (sessionId: string, projectId: string) => void
  open: boolean
  onToggle: () => void
  isAdmin?: boolean
  onOpenAdminLogs?: () => void
}

export function Sidebar({
  projects,
  sessionsByProject,
  activeProjectId,
  activeSessionId,
  onSelectProject,
  onSelectSession,
  onNewSession,
  onNewProject,
  onResetProject,
  onDeleteProject,
  onDeleteSession,
  open,
  onToggle,
  isAdmin,
  onOpenAdminLogs,
}: Props) {
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
          <div className="sidebar-mascot">
            <svg width="48" height="48" viewBox="0 0 64 64" fill="none">
              <rect x="16" y="24" width="32" height="24" rx="4" fill="#1a1a1a" stroke="#ffe600" strokeWidth="2"/>
              <rect x="14" y="10" width="28" height="22" rx="6" fill="#1a1a1a" stroke="#ffe600" strokeWidth="2"/>
              <polygon points="18,14 22,4 28,12" fill="#1a1a1a" stroke="#ffe600" strokeWidth="1.5"/>
              <polygon points="20,13 22,7 26,12" fill="#ffe600"/>
              <polygon points="46,14 42,4 36,12" fill="#1a1a1a" stroke="#ffe600" strokeWidth="1.5"/>
              <polygon points="44,13 42,7 38,12" fill="#ffe600"/>
              <rect className="mascot-blink-eye" x="22" y="18" width="6" height="6" rx="1" fill="#ffe600" style={{ transformOrigin: '25px 21px' }}/>
              <rect className="mascot-blink-eye" x="36" y="18" width="6" height="6" rx="1" fill="#ffe600" style={{ transformOrigin: '39px 21px' }}/>
              <rect x="24" y="19" width="3" height="4" rx="0.5" fill="#0A0A0A" className="mascot-blink-eye" style={{ transformOrigin: '25.5px 21px' }}/>
              <rect x="38" y="19" width="3" height="4" rx="0.5" fill="#0A0A0A" className="mascot-blink-eye" style={{ transformOrigin: '39.5px 21px' }}/>
              <path d="M29 27 L32 30 L35 27" stroke="#ffe600" strokeWidth="1.5" fill="none" strokeLinecap="round"/>
              <rect x="26" y="30" width="12" height="10" rx="1" fill="#1a1a1a" stroke="#ffe600" strokeWidth="1"/>
              <text x="32" y="38" textAnchor="middle" fill="#ffe600" fontSize="7" fontWeight="800" fontFamily="monospace">B</text>
              <path className="mascot-tail" d="M48 32 Q56 28 54 20" stroke="#ffe600" strokeWidth="2.5" fill="none" strokeLinecap="round"/>
            </svg>
          </div>
          <button className="sidebar-close-btn" onClick={onToggle} title="Collapse">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <rect x="3" y="3" width="18" height="18" rx="2" />
              <line x1="9" y1="3" x2="9" y2="21" />
            </svg>
          </button>
        </div>

        {/* Hero NEW-TOPIC button: yellow-on-black slab */}
        <button className="topic-cta" onClick={onNewProject}>
          <span className="topic-cta__icon">+</span>
          <span className="topic-cta__label">NEW TOPIC</span>
          <span className="topic-cta__chevron" aria-hidden="true">›</span>
        </button>

        <div className="sidebar-projects">
          {projects.length === 0 ? (
            <div className="sidebar-empty">
              <span className="sidebar-empty__line">NO TOPICS YET</span>
              <span className="sidebar-empty__hint">PRESS [ + NEW TOPIC ] TO BEGIN</span>
            </div>
          ) : (
            projects.map((p, idx) => {
              const isActive = p.id === activeProjectId
              const sessions = sessionsByProject[p.id] ?? []
              const numLabel = String(idx + 1).padStart(3, '0')
              return (
                <article
                  key={p.id}
                  className={`topic-card ${isActive ? 'topic-card--active' : ''}`}
                  data-phase={p.progress?.phase ?? 'uninitialized'}
                >
                  <button
                    className="topic-card__header"
                    onClick={() => onSelectProject(p.id)}
                    type="button"
                  >
                    <span className="topic-card__num">#{numLabel}</span>
                    <span className="topic-card__dot" aria-hidden="true">●</span>
                    <span className="topic-card__title">
                      {(p.title || p.name).toUpperCase()}
                    </span>
                    <span
                      className="topic-card__menu"
                      role="button"
                      tabIndex={0}
                      onClick={(e) => {
                        e.stopPropagation()
                        onDeleteProject(p.id)
                      }}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.stopPropagation()
                          onDeleteProject(p.id)
                        }
                      }}
                      title="Delete topic"
                    >
                      [/]
                    </span>
                  </button>

                  <div className="topic-card__progress-row">
                    <ProgressBar progress={p.progress} />
                  </div>

                  <div className="topic-card__meta">
                    {renderMeta(p)}
                  </div>

                  {isActive && (
                    <div className="topic-card__sessions">
                      <div className="topic-card__divider" />
                      {sessions.length === 0 ? (
                        <div className="topic-session topic-session--empty">
                          NO SESSIONS · WAITING
                        </div>
                      ) : (
                        sessions.map((s) => {
                          const isActiveSession = s.id === activeSessionId
                          return (
                            <div key={s.id} className="topic-session-row">
                              <button
                                className={`topic-session ${isActiveSession ? 'topic-session--active' : ''}`}
                                onClick={() => onSelectSession(s.id)}
                                type="button"
                              >
                                <span className="topic-session__bullet">·</span>
                                <span className="topic-session__time">
                                  {formatSessionId(s.id)}
                                </span>
                                {isActiveSession && (
                                  <span className="topic-session__indicator" aria-hidden="true">▶</span>
                                )}
                              </button>
                              <button
                                className="topic-session__delete"
                                onClick={(e) => {
                                  e.stopPropagation()
                                  onDeleteSession(s.id, p.id)
                                }}
                                title="Delete session"
                                type="button"
                              >
                                ×
                              </button>
                            </div>
                          )
                        })
                      )}
                      <button
                        className="topic-session topic-session--new"
                        onClick={() => onNewSession(p.id)}
                        type="button"
                      >
                        <span className="topic-session__bullet">+</span>
                        <span className="topic-session__time">NEW SESSION</span>
                      </button>
                    </div>
                  )}
                </article>
              )
            })
          )}
        </div>

        <div className="data-stream">
          <div className="data-stream__inner">
            <span>BERRY://LEARNING</span>
            <span>&#9632;</span>
            <span>SESSION ACTIVE</span>
            <span>&#9632;</span>
            <span>{projects.length} TOPICS</span>
            <span>&#9632;</span>
            <span>READY</span>
            <span>&#9632;</span>
            <span>BERRY://LEARNING</span>
            <span>&#9632;</span>
            <span>SESSION ACTIVE</span>
            <span>&#9632;</span>
            <span>{projects.length} TOPICS</span>
            <span>&#9632;</span>
            <span>READY</span>
            <span>&#9632;</span>
          </div>
        </div>

        {(activeProjectId || isAdmin) && (
          <div className="sidebar-bottom">
            {isAdmin && onOpenAdminLogs && (
              <button
                className="reset-btn"
                onClick={onOpenAdminLogs}
                title="Open admin log viewer"
                style={{ marginBottom: activeProjectId ? 8 : 0 }}
                type="button"
              >
                <span className="reset-btn__warn" aria-hidden="true">▤</span>
                <span className="reset-btn__label">ADMIN · LOGS</span>
              </button>
            )}
            {activeProjectId && (
              <button
                className="reset-btn"
                onClick={() => onResetProject(activeProjectId)}
                title="Wipe sessions + progress for current topic"
              >
                <span className="reset-btn__warn" aria-hidden="true">⚠</span>
                <span className="reset-btn__label">RESET CURRENT</span>
              </button>
            )}
          </div>
        )}
      </aside>
    </>
  )
}

function ProgressBar({ progress }: { progress: Project['progress'] }) {
  if (!progress || progress.phase === 'uninitialized') {
    return (
      <span className="progress">
        <span className="progress__track">
          <span className="progress__fill progress__fill--zero" style={{ width: 0 }} />
        </span>
        <span className="progress__pct">--%</span>
      </span>
    )
  }
  const pct = Math.max(0, Math.min(100, progress.percent))
  return (
    <span className={`progress progress--${progress.phase}`}>
      <span className="progress__track">
        <span className="progress__fill" style={{ width: `${pct}%` }} />
      </span>
      <span className="progress__pct">{pct}%</span>
    </span>
  )
}

function renderMeta(p: Project): string {
  const prog = p.progress
  if (!prog || prog.phase === 'uninitialized') {
    return 'WAITING · NO PLAN YET'
  }
  if (prog.phase === 'planning') {
    return 'PLANNING · 0/0 ATOMS'
  }
  if (prog.phase === 'done') {
    return `COMPLETED · ${prog.done_atoms}/${prog.total_atoms} ATOMS`
  }
  // learning
  return `LEARNING · ${prog.done_atoms}/${prog.total_atoms} ATOMS`
}

function formatSessionId(id: string): string {
  const m = /^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})/.exec(id)
  if (!m) return id.slice(0, 8).toUpperCase()
  const utc = new Date(`${m[1]}-${m[2]}-${m[3]}T${m[4]}:${m[5]}:00Z`)
  const mm = String(utc.getMonth() + 1).padStart(2, '0')
  const dd = String(utc.getDate()).padStart(2, '0')
  const hh = String(utc.getHours()).padStart(2, '0')
  const mi = String(utc.getMinutes()).padStart(2, '0')
  return `${mm}/${dd} ${hh}:${mi}`
}
