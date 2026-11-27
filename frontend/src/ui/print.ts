/**
 * Opens the browser's print window once every picture inside `root` has loaded (or after a short wait, so a slow picture never blocks
 * printing). `started` runs just before the window opens. Returns a function that cancels a print that has not started yet.
 */
export function printWhenReady(root: HTMLElement, started?: () => void, waitMs = 2500): () => void {
  let cancelled = false
  let timer: ReturnType<typeof setTimeout> | undefined
  const pictures = Array.from(root.querySelectorAll('img')).filter((img) => !img.complete)
  const loaded = Promise.all(pictures.map((img) => new Promise<void>((done) => { img.addEventListener('load', () => done()); img.addEventListener('error', () => done()) })))
  const limit = new Promise<void>((done) => { timer = setTimeout(done, waitMs) })
  void Promise.race([loaded.then(() => undefined), limit]).then(() => {
    clearTimeout(timer)
    if (cancelled) return
    // one more frame, so the pictures are painted
    timer = setTimeout(() => { if (cancelled) return; started?.(); window.print() }, 150)
  })
  return () => { cancelled = true; clearTimeout(timer) }
}
