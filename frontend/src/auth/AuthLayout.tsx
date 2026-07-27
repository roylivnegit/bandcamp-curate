import type { ReactNode } from 'react'

import './auth.css'

/** The shared frame for login/signup: a centred card under the wordmark. */
export function AuthLayout({
  title,
  blurb,
  children,
  footer,
}: {
  title: string
  blurb: string
  children: ReactNode
  footer: ReactNode
}) {
  return (
    <div className="authpage">
      <div className="authbox">
        <div className="authbrand">
          <span className="brand-mark" aria-hidden="true" />
          <span className="authbrand-name">
            crate <span className="brand-hl">digger</span>
          </span>
        </div>
        <h1 className="authtitle">{title}</h1>
        <p className="authblurb">{blurb}</p>
        <div className="panel authcard">{children}</div>
        <p className="authfoot">{footer}</p>
      </div>
    </div>
  )
}
