import { useEffect, useRef, useState } from 'react'
import { api } from './api.js'

const GSI_SCRIPT = 'https://accounts.google.com/gsi/client'

export default function Login({ config, onSignedIn }) {
  const buttonRef = useRef(null)
  const [error, setError] = useState(null)
  const [email, setEmail] = useState('')
  const [name, setName] = useState('')

  useEffect(() => {
    if (!config.google_client_id) return
    const init = () => {
      window.google.accounts.id.initialize({
        client_id: config.google_client_id,
        callback: (r) => api.loginGoogle(r.credential).then(onSignedIn).catch((e) => setError(e.message)),
      })
      window.google.accounts.id.renderButton(buttonRef.current, { theme: 'outline', size: 'large', text: 'signin_with' })
    }
    if (window.google?.accounts?.id) {
      init()
      return
    }
    const script = document.createElement('script')
    script.src = GSI_SCRIPT
    script.async = true
    script.onload = init
    script.onerror = () => setError('Could not load Google sign-in.')
    document.head.appendChild(script)
  }, [config.google_client_id, onSignedIn])

  const devSignIn = (e) => {
    e.preventDefault()
    setError(null)
    api.loginDev(email, name).then(onSignedIn).catch((err) => setError(err.message))
  }

  return (
    <div className="app narrow">
      <h1>TrueAcre</h1>
      <p className="muted">Sign in to your company's workspace.</p>

      {config.google_client_id ? (
        <div ref={buttonRef} className="google-button" />
      ) : (
        <p className="muted">Google sign-in is not configured on this server.</p>
      )}

      {config.dev_login && (
        <form onSubmit={devSignIn} className="panel">
          <h3>Development sign-in</h3>
          <p className="muted">Only available on local development servers.</p>
          <input type="email" placeholder="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          <input type="text" placeholder="name" value={name} onChange={(e) => setName(e.target.value)} />
          <button className="primary" type="submit">Sign in</button>
        </form>
      )}

      {error && <p className="error">{error}</p>}
      <p className="muted small">
        By signing in you agree to the <a href="/terms.html">Terms of Use</a> and{' '}
        <a href="/privacy.html">Privacy Policy</a>.
      </p>
    </div>
  )
}
