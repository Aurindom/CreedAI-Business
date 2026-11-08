import React from 'react'

// An original character drawn here, so there's no image file to host or license.
function PennyAvatar({ size = 40, state = 'idle', variant = 'portrait' }) {
  if (variant === 'figure') return <PennyFigure size={size} state={state} />
  return (
    <svg className={`msc-avatar msc-avatar-${state}`} width={size} height={size} viewBox="0 0 64 64" role="img" aria-label="Penny">
      <circle cx="32" cy="32" r="31" fill="#33263f" />
      <circle cx="32" cy="32" r="30" fill="none" stroke="#a68abc" strokeWidth="1" />
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

function PennyFigure({ size, state }) {
  return <svg className={`penny-figure penny-figure-${state}`} width={size} height={Math.round(size * 1.45)} viewBox="0 0 160 232" role="img" aria-label="Penny, your animated business guide">
    <ellipse className="penny-ground" cx="80" cy="222" rx="39" ry="7" fill="#08060f" opacity=".35" />
    <g className="penny-character">
      <path d="M56 170l-3 34c-1 9 15 9 16 0l8-30M87 174l7 31c2 8 17 5 15-3l-5-33" fill="#3b2b50" />
      <path d="M52 201c-9 6-12 14-6 16h22l2-15M94 202l1 15h23c6-3-1-13-11-16" fill="#e6dcf6" />
      <path d="M70 88c-10 2-16 13-18 31l-5 54c16 12 50 13 65 0l-8-54c-3-18-9-29-20-31z" fill="#bba0e1" stroke="#eadbff" strokeWidth="2" />
      <path d="M68 92l12 16 12-16-5 49H73z" fill="#f5edff" />
      <path d="M79 110v65" stroke="#8c70ad" strokeWidth="2" />
      <path d="M94 129h12v14c-5 3-8 3-12 0z" fill="#80639f" />
      <text x="100" y="140" fill="#fff" fontSize="9" fontWeight="700" textAnchor="middle">P</text>
      <path d="M53 105c-9 6-15 23-15 36 0 8 12 11 16 3l8-27" fill="#bba0e1" stroke="#eadbff" strokeWidth="2" />
      <path d="M38 140c-5 4-5 11 0 15 6 4 13 0 14-8" fill="#e9b995" />
      <g className="penny-wave-arm">
        <path d="M101 105c10 2 16 14 21 10l11-20" fill="none" stroke="#eadbff" strokeWidth="19" strokeLinecap="round" />
        <path d="M101 105c10 2 16 14 21 10l11-20" fill="none" stroke="#bba0e1" strokeWidth="15" strokeLinecap="round" />
        <path d="M130 98c-5-7-9-11-7-14 2-2 6 4 7 4l-1-14c0-5 4-5 5-1l3 12 2-15c1-4 5-3 5 1l-1 15 4-10c2-4 5-1 3 3l-6 18c-2 6-9 8-14 1z" fill="#e9b995" stroke="#bf8d70" strokeWidth=".7" />
      </g>
      <g className="penny-head">
        <path d="M46 53c-2-29 12-46 34-46 25 0 39 22 33 51l-5 23H52z" fill="#352332" />
        <circle cx="106" cy="18" r="15" fill="#352332" />
        <path d="M99 10c8-4 17 5 15 12" fill="none" stroke="#74506b" strokeWidth="3" strokeLinecap="round" />
        <path d="M71 80v14c5 8 15 8 19 0V80" fill="#dba482" />
        <ellipse cx="49" cy="58" rx="6" ry="9" fill="#e9b995" /><ellipse cx="111" cy="58" rx="6" ry="9" fill="#e9b995" />
        <path d="M50 45c0-22 57-28 61 0v17c0 22-15 31-30 31S50 78 50 62z" fill="#f1c7a4" />
        <path d="M47 47c1-24 14-33 33-33 21 0 32 11 33 35-12-5-21-15-24-20-8 10-22 15-42 18z" fill="#352332" />
        <path d="M58 27c6-8 15-10 24-9" fill="none" stroke="#74506b" strokeWidth="3" strokeLinecap="round" />
        <g className="penny-figure-eyes"><ellipse cx="66" cy="56" rx="3.5" ry="4" fill="#352332" /><ellipse cx="94" cy="56" rx="3.5" ry="4" fill="#352332" /><circle cx="67" cy="55" r="1" fill="#fff" /><circle cx="95" cy="55" r="1" fill="#fff" /></g>
        <path className="penny-brows" d="M60 48q6-4 11 0m18 0q6-4 11 0" fill="none" stroke="#513342" strokeWidth="2" strokeLinecap="round" />
        <ellipse cx="59" cy="65" rx="6" ry="3" fill="#eaa38f" opacity=".7" /><ellipse cx="102" cy="65" rx="6" ry="3" fill="#eaa38f" opacity=".7" />
        <path d="M79 58l-2 7h5" fill="none" stroke="#cc9376" strokeWidth="1.5" strokeLinecap="round" />
        <g className="penny-figure-mouth"><path d="M70 72q11 13 22 0z" fill="#854252" /><path d="M73 73h16q-7 5-16 0" fill="#fff8f0" /></g>
        <circle cx="48" cy="68" r="2" fill="#ead5ac" /><circle cx="112" cy="68" r="2" fill="#ead5ac" />
      </g>
    </g>
    <g className="penny-thoughts" fill="#e4d1ff"><circle cx="123" cy="37" r="3" /><circle cx="134" cy="26" r="4" /><circle cx="148" cy="17" r="5" /></g>
    <g className="penny-reply-bars" stroke="#d8c8ff" strokeWidth="3" strokeLinecap="round"><path d="M12 66v12" /><path d="M20 60v24" /><path d="M28 66v12" /></g>
  </svg>
}

export default PennyAvatar
