const BASE = 'http://localhost:8000'

async function get(path) {
  const res = await fetch(BASE + path)
  if (!res.ok) throw new Error(`API returned ${res.status} for ${path}`)
  return res.json()
}

export const fetchScores = () => get('/scores')
export const fetchEvidence = (growerId, season) => get(`/growers/${growerId}/seasons/${season}`)
