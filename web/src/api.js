// Override with VITE_API_URL in web/.env (see web/.env.example); default is the local uvicorn server.
const BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

async function request(path, method = 'GET') {
  const res = await fetch(BASE + path, { method })
  if (!res.ok) {
    let detail = ''
    try {
      detail = (await res.json()).detail
    } catch {
      // no JSON body; fall through to the generic message
    }
    throw new Error(detail || `API returned ${res.status} for ${path}`)
  }
  return res.json()
}

export const fetchConfig = () => request('/config')
export const fetchScores = () => request('/scores')
export const fetchUnmatched = () => request('/unmatched')
export const fetchEvidence = (growerId, season) => request(`/growers/${growerId}/seasons/${season}`)
export const fetchExplanation = (growerId, season) =>
  request(`/growers/${growerId}/seasons/${season}/explanation`, 'POST')
