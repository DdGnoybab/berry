import type { SuggestionEvent } from '../types'

interface Props {
  suggestion: SuggestionEvent
  onPick: (key: string) => void
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
            key={opt.key}
            className={`suggestion-btn ${opt.recommended ? 'recommended' : ''}`}
            onClick={() => onPick(opt.label)}
            disabled={disabled}
          >
            {opt.recommended && <span className="rec-star">⭐ </span>}
            {opt.label}
          </button>
        ))}
      </div>
    </div>
  )
}
