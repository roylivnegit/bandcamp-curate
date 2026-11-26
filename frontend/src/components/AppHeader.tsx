import { Link } from 'react-router-dom'

import { APP_NAME } from '../config'
import { openCommandPalette } from '../lib/commandPalette'
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
        {/* Ctrl/Cmd+K opens the same palette, but a shortcut nobody can see is
            a feature only the people who read the shortcuts panel have — and
            on a phone there is no Ctrl at all. The visible keycap is a hint
            for the people who can use it, hidden where it would be a lie. */}
        <button
          type="button"
          className="apphead-search"
          onClick={openCommandPalette}
          aria-label="Search scans, records and artists"
        >
          <span className="apphead-search-icon" aria-hidden="true">
            ⌕
          </span>
          <span className="apphead-search-text" aria-hidden="true">
            Search
          </span>
          <kbd className="apphead-search-key" aria-hidden="true">
            ⌘K
          </kbd>
        </button>
      </div>
    </header>
  )
}
