import './BerryLoading.css'

interface Props {
  text?: string
}

export function BerryLoading({ text = 'Loading...' }: Props) {
  return (
    <div className="berry-loading">
      <div className="berry-loading__runner">
        {/* Cat mascot running - SVG frame animation */}
        <svg className="berry-loading__cat" width="64" height="64" viewBox="0 0 64 64" fill="none">
          {/* Body */}
          <rect x="16" y="24" width="32" height="24" rx="4" fill="#1a1a1a" stroke="#ffe600" strokeWidth="2"/>
          {/* Head */}
          <rect x="14" y="10" width="28" height="22" rx="6" fill="#1a1a1a" stroke="#ffe600" strokeWidth="2"/>
          {/* Left ear */}
          <polygon points="18,14 22,4 28,12" fill="#1a1a1a" stroke="#ffe600" strokeWidth="1.5"/>
          <polygon points="20,13 22,7 26,12" fill="#ffe600"/>
          {/* Right ear */}
          <polygon points="46,14 42,4 36,12" fill="#1a1a1a" stroke="#ffe600" strokeWidth="1.5"/>
          <polygon points="44,13 42,7 38,12" fill="#ffe600"/>
          {/* Eyes */}
          <rect x="22" y="18" width="6" height="6" rx="1" fill="#ffe600"/>
          <rect x="36" y="18" width="6" height="6" rx="1" fill="#ffe600"/>
          <rect x="24" y="19" width="3" height="4" rx="0.5" fill="#0A0A0A"/>
          <rect x="38" y="19" width="3" height="4" rx="0.5" fill="#0A0A0A"/>
          {/* Mouth */}
          <path d="M29 27 L32 30 L35 27" stroke="#ffe600" strokeWidth="1.5" fill="none" strokeLinecap="round"/>
          {/* Belly B */}
          <rect x="26" y="30" width="12" height="10" rx="1" fill="#1a1a1a" stroke="#ffe600" strokeWidth="1"/>
          <text x="32" y="38" textAnchor="middle" fill="#ffe600" fontSize="7" fontWeight="800" fontFamily="monospace">B</text>
          {/* Front legs (animated via CSS) */}
          <g className="berry-loading__legs-front">
            <rect x="18" y="48" width="6" height="12" rx="2" fill="#1a1a1a" stroke="#ffe600" strokeWidth="1.5"/>
            <rect x="28" y="48" width="6" height="12" rx="2" fill="#1a1a1a" stroke="#ffe600" strokeWidth="1.5"/>
          </g>
          {/* Back legs (animated opposite) */}
          <g className="berry-loading__legs-back">
            <rect x="34" y="48" width="6" height="12" rx="2" fill="#1a1a1a" stroke="#ffe600" strokeWidth="1.5"/>
            <rect x="44" y="48" width="6" height="12" rx="2" fill="#1a1a1a" stroke="#ffe600" strokeWidth="1.5"/>
          </g>
          {/* Tail */}
          <path className="berry-loading__tail" d="M48 32 Q56 28 54 20" stroke="#ffe600" strokeWidth="2.5" fill="none" strokeLinecap="round"/>
        </svg>
        {/* Ground shadow */}
        <div className="berry-loading__shadow" />
      </div>
      {/* Progress dots */}
      <div className="berry-loading__text">
        {text}
        <span className="berry-loading__dots">
          <span>.</span><span>.</span><span>.</span>
        </span>
      </div>
    </div>
  )
}