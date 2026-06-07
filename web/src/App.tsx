import { useCallback, useEffect, useRef, useState } from 'react'
import { createSession, deleteProject, deleteSession, listProjects, listSessions, resetLearning, streamResumeCreateSession } from './api'
import { BerryLoading } from './components/BerryLoading'
import { ChatInput } from './components/ChatInput'
import { ChatMessage } from './components/ChatMessage'
import { ConfirmModal } from './components/ConfirmModal'
import { NewProjectModal } from './components/NewProjectModal'
import { Sidebar } from './components/Sidebar'
import { SuggestionButtons } from './components/SuggestionButtons'
import { Welcome } from './components/Welcome'
import { useChat } from './hooks/useChat'
import type { Project, Session } from './types'

interface ConfirmState {
  title: string
  message: string
  confirmLabel: string
  variant: 'danger' | 'default'
  onConfirm: () => void
}

function App() {
  const [projects, setProjects] = useState<Project[]>([])
  const [sessionsByProject, setSessionsByProject] = useState<Record<string, Session[]>>({})
  const [activeProjectId, setActiveProjectId] = useState<string | null>(null)
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [showNewProjectModal, setShowNewProjectModal] = useState(false)
  const [confirmState, setConfirmState] = useState<ConfirmState | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)

  const activeProject = projects.find((p) => p.id === activeProjectId) ?? null
  const {
    messages,
    isStreaming,
    sendMessage,
    stopStreaming,
    clearMessages,
    feedEvent,
    beginExternalTurn,
    finishExternalTurn,
  } = useChat(activeSessionId ?? null, activeProjectId ?? undefined)

  const lastSuggestion = [...messages].reverse().find((m) => m.suggestions)?.suggestions ?? null
  const showSuggestions = lastSuggestion && !isStreaming

  // Load sessions for a project (and cache)
  const loadProjectSessions = useCallback(async (projectId: string) => {
    try {
      const sess = await listSessions(projectId)
      setSessionsByProject((prev) => ({ ...prev, [projectId]: sess.items }))
      return sess.items
    } catch (err) {
      console.error('listSessions error:', err)
      return []
    }
  }, [])

  // Initial bootstrap
  useEffect(() => {
    async function init() {
      try {
        const ps = await listProjects()
        // learning projects first, then others; within each group, newest first
        const sorted = [...ps.items].sort((a, b) => {
          if (a.domain === 'learning' && b.domain !== 'learning') return -1
          if (a.domain !== 'learning' && b.domain === 'learning') return 1
          return b.created_at.localeCompare(a.created_at)
        })
        setProjects(sorted)
        if (sorted.length > 0) {
          const first = sorted[0]
          setActiveProjectId(first.id)
          const sess = await loadProjectSessions(first.id)
          if (sess.length > 0) {
            setActiveSessionId(sess[0].id)
          }
        }
      } catch (err) {
        console.error('Init error:', err)
      } finally {
        setLoading(false)
      }
    }
    init()
  }, [loadProjectSessions])

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages])

  const handleSelectProject = useCallback(
    async (projectId: string) => {
      if (projectId === activeProjectId) return
      setActiveProjectId(projectId)
      clearMessages()
      const sess = sessionsByProject[projectId] ?? (await loadProjectSessions(projectId))
      setActiveSessionId(sess.length > 0 ? sess[0].id : null)
    },
    [activeProjectId, sessionsByProject, loadProjectSessions, clearMessages],
  )

  const handleSelectSession = useCallback(
    (sessionId: string) => {
      if (sessionId === activeSessionId) return
      setActiveSessionId(sessionId)
      clearMessages()
    },
    [activeSessionId, clearMessages],
  )

  const handleNewSession = useCallback(
    (projectId: string) => {
      // Stream session.resume_create — backend creates the session AND
      // primes a "where do you want to pick up?" turn so the user lands
      // on a chat with buttons, not a blank page. Same UX as
      // handleProjectCreated but driven by progress.json instead of a
      // fresh plan.
      const targetProject = projects.find((p) => p.id === projectId)
      const isLearning = targetProject?.domain === 'learning'

      if (!isLearning) {
        // Non-learning project (e.g. demo) — fall back to plain create.
        ;(async () => {
          try {
            const sess = await createSession(projectId)
            setSessionsByProject((prev) => ({
              ...prev,
              [projectId]: [sess, ...(prev[projectId] ?? [])],
            }))
            setActiveProjectId(projectId)
            setActiveSessionId(sess.id)
            clearMessages()
          } catch (err) {
            console.error('Create session error:', err)
          }
        })()
        return
      }

      streamResumeCreateSession(projectId, {
        onSessionCreated: (session) => {
          // Switch active context BEFORE LLM events arrive, so feedEvent
          // routes them into the freshly-armed chat view.
          setSessionsByProject((prev) => ({
            ...prev,
            [projectId]: [session, ...(prev[projectId] ?? [])],
          }))
          setActiveProjectId(projectId)
          setActiveSessionId(session.id)
          clearMessages()
          beginExternalTurn()
        },
        onEvent: (ev) => {
          feedEvent(ev)
        },
        onError: (msg) => {
          console.error('resume_create_session error:', msg)
          finishExternalTurn()
        },
        onDone: () => {
          finishExternalTurn()
          // Refresh project list so progress percent updates if the
          // priming turn touched progress.json.
          listProjects()
            .then((ps) => setProjects(ps.items))
            .catch((err) => console.error('post-resume listProjects failed:', err))
        },
      })
    },
    [projects, clearMessages, feedEvent, beginExternalTurn, finishExternalTurn],
  )

  const handleNewProject = useCallback(() => {
    setShowNewProjectModal(true)
  }, [])

  const handleProjectCreated = useCallback(
    async (project: Project, session: Session) => {
      // Backend has committed Project + Session. Switch active context
      // and arm the chat view for the priming turn that's already
      // streaming behind us. Modal closes; events from the create stream
      // continue flowing through onStreamEvent → feedEvent.
      setShowNewProjectModal(false)
      clearMessages()
      setSessionsByProject((prev) => ({ ...prev, [project.id]: [session] }))
      setActiveProjectId(project.id)
      setActiveSessionId(session.id)
      beginExternalTurn()
      // Re-fetch project list (progress fresh)
      try {
        const ps = await listProjects()
        setProjects(ps.items)
      } catch (err) {
        console.error('post-create listProjects failed:', err)
      }
    },
    [clearMessages, beginExternalTurn],
  )

  const handleProjectStreamEvent = useCallback(
    (event: Record<string, unknown>) => {
      feedEvent(event)
    },
    [feedEvent],
  )

  const handleProjectStreamDone = useCallback(() => {
    finishExternalTurn()
    // Re-fetch project to refresh progress after init turn (LLM may have
    // touched progress.json).
    listProjects()
      .then((ps) => setProjects(ps.items))
      .catch((err) => console.error('post-stream listProjects failed:', err))
  }, [finishExternalTurn])

  const handleResetProject = useCallback(
    (projectId: string) => {
      setConfirmState({
        title: 'Reset Topic',
        message: 'This will clear all sessions and progress for this topic. This action cannot be undone.',
        confirmLabel: 'Reset',
        variant: 'danger',
        onConfirm: async () => {
          setConfirmState(null)
          try {
            await resetLearning(projectId)
            const ps = await listProjects()
            setProjects(ps.items)
            const sess = await listSessions(projectId)
            setSessionsByProject((prev) => ({ ...prev, [projectId]: sess.items }))
            const newSess = await createSession(projectId)
            setSessionsByProject((prev) => ({
              ...prev,
              [projectId]: [newSess],
            }))
            setActiveSessionId(newSess.id)
            clearMessages()
          } catch (err) {
            console.error('Reset error:', err)
          }
        },
      })
    },
    [clearMessages],
  )

  const handleDeleteProject = useCallback(
    (projectId: string) => {
      const project = projects.find((p) => p.id === projectId)
      setConfirmState({
        title: 'Delete Topic',
        message: `This will permanently delete "${project?.title || project?.name || 'this topic'}" including all sessions, progress, and workspace files. This cannot be undone.`,
        confirmLabel: 'Delete',
        variant: 'danger',
        onConfirm: async () => {
          setConfirmState(null)
          try {
            await deleteProject(projectId)
            const ps = await listProjects()
            setProjects(ps.items)
            setSessionsByProject((prev) => {
              const next = { ...prev }
              delete next[projectId]
              return next
            })
            if (activeProjectId === projectId) {
              const firstProject = ps.items[0]
              if (firstProject) {
                setActiveProjectId(firstProject.id)
                const sess = await listSessions(firstProject.id)
                setSessionsByProject((prev) => ({ ...prev, [firstProject.id]: sess.items }))
                setActiveSessionId(sess.items[0]?.id ?? null)
              } else {
                setActiveProjectId(null)
                setActiveSessionId(null)
              }
              clearMessages()
            }
          } catch (err) {
            console.error('Delete error:', err)
          }
        },
      })
    },
    [projects, activeProjectId, clearMessages],
  )

  const handleDeleteSession = useCallback(
    (sessionId: string, projectId: string) => {
      setConfirmState({
        title: 'Delete Session',
        message: 'This will permanently delete this conversation. This cannot be undone.',
        confirmLabel: 'Delete',
        variant: 'danger',
        onConfirm: async () => {
          setConfirmState(null)
          try {
            await deleteSession(sessionId)
            const sess = await listSessions(projectId)
            setSessionsByProject((prev) => ({ ...prev, [projectId]: sess.items }))

            if (sess.items.length > 0) {
              if (activeSessionId === sessionId) {
                setActiveSessionId(sess.items[0].id)
                clearMessages()
              }
            } else {
              const proj = projects.find((p) => p.id === projectId)
              if (proj?.domain === 'learning') {
                streamResumeCreateSession(projectId, {
                  onSessionCreated: (session) => {
                    setSessionsByProject((prev) => ({
                      ...prev,
                      [projectId]: [session],
                    }))
                    setActiveProjectId(projectId)
                    setActiveSessionId(session.id)
                    clearMessages()
                    beginExternalTurn()
                  },
                  onEvent: (ev) => feedEvent(ev),
                  onError: (msg) => {
                    console.error('auto-resume after delete error:', msg)
                    finishExternalTurn()
                  },
                  onDone: () => {
                    finishExternalTurn()
                    listProjects()
                      .then((ps) => setProjects(ps.items))
                      .catch(() => {})
                  },
                })
              } else {
                const newSess = await createSession(projectId)
                setSessionsByProject((prev) => ({
                  ...prev,
                  [projectId]: [newSess],
                }))
                setActiveProjectId(projectId)
                setActiveSessionId(newSess.id)
                clearMessages()
              }
            }
          } catch (err) {
            console.error('Delete session error:', err)
          }
        },
      })
    },
    [activeSessionId, projects, clearMessages, feedEvent, beginExternalTurn, finishExternalTurn],
  )

  if (loading) {
    return (
      <div className="loading-screen">
        <BerryLoading text="Loading" />
      </div>
    )
  }

  const activeSession = (sessionsByProject[activeProjectId ?? ''] ?? []).find(
    (s) => s.id === activeSessionId,
  ) ?? null

  return (
    <div className="app">
      <Sidebar
        projects={projects}
        sessionsByProject={sessionsByProject}
        activeProjectId={activeProjectId}
        activeSessionId={activeSessionId}
        onSelectProject={handleSelectProject}
        onSelectSession={handleSelectSession}
        onNewSession={handleNewSession}
        onNewProject={handleNewProject}
        onResetProject={handleResetProject}
        onDeleteProject={handleDeleteProject}
        onDeleteSession={handleDeleteSession}
        open={sidebarOpen}
        onToggle={() => setSidebarOpen(!sidebarOpen)}
      />
      <main className="main">
        <header className="main-header">
          <button
            className="menu-btn"
            onClick={() => setSidebarOpen(!sidebarOpen)}
            title="Toggle sidebar"
          >
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="3" y1="6" x2="21" y2="6" />
              <line x1="3" y1="12" x2="21" y2="12" />
              <line x1="3" y1="18" x2="21" y2="18" />
            </svg>
          </button>
          <span className="header-title">
            {activeProject
              ? `${activeProject.title || activeProject.name}${activeSession?.title ? ` · ${activeSession.title}` : ''}`
              : 'Berry'}
          </span>
          {activeProjectId && <span className="status-dot" />}
        </header>

        <div className="messages-container" ref={scrollRef}>
          {messages.length === 0 ? (
            <Welcome
              hasProjects={projects.length > 0}
              onCreateProject={() => setShowNewProjectModal(true)}
            />
          ) : (
            <div className="messages">
              {messages.map((msg) => (
                <ChatMessage key={msg.id} message={msg} />
              ))}
              {showSuggestions && (
                <SuggestionButtons
                  suggestion={lastSuggestion}
                  onPick={sendMessage}
                  disabled={isStreaming}
                />
              )}
              {isStreaming && messages[messages.length - 1]?.role === 'user' && (
                <div className="message assistant">
                  <div className="typing-indicator">
                    <span /><span /><span />
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        <div className="input-area">
          {activeSessionId ? (
            <ChatInput
              onSend={sendMessage}
              onStop={stopStreaming}
              disabled={false}
              isStreaming={isStreaming}
            />
          ) : (
            <div className="input-empty-state">
              <span className="input-empty-hint">
                {projects.length > 0
                  ? 'Select a session or create a new topic to start'
                  : 'Create a learning topic to start chatting'}
              </span>
            </div>
          )}
        </div>
      </main>

      {showNewProjectModal && (
        <NewProjectModal
          onClose={() => setShowNewProjectModal(false)}
          onCreated={handleProjectCreated}
          onStreamEvent={handleProjectStreamEvent}
          onStreamDone={handleProjectStreamDone}
        />
      )}

      {confirmState && (
        <ConfirmModal
          title={confirmState.title}
          message={confirmState.message}
          confirmLabel={confirmState.confirmLabel}
          variant={confirmState.variant}
          onConfirm={confirmState.onConfirm}
          onCancel={() => setConfirmState(null)}
        />
      )}
    </div>
  )
}

export default App
