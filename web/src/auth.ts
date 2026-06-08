// Auth API client. All fetches use credentials:'include' so the
// session cookie travels with each request.

const BASE = ''

export interface MeResponse {
  user_id: string
  username: string
  display_name: string
}

export class AuthRequiredError extends Error {
  constructor() {
    super('login required')
    this.name = 'AuthRequiredError'
  }
}

export async function fetchMe(): Promise<MeResponse | null> {
  const res = await fetch(`${BASE}/auth/me`, {
    method: 'GET',
    credentials: 'include',
  })
  if (res.status === 401) return null
  if (!res.ok) throw new Error(`auth.me failed: HTTP ${res.status}`)
  return (await res.json()) as MeResponse
}

export async function login(username: string, password: string): Promise<MeResponse> {
  const res = await fetch(`${BASE}/auth/login`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  if (res.status === 401) {
    throw new Error('Invalid username or password')
  }
  if (!res.ok) {
    throw new Error(`Login failed: HTTP ${res.status}`)
  }
  // Server set-cookie has been received by the browser; refetch /auth/me to
  // get the canonical user record (display_name might be richer than the
  // login response's username).
  const me = await fetchMe()
  if (!me) throw new Error('login succeeded but /auth/me still returned 401')
  return me
}

export async function logout(): Promise<void> {
  await fetch(`${BASE}/auth/logout`, {
    method: 'POST',
    credentials: 'include',
  })
}
