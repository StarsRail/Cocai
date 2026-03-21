(function () {
  const AUTH_STATE_TYPE = 'cocai:auth-state'
  const AUTH_STATE_REQUEST_TYPE = 'cocai:auth:request'
  let lastSentState = null
  let observer = null

  function detectAuthenticatedInChainlitWindow () {
    try {
      const path = (window.location.pathname || '').toLowerCase()
      if (path.includes('login') || path.includes('auth')) return false

      const doc = window.document
      if (!doc || !doc.body) return false

      if (doc.querySelector('input[type="password"]')) return false

      const hasComposer = !!doc.querySelector(
        'textarea, [contenteditable="true"], input[placeholder*="message" i], [data-testid*="composer" i]'
      )
      if (hasComposer) return true

      const bodyText = (doc.body.innerText || '').toLowerCase()
      if (bodyText.includes('sign in') || bodyText.includes('log in')) { return false }
    } catch (e) {
      return false
    }

    return false
  }

  function emitAuthState (force) {
    const authenticated = detectAuthenticatedInChainlitWindow()
    if (!force && lastSentState === authenticated) return
    lastSentState = authenticated

    try {
      window.parent.postMessage(
        { type: AUTH_STATE_TYPE, authenticated },
        window.location.origin
      )
    } catch (e) {
      // Ignore postMessage failures.
    }
  }

  function installObservers () {
    if (observer) return

    const body = window.document && window.document.body
    if (!body) {
      setTimeout(installObservers, 50)
      return
    }

    observer = new MutationObserver(() => {
      emitAuthState(false)
    })

    observer.observe(body, {
      subtree: true,
      childList: true,
      attributes: true
    })
  }

  function onParentMessage (event) {
    if (event.origin !== window.location.origin) return
    const data = event.data
    if (!data || data.type !== AUTH_STATE_REQUEST_TYPE) return
    emitAuthState(true)
  }

  window.addEventListener('message', onParentMessage)
  window.addEventListener('hashchange', () => emitAuthState(true))
  window.addEventListener('popstate', () => emitAuthState(true))

  if (window.document.readyState === 'loading') {
    window.document.addEventListener('DOMContentLoaded', () => {
      installObservers()
      emitAuthState(true)
    })
  } else {
    installObservers()
    emitAuthState(true)
  }
})()
