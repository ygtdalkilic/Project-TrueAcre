import { useEffect, useState } from 'react'
import { api } from './api.js'
import Evidence from './Evidence.jsx'
import { Label, fmt } from './ui.jsx'

// A grower's own page: every season the company has on record for them, the evidence behind each
// score, and the one thing only the grower can supply, the seed statement.
export default function GrowerHome({ company }) {
  const [seasons, setSeasons] = useState(null)
  const [selected, setSelected] = useState(null)
  const [version, setVersion] = useState(0)
  const [acres, setAcres] = useState('')
  const [message, setMessage] = useState(null)
  const [error, setError] = useState(null)

  const refresh = () => api.growerSeasons().then(setSeasons).catch((e) => setError(e.message))
  useEffect(() => {
    refresh()
  }, [])

  const choose = (row) => {
    setSelected(row)
    setAcres(row.has_statement ? String(row.other_seed_acres) : '')
    setMessage(null)
    setError(null)
  }

  const file = (e) => {
    e.preventDefault()
    setError(null)
    api.fileStatement(selected.season, selected.crop, Number(acres))
      .then(() => {
        setMessage(`Statement recorded for ${selected.crop}, ${selected.season}.`)
        setVersion(version + 1)
        return api.growerSeasons().then((rows) => {
          setSeasons(rows)
          setSelected(rows.find((r) => r.season === selected.season && r.crop === selected.crop))
        })
      })
      .catch((err) => setError(err.message))
  }

  if (error && !seasons) return <p className="error">{error}</p>
  if (!seasons) return <p className="muted">Loading…</p>

  return (
    <div className="layout">
      <section>
        <p>
          These are the records {company} holds for you, and the arithmetic behind each season. You can check every
          number and add the one record only you can give: how many acres you planted with other seed.
        </p>
        {seasons.length === 0 ? <p className="muted">No seasons on record yet.</p> : (
          <table>
            <thead><tr><th>Season</th><th>Crop</th><th className="num">Score</th><th>Label</th><th>Seed statement</th></tr></thead>
            <tbody>
              {seasons.map((r) => (
                <tr key={`${r.season}-${r.crop}`} onClick={() => choose(r)}
                    className={selected && selected.season === r.season && selected.crop === r.crop ? 'selected' : ''}>
                  <td>{r.season}</td><td>{r.crop}</td><td className="num">{r.fair_play_score}</td>
                  <td><Label value={r.label} /></td>
                  <td>{r.has_statement ? `${fmt(r.other_seed_acres)} acres other seed` : <span className="muted">none on file</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <aside>
        {selected ? (
          <>
            <Evidence season={selected.season} crop={selected.crop} grower version={version} />
            <h3>Your seed statement</h3>
            <form onSubmit={file} className="inline">
              <label>
                Acres of {selected.crop} you planted in {selected.season} with seed not bought from {company}{' '}
                <input type="number" min="0" step="0.1" required value={acres} onChange={(e) => setAcres(e.target.value)} />
              </label>
              <button className="primary" type="submit">Save statement</button>
            </form>
            <p className="muted small">
              Another company's seed or conventional seed. Enter 0 if all of it was {company}'s. Your statement is
              recorded with the date and shown to {company}'s staff.
            </p>
            {message && <p className="ok">{message}</p>}
            {error && <p className="error">{error}</p>}
          </>
        ) : (
          <p className="muted">Select a season to see the records and arithmetic behind it.</p>
        )}
      </aside>
    </div>
  )
}
