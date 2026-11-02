import { useEffect, useState } from 'react'
import { api } from './api.js'
import { Label, fmt, pct } from './ui.jsx'

function conclusion(s, grower) {
  if (s.label === 'consistent') {
    return 'The purchased seed accounts for the declared acres and delivered bushels within tolerance.'
  }
  if (!s.has_purchases) {
    return 'No purchases of this seed are visible for this grower and season, so there is nothing to compare against. No conclusion can be drawn.'
  }
  if (s.label === 'insufficient data' && !s.has_statement) {
    return "There is a gap, but the grower has no seed statement on file, so the unsupported acres may have been planted with another company's seed or conventional seed. No conclusion should be drawn."
  }
  if (grower) {
    return s.label === 'insufficient data'
      ? 'There is a gap, but the records available are not complete enough to draw any conclusion.'
      : 'There is a gap that the records on file do not explain. The list below shows what record would settle it.'
  }
  if (s.label === 'insufficient data') {
    return `There is a gap, but only ${pct(s.coverage)} of dealers in this county and the counties bordering it report into the system, so the missing seed may simply have been bought elsewhere. No conclusion should be drawn.`
  }
  return "There is a gap that the grower's own seed statement does not account for, and dealer coverage is high, so unseen purchases are unlikely. The evidence above warrants a review."
}

// What one more record would settle. Dealer names are left out of the grower's own view.
export function WhatWouldClear({ s, clear, showDealers = true }) {
  if (s.label === 'consistent') return null
  const acres = Math.ceil(clear.acres)
  return (
    <>
      <h3>What would clear this</h3>
      <ul>
        {acres > 0 && (
          <li>
            Records for <b>{fmt(acres)}</b> more acres would make this season consistent
            {clear.units && <>: for example <b>{fmt(clear.units.units)}</b> more units of {clear.units.variety} bought this season</>}
            , or a seed statement covering {fmt(acres)} acres of other seed.
          </li>
        )}
        {clear.needs.includes('statement') && <li>No seed statement is on file for this season. Without one, no conclusion can be drawn.</li>}
        {clear.needs.includes('purchases') && <li>No purchases of this seed are on record for this season.</li>}
        {showDealers && clear.non_reporting_dealers.length > 0 && (
          <li>Receipts from these nearby dealers, who do not report into the system, could explain it: {clear.non_reporting_dealers.join(', ')}.</li>
        )}
      </ul>
    </>
  )
}

export function AcrossSeasons({ s, history }) {
  if (history.length < 2) return null
  const from = history.find((h) => h.season === s.replant_from_season)
  return (
    <>
      <h3>Across seasons</h3>
      <table>
        <thead><tr><th>Season</th><th className="num">Declared ac</th><th className="num">Licensed + other ac</th><th className="num">Explained</th><th>Label</th></tr></thead>
        <tbody>
          {history.map((h) => (
            <tr key={h.season} className={h.season === s.season ? 'selected' : ''}>
              <td>{h.season}</td><td className="num">{fmt(h.declared_acres)}</td>
              <td className="num">{fmt(h.licensed_acres + h.other_seed_acres)}</td>
              <td className="num">{h.explained_share === null ? '—' : pct(h.explained_share)}</td><td>{h.label}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {s.replant_signal && from && (
        <p>
          <b>Replant pattern.</b> In {from.season}, purchases explained {pct(from.explained_share)} of the declared acres; in {s.season} they
          explain {pct(s.explained_share)} of a similar acreage. That matches buying seed once and replanting saved seed. It is context
          only and does not change the score.
        </p>
      )}
    </>
  )
}

// `grower` is the grower's own view: their endpoint, no dealer coverage, no explanation button.
export default function Evidence({ growerId, season, crop, explain, grower = false, version = 0 }) {
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
    const load = grower ? api.growerEvidence(season, crop) : api.evidence(growerId, season, crop)
    load.then(setData).catch((e) => setError(e.message))
  }, [growerId, season, crop, grower, version])

  const requestExplanation = () => {
    setExplaining(true)
    setExplainError(null)
    api.explanation(growerId, season, crop)
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
        {s.name} <span className="muted">{s.grower_id} · {s.season} · {s.crop}</span>
      </h2>
      <div className="scorecard">
        <div className="big">{s.fair_play_score}</div>
        <div>
          <Label value={s.label} />
          {!grower && <div className="muted">dealer coverage {pct(s.coverage)}</div>}
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
        {s.has_statement
          ? <>Other seed, per the grower's statement = <b>{fmt(s.other_seed_acres)}</b> acres</>
          : 'No seed statement on file: other seed counted as 0 acres'}
      </p>
      <p className="calc">
        Acre gap = {fmt(s.declared_acres)} − {fmt(s.licensed_acres)} − {fmt(s.other_seed_acres)} = <b>{fmt(s.acre_gap)}</b>{' '}
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
        Max bushels from licensed and other seed = ({fmt(s.licensed_acres)} + {fmt(s.other_seed_acres)}) × {fmt(s.yield_ceiling)} = <b>{fmt(s.max_bushels)}</b>
      </p>
      <p className="calc">
        Bushel gap = {fmt(s.delivered_bushels)} − {fmt(s.max_bushels)} = <b>{fmt(s.bushel_gap)}</b>{' '}
        ({pct(s.unsupported_bushel_fraction)} of delivered bushels unsupported)
      </p>

      <h3>Result</h3>
      <p className="calc">
        Fair-Play Score = 100 × (1 − {pct(s.gap_fraction)}) = <b>{s.fair_play_score}</b>
      </p>
      <p>{conclusion(s, grower)}</p>
      <WhatWouldClear s={s} clear={data.clear} showDealers={!grower} />
      <AcrossSeasons s={s} history={data.history} />

      {!grower && explain.explanations_enabled && !explanation && (
        <button className="primary" onClick={requestExplanation} disabled={explaining}>
          {explaining ? 'Writing…' : 'Explain in plain English'}
        </button>
      )}
      {explainError && <p className="error">{explainError}</p>}
      {explanation && (
        <>
          <h3>Plain-English reading</h3>
          <p className="explanation">{explanation}</p>
          <p className="muted">
            Written by {explain.model} via {explain.provider} from the evidence above. It does not change the score.
          </p>
        </>
      )}
    </div>
  )
}
