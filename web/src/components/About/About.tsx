import { useState } from 'react'
import { PostList } from './PostList'
import { PostView } from './PostView'
import { Profile } from './Profile'
import { getPostBySlug } from '../../data/posts'
import './About.css'

interface AboutProps {
  /** Click the BACK button to leave About and return to the chat view. */
  onBack: () => void
}

/**
 * Personal About page — Profile (top) + Posts (list / detail).
 *
 * Reuses the cheap router pattern from App.tsx: sub-mode is a useState, not a
 * real route. The whole view takes over the window (mirrors AdminLogs), so
 * the Sidebar + ChatInput are gone while About is open.
 *
 * "Reference" only borrows the ZZZ aesthetic from /Users/bbb/PROJECT/MYSELF/blog
 * (dark + electric yellow + clipped corners + Bebas Neue display). No data
 * crosses between the two projects.
 */
export function About({ onBack }: AboutProps) {
  const [openSlug, setOpenSlug] = useState<string | null>(null)
  const openPost = openSlug ? getPostBySlug(openSlug) : null

  return (
    <div className="about">
      <header className="about-header">
        <button
          type="button"
          className="about-header__back"
          onClick={onBack}
          title="Back to chat"
          aria-label="back to chat"
        >
          ← BACK
        </button>
        <span className="about-header__title">ABOUT</span>
        <span className="about-header__spacer" aria-hidden="true" />
      </header>

      <div className="about-content">
        {openPost ? (
          <PostView post={openPost} onBack={() => setOpenSlug(null)} />
        ) : (
          <>
            <Profile />
            <PostList onSelect={setOpenSlug} />
          </>
        )}
      </div>
    </div>
  )
}
