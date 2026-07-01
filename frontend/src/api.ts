export async function apiGet(path: string, params?: Record<string, any>) {
  const url = new URL(path, window.location.origin)
  if (params) {
    Object.entries(params).forEach(([k, v]) => url.searchParams.append(k, String(v)))
  }
  const resp = await fetch(url.toString(), { credentials: 'same-origin' })
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
  return await resp.json()
}

export async function apiPost(path: string, body?: any) {
  const resp = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
    credentials: 'same-origin'
  })
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
  return await resp.json()
}
