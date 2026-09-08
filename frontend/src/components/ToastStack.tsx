import { dismissToast, pauseToast, resumeToast, useToasts } from '../lib/toast'
import './ToastStack.css'

/** Mounted once in the app shell (`App.tsx`). Renders whatever's currently in
 *  the module-scope toast queue — `showToast()` (lib/toast.ts) is how
 *  anything gets in it; this component only ever reads and dismisses. */
export function ToastStack() {
  const toasts = useToasts()
  if (toasts.length === 0) return null

  return (
    <div className="toaststack">
      {toasts.map((t) => (
        <div
          key={t.id}
          role={t.variant}
          className={`toast ${t.variant}`}
          onMouseEnter={() => pauseToast(t.id)}
          onMouseLeave={() => resumeToast(t.id)}
          onFocus={(e) => {
            // Only pause once when focus actually enters this toast — moving
            // focus between two buttons inside the same one (action, then
            // dismiss) re-fires onFocus for the new button and would
            // over-pause (see the matching onBlur check below) without this.
            if (!e.currentTarget.contains(e.relatedTarget as Node | null)) pauseToast(t.id)
          }}
          onBlur={(e) => {
            // Mirror image: only resume once focus actually leaves this
            // toast, not on every transition between its own buttons.
            if (!e.currentTarget.contains(e.relatedTarget as Node | null)) resumeToast(t.id)
          }}
        >
          <span>{t.message}</span>
          {t.action && (
            <button
              type="button"
              className="toast-action"
              onClick={() => {
                t.action?.onClick()
                dismissToast(t.id)
              }}
            >
              {t.action.label}
            </button>
          )}
          <button
            type="button"
            className="toast-dismiss"
            aria-label="Dismiss notification"
            onClick={() => dismissToast(t.id)}
          >
            ×
          </button>
        </div>
      ))}
    </div>
  )
}
