import { useCallback, useEffect, useRef, useState } from 'react'
import { createSession, listProjects, listSessions, resetLearning } from './api'
import { ChatInput } from './components/ChatInput'
import { ChatMessage } from './components/ChatMessage'
import { Sidebar } from './components/Sidebar'
import { SuggestionButtons } from './components/SuggestionButtons'
import { Welcome } from './components/Welcome'
import { useChat } from './hooks/useChat'
import type { Project, Session } from './types'

function App() {
  const [project, setProject] = useState<Project | null>(null)
  const [sessions, setSessions] = useState<Session[]>([])
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const scrollRef = useRef<HTMLDivElement>(null)

  const { messages, isStreaming, sendMessage, stopStreaming, clearMessages } =
    useChat(activeSessionId ?? null, project?.id)

  // Find the last assistant message with suggestions
  const lastSuggestion = [...messages].reverse().find((m) => m.suggestions)?.suggestions ?? null
  const showSuggestions = lastSuggestion && !isStreaming

  useEffect(() => {
    async function init() {
      try {
        const projects = await listProjects()
        if (projects.items.length > 0) {
          const p = projects.items[0]
          setProject(p)
          const sess = await listSessions(p.id)
          setSessions(sess.items)
        }
      } catch (err) {
        console.error('Init error:', err)
      } finally {
        setLoading(false)
      }
    }
    init()
  }, [])

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages])

  const handleNewSession = useCallback(async () => {
    if (!project) return
    try {
      const sess = await createSession(project.id)
      setSessions((prev) => [sess, ...prev])
      setActiveSessionId(sess.id)
      clearMessages()
    } catch (err) {
      console.error('Create session error:', err)
    }
  }, [project, clearMessages])

  const handleSelectSession = useCallback(
    (id: string) => {
      if (id === activeSessionId) return
      setActiveSessionId(id)
      clearMessages()
    },
    [activeSessionId, clearMessages],
  )

  const handleReset = useCallback(async () => {
    if (!project) return
    if (!confirm('确认要清除所有学习数据重新开始？这会删除所有会话、记忆和学习进度。')) return
    try {
      await resetLearning(project.id)
      setSessions([])
      setActiveSessionId(null)
      clearMessages()
    } catch (err) {
      console.error('Reset error:', err)
    }
  }, [project, clearMessages])

  if (loading) {
    return (
      <div className="loading-screen">
        <div className="loading-spinner" />
      </div>
    )
  }

  const activeSession = sessions.find((s) => s.id === activeSessionId) ?? null

  return (
    <div className="app">
      <Sidebar
        sessions={sessions}
        activeId={activeSessionId}
        onSelect={handleSelectSession}
        onNew={handleNewSession}
        onReset={handleReset}
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
            {activeSession?.title || 'New chat'}
          </span>
        </header>

        <div className="messages-container" ref={scrollRef}>
          {messages.length === 0 ? (
            <Welcome />
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
          <ChatInput
            onSend={sendMessage}
            onStop={stopStreaming}
            disabled={!activeSessionId}
            isStreaming={isStreaming}
          />
        </div>
      </main>
    </div>
  )
}

export default App
