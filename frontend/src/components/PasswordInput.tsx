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
  const [capsLock, setCapsLock] = useState(false)
  const capsLockId = `${id}-capslock`

  // getModifierState only reflects Caps Lock once the user has pressed a key in this
  // field -- it can't see a Caps Lock that was already on before the field was
  // touched. A known limitation of the API, not a bug to work around.
  function checkCapsLock(e: React.KeyboardEvent<HTMLInputElement>) {
    setCapsLock(e.getModifierState('CapsLock'))
  }

  return (
    <div className="pwfield">
      <input
        id={id}
        className="input"
        type={visible ? 'text' : 'password'}
        autoComplete={autoComplete}
        value={value}
        onChange={onChange}
        onKeyUp={checkCapsLock}
        onKeyDown={checkCapsLock}
        aria-describedby={capsLock ? capsLockId : undefined}
      />
      <button
        type="button"
        className="pwtoggle"
        aria-pressed={visible}
        onClick={() => setVisible((v) => !v)}
      >
        {visible ? 'Hide' : 'Show'}
      </button>
      {capsLock && (
        <p className="pwcaps" role="status" id={capsLockId}>
          Caps Lock is on
        </p>
      )}
    </div>
  )
}
