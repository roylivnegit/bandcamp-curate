import { Component, type ErrorInfo, type ReactNode } from 'react'

interface Props {
  children: ReactNode
}

interface State {
  hasError: boolean
}

/** Catches a render-time exception anywhere below it and shows a fallback
 *  instead of letting React unmount the whole tree to a white screen — the
 *  app had no error boundary at all before this, so a bad API response shape
 *  (or any other render-time bug) took everything down with it, including
 *  the toast/offline-banner layer that could otherwise have explained it.
 *  Class-based because `getDerivedStateFromError`/`componentDidCatch` have no
 *  hook equivalent. `componentDidCatch`'s `error`/`info` args are unused here
 *  (there's no error-reporting service to send them to) — logged to the
 *  console so they're not silently lost. */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false }

  static getDerivedStateFromError(): State {
    return { hasError: true }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Unhandled error in the app tree:', error, info)
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="wrap">
          <p className="empty">
            Something went wrong.
            <br />
            <button type="button" className="btn" onClick={() => window.location.reload()}>
              Reload
            </button>
          </p>
        </div>
      )
    }
    return this.props.children
  }
}
