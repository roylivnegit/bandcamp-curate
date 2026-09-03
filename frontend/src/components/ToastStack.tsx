import { dismissToast, useToasts } from '../lib/toast'
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
        <div key={t.id} role={t.variant} className={`toast ${t.variant}`}>
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
