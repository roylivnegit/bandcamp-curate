import type { ReactNode } from 'react'

import { APP_NAME } from '../config'
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
          <span className="authbrand-name">{APP_NAME}</span>
        </div>
        <h1 className="authtitle">{title}</h1>
        <p className="authblurb">{blurb}</p>
        <div className="panel authcard">{children}</div>
        <p className="authfoot">{footer}</p>
      </div>
    </div>
  )
}
