import { useEffect, useState } from 'react'
import { fetchScores } from './api.js'
import Evidence from './Evidence.jsx'
import { Label, fmt, pct } from './ui.jsx'

const LABELS = ['review recommended', 'insufficient data', 'consistent']

export default function App() {
  const [scores, setScores] = useState([])
  const [error, setError] = useState(null)
  const [season, setSeason] = useState('')
  const [county, setCounty] = useState('')
  const [label, setLabel] = useState('')
  const [selected, setSelected] = useState(null)

  useEffect(() => {
    fetchScores().then(setScores).catch((e) => setError(e.message))
  }, [])

  const seasons = [...new Set(scores.map((s) => s.season))].sort()
  const counties = [...new Set(scores.map((s) => s.county))].sort()
  const rows = scores.filter(
    (s) =>
      (!season || s.season === Number(season)) &&
      (!county || s.county === county) &&
      (!label || s.label === label),
  )
  const isSelected = (r) => selected && selected.grower_id === r.grower_id && selected.season === r.season

  return (
    <div className="app">
      <header>
        <h1>TrueAcre</h1>
        <p>
          Fair-Play Scores per grower and season. A low score means more declared acres or delivered
          bushels than the purchased seed can explain. The label says whether the data is complete
          enough to draw any conclusion.
        </p>
      </header>

      {error && <p className="error">Could not reach the API at localhost:8000. {error}</p>}

      <div className="layout">
        <section>
          <div className="filters">
            <select value={season} onChange={(e) => setSeason(e.target.value)}>
              <option value="">All seasons</option>
              {seasons.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
            <select value={county} onChange={(e) => setCounty(e.target.value)}>
              <option value="">All counties</option>
              {counties.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
            <select value={label} onChange={(e) => setLabel(e.target.value)}>
              <option value="">All labels</option>
              {LABELS.map((l) => <option key={l} value={l}>{l}</option>)}
            </select>
            <span className="muted">{rows.length} grower-seasons</span>
          </div>

          <table>
            <thead>
              <tr>
                <th className="num">Score</th>
                <th>Label</th>
                <th>Grower</th>
                <th>County</th>
                <th>Season</th>
                <th className="num">Licensed ac</th>
                <th className="num">Declared ac</th>
                <th className="num">Coverage</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr
                  key={`${r.grower_id}-${r.season}`}
                  className={isSelected(r) ? 'selected' : ''}
                  onClick={() => setSelected(r)}
                >
                  <td className="num">{r.fair_play_score}</td>
                  <td><Label value={r.label} /></td>
                  <td>{r.name} <span className="muted">{r.grower_id}</span></td>
                  <td>{r.county}, {r.state}</td>
                  <td>{r.season}</td>
                  <td className="num">{fmt(r.licensed_acres)}</td>
                  <td className="num">{fmt(r.declared_acres)}</td>
                  <td className="num">{pct(r.coverage)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <aside>
          {selected ? (
            <Evidence growerId={selected.grower_id} season={selected.season} />
          ) : (
            <p className="muted">Select a grower to see the evidence behind the score.</p>
          )}
        </aside>
      </div>
    </div>
  )
}
