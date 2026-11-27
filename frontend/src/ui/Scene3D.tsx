import { useEffect, useRef } from 'react'

/**
 * A real-time 3D model of a serving cloche over a plate of food, drawn on a canvas with a tiny software renderer (no 3D library to
 * download): meshes are surfaces of revolution and spheres, projected in perspective, depth-sorted and flat-shaded.
 * It turns slowly, the lid lifts to show the food, and it follows the pointer a little. It stops when off screen, and shows a still
 * picture for people who prefer reduced motion. Colours come from the theme, so each restaurant gets its own.
 */
type V = [number, number, number]
type Face = { pts: V[]; color: [number, number, number]; shine: number; lid?: boolean }

const TAU = Math.PI * 2

/** Spin a profile of (radius, height) points around the vertical axis. */
function lathe(profile: [number, number][], segments: number, color: Face['color'], shine: number, lid = false): Face[] {
  const out: Face[] = []
  for (let s = 0; s < segments; s++) {
    const a = (s / segments) * TAU
    const b = ((s + 1) / segments) * TAU
    for (let i = 0; i < profile.length - 1; i++) {
      const [r1, y1] = profile[i]
      const [r2, y2] = profile[i + 1]
      out.push({ pts: [[r1 * Math.cos(a), y1, r1 * Math.sin(a)], [r1 * Math.cos(b), y1, r1 * Math.sin(b)], [r2 * Math.cos(b), y2, r2 * Math.sin(b)], [r2 * Math.cos(a), y2, r2 * Math.sin(a)]], color, shine, lid })
    }
  }
  return out
}

function ball(cx: number, cy: number, cz: number, r: number, color: Face['color'], squash = 1, lid = false): Face[] {
  const profile: [number, number][] = []
  for (let i = 0; i <= 7; i++) {
    const t = -Math.PI / 2 + (i / 7) * Math.PI
    profile.push([Math.cos(t) * r, Math.sin(t) * r * squash])
  }
  return lathe(profile, 12, color, 0.35, lid).map((f) => ({ ...f, pts: f.pts.map(([x, y, z]) => [x + cx, y + cy, z + cz] as V) }))
}

