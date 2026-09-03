/* Tunables that more than one feature cares about, or that someone might
 * reasonably want to change without reading component code. POLL_MS in
 * particular was duplicated across the scan list and the feed, which is exactly
 * how two pollers end up drifting out of step. */

/** Matches the `<title>` in index.html — the suffix `useDocumentTitle` appends
 *  to every per-page title. */
export const APP_NAME = 'bandcamp music finder'

/** Recommendations fetched per page (the API caps this at 200). */
export const FEED_PAGE_SIZE = 50

/** How often to re-check a queued/running scan. The crawl runs on someone's
 *  laptop, so there's no push channel — this is the only way progress appears. */
export const SCAN_POLL_MS = 4000

/** Duration of the card evaporate animation. Must stay in step with the
 *  `evaporate` keyframes in features/feed/feed.css: the row is removed from
 *  state when this elapses, and a mismatch either truncates the animation or
 *  leaves a blank gap behind it. */
export const CARD_EXIT_MS = 800

/** How long the "Undo" affordance stays up after a like/block, in ms. Long
 *  enough to catch a mis-click without becoming visual clutter. */
export const UNDO_WINDOW_MS = 6000

/** How long the "Copy link" button shows its "Copied" confirmation, in ms. */
export const COPY_LINK_FEEDBACK_MS = 2000

/** How long a toast (see lib/toast.ts) stays up before auto-dismissing, in ms. */
export const TOAST_DURATION_MS = 4000

/** Max toasts kept in the stack at once (see lib/toast.ts) — a burst of
 *  rapid likes/blocks, or a bulk-block finishing, would otherwise queue one
 *  toast per action with no upper bound. The oldest toast with no pending
 *  `action` is evicted first when a new one would exceed this. */
export const TOAST_STACK_CAP = 4

/** How often `<RelativeTime>` re-renders itself to keep "Xm ago" text current
 *  on a page that isn't otherwise polling. */
export const RELATIVE_TIME_REFRESH_MS = 30000

/** Scroll distance, in px, past which `<ScrollTopButton>` appears. */
export const SCROLL_TOP_THRESHOLD_PX = 600

/** How long before a session's JWT `exp` claim lapses that
 *  `useSessionExpiryWarning` fires its one warning toast, in ms. */
export const SESSION_EXPIRY_WARNING_MS = 5 * 60 * 1000

/** Options offered by `FeedCard`'s "block for… ▾" duration picker — a
 *  temporary block, as opposed to the plain "⊘ block" button's permanent one.
 *  `ms` is added to `Date.now()` to produce the `expires_at` sent to
 *  `POST /api/blacklist`. */
export const BLOCK_DURATIONS: { label: string; ms: number }[] = [
  { label: '1 day', ms: 24 * 60 * 60 * 1000 },
  { label: '1 week', ms: 7 * 24 * 60 * 60 * 1000 },
  { label: '1 month', ms: 30 * 24 * 60 * 60 * 1000 },
]

/** Below this much time left, a temporary block in the Blocked panel gets a
 *  "renew ▾" action (reusing `BLOCK_DURATIONS`) instead of just an expiry
 *  label — the point at which it's actually about to lapse, not merely
 *  temporary. */
export const RENEW_WINDOW_MS = 24 * 60 * 60 * 1000

/** Above this many selected cards, `<BulkActionBar>` requires a second
 *  confirming click before firing the block calls — undo exists, but a
 *  stray "select all" + block on a large filtered set has a bigger blast
 *  radius than the click that caused it. At or below, block fires immediately
 *  (today's behavior, unchanged). */
export const BULK_CONFIRM_THRESHOLD = 5

/** How long the armed "Block N?" confirm state stays up before reverting on
 *  its own, in ms — same window/reasoning as `DeleteScanButton`'s. */
export const BULK_CONFIRM_WINDOW_MS = 4000
