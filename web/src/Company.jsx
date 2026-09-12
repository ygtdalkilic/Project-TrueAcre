import { useState } from 'react'
import { api } from './api.js'

export default function Company({ me, onChanged, onSignOut, onDeleted }) {
  const [name, setName] = useState('')
  const [error, setError] = useState(null)

  const choose = (id) => api.chooseOrg(id).then(onChanged).catch((e) => setError(e.message))
  const deleteAccount = () => {
    if (!window.confirm('Delete your account? Companies where you are the only member are deleted with it.')) return
    api.deleteAccount().then(onDeleted).catch((e) => setError(e.message))
  }
  const create = (e) => {
    e.preventDefault()
    setError(null)
    api.createOrg(name).then(onChanged).catch((err) => setError(err.message))
  }

  return (
    <div className="app narrow">
      <h1>TrueAcre</h1>
      <p className="muted">
        Signed in as {me.user.name} ({me.user.email}). <button className="link" onClick={onSignOut}>sign out</button>
      </p>

      {me.organizations.length > 0 && (
        <div className="panel">
          <h3>Your companies</h3>
          <ul className="plain">
            {me.organizations.map((o) => (
              <li key={o.id}>
                <button className="link" onClick={() => choose(o.id)}>{o.name}</button>{' '}
                <span className="muted">{o.role}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <form onSubmit={create} className="panel">
        <h3>{me.organizations.length ? 'Create another company' : 'Create your company'}</h3>
        <p className="muted">You become its first admin and can invite colleagues by email.</p>
        <input type="text" placeholder="company name" value={name} onChange={(e) => setName(e.target.value)} required />
        <button className="primary" type="submit">Create</button>
      </form>

      {me.organizations.length === 0 && (
        <p className="muted">Waiting for an invite? Sign in again after your admin adds your email.</p>
      )}
      {error && <p className="error">{error}</p>}
      <p className="muted small">
        <button className="link" onClick={deleteAccount}>Delete my account</button> ·{' '}
        <a href="/privacy.html">Privacy Policy</a> · <a href="/terms.html">Terms of Use</a>
      </p>
    </div>
  )
}
