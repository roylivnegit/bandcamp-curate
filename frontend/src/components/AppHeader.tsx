import { Link } from 'react-router-dom'

import { useAuth } from '../auth/context'
import { APP_NAME } from '../config'
import { Dropdown } from './Dropdown'
import './AppHeader.css'

export function AppHeader() {
  const { me, logout } = useAuth()

  return (
    <header className="apphead">
      <div className="wrap apphead-inner">
        <Dropdown
          label={
            <>
              <span className="menu-icon" aria-hidden="true">
                <span />
                <span />
                <span />
              </span>
              <span className="sr-only">Menu</span>
            </>
          }
        >
          {(close) => (
            <div>
              {me && (
                <>
                  <div className="ddhead">
                    Signed in as <b>{me.username}</b>
                  </div>
                  <div className="ddsep" />
                </>
              )}
              <Link to="/scans" className="ddrow" onClick={close}>
                <span className="nm">Scans</span>
              </Link>
              {me && (
                <button
                  type="button"
                  className="ddrow"
                  onClick={() => {
                    close()
                    logout()
                  }}
                >
                  <span className="nm">Sign out</span>
                </button>
              )}
            </div>
          )}
        </Dropdown>
        <Link to="/scans" className="brand">
          <span className="brand-name">{APP_NAME}</span>
        </Link>
      </div>
    </header>
  )
}
