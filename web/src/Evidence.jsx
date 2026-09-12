import { useEffect, useState } from 'react'
import { fetchEvidence, fetchExplanation } from './api.js'
import { Label, fmt, pct } from './ui.jsx'

function conclusion(s) {
  if (s.label === 'consistent') {
    return 'The purchased seed accounts for the declared acres and delivered bushels within tolerance.'
  }
  if (!s.has_purchases) {
    return 'No purchases of this seed are visible for this grower and season, so there is nothing to compare against. No conclusion can be drawn.'
  }
  if (s.label === 'insufficient data') {
    return `There is a gap, but only ${pct(s.coverage)} of dealers in this county report into the system, so the missing seed may simply have been bought elsewhere. No conclusion should be drawn.`
  }
  return 'There is a gap and dealer coverage is high, so unseen purchases are unlikely. The evidence above warrants a review.'
}

export default function Evidence({ growerId, season, explainEnabled }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [explanation, setExplanation] = useState(null)
  const [explaining, setExplaining] = useState(false)
  const [explainError, setExplainError] = useState(null)

  useEffect(() => {
    setData(null)
    setError(null)
    setExplanation(null)
    setExplainError(null)
    fetchEvidence(growerId, season).then(setData).catch((e) => setError(e.message))
  }, [growerId, season])

  const requestExplanation = () => {
    setExplaining(true)
    setExplainError(null)
    fetchExplanation(growerId, season)
      .then((r) => setExplanation(r.explanation))
      .catch((e) => setExplainError(e.message))
      .finally(() => setExplaining(false))
  }

  if (error) return <p className="error">{error}</p>
  if (!data) return <p className="muted">Loading…</p>

  const s = data.score
  const cy = data.county_yield

  return (
    <div className="evidence">
      <h2>
        {s.name} <span className="muted">{s.grower_id} · {s.season}</span>
      </h2>
      <div className="scorecard">
        <div className="big">{s.fair_play_score}</div>
        <div>
          <Label value={s.label} />
          <div className="muted">dealer coverage {pct(s.coverage)}</div>
        </div>
      </div>

      <h3>1. Seed purchased</h3>
      {data.purchases.length ? (
        <table>
          <thead>
            <tr><th>Dealer</th><th>Variety</th><th className="num">Units</th><th className="num">Seeds/unit</th><th className="num">Seeds/acre</th><th className="num">Acres</th></tr>
          </thead>
          <tbody>
            {data.purchases.map((p) => (
              <tr key={p.purchase_id}>
                <td>{p.dealer}</td>
                <td>{p.variety}</td>
                <td className="num">{p.units}</td>
                <td className="num">{fmt(p.seeds_per_unit)}</td>
                <td className="num">{fmt(p.target_seeds_per_acre)}</td>
                <td className="num">{fmt(p.acres_supported)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="muted">No purchases visible for this grower and season.</p>
      )}
      <p className="calc">Licensed acres = Σ units × seeds per unit ÷ seeds per acre = <b>{fmt(s.licensed_acres)}</b></p>

      <h3>2. Acres declared</h3>
      {data.acreage_reports.length ? (
        <table>
          <thead><tr><th>Report</th><th>Name on form</th><th>Linked by</th><th className="num">Acres</th></tr></thead>
          <tbody>
            {data.acreage_reports.map((a) => (
              <tr key={a.report_id}>
                <td>{a.report_id}</td><td>{a.operator_name}</td><td>{a.match_method}</td>
                <td className="num">{fmt(a.acres)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="muted">No acreage report could be linked to this grower for this season.</p>
      )}
      <p className="calc">
        Acre gap = {fmt(s.declared_acres)} − {fmt(s.licensed_acres)} = <b>{fmt(s.acre_gap)}</b>{' '}
        ({pct(s.unsupported_acre_fraction)} of declared acres unsupported)
      </p>

      <h3>3. Grain delivered</h3>
      {data.elevator_receipts.length ? (
        <table>
          <thead><tr><th>Receipt</th><th>Name on ticket</th><th>Elevator</th><th>Linked by</th><th className="num">Bushels</th></tr></thead>
          <tbody>
            {data.elevator_receipts.map((r) => (
              <tr key={r.receipt_id}>
                <td>{r.receipt_id}</td><td>{r.seller_name}</td><td>{r.elevator_id}</td><td>{r.match_method}</td>
                <td className="num">{fmt(r.bushels)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="muted">No elevator receipts could be linked to this grower for this season.</p>
      )}
      {cy && (
        <p className="calc">
          Yield ceiling = county mean {cy.mean_yield} + {data.yield_sigmas} × std {cy.std_yield} = <b>{fmt(s.yield_ceiling)}</b> bu/acre
        </p>
      )}
      <p className="calc">
        Max bushels from licensed seed = {fmt(s.licensed_acres)} × {fmt(s.yield_ceiling)} = <b>{fmt(s.max_bushels)}</b>
      </p>
      <p className="calc">
        Bushel gap = {fmt(s.delivered_bushels)} − {fmt(s.max_bushels)} = <b>{fmt(s.bushel_gap)}</b>{' '}
        ({pct(s.unsupported_bushel_fraction)} of delivered bushels unsupported)
      </p>

      <h3>Result</h3>
      <p className="calc">
        Fair-Play Score = 100 × (1 − {pct(s.gap_fraction)}) = <b>{s.fair_play_score}</b>
      </p>
      <p>{conclusion(s)}</p>

      {explainEnabled && !explanation && (
        <button className="primary" onClick={requestExplanation} disabled={explaining}>
          {explaining ? 'Writing…' : 'Explain in plain English'}
        </button>
      )}
      {explainError && <p className="error">{explainError}</p>}
      {explanation && (
        <>
          <h3>Plain-English reading</h3>
          <p className="explanation">{explanation}</p>
          <p className="muted">Written by Claude from the evidence above. It does not change the score.</p>
        </>
      )}
    </div>
  )
}
