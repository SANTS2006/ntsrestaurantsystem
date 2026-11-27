// Bold markers in website texts: `**these words**` are bold. The same rule is applied on the server (apps/website/content.py).
const BOLD = /\*\*([\s\S]+?)\*\*/g

export function splitBold(text: string): { text: string; bold: boolean }[] {
  const out: { text: string; bold: boolean }[] = []
  let last = 0
  for (const m of text.matchAll(BOLD)) {
    if (m.index > last) out.push({ text: text.slice(last, m.index), bold: false })
    out.push({ text: m[1], bold: true })
    last = m.index + m[0].length
  }
  if (last < text.length) out.push({ text: text.slice(last), bold: false })
  return out
}

/** The same text without the markers, for page titles, search descriptions and other plain-text places. */
export const plain = (text: string | null | undefined) => (text ?? '').replace(BOLD, '$1').replace(/\*\*/g, '')

/** Make the selected range bold, or remove the bold if it already is. Returns the new text and what should stay selected. */
export function boldSelection(value: string, start: number, end: number): { value: string; start: number; end: number } {
  // spaces at the edges of a selection stay outside the markers
  while (start < end && /\s/.test(value[start])) start++
  while (end > start && /\s/.test(value[end - 1])) end--
  const picked = value.slice(start, end)
  if (value.slice(start - 2, start) === '**' && value.slice(end, end + 2) === '**') {
    return { value: value.slice(0, start - 2) + picked + value.slice(end + 2), start: start - 2, end: end - 2 }
  }
  if (picked.startsWith('**') && picked.endsWith('**') && picked.length > 4) {
    const inner = picked.slice(2, -2)
    return { value: value.slice(0, start) + inner + value.slice(end), start, end: start + inner.length }
  }
  const words = picked || 'bold text'
  return { value: `${value.slice(0, start)}**${words}**${value.slice(end)}`, start: start + 2, end: start + 2 + words.length }
}
