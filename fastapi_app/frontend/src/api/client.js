const TOKEN_KEY = 'ardesign_access_token'
const REFRESH_KEY = 'ardesign_refresh_token'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY)
}

export function getRefreshToken() {
  return localStorage.getItem(REFRESH_KEY)
}

export function setTokens(access, refresh) {
  localStorage.setItem(TOKEN_KEY, access)
  localStorage.setItem(REFRESH_KEY, refresh)
}

export function clearTokens() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(REFRESH_KEY)
}

async function tryRefresh() {
  const refresh = getRefreshToken()
  if (!refresh) return false

  const res = await fetch('/api/auth/refresh', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: refresh }),
  })
  if (!res.ok) {
    clearTokens()
    return false
  }
  const data = await res.json()
  setTokens(data.access_token, data.refresh_token)
  return true
}

export async function apiFetch(url, options = {}) {
  const token = getToken()
  const headers = { ...options.headers }
  if (token) headers['Authorization'] = `Bearer ${token}`

  let res = await fetch(url, { ...options, headers })

  if (res.status === 401 && (await tryRefresh())) {
    headers['Authorization'] = `Bearer ${getToken()}`
    res = await fetch(url, { ...options, headers })
  }

  return res
}
