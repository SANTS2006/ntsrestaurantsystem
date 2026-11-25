import { useCallback, useRef } from 'react'

/**
 * Calls `onTrigger` after `count` clicks that each happen within `windowMs` of the previous one.
 * This is a UX convenience only, NOT a security control: the login page and API stay fully protected.
 */
export function useSecretClicks(onTrigger: () => void, count = 5, windowMs = 3000) {
  const clicks = useRef(0)
  const last = useRef(0)
  return useCallback(() => {
    const now = Date.now()
    clicks.current = now - last.current > windowMs ? 1 : clicks.current + 1
    last.current = now
    if (clicks.current >= count) {
      clicks.current = 0
      onTrigger()
    }
  }, [onTrigger, count, windowMs])
}
