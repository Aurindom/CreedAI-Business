import React from 'react'

export default function MainStreetBrand() {
  return <a className="brand mainstreet-brand mainstreet-cart-wordmark" href="#" aria-label="Creed AI home">
    <svg className="mainstreet-cart-logo" viewBox="0 0 274 84" fill="none" aria-hidden="true">
      <path d="M36 5 63 14v26c0 18-12 31-27 39C21 71 9 58 9 40V14L36 5Z" fill="#241a33" stroke="#d8c8ff" strokeWidth="3" strokeLinejoin="round" />
      <path d="M36 13 56 20v20c0 14-9 25-20 31-11-6-20-17-20-31V20l20-7Z" stroke="#efd1a2" strokeWidth="1.5" strokeLinejoin="round" />
      <path d="m25 41 8 9 15-20" stroke="#efd1a2" strokeWidth="5.5" strokeLinecap="round" strokeLinejoin="round" />
      <text className="cart-sign-name" x="76" y="56" fill="#f4e9d8" fontFamily="Georgia, 'Times New Roman', serif" fontSize="42" fontWeight="700" letterSpacing="-1">Creed</text>
      <text x="216" y="56" fill="#d7c2e8" fontFamily="Georgia, 'Times New Roman', serif" fontSize="26" fontWeight="700">AI</text>
    </svg>
  </a>
}
