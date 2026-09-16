import { useEffect, useState } from 'react'
import { api } from './api.js'
import { fmt } from './ui.jsx'

const STATUS = {
  unmatched: { text: 'unmatched', cls: 'label-review', help: 'The resolver found no single grower for this record. It counts toward nobody until you rule.' },
  check: { text: 'check link', cls: 'label-unknown', help: 'Linked automatically by name similarity only. Confirm or correct it.' },
  analyst: { text: 'ruled', cls: 'label-ok', help: 'Your ruling overrides the resolver.' },
}

export default function Links({ onNeedData }) {
  const [items, setItems] = useState(null)
  const [choice, setChoice] = useState({})
  const [needData, setNeedData] = useState(false)
  const [error, setError] = useState(null)

  const refresh = () => api.reviewLinks().then(setItems).catch((e) => (e.status === 409 ? setNeedData(true) : setError(e.message)))
  useEffect(() => {
    refresh()
  }, [])

  const decide = (item, growerId) => api.decideLink(item.record_id, growerId, null).then(refresh).catch((e) => setError(e.message))
  const revert = (item) => api.revertLink(item.record_id).then(refresh).catch((e) => setError(e.message))

  if (needData) return <p>No records to review yet: upload all seven tables first. <button className="link" onClick={onNeedData}>Go to Data</button></p>
  if (error) return <p className="error">{error}</p>
  if (!items) return <p className="muted">Loading…</p>

  const counts = items.reduce((c, i) => ({ ...c, [i.status]: (c[i.status] || 0) + 1 }), {})

  return (
    <div>
      <p>
        Acreage reports and scale tickets name the grower as someone else wrote it. The resolver links
        a record only when exactly one grower fits; everything else waits here for a person. Rulings
        override the resolver and are recorded in the activity log.
      </p>
      <p className="muted">
        {counts.unmatched || 0} unmatched · {counts.check || 0} to check · {counts.analyst || 0} ruled
      </p>
      {items.length === 0 && <p className="ok">Every record is linked with confidence. Nothing to review.</p>}
      {items.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Status</th><th>Record</th><th>Name on record</th><th>County</th><th>Season</th>
              <th className="num">Amount</th><th>Grower</th><th></th>
            </tr>
          </thead>
          <tbody>
            {items.map((it) => {
              const selected = choice[it.record_id] ?? it.candidates[0]?.grower_id ?? ''
              return (
                <tr key={it.record_id}>
                  <td title={STATUS[it.status].help}><span className={`label ${STATUS[it.status].cls}`}>{STATUS[it.status].text}</span></td>
                  <td>{it.record_id} <span className="muted small">{it.source === 'acreage_reports' ? 'acreage' : 'elevator'}</span></td>
                  <td>{it.name}{it.reason && <div className="muted small">{it.reason}</div>}</td>
                  <td>{it.county}</td>
                  <td>{it.season}</td>
                  <td className="num">{fmt(it.amount)} {it.source === 'acreage_reports' ? 'ac' : 'bu'}</td>
                  <td>
                    {it.status === 'analyst' ? (
                      it.grower_id ? `${it.candidates.find((c) => c.grower_id === it.grower_id)?.name ?? ''} ${it.grower_id}` : 'matches nobody'
                    ) : (
                      <select value={selected} onChange={(e) => setChoice({ ...choice, [it.record_id]: e.target.value })}>
                        {it.candidates.map((c) => (
                          <option key={c.grower_id} value={c.grower_id}>
                            {c.name} ({c.grower_id}) · {Math.round(c.similarity * 100)}%
                          </option>
                        ))}
                      </select>
                    )}
                  </td>
                  <td className="row-actions">
                    {it.status === 'analyst' ? (
                      <button className="link" onClick={() => revert(it)}>undo</button>
                    ) : (
                      <>
                        <button className="link" onClick={() => decide(it, selected)} disabled={!selected}>link</button>
                        <button className="link" onClick={() => decide(it, null)}>not a match</button>
                      </>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
    </div>
  )
}
