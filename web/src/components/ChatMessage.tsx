import { useState } from 'react'
import Markdown from 'react-markdown'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism'
import remarkGfm from 'remark-gfm'
import type { ChatMessage as ChatMessageType, ToolCallInfo } from '../types'

interface AskOption {
  label: string
  description?: string | null
  recommended?: boolean
}

/**
 * Inline button group for an ``ask_user_question`` tool call.
 *
 * Rationale: the buttons live on the assistant bubble that issued the
 * question, not as a global floating UI element. This way:
 *   - history replay shows the same buttons that were live at that turn
 *     (rendered straight from ``tool_use.input.options``)
 *   - already-answered questions stay visible but disabled (``hasOutput``
 *     ⇒ the user has moved past this turn), so the chat history stays
 *     coherent even after multiple rounds
 *   - the only live, clickable group is the most recent unanswered one,
 *     guarded by ``answerable`` (caller passes false for old turns).
 */
function AskUserQuestionButtons({
  tc,
  onPick,
  answerable,
}: {
  tc: ToolCallInfo
  onPick?: (text: string) => void
  answerable: boolean
}) {
  const question = (tc.args.question as string) ?? ''
  const options = (tc.args.options as AskOption[] | undefined) ?? []
  // ``tc.output`` is NOT a signal of "user answered" — the backend
  // returns a stub ("presented N options...") the moment the LLM calls
  // the tool, so output is set even when the user hasn't replied yet.
  // Whether this group is still answerable is decided purely by the
  // caller (it knows whether this bubble is the trailing assistant
  // turn with no user reply after it).
  const disabled = !answerable || !onPick

  if (options.length === 0) return null

  return (
    <div className="suggestions">
      {question && <div className="suggestions-prompt">{question}</div>}
      <div className="suggestions-row">
        {options.map((opt) => (
          <button
            key={opt.label}
            className={`suggestion-btn ${opt.recommended ? 'recommended' : ''}`}
            onClick={() => onPick?.(opt.label)}
            disabled={disabled}
            title={opt.description ?? undefined}
          >
            <span className="suggestion-label">
              {opt.recommended && <span className="rec-star">⭐ </span>}
              {opt.label}
              {opt.description && (
                <span className="suggestion-desc"> ({opt.description})</span>
              )}
            </span>
          </button>
        ))}
      </div>
    </div>
  )
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  const handleCopy = () => {
    navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }
  return (
    <button className="copy-btn" onClick={handleCopy}>
      {copied ? (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <polyline points="20 6 9 17 4 12" />
        </svg>
      ) : (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
          <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
        </svg>
      )}
      {copied ? 'Copied!' : 'Copy code'}
    </button>
  )
}

function ToolCallView({ tc }: { tc: ToolCallInfo }) {
  const [expanded, setExpanded] = useState(false)
  const hasOutput = tc.output !== undefined

  return (
    <div className={`tool-call ${expanded ? 'expanded' : ''}`}>
      <button className="tool-call-toggle" onClick={() => setExpanded(!expanded)}>
        <svg
          width="12"
          height="12"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          className={`chevron ${expanded ? 'open' : ''}`}
        >
          <polyline points="9 18 15 12 9 6" />
        </svg>
        <span className="tool-call-name">{tc.name}</span>
        {hasOutput && (
          <span className={tc.isError ? 'tool-badge error' : 'tool-badge ok'}>
            {tc.isError ? 'error' : 'done'}
          </span>
        )}
      </button>
      {expanded && (
        <div className="tool-call-detail">
          <div className="tool-call-section">
            <span className="tool-call-label">Arguments</span>
            <pre className="tool-call-code">{JSON.stringify(tc.args, null, 2)}</pre>
          </div>
          {hasOutput && (
            <div className="tool-call-section">
              <span className="tool-call-label">Output</span>
              <pre className={`tool-call-code ${tc.isError ? 'error' : ''}`}>{tc.output}</pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

const markdownComponents = {
  code({ className, children, ...props }: { className?: string; children?: React.ReactNode }) {
    const match = /language-(\w+)/.exec(className || '')
    const codeStr = String(children).replace(/\n$/, '')
    if (match) {
      return (
        <div className="code-block">
          <div className="code-header">
            <span className="code-lang">{match[1]}</span>
            <CopyButton text={codeStr} />
          </div>
          <SyntaxHighlighter
            style={oneDark}
            language={match[1]}
            PreTag="div"
            customStyle={{
              margin: 0,
              borderRadius: '0 0 8px 8px',
              fontSize: '0.875rem',
              background: '#1e1e2e',
            }}
          >
            {codeStr}
          </SyntaxHighlighter>
        </div>
      )
    }
    return <code className="inline-code" {...props}>{children}</code>
  },
  table({ children }: { children?: React.ReactNode }) {
    return (
      <div className="table-wrapper">
        <table>{children}</table>
      </div>
    )
  },
}

export function ChatMessage({
  message,
  onPickSuggestion,
  isLatestAssistant,
}: {
  message: ChatMessageType
  onPickSuggestion?: (text: string) => void
  isLatestAssistant?: boolean
}) {
  const isUser = message.role === 'user'

  // Split tool calls: ask_user_question renders as inline button group
  // (questions belong to their bubble, not to a global UI slot — so they
  // survive page refresh and stay anchored when newer turns arrive).
  // Everything else stays as the collapsible ToolCallView.
  const toolCalls = message.toolCalls ?? []
  const askToolCalls = toolCalls.filter((tc) => tc.name === 'ask_user_question')
  const otherToolCalls = toolCalls.filter((tc) => tc.name !== 'ask_user_question')

  return (
    <div className={`message ${message.role}`}>
      <div className="message-col">
        <div className="avatar">
          {isUser ? (
            // Friendly round face — same stroke language as berry,
            // mouth + eyes drawn with the same line weight.
            <svg
              width="20"
              height="20"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <circle cx="12" cy="12" r="9" />
              <circle cx="9" cy="10" r="0.9" fill="currentColor" stroke="none" />
              <circle cx="15" cy="10" r="0.9" fill="currentColor" stroke="none" />
              <path d="M8.5 14.5c1 1.2 2.2 1.8 3.5 1.8s2.5-0.6 3.5-1.8" />
            </svg>
          ) : (
            // Blueberry: round berry body with a tiny stem-leaf and a
            // soft smile. Same 1.6 stroke + round caps as the user
            // avatar so the two read as a matched pair.
            <svg
              width="20"
              height="20"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <circle cx="12" cy="13.5" r="7.5" />
              <path d="M12 6 Q12.5 4 14 3.2" />
              <path d="M12 6 Q11.5 4 10 3.6" />
              <circle cx="9.5" cy="12" r="0.8" fill="currentColor" stroke="none" />
              <circle cx="14.5" cy="12" r="0.8" fill="currentColor" stroke="none" />
              <path d="M9.5 15.5c0.8 0.9 1.7 1.3 2.5 1.3s1.7-0.4 2.5-1.3" />
            </svg>
          )}
        </div>
        <div className="message-content">
          {otherToolCalls.length > 0 && (
            <div className="tool-calls">
              {otherToolCalls.map((tc) => (
                <ToolCallView key={tc.id} tc={tc} />
              ))}
            </div>
          )}
          {message.content && (
            <div className="markdown-body">
              <Markdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                {message.content}
              </Markdown>
            </div>
          )}
          {askToolCalls.map((tc) => (
            <AskUserQuestionButtons
              key={tc.id}
              tc={tc}
              onPick={onPickSuggestion}
              answerable={!!isLatestAssistant}
            />
          ))}
        </div>
      </div>
    </div>
  )
}
