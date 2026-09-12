import { useEffect, useState } from 'react'
import { api } from './api.js'

export default function Members({ me, onOrgDeleted }) {
  const [data, setData] = useState(null)
  const [email, setEmail] = useState('')
  const [role, setRole] = useState('analyst')
  const [message, setMessage] = useState(null)
  const [error, setError] = useState(null)

  const refresh = () => api.members().then(setData).catch((e) => setError(e.message))
  useEffect(() => {
    refresh()
  }, [])

  const invite = (e) => {
    e.preventDefault()
    setError(null)
    setMessage(null)
    api.invite(email, role)
      .then((r) => {
        setMessage(r.joined ? `${r.email} already had an account and is now a member.` : `Invite recorded for ${r.email}. They join when they sign in.`)
        setEmail('')
        refresh()
      })
      .catch((err) => setError(err.message))
  }
  const revoke = (id) => api.revokeInvite(id).then(refresh).catch((err) => setError(err.message))
  const remove = (userId) => api.removeMember(userId).then(refresh).catch((err) => setError(err.message))
  const deleteCompany = () => {
    if (!window.confirm(`Delete ${me.current_org.name} and all of its uploaded data? This cannot be undone.`)) return
    api.deleteOrg().then(api.me).then(onOrgDeleted).catch((err) => setError(err.message))
  }

  if (!data) return <p className="muted">Loading…</p>

  return (
    <div className="narrow-left">
      <h3>Members of {me.current_org.name}</h3>
      <table>
        <thead><tr><th>Name</th><th>Email</th><th>Role</th><th></th></tr></thead>
        <tbody>
          {data.members.map((m) => (
            <tr key={m.user_id}>
              <td>{m.name}</td><td>{m.email}</td><td>{m.role}</td>
              <td>{m.user_id !== me.user.id && <button className="link" onClick={() => remove(m.user_id)}>remove</button>}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h3>Invite a colleague</h3>
      <form onSubmit={invite} className="inline">
        <input type="email" placeholder="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        <select value={role} onChange={(e) => setRole(e.target.value)}>
          <option value="analyst">analyst</option>
          <option value="admin">admin</option>
        </select>
        <button className="primary" type="submit">Invite</button>
      </form>
      <p className="muted">Analysts can view scores and upload data. Admins can also manage members.</p>
      {message && <p className="ok">{message}</p>}
      {error && <p className="error">{error}</p>}

      {data.invites?.length > 0 && (
        <>
          <h3>Pending invites</h3>
          <table>
            <thead><tr><th>Email</th><th>Role</th><th></th></tr></thead>
            <tbody>
              {data.invites.map((i) => (
                <tr key={i.id}>
                  <td>{i.email}</td><td>{i.role}</td>
                  <td><button className="link" onClick={() => revoke(i.id)}>revoke</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      <h3>Delete company</h3>
      <p className="muted">Removes every uploaded table, invite, and membership immediately and permanently.</p>
      <button className="danger" onClick={deleteCompany}>Delete {me.current_org.name}</button>
    </div>
  )
}
