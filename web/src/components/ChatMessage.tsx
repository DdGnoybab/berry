import { useState } from 'react'
import Markdown from 'react-markdown'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism'
import remarkGfm from 'remark-gfm'
import type { ChatMessage as ChatMessageType, ToolCallInfo } from '../types'

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

export function ChatMessage({ message }: { message: ChatMessageType }) {
  const isUser = message.role === 'user'

  return (
    <div className={`message ${message.role}`}>
      <div className="message-col">
        <div className="avatar">
          {isUser ? (
            <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
              <path d="M12 12c2.7 0 5-2.3 5-5s-2.3-5-5-5-5 2.3-5 5 2.3 5 5 5zm0 2c-3.3 0-10 1.7-10 5v2h20v-2c0-3.3-6.7-5-10-5z" />
            </svg>
          ) : (
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <circle cx="12" cy="12" r="10" />
              <circle cx="12" cy="12" r="4" fill="currentColor" />
            </svg>
          )}
        </div>
        <div className="message-content">
          {message.toolCalls && message.toolCalls.length > 0 && (
            <div className="tool-calls">
              {message.toolCalls.map((tc) => (
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
        </div>
      </div>
    </div>
  )
}
