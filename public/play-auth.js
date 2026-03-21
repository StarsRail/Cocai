(function () {
  const AUTH_STATE_TYPE = 'cocai:auth-state'
  const AUTH_STATE_REQUEST_TYPE = 'cocai:auth:request'
  let lastAuthState = null
  let handshakeTimer = null

  function setAuthGateState (isAuthenticated, onAuthenticated) {
    if (lastAuthState === isAuthenticated) return
    lastAuthState = isAuthenticated

    document.body.classList.toggle('auth-required', !isAuthenticated)
    if (isAuthenticated && typeof onAuthenticated === 'function') {
      onAuthenticated()
    }
  }

  function setupPlayAuthGate (opts = {}) {
    const onAuthenticated = opts.onAuthenticated
    const handshakeIntervalMs = Number.isFinite(opts.handshakeIntervalMs)
      ? opts.handshakeIntervalMs
      : 150
    const handshakeMaxAttempts = Number.isFinite(opts.handshakeMaxAttempts)
      ? opts.handshakeMaxAttempts
      : 10

    const iframe = document.querySelector('#chat iframe')
    if (!iframe) return

    const requestAuthState = () => {
      try {
        iframe.contentWindow?.postMessage(
          { type: AUTH_STATE_REQUEST_TYPE },
          window.location.origin
        )
      } catch (e) {
        // Ignore request failures and keep gate closed.
      }
    }

    const onWindowMessage = (event) => {
      if (event.origin !== window.location.origin) return
      if (event.source !== iframe.contentWindow) return

      const data = event.data
      if (!data || data.type !== AUTH_STATE_TYPE) return
      if (typeof data.authenticated !== 'boolean') return

      setAuthGateState(data.authenticated, onAuthenticated)

      // Once the iframe answered, the handshake retry loop is no longer needed.
      if (handshakeTimer) {
        clearInterval(handshakeTimer)
        handshakeTimer = null
      }
    }

    const startHandshake = () => {
      if (handshakeTimer) {
        clearInterval(handshakeTimer)
        handshakeTimer = null
      }

      // Retry auth-state request for a short bounded window to absorb load races.
      let attempts = 0
      requestAuthState()
      handshakeTimer = setInterval(() => {
        attempts += 1
        requestAuthState()
        if (attempts >= handshakeMaxAttempts) {
          clearInterval(handshakeTimer)
          handshakeTimer = null
        }
      }, handshakeIntervalMs)
    }

    window.addEventListener('message', onWindowMessage)

    iframe.addEventListener('load', () => {
      // Pessimistically gate while a new iframe page is loading.
      setAuthGateState(false, onAuthenticated)
      // Ask the iframe to report its current auth state with bounded retries.
      startHandshake()
    })

    window.addEventListener('beforeunload', () => {
      if (handshakeTimer) {
        clearInterval(handshakeTimer)
        handshakeTimer = null
      }
      window.removeEventListener('message', onWindowMessage)
    })

    // Initial gate state: locked until iframe reports authenticated state.
    setAuthGateState(false, onAuthenticated)
    startHandshake()
  }

  window.setupPlayAuthGate = setupPlayAuthGate
})()