function hexToRgb(value: string, fallback: Face['color']): Face['color'] {
  const m = value.trim().match(/^#?([0-9a-f]{6})$/i)
  if (!m) return fallback
  const n = parseInt(m[1], 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

function model(brand: Face['color'], accent: Face['color']): Face[] {
  const china: Face['color'] = [238, 243, 250]
  const silver: Face['color'] = [196, 210, 230]
  const faces: Face[] = [
    // plate: foot, well, wide rim
    ...lathe([[0, -0.62], [1.15, -0.62], [1.3, -0.55], [1.78, -0.42], [1.98, -0.34], [1.95, -0.29], [1.68, -0.37], [1.28, -0.5], [0, -0.5]], 40, china, 0.5),
    ...lathe([[1.8, -0.405], [1.93, -0.35]], 40, brand, 0.6),
    // food
    ...ball(-0.45, -0.28, 0.1, 0.38, [230, 126, 34], 0.72),
    ...ball(0.38, -0.31, -0.32, 0.33, [196, 70, 52], 0.7),
    ...ball(0.34, -0.33, 0.42, 0.3, [243, 198, 83], 0.62),
    ...ball(-0.08, -0.36, -0.52, 0.2, [76, 153, 87], 0.9),
    ...ball(-0.72, -0.38, -0.3, 0.17, [92, 170, 92], 0.9),
    ...ball(0.72, -0.4, 0.06, 0.15, [76, 153, 87], 0.9),
  ]
  const dome: [number, number][] = [[1.45, -0.36]]
  for (let i = 0; i <= 10; i++) {
    const t = (i / 10) * (Math.PI / 2)
    dome.push([Math.cos(t) * 1.38, -0.28 + Math.sin(t) * 1.12])
  }
  faces.push(...lathe(dome, 40, silver, 0.95, true))
  faces.push(...lathe([[1.5, -0.38], [1.47, -0.3], [1.4, -0.28]], 40, brand, 0.8, true))
  faces.push(...lathe([[0.1, 0.82], [0.08, 0.94]], 16, brand, 0.8, true))
  faces.push(...ball(0, 1.03, 0, 0.14, accent, 1, true))
  return faces
}

export type ModelKind = 'cloche' | 'burger' | 'drink' | 'cake' | 'globe'

/** A burger whose top layers float apart and settle again. */
function burger(brand: Face['color']): Face[] {
  const bun: Face['color'] = [222, 150, 66]
  return [
    ...lathe([[0, -0.9], [1.5, -0.9], [1.75, -0.82], [1.8, -0.72], [0, -0.7]], 32, [238, 243, 250], 0.5),
    ...lathe([[0, -0.7], [1.18, -0.68], [1.3, -0.5], [1.22, -0.36], [0, -0.36]], 32, bun, 0.3),
    ...lathe([[0, -0.36], [1.3, -0.35], [1.38, -0.2], [1.28, -0.06], [0, -0.06]], 32, [112, 62, 38], 0.25),
    ...lathe([[0, -0.05], [1.42, -0.05], [1.4, 0.02], [0, 0.03]], 6, [247, 190, 52], 0.5),
    ...lathe([[0, 0.04], [1.46, 0.05], [1.36, 0.13], [0, 0.14]], 14, [86, 168, 76], 0.2, true),
    ...lathe([[0, 0.16], [1.2, 0.16], [1.18, 0.28], [0, 0.28]], 28, [201, 62, 50], 0.45, true),
    ...lathe([[0, 0.3], [1.3, 0.3], [1.28, 0.5], [1.05, 0.76], [0.65, 0.93], [0, 1]], 32, bun, 0.45, true),
    ...[[0.3, 0.2], [-0.4, 0.35], [0.1, -0.5], [-0.55, -0.25], [0.6, -0.2], [-0.05, 0.62]].flatMap(([x, z]) => ball(x, 0.97 - (x * x + z * z) * 0.28, z, 0.075, [252, 236, 190], 0.5, true)),
    ...lathe([[1.78, -0.76], [1.8, -0.72]], 32, brand, 0.6),
  ]
}

/** A cold drink with ice cubes bobbing above it and a straw. */
function drink(brand: Face['color'], accent: Face['color']): Face[] {
  return [
    ...lathe([[0, -1], [0.78, -1], [0.84, -0.86], [1.06, 0.68]], 32, brand, 0.9),
    ...lathe([[1.06, 0.68], [1.13, 0.74], [1.04, 0.76], [0, 0.72]], 32, [238, 243, 250], 0.8),
    ...lathe([[0.9, -0.4], [0.99, 0.18]], 32, [238, 243, 250], 0.6),
    ...[0, 1, 2, 3, 4, 5, 6, 7, 8].flatMap((i) => ball(0.32 + i * 0.075, 0.7 + i * 0.14, 0, 0.075, accent)),
    ...ball(-0.42, 0.9, 0.25, 0.2, [214, 240, 255], 0.9, true),
    ...ball(-0.1, 0.86, -0.4, 0.17, [214, 240, 255], 0.9, true),
    ...ball(-0.55, 0.82, -0.2, 0.28, [244, 170, 44], 0.35, true),
  ]
}

/** A two-tier cake; the topping rises like a celebration. */
function cake(brand: Face['color'], accent: Face['color']): Face[] {
  const cream: Face['color'] = [250, 240, 224]
  const around = (n: number, r: number, y: number, size: number, color: Face['color'], lift = false) =>
    Array.from({ length: n }, (_, i) => ball(r * Math.cos((i / n) * TAU), y, r * Math.sin((i / n) * TAU), size, color, 1, lift)).flat()
  return [
    ...lathe([[0, -0.95], [1.6, -0.95], [1.85, -0.85], [0, -0.8]], 36, [238, 243, 250], 0.5),
    ...lathe([[0, -0.8], [1.35, -0.8], [1.35, -0.14], [0, -0.12]], 36, cream, 0.3),
    ...lathe([[1.37, -0.55], [1.37, -0.4]], 36, brand, 0.5),
    ...around(14, 1.2, -0.08, 0.11, accent),
    ...lathe([[0, -0.12], [0.86, -0.12], [0.86, 0.4], [0, 0.42]], 32, cream, 0.3),
    ...lathe([[0.88, 0.12], [0.88, 0.25]], 32, brand, 0.5),
    ...around(9, 0.72, 0.47, 0.1, [208, 50, 70]),
    ...ball(0, 0.72, 0, 0.2, [208, 50, 70], 1, true),
    ...ball(0.1, 0.97, 0, 0.07, [86, 168, 76], 1, true),
  ]
}

/** A globe with dishes circling it: many places, one system. */
function globe(brand: Face['color'], accent: Face['color']): Face[] {
  const ring = Array.from({ length: 40 }, (_, i) => ball(1.65 * Math.cos((i / 40) * TAU), 0.1 + 0.42 * Math.sin((i / 40) * TAU), 1.65 * Math.sin((i / 40) * TAU), 0.035, [196, 210, 230])).flat()
  return [
    ...ball(0, 0.1, 0, 1.08, brand),
    ...ring,
    ...ball(1.65, 0.1, 0, 0.24, [230, 126, 34], 1, true),
    ...ball(-0.82, 0.46, 1.43, 0.2, accent, 1, true),
    ...ball(-0.82, -0.26, -1.43, 0.22, [86, 168, 76], 1, true),
    ...lathe([[0, -1.2], [0.7, -1.2], [0.5, -1.08], [0, -1.05]], 24, [196, 210, 230], 0.7),
  ]
}

const BUILD: Record<ModelKind, (brand: Face['color'], accent: Face['color']) => Face[]> = { cloche: model, burger: (b) => burger(b), drink, cake, globe }
const LABEL: Record<ModelKind, string> = {
  cloche: 'a serving dome lifting from a plate of food', burger: 'a burger', drink: 'a cold drink', cake: 'a celebration cake', globe: 'a globe with dishes circling it',
}

export default function Scene3D({ className = '', kind = 'cloche' }: { className?: string; kind?: ModelKind }) {
  const ref = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const canvas = ref.current
    const ctx = canvas?.getContext?.('2d')
    if (!canvas || !ctx) return
    const style = getComputedStyle(document.documentElement)
    const faces = BUILD[kind](hexToRgb(style.getPropertyValue('--brand'), [10, 114, 224]), hexToRgb(style.getPropertyValue('--gold'), [20, 180, 245]))
    const still = typeof matchMedia !== 'undefined' && matchMedia('(prefers-reduced-motion: reduce)').matches
    const pointer = { x: 0, y: 0 }
    const look = { x: 0, y: 0 }
    let raf = 0
    let visible = true
    let w = 0
    let h = 0

    const resize = () => {
      const dpr = Math.min(2, window.devicePixelRatio || 1)
      w = canvas.clientWidth || 480
      h = canvas.clientHeight || 400
      canvas.width = w * dpr
      canvas.height = h * dpr
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    }

    const draw = (time: number) => {
      const t = time / 1000
      look.x += (pointer.x - look.x) * 0.06
      look.y += (pointer.y - look.y) * 0.06
      const spin = t * 0.45 + look.x * 0.9
      const tilt = 0.46 + look.y * 0.22
      // the lid rests, lifts, hovers and comes down again, on an eight-second loop
      const phase = still ? 0.6 : (t % 8) / 8
      const raw = phase < 0.2 ? 0 : phase < 0.42 ? (phase - 0.2) / 0.22 : phase < 0.78 ? 1 : 1 - (phase - 0.78) / 0.22
      const lift = raw * raw * (3 - 2 * raw)
      const bob = still ? 0 : Math.sin(t * 1.4) * 0.05
      const cs = Math.cos(spin)
      const sn = Math.sin(spin)
      const ct = Math.cos(tilt)
      const st = Math.sin(tilt)
      const scale = Math.min(w / 4.5, h / 4.1)

      ctx.clearRect(0, 0, w, h)
      const shadow = ctx.createRadialGradient(w / 2, h * 0.83, 6, w / 2, h * 0.83, scale * 2.2)
      shadow.addColorStop(0, 'rgba(5, 20, 55, .30)')
      shadow.addColorStop(1, 'rgba(5, 20, 55, 0)')
      ctx.fillStyle = shadow
      ctx.beginPath()
      ctx.ellipse(w / 2, h * 0.83, scale * 2.2, scale * 0.45, 0, 0, TAU)
      ctx.fill()

      const projected = faces.map((f) => {
        const pts = f.pts.map(([x, y, z]) => {
          let px = x
          let py = y + bob
          const pz = z
          if (f.lid && kind !== 'cloche') { // the other models: the marked parts float up and settle
            py = y + bob + lift * 0.3
          } else if (f.lid) { // lift the lid and tip it back a little
            const a = lift * 0.38
            const ly = y + 0.3
            px = x * Math.cos(a) - ly * Math.sin(a) - lift * 0.35
            py = x * Math.sin(a) + ly * Math.cos(a) - 0.3 + lift * 1.15 + bob
          }
          const rx = px * cs - pz * sn
          const rz = px * sn + pz * cs
          return [rx, py * ct - rz * st, py * st + rz * ct] as V
        })
        const depth = pts.reduce((s, p) => s + p[2], 0) / pts.length
        return { f, pts, depth }
      }).sort((a, b) => a.depth - b.depth)

      for (const { f, pts } of projected) {
        const [a, b, c, d] = pts
        const u: V = [c[0] - a[0], c[1] - a[1], c[2] - a[2]]
        const v: V = [d[0] - b[0], d[1] - b[1], d[2] - b[2]]
        let nx = u[1] * v[2] - u[2] * v[1]
        let ny = u[2] * v[0] - u[0] * v[2]
        let nz = u[0] * v[1] - u[1] * v[0]
        const len = Math.hypot(nx, ny, nz) || 1
        nx /= len; ny /= len; nz /= len
        if (nz < 0) { nx = -nx; ny = -ny; nz = -nz } // light both sides: the underside of the lid shows when it opens
        const diffuse = Math.max(0, nx * -0.45 + ny * 0.62 + nz * 0.64)
        const spec = Math.pow(diffuse, 22) * f.shine
        const k = 0.42 + diffuse * 0.66
        const [r, g, bl] = f.color.map((ch) => Math.min(255, Math.round(ch * k + 255 * spec)))
        ctx.beginPath()
        pts.forEach(([x, y, z], i) => {
          const persp = 6.5 / (6.5 - z)
          const sx = w / 2 + x * scale * persp
          const sy = h * (kind === 'cloche' ? 0.6 : 0.52) - y * scale * persp
          if (i) ctx.lineTo(sx, sy)
          else ctx.moveTo(sx, sy)
        })
        ctx.closePath()
        ctx.fillStyle = `rgb(${r},${g},${bl})`
        ctx.strokeStyle = ctx.fillStyle
        ctx.lineWidth = 0.7
        ctx.fill()
        ctx.stroke()
      }
    }

    const loop = (time: number) => {
      draw(time)
      if (visible && !still) raf = requestAnimationFrame(loop)
    }
    const move = (e: PointerEvent) => {
      pointer.x = e.clientX / window.innerWidth - 0.5
      pointer.y = e.clientY / window.innerHeight - 0.5
    }
    resize()
    const io = typeof IntersectionObserver !== 'undefined' ? new IntersectionObserver(([entry]) => {
      const was = visible
      visible = entry.isIntersecting
      if (visible && !was && !still) raf = requestAnimationFrame(loop)
    }) : null
    io?.observe(canvas)
    const onResize = () => { resize(); if (still) draw(0) }
    window.addEventListener('resize', onResize)
    window.addEventListener('pointermove', move, { passive: true })
    if (still) draw(0)
    else raf = requestAnimationFrame(loop)
    return () => { visible = false; cancelAnimationFrame(raf); io?.disconnect(); window.removeEventListener('resize', onResize); window.removeEventListener('pointermove', move) }
  }, [kind])
  return <canvas ref={ref} className={`scene3d ${className}`} role="img" aria-label={`Animated 3D model of ${LABEL[kind]}`} />
}
