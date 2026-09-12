import { useEffect, useState } from 'react'
import { api } from './api.js'

const DESCRIPTIONS = {
  growers: 'Your customer list: one row per grower, with the FSA farm number when you have it.',
  dealers: 'Dealers in each county and whether they report their receipts into the system.',
  varieties: 'Seed varieties with seeds per unit and the target seeding rate.',
  seed_purchases: 'Dealer receipts: units of each variety bought by each grower per season.',
  acreage_reports: 'Government acreage filings, with the operator name as written on the form.',
  elevator_receipts: 'Grain elevator scale tickets, with the seller name as written on the ticket.',
  county_yields: 'County average yield and standard deviation per crop and season.',
}

export default function Data() {
  const [status, setStatus] = useState(null)
  const [busy, setBusy] = useState(null)
  const [message, setMessage] = useState(null)
  const [error, setError] = useState(null)

  const refresh = () => api.dataStatus().then(setStatus).catch((e) => setError(e.message))
  useEffect(() => {
    refresh()
  }, [])

  const run = (label, promise) => {
    setBusy(label)
    setError(null)
    setMessage(null)
    return promise.then((r) => { setMessage(r); refresh() }).catch((e) => setError(e.message)).finally(() => setBusy(null))
  }

  const upload = (table, file) => {
    if (!file) return
    run(table, api.uploadTable(table, file).then((r) => `${r.table}: ${r.rows} rows uploaded.`))
  }
  const remove = (table) => run(table, api.deleteTable(table).then(() => `${table}: removed.`))
  const demo = () => run('demo', api.loadDemo().then(() => 'Sample dataset loaded into all seven tables.'))

  if (!status) return <p className="muted">Loading…</p>
  const missing = status.filter((s) => s.rows === null).length

  return (
    <div>
      <p>
        Upload the seven tables as CSV. Download a template for the exact column names. Scores are
        recomputed after every upload.{' '}
        {missing > 0 ? <b>{missing} of 7 tables still missing.</b> : <b>All tables present.</b>}
      </p>
      <p>
        <button className="primary" onClick={demo} disabled={busy !== null}>Load sample dataset</button>{' '}
        <span className="muted">Replaces every table with the synthetic demo company.</span>
      </p>
      {message && <p className="ok">{message}</p>}
      {error && <p className="error">{error}</p>}

      <div className="cards">
        {status.map((s) => (
          <div key={s.table} className="card">
            <h3>{s.table}</h3>
            <p className="muted">{DESCRIPTIONS[s.table]}</p>
            <p className="muted small">columns: {s.columns.join(', ')}</p>
            <p>
              {s.rows === null ? <span className="label label-unknown">not uploaded</span> : (
                <span className="label label-ok">{s.rows.toLocaleString()} rows</span>
              )}
              {s.uploaded_at && <span className="muted"> · {new Date(s.uploaded_at).toLocaleString()}</span>}
            </p>
            <p className="actions">
              <a href={api.templateUrl(s.table)}>template</a>
              <label className="link">
                {busy === s.table ? 'working…' : 'upload CSV'}
                <input type="file" accept=".csv,text/csv" hidden disabled={busy !== null}
                       onChange={(e) => { upload(s.table, e.target.files[0]); e.target.value = '' }} />
              </label>
              {s.rows !== null && <button className="link" onClick={() => remove(s.table)} disabled={busy !== null}>remove</button>}
            </p>
          </div>
        ))}
      </div>
    </div>
  )
}
