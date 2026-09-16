import { useEffect, useState } from 'react'
import { api, AuthError } from './api.js'
import Company from './Company.jsx'
import Data from './Data.jsx'
import Links from './Links.jsx'
import Login from './Login.jsx'
import Members from './Members.jsx'
import Scores from './Scores.jsx'

const VIEWS = { scores: 'Scores', links: 'Links', data: 'Data', members: 'Members' }

export default function App() {
  const [config, setConfig] = useState(null)
  const [me, setMe] = useState(undefined) // undefined = loading, null = signed out
  const [view, setView] = useState('scores')
  const [error, setError] = useState(null)

  useEffect(() => {
    api.config().then(setConfig).catch((e) => setError(e.message))
    api.me().then(setMe).catch((e) => (e instanceof AuthError ? setMe(null) : setError(e.message)))
  }, [])

  const signOut = () => api.logout().then(() => setMe(null)).catch((e) => setError(e.message))

  if (error) return <div className="app"><p className="error">{error}</p></div>
  if (!config || me === undefined) return <div className="app"><p className="muted">Loading…</p></div>
  if (!me) return <Login config={config} onSignedIn={setMe} />
  if (!me.current_org) {
    return <Company me={me} onChanged={setMe} onSignOut={signOut} onDeleted={() => setMe(null)} />
  }

  const isAdmin = me.current_org.role === 'admin'
  const views = isAdmin ? Object.keys(VIEWS) : Object.keys(VIEWS).filter((v) => v !== 'members')

  return (
    <div className="app">
      <header className="bar">
        <div className="brand">
          <h1>TrueAcre</h1>
          <span className="muted">{me.current_org.name}</span>
        </div>
        <nav>
          {views.map((v) => (
            <button key={v} className={view === v ? 'tab active' : 'tab'} onClick={() => setView(v)}>
              {VIEWS[v]}
            </button>
          ))}
        </nav>
        <div className="who">
          <span>{me.user.name}</span>
          <button className="link" onClick={() => setMe({ ...me, current_org: null })}>switch company</button>
          <button className="link" onClick={signOut}>sign out</button>
        </div>
      </header>

      {view === 'scores' && <Scores config={config} onNeedData={() => setView('data')} />}
      {view === 'links' && <Links onNeedData={() => setView('data')} />}
      {view === 'data' && <Data config={config} />}
      {view === 'members' && isAdmin && <Members me={me} onOrgDeleted={(m) => { setMe(m); setView('scores') }} />}

      <footer className="muted small">
        Scores are indicators computed from uploaded records, never findings about a person.{' '}
        <a href="/terms.html">Terms of Use</a> · <a href="/privacy.html">Privacy Policy</a>
      </footer>
    </div>
  )
}
