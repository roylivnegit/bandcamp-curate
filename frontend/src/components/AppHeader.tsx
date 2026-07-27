import { Link } from 'react-router-dom'

import { useAuth } from '../auth/context'
import './AppHeader.css'

export function AppHeader() {
  const { me, logout } = useAuth()

  return (
    <header className="apphead">
      <div className="wrap apphead-inner">
        <Link to="/scans" className="brand">
          <span className="brand-mark" aria-hidden="true" />
          <span className="brand-name">
            crate <span className="brand-hl">digger</span>
          </span>
        </Link>
        <div className="spacer" />
        {me && (
          <>
            <span className="whoami num" title="Signed in">
              {me.username}
            </span>
            <button type="button" className="btn ghost signout" onClick={logout}>
              Sign out
            </button>
          </>
        )}
      </div>
    </header>
  )
}
