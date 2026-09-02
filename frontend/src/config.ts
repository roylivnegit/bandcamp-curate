/* Tunables that more than one feature cares about, or that someone might
 * reasonably want to change without reading component code. POLL_MS in
 * particular was duplicated across the scan list and the feed, which is exactly
 * how two pollers end up drifting out of step. */

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
