# Play Auth Gating

## Purpose

The `/play` UI wraps Chainlit and additional gameplay panes. We need a safe UX where:

- Logged out users only see the Chainlit login screen.
- Logged in users see the full split-pane gameplay layout.
- Logging out from Chainlit re-locks `/play` automatically.

## Design

Auth gating is implemented as a thin layer separate from gameplay logic.

### Files

- `public/play-auth.css`: auth-mode layout overrides.
- `public/play-auth.js`: parent-side auth gate wiring and window-message handling.
- `public/chainlit-auth-bridge.js`: Chainlit-side auth-state detector and message emitter.
- `public/play.js`: gameplay UI rendering and split layout setup (no auth internals).

### Flow

1. `/play` starts with `body.auth-required`.
2. `play-auth.js` subscribes to window messages from the embedded `#chat iframe`.
3. If chat is authenticated, it removes `auth-required` and calls the provided callback.
4. The callback initializes split layout once (`initLayout`) from `play.js`.
5. If logout is detected later, `auth-required` is re-applied and panes are hidden.

## Detection Strategy

`chainlit-auth-bridge.js` considers chat unauthenticated when it detects one of:

- login/auth route hints in iframe pathname,
- password input in iframe DOM,
- login-like text fallback.

It considers chat authenticated when a composer-like element is present.

## Why Window Messaging

Chainlit supports parent/iframe window messaging. We use that channel to send explicit auth-state updates from the iframe to `/play`, which avoids parent-side polling.

Message contract:

- `cocai:auth-state` with `{ authenticated: boolean }` from iframe -> parent.
- `cocai:auth:request` from parent -> iframe for handshake after iframe loads.

Handshake behavior:

- Parent sends an immediate `cocai:auth:request` after iframe load.
- Parent retries at a short interval for a bounded number of attempts.
- Retry loop stops as soon as an `cocai:auth-state` response arrives.

## CSS Rules

In `body.auth-required` mode:

- Left/right columns and illustration are hidden.
- Center chat stretches to full viewport (`100vw x 100vh`).
- Split.js gutters are hidden to avoid divider artifacts.

## Integration Notes

In `public/play.html`, load order is important:

1. `play.css`
2. `play-auth.css`
3. `play-auth.js`
4. `play.js`

In Chainlit config (`.chainlit/config.toml`), ensure:

- `custom_js = "/public/chainlit-auth-bridge.js"`

`play.js` calls:

```js
window.setupPlayAuthGate({ onAuthenticated: ensureLayoutInitialized })
```

with a fallback to initialize layout if auth script fails to load.

## Future Improvements

- Add a top-level "Start New Session" control in `/play` that proxies Chainlit new-chat behavior.
- Add E2E test coverage for login -> gameplay -> logout transitions.
