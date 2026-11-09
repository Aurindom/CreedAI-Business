import React from 'react'

// Arkadio, the Creed AI guide: a shield mascot drawn here, so there's no image file to host or license.
function PennyAvatar({ size = 40, state = 'idle', variant = 'portrait' }) {
  if (variant === 'figure') return <ArkadioFigure size={size} state={state} />
  return (
    <svg className={`msc-avatar msc-avatar-${state}`} width={size} height={size} viewBox="0 0 64 64" role="img" aria-label="Arkadio">
      <circle cx="32" cy="32" r="31" fill="#17112a" />
      <path d="M32 6 53 13v19c0 13-9 22-21 27C20 54 11 45 11 32V13l21-7Z" fill="#3a2a6e" stroke="#d8c8ff" strokeWidth="2" strokeLinejoin="round" />
      <rect x="18" y="16" width="28" height="23" rx="10" fill="#120c20" />
      <g className="msc-eyes">
        <g className="msc-pupils" fill="#ffe9bd"><ellipse cx="26" cy="26" rx="3.4" ry="4.6" /><ellipse cx="38" cy="26" rx="3.4" ry="4.6" /></g>
      </g>
      <path className="msc-mouth" d="M27 33c2 3.200 8 3.200 10 0" fill="none" stroke="#efd1a2" strokeWidth="2.200" strokeLinecap="round" />
      <path d="m25 45 5 5 9-11" fill="none" stroke="#efd1a2" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
      <g className="msc-dots" fill="#fff"><circle cx="25" cy="59" r={state === 'thinking' ? 2 : 0} /><circle cx="32" cy="59" r={state === 'thinking' ? 2 : 0} /><circle cx="39" cy="59" r={state === 'thinking' ? 2 : 0} /></g>
    </svg>
  )
}

function ArkadioFigure({ size, state }) {
  return <svg className={`penny-figure penny-figure-${state}`} width={size} height={Math.round(size * 1.45)} viewBox="0 0 160 232" role="img" aria-label="Arkadio, your animated business guide">
    <defs>
      <linearGradient id="ark-body" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#5a42a8" /><stop offset="1" stopColor="#2c1f5c" /></linearGradient>
    </defs>
    <ellipse className="penny-ground" cx="80" cy="222" rx="42" ry="7" fill="#08060f" opacity=".35" />
    <g className="penny-character">
      <path d="M56 192v18c0 9 22 9 22 0v-14M82 196v14c0 9 22 9 22 0v-18" fill="#efd1a2" />
      <path d="M34 112c-13 6-20 20-20 35" fill="none" stroke="#d8c8ff" strokeWidth="11" strokeLinecap="round" />
      <circle cx="14" cy="151" r="9" fill="#efd1a2" />
      <g className="penny-wave-arm">
        <path d="M118 112c10-3 18-10 24-20" fill="none" stroke="#d8c8ff" strokeWidth="11" strokeLinecap="round" />
        <circle cx="145" cy="87" r="9" fill="#efd1a2" />
      </g>
      <g className="penny-head">
        <path d="M80 2v12" stroke="#efd1a2" strokeWidth="4" strokeLinecap="round" />
        <circle cx="80" cy="4" r="6" fill="#ffd27a" />
        <path d="M80 15 139 35v68c0 48-26 80-59 99-33-19-59-51-59-99V35l59-20Z" fill="url(#ark-body)" stroke="#d8c8ff" strokeWidth="5" strokeLinejoin="round" />
        <path d="M80 27 128 43v60c0 40-22 69-48 85-26-16-48-45-48-85V43l48-16Z" fill="none" stroke="#efd1a2" strokeWidth="2.500" strokeLinejoin="round" />
        <rect x="40" y="32" width="80" height="62" rx="26" fill="#120c20" />
        <g className="penny-figure-eyes">
          <ellipse cx="62" cy="56" rx="9" ry="13" fill="#ffe9bd" /><ellipse cx="98" cy="56" rx="9" ry="13" fill="#ffe9bd" />
          <circle cx="64" cy="52" r="3" fill="#fff" /><circle cx="100" cy="52" r="3" fill="#fff" />
        </g>
        <g className="penny-figure-mouth"><path d="M68 74q13 12 26 0" fill="none" stroke="#efd1a2" strokeWidth="5" strokeLinecap="round" /></g>
        <ellipse cx="48" cy="74" rx="6" ry="3.500" fill="#f58a8a" opacity=".55" /><ellipse cx="112" cy="74" rx="6" ry="3.500" fill="#f58a8a" opacity=".55" />
        <path d="m60 134 14 16 26-34" fill="none" stroke="#efd1a2" strokeWidth="10" strokeLinecap="round" strokeLinejoin="round" />
      </g>
    </g>
    <g className="penny-thoughts" fill="#e4d1ff"><circle cx="123" cy="37" r="3" /><circle cx="134" cy="26" r="4" /><circle cx="148" cy="17" r="5" /></g>
    <g className="penny-reply-bars" stroke="#d8c8ff" strokeWidth="3" strokeLinecap="round"><path d="M12 66v12" /><path d="M20 60v24" /><path d="M28 66v12" /></g>
  </svg>
}

export default PennyAvatar
