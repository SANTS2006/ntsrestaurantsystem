// Notification sounds are generated with the Web Audio API (no audio files to download or license).
// Browsers only allow sound after the person has interacted with the page, so the audio context is unlocked on the first click or key press.
type Kind = 'ready' | 'new' | 'soft'
let ctx: AudioContext | null = null

function audio(): AudioContext | null {
  try {
    const AC = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
    if (!AC) return null
    ctx ??= new AC()
    if (ctx.state === 'suspended') void ctx.resume()
    return ctx
  } catch {
    return null
  }
}

if (typeof window !== 'undefined') {
  const unlock = () => { audio(); window.removeEventListener('pointerdown', unlock); window.removeEventListener('keydown', unlock) }
  window.addEventListener('pointerdown', unlock)
  window.addEventListener('keydown', unlock)
}

function tone(c: AudioContext, freq: number, start: number, length: number, volume = 0.18) {
  const osc = c.createOscillator()
  const gain = c.createGain()
  osc.type = 'sine'
  osc.frequency.value = freq
  gain.gain.setValueAtTime(0.0001, c.currentTime + start)
  gain.gain.exponentialRampToValueAtTime(volume, c.currentTime + start + 0.02)
  gain.gain.exponentialRampToValueAtTime(0.0001, c.currentTime + start + length)
  osc.connect(gain).connect(c.destination)
  osc.start(c.currentTime + start)
  osc.stop(c.currentTime + start + length + 0.05)
}

/** ready: a bright rising chime (an order is ready for pickup); new: a two-note ding; soft: a single gentle blip. */
export function playChime(kind: Kind = 'soft') {
  const c = audio()
  if (!c || c.state !== 'running') return
  if (kind === 'ready') { tone(c, 659, 0, 0.35); tone(c, 880, 0.18, 0.35); tone(c, 1175, 0.36, 0.6) }
  else if (kind === 'new') { tone(c, 880, 0, 0.3); tone(c, 660, 0.22, 0.45) }
  else tone(c, 740, 0, 0.35, 0.12)
}
