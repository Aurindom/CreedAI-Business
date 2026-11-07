import React from 'react'

// An original character drawn here, so there's no image file to host or license.
function PennyAvatar({ size = 40, state = 'idle' }) {
  return (
    <svg className={`msc-avatar msc-avatar-${state}`} width={size} height={size} viewBox="0 0 64 64" role="img" aria-label="Penny">
      <circle cx="32" cy="32" r="31" fill="#b86a2c" />
      <circle cx="32" cy="32" r="27" fill="none" stroke="#e2a564" strokeWidth="2" strokeDasharray="2 3" />
      <path d="M13 34C12 16 22 9 32 9s20 7 19 25c-3-7-8-12-13-14-5 5-14 8-21 8-2 2-3 4-4 6z" fill="#2f2019" />
      <circle cx="49" cy="14" r="6" fill="#2f2019" />
      <path d="M16 31c0-4 5-7 8-8 5-1 11-3 14-5 5 2 10 7 10 13 0 12-7 20-16 20S16 43 16 31z" fill="#f2c9a1" />
      <g className="msc-eyes">
        <g className="msc-pupils" fill="#2f2019"><circle cx="25" cy="31" r="2.6" /><circle cx="39" cy="31" r="2.6" /></g>
      </g>
      <path d="M21 25c2-1.500 5-1.500 7 0M36 25c2-1.500 5-1.500 7 0" fill="none" stroke="#2f2019" strokeWidth="1.8" strokeLinecap="round" />
      <circle cx="21" cy="37" r="3" fill="#e9a58a" /><circle cx="43" cy="37" r="3" fill="#e9a58a" />
      <path className="msc-mouth" d="M26 40c2 3.500 10 3.500 12 0-3 1-9 1-12 0z" fill="#8c3b2e" stroke="#8c3b2e" strokeWidth="1.5" strokeLinejoin="round" />
      <g className="msc-dots" fill="#fff"><circle cx="25" cy="57" r={state === "thinking" ? 2 : 0} /><circle cx="32" cy="57" r={state === "thinking" ? 2 : 0} /><circle cx="39" cy="57" r={state === "thinking" ? 2 : 0} /></g>
    </svg>
  )
}

export default PennyAvatar
