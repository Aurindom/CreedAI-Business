import { useCallback, useEffect, useRef, useState } from 'react'

const EDGE = 8
const DRAG_START_PX = 5
const KEY_STEP_PX = 24
const INTERACTIVE = 'button, a, input, textarea, select, summary, [data-no-drag]'

function readPosition(key) {
  try {
    const saved = JSON.parse(window.sessionStorage.getItem(key) || 'null')
    return Number.isFinite(saved?.x) && Number.isFinite(saved?.y) ? saved : null
  } catch {
    return null
  }
}

function savePosition(key, position) {
  try {
    window.sessionStorage.setItem(key, JSON.stringify(position))
  } catch {
    // Remembering the spot is a convenience only.
  }
}

// Lets an element be dragged anywhere in the window and keeps it on screen.
// `handleOnly` limits dragging to the element passed to `handleProps`.
export function useDraggable({ storageKey, enabled = true }) {
  const ref = useRef(null)
  const [position, setPosition] = useState(() => readPosition(storageKey))
  const moved = useRef(false)

  const clamp = useCallback((next) => {
    // offsetWidth/offsetHeight ignore the opening animation's scale, unlike getBoundingClientRect.
    const width = ref.current?.offsetWidth || 0
    const height = ref.current?.offsetHeight || 0
    return {
      x: Math.round(Math.min(Math.max(EDGE, next.x), Math.max(EDGE, window.innerWidth - width - EDGE))),
      y: Math.round(Math.min(Math.max(EDGE, next.y), Math.max(EDGE, window.innerHeight - height - EDGE))),
    }
  }, [])

  const reclamp = useCallback(() => {
    setPosition((current) => {
      if (!current) return current
      const next = clamp(current)
      return next.x === current.x && next.y === current.y ? current : next
    })
  }, [clamp])

  // A saved spot from a bigger screen could be off this one, so check on every show.
  useEffect(() => {
    reclamp()
  })

  useEffect(() => {
    window.addEventListener('resize', reclamp)
    return () => window.removeEventListener('resize', reclamp)
  }, [reclamp])

  const stopListening = useRef(() => {})
  useEffect(() => () => stopListening.current(), [])

  // Moves are tracked on the whole window, so a fast drag can't slip off the handle.
  function onPointerDown(event) {
    if (!enabled || event.button !== 0 || !ref.current) return
    const control = event.target.closest(INTERACTIVE)
    if (control && control !== event.currentTarget && !control.hasAttribute('data-drag-ok')) return
    const box = ref.current.getBoundingClientRect()
    const start = { id: event.pointerId, dx: event.clientX - box.left, dy: event.clientY - box.top, sx: event.clientX, sy: event.clientY }
    moved.current = false
    stopListening.current()

    function move(moveEvent) {
      if (moveEvent.pointerId !== start.id) return
      if (!moved.current && Math.hypot(moveEvent.clientX - start.sx, moveEvent.clientY - start.sy) < DRAG_START_PX) return
      moved.current = true
      moveEvent.preventDefault()
      setPosition(clamp({ x: moveEvent.clientX - start.dx, y: moveEvent.clientY - start.dy }))
    }

    function end(endEvent) {
      if (endEvent.pointerId !== start.id) return
      stopListening.current()
      if (moved.current) setPosition((latest) => {
        if (latest) savePosition(storageKey, latest)
        return latest
      })
    }

    window.addEventListener('pointermove', move, { passive: false })
    window.addEventListener('pointerup', end)
    window.addEventListener('pointercancel', end)
    stopListening.current = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', end)
      window.removeEventListener('pointercancel', end)
      stopListening.current = () => {}
    }
  }

  function onKeyDown(event) {
    const steps = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }
    const step = steps[event.key]
    if (!enabled || !step || !ref.current) return
    event.preventDefault()
    const box = ref.current.getBoundingClientRect()
    setPosition((current) => {
      const from = current || { x: box.left, y: box.top }
      const next = clamp({ x: from.x + step[0] * KEY_STEP_PX, y: from.y + step[1] * KEY_STEP_PX })
      savePosition(storageKey, next)
      return next
    })
  }

  // Puts the element beside an anchor box (Arkadio's button), above it when there's room.
  function placeNear(anchor) {
    const element = ref.current
    if (!enabled || !element || !anchor) return
    const above = anchor.top - element.offsetHeight - 12
    const y = above >= EDGE ? above : anchor.bottom + 12
    setPosition(clamp({ x: anchor.right - element.offsetWidth, y }))
  }

  // True right after a drag, so the click that ends a drag doesn't also open or close something.
  function wasDragged() {
    const value = moved.current
    moved.current = false
    return value
  }

  return {
    ref,
    position,
    reclamp,
    placeNear,
    wasDragged,
    style: enabled && position ? { left: position.x, top: position.y, right: 'auto', bottom: 'auto' } : undefined,
    handleProps: { onPointerDown },
    onKeyDown,
  }
}

export function useIsPhone() {
  const query = '(max-width: 640px)'
  const [phone, setPhone] = useState(() => typeof window !== 'undefined' && window.matchMedia?.(query).matches)
  useEffect(() => {
    const list = window.matchMedia?.(query)
    if (!list) return undefined
    const update = () => setPhone(list.matches)
    list.addEventListener('change', update)
    return () => list.removeEventListener('change', update)
  }, [])
  return phone
}
