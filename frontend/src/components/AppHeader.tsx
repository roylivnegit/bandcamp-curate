import { Link } from 'react-router-dom'

import { APP_NAME } from '../config'
import { SideNav } from './SideNav'
import './AppHeader.css'

export function AppHeader() {
  return (
    <header className="apphead">
      <div className="apphead-inner">
        <SideNav />
        <Link to="/scans" className="brand">
          <span className="brand-name">{APP_NAME}</span>
        </Link>
      </div>
    </header>
  )
}
