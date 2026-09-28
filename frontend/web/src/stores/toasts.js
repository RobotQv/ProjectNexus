import { reactive } from 'vue'

let seq = 0

export const toasts = reactive({ items: [] })

/** kind: 'info' | 'ok' | 'err' */
export function toast(message, kind = 'info') {
  const id = ++seq
  toasts.items.push({ id, message, kind })
  setTimeout(() => dismiss(id), kind === 'err' ? 5200 : 3200)
}

export function dismiss(id) {
  const index = toasts.items.findIndex((t) => t.id === id)
  if (index >= 0) toasts.items.splice(index, 1)
}
