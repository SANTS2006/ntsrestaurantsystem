// Every data-loading hook (useAsync) registers here. A refresh button, a push from the server or a timer can then reload
// everything that is currently on screen without a page refresh.
const registry = new Set<() => void>()
const listeners = new Set<() => void>()
let lastRefresh = Date.now()

export function registerRefresh(fn: () => void): () => void {
  registry.add(fn)
  return () => { registry.delete(fn) }
}
export function refreshAll() {
  lastRefresh = Date.now()
  registry.forEach((f) => f())
  listeners.forEach((f) => f())
}
export function onRefresh(f: () => void): () => void {
  listeners.add(f)
  return () => { listeners.delete(f) }
}
export const lastRefreshedAt = () => lastRefresh
