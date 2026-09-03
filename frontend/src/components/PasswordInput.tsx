import { useState } from 'react'

import './PasswordInput.css'

/** A password `<input>` with a "Show"/"Hide" toggle. Drop-in replacement for a raw
 *  `<input type="password">` -- LoginPage/SignupPage pass the same id/autoComplete/
 *  value/onChange they already had. */
export function PasswordInput({
  id,
  autoComplete,
  value,
  onChange,
}: {
  id: string
  autoComplete: string
  value: string
  onChange: (e: React.ChangeEvent<HTMLInputElement>) => void
}) {
  const [visible, setVisible] = useState(false)

  return (
    <div className="pwfield">
      <input
        id={id}
        className="input"
        type={visible ? 'text' : 'password'}
        autoComplete={autoComplete}
        value={value}
        onChange={onChange}
      />
      <button
        type="button"
        className="pwtoggle"
        aria-pressed={visible}
        onClick={() => setVisible((v) => !v)}
      >
        {visible ? 'Hide' : 'Show'}
      </button>
    </div>
  )
}
