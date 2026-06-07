import type { SuggestionEvent } from '../types'

interface Props {
  suggestion: SuggestionEvent
  onPick: (text: string) => void
  disabled: boolean
}

export function SuggestionButtons({ suggestion, onPick, disabled }: Props) {
  if (!suggestion.options.length) return null

  return (
    <div className="suggestions">
      {suggestion.prompt && (
        <div className="suggestions-prompt">{suggestion.prompt}</div>
      )}
      <div className="suggestions-row">
        {suggestion.options.map((opt) => (
          <button
            key={opt.label}
            className={`suggestion-btn ${opt.recommended ? 'recommended' : ''}`}
            onClick={() => onPick(opt.label)}
            disabled={disabled}
            title={opt.description ?? undefined}
          >
            {opt.recommended && <span className="rec-star">⭐ </span>}
            <span className="suggestion-label">{opt.label}</span>
            {opt.description && (
              <span className="suggestion-desc">{opt.description}</span>
            )}
          </button>
        ))}
      </div>
    </div>
  )
}
