// Override with VITE_API_URL in web/.env (see web/.env.example); default is the local uvicorn server.
const BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

async function get(path) {
  const res = await fetch(BASE + path)
  if (!res.ok) throw new Error(`API returned ${res.status} for ${path}`)
  return res.json()
}

export const fetchScores = () => get('/scores')
export const fetchUnmatched = () => get('/unmatched')
export const fetchEvidence = (growerId, season) => get(`/growers/${growerId}/seasons/${season}`)
