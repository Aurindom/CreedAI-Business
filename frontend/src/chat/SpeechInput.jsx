import React, { useEffect, useRef, useState } from 'react'

const MESSAGES = {
  'not-allowed': "Microphone access is off. You can turn it on in your browser, or type instead.",
  'service-not-allowed': "Voice input isn't available in this browser. You can type instead.",
  'no-speech': "I didn't catch that. Try again, or type instead.",
  'audio-capture': "I couldn't find a microphone. You can type instead.",
  network: "Voice input needs an internet connection. You can type instead.",
}

function recognitionClass() {
  return typeof window === 'undefined' ? null : window.SpeechRecognition || window.webkitSpeechRecognition || null
}

function SpeechInput({ value, onText, onNotice, disabled }) {
  const [listening, setListening] = useState(false)
  const recognition = useRef(null)
  const Recognition = recognitionClass()

  useEffect(() => () => recognition.current?.abort(), [])

  useEffect(() => {
    if (disabled) recognition.current?.stop()
  }, [disabled])

  if (!Recognition) return null

  function toggle() {
    if (listening) {
      recognition.current?.stop()
      return
    }
    const base = value.trim() ? `${value.trim()} ` : ''
    const session = new Recognition()
    session.lang = navigator.language || 'en-US'
    session.interimResults = true
    session.continuous = false
    session.onresult = (event) => {
      const heard = Array.from(event.results).map((result) => result[0].transcript).join('')
      onText(`${base}${heard}`.slice(0, 500))
    }
    session.onerror = (event) => {
      if (event.error !== 'aborted') onNotice(MESSAGES[event.error] || "Voice input stopped. You can try again, or type instead.")
    }
    session.onend = () => setListening(false)
    recognition.current = session
    onNotice('')
    try {
      session.start()
      setListening(true)
    } catch {
      onNotice('Voice input stopped. You can try again, or type instead.')
    }
  }

  return (
    <button
      type="button"
      className={`msc-mic${listening ? ' msc-mic-on' : ''}`}
      onClick={toggle}
      disabled={disabled}
      aria-pressed={listening}
      aria-label={listening ? 'Stop listening' : 'Speak instead of typing'}
      title="Your browser's speech service may process what you say"
    >
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0 0 14 0" /><path d="M12 18v3" />
      </svg>
    </button>
  )
}

export default SpeechInput
