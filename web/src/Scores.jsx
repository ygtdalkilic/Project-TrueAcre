import { useEffect, useState } from 'react'
import { api } from './api.js'
import Evidence from './Evidence.jsx'
import { Label, fmt, pct } from './ui.jsx'

const LABELS = ['review recommended', 'insufficient data', 'consistent']

export default function Scores({ config, onNeedData }) {
  const [scores, setScores] = useState(null)
  const [unmatched, setUnmatched] = useState([])
  const [showUnmatched, setShowUnmatched] = useState(false)
  const [needData, setNeedData] = useState(false)
  const [error, setError] = useState(null)
  const [season, setSeason] = useState('')
  const [county, setCounty] = useState('')
  const [label, setLabel] = useState('')
  const [crop, setCrop] = useState('')
  const [selected, setSelected] = useState(null)

  useEffect(() => {
    Promise.all([api.scores(), api.unmatched()])
      .then(([s, u]) => { setScores(s); setUnmatched(u) })
      .catch((e) => (e.status === 409 ? setNeedData(true) : setError(e.message)))
  }, [])

  if (error) return <p className="error">{error}</p>
  if (needData) {
    return (
      <p>
        No scores yet: this company has not uploaded all seven tables.{' '}
        <button className="link" onClick={onNeedData}>Go to Data</button>
      </p>
    )
  }
  if (!scores) return <p className="muted">Loading…</p>

  const seasons = [...new Set(scores.map((s) => s.season))].sort()
  const counties = [...new Set(scores.map((s) => s.county))].sort()
  const crops = [...new Set(scores.map((s) => s.crop))].sort()
  const rows = scores.filter(
    (s) =>
      (!season || s.season === Number(season)) &&
      (!county || s.county === county) &&
      (!label || s.label === label) &&
      (!crop || s.crop === crop),
  )
  const sameRow = (a, b) => a.grower_id === b.grower_id && a.season === b.season && a.crop === b.crop
  const isSelected = (r) => selected && sameRow(selected, r)

  return (
    <div className="layout">
      <section>
        <p className="muted">
          A low score means more declared acres or delivered bushels than the purchased seed can
          explain. The label says whether the data is complete enough to draw any conclusion.
        </p>
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
          {crops.length > 1 && (
            <select value={crop} onChange={(e) => setCrop(e.target.value)}>
              <option value="">All crops</option>
              {crops.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          )}
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
              <th>Crop</th>
              <th className="num">Licensed ac</th>
              <th className="num">Declared ac</th>
              <th className="num">Coverage</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={`${r.grower_id}-${r.season}-${r.crop}`} className={isSelected(r) ? 'selected' : ''} onClick={() => setSelected(r)}>
                <td className="num">{r.fair_play_score}</td>
                <td><Label value={r.label} /></td>
                <td>{r.name} <span className="muted">{r.grower_id}</span></td>
                <td>{r.county}, {r.state}</td>
                <td>{r.season}</td>
                <td>{r.crop}</td>
                <td className="num">{fmt(r.licensed_acres)}</td>
                <td className="num">{fmt(r.declared_acres)}</td>
                <td className="num">{pct(r.coverage)}</td>
              </tr>
            ))}
          </tbody>
        </table>

        {unmatched.length > 0 && (
          <p className="muted">
            {unmatched.length} external records could not be linked to a registered grower with confidence
            and are excluded from every score.{' '}
            <button className="link" onClick={() => setShowUnmatched(!showUnmatched)}>
              {showUnmatched ? 'hide' : 'show'}
            </button>
          </p>
        )}
        {showUnmatched && (
          <table>
            <thead><tr><th>Source</th><th>Record</th><th>Name on record</th><th>County</th><th>Reason</th></tr></thead>
            <tbody>
              {unmatched.map((u) => (
                <tr key={u.record_id}>
                  <td>{u.source}</td><td>{u.record_id}</td><td>{u.name}</td><td>{u.county}</td><td>{u.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <aside>
        {selected ? (
          <Evidence growerId={selected.grower_id} season={selected.season} crop={selected.crop} explain={config} />
        ) : (
          <p className="muted">Select a grower to see the evidence behind the score.</p>
        )}
      </aside>
    </div>
  )
}
