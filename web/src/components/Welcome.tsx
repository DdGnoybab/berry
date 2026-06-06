export function Welcome() {
  return (
    <div className="welcome">
      <div className="welcome-logo">
        <svg width="48" height="48" viewBox="0 0 48 48" fill="none">
          <circle cx="24" cy="24" r="22" stroke="currentColor" strokeWidth="1.5" opacity="0.3" />
          <circle cx="24" cy="24" r="16" stroke="currentColor" strokeWidth="1.5" opacity="0.5" />
          <circle cx="24" cy="24" r="8" fill="currentColor" opacity="0.8" />
        </svg>
      </div>
      <h1>Berry</h1>
      <p className="welcome-sub">How can I help you today?</p>
    </div>
  )
}
