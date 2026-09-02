import { useEffect } from 'react'

import { APP_NAME } from '../config'

/** Sets the browser tab/history title to `<title> · crate digger` for as long
 *  as the calling component is mounted on this route. `title` is nullable
 *  because a page's real title (a scan's name) is often only known after a
 *  fetch resolves — while it's `null`, the previous title is left alone
 *  rather than flashing a bare "crate digger" in between. */
export function useDocumentTitle(title: string | null | undefined) {
  useEffect(() => {
    if (!title) return
    document.title = `${title} · ${APP_NAME}`
  }, [title])
}
