import { sortedPosts, type PostCategory } from '../../data/posts'

const CATEGORY_LABEL: Record<PostCategory, string> = {
  tech: '技术',
  life: '生活',
  note: '杂记',
}

interface PostListProps {
  onSelect: (slug: string) => void
}

export function PostList({ onSelect }: PostListProps) {
  if (sortedPosts.length === 0) {
    return (
      <section className="about-empty">
        <p>还没有文章。</p>
      </section>
    )
  }

  return (
    <section className="about-posts">
      <h2 className="about-section-title">「 文章 」</h2>
      <ul className="about-posts__list">
        {sortedPosts.map((post) => (
          <li key={post.slug}>
            <button
              type="button"
              className="about-post-card"
              onClick={() => onSelect(post.slug)}
            >
              <div className="about-post-card__meta">
                <span className="about-tag about-tag--category">
                  {CATEGORY_LABEL[post.category]}
                </span>
                <span className="about-post-card__date">{post.date}</span>
              </div>
              <h3 className="about-post-card__title">{post.title}</h3>
              <p className="about-post-card__excerpt">{post.excerpt}</p>
              {post.tags.length > 0 && (
                <div className="about-post-card__tags">
                  {post.tags.map((t) => (
                    <span key={t} className="about-tag">
                      {t}
                    </span>
                  ))}
                </div>
              )}
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}
