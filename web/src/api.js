// All calls go to /api on the same origin: the Vite proxy in development, this server in production.
const BASE = '/api'

export class AuthError extends Error {}

async function request(path, { method = 'GET', body, form } = {}) {
  const options = { method, headers: {} }
  if (form) options.body = form
  else if (body !== undefined) {
    options.headers['Content-Type'] = 'application/json'
    options.body = JSON.stringify(body)
  }
  const res = await fetch(BASE + path, options)
  if (res.status === 401) throw new AuthError('sign in required')
  if (!res.ok) {
    let detail = ''
    try {
      detail = (await res.json()).detail
    } catch {
      // no JSON body; fall through to the generic message
    }
    if (detail && typeof detail === 'object') detail = detail.message
    const error = new Error(detail || `API returned ${res.status} for ${path}`)
    error.status = res.status
    throw error
  }
  return res.status === 204 ? null : res.json()
}

export const api = {
  config: () => request('/config'),
  me: () => request('/me'),
  loginGoogle: (credential) => request('/auth/google', { method: 'POST', body: { credential } }),
  loginDev: (email, name) => request('/auth/dev', { method: 'POST', body: { email, name } }),
  logout: () => request('/auth/logout', { method: 'POST' }),
  deleteAccount: () => request('/me', { method: 'DELETE' }),
  createOrg: (name) => request('/orgs', { method: 'POST', body: { name } }),
  deleteOrg: () => request('/orgs/current', { method: 'DELETE' }),
  chooseOrg: (org_id) => request('/me/org', { method: 'PUT', body: { org_id } }),
  members: () => request('/orgs/current/members'),
  invite: (email, role) => request('/orgs/current/invites', { method: 'POST', body: { email, role } }),
  revokeInvite: (id) => request(`/orgs/current/invites/${id}`, { method: 'DELETE' }),
  removeMember: (userId) => request(`/orgs/current/members/${userId}`, { method: 'DELETE' }),
  dataStatus: () => request('/data'),
  templateUrl: (table) => `${BASE}/data/templates/${table}.csv`,
  uploadTable: (table, file) => {
    const form = new FormData()
    form.append('file', file)
    return request(`/data/${table}`, { method: 'PUT', form })
  },
  deleteTable: (table) => request(`/data/${table}`, { method: 'DELETE' }),
  loadDemo: () => request('/data/demo', { method: 'POST' }),
  scores: () => request('/scores'),
  unmatched: () => request('/unmatched'),
  evidence: (growerId, season) => request(`/growers/${growerId}/seasons/${season}`),
  explanation: (growerId, season) => request(`/growers/${growerId}/seasons/${season}/explanation`, { method: 'POST' }),
}
