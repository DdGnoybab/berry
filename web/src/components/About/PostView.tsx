import Markdown from 'react-markdown'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism'
import remarkGfm from 'remark-gfm'
import { type Post } from '../../data/posts'

const CATEGORY_LABEL: Record<Post['category'], string> = {
  tech: '技术',
  life: '生活',
  note: '杂记',
}

interface PostViewProps {
  post: Post
  onBack: () => void
}

export function PostView({ post, onBack }: PostViewProps) {
  return (
    <article className="about-post">
      <button type="button" className="about-back-btn" onClick={onBack}>
        ← BACK
      </button>

      <header className="about-post__head">
        <div className="about-post__meta">
          <span className="about-tag about-tag--category">
            {CATEGORY_LABEL[post.category]}
          </span>
          <span className="about-post__date">{post.date}</span>
        </div>
        <h1 className="about-post__title">{post.title}</h1>
        {post.tags.length > 0 && (
          <div className="about-post__tags">
            {post.tags.map((t) => (
              <span key={t} className="about-tag">
                {t}
              </span>
            ))}
          </div>
        )}
        <div className="about-post__rule" aria-hidden="true" />
      </header>

      <div className="about-post__body prose-zzz">
        <Markdown
          remarkPlugins={[remarkGfm]}
          components={{
            code({ className, children, ...props }) {
              const match = /language-(\w+)/.exec(className ?? '')
              const code = String(children).replace(/\n$/, '')
              // Inline code (no language token AND no newline) → use plain <code>
              if (!match && !code.includes('\n')) {
                return (
                  <code className={className} {...props}>
                    {children}
                  </code>
                )
              }
              return (
                <SyntaxHighlighter
                  style={oneDark}
                  language={match?.[1] ?? 'text'}
                  PreTag="div"
                  customStyle={{
                    background: '#0D0D0D',
                    border: '2px solid #2A2A2A',
                    borderLeft: '3px solid #FFE600',
                    padding: '1rem',
                    margin: 0,
                  }}
                >
                  {code}
                </SyntaxHighlighter>
              )
            },
          }}
        >
          {post.body}
        </Markdown>
      </div>
    </article>
  )
}
