function renderHistory (history) {
  document.getElementById('history').textContent = history || ''
}

function renderClues (clues) {
  const container = document.getElementById('clues')
  container.innerHTML = '';
  (clues || []).forEach((c, idx) => {
    const id = `clue-${idx}`
    const item = document.createElement('div')
    item.className = 'acc-item mb-2'

    // Button that controls the Bootstrap collapse
    const btn = document.createElement('button')
    btn.className = 'acc-summary btn btn-toggle'
    btn.setAttribute('type', 'button')
    btn.setAttribute('data-bs-toggle', 'collapse')
    btn.setAttribute('data-bs-target', `#${id}`)
    btn.setAttribute('aria-expanded', 'false')
    btn.setAttribute('aria-controls', id)
    btn.innerHTML = `<span>${c.title}</span><span class="tag">${
      c.found_at || 'Unknown'
    }</span>`

    const bodyWrap = document.createElement('div')
    bodyWrap.className = 'collapse acc-body'
    bodyWrap.id = id
    bodyWrap.setAttribute('role', 'region')
    bodyWrap.setAttribute('aria-labelledby', id + '-label')
    const body = document.createElement('div')
    body.id = id + '-label'
    body.textContent = c.content
    bodyWrap.appendChild(body)

    item.appendChild(btn)
    item.appendChild(bodyWrap)
    container.appendChild(item)
  })
}

function renderIllustration (url) {
  const img = document.getElementById('scene-image')
  if (url) img.src = url
  else img.removeAttribute('src')
}

// Subtle status indicators state
const paneStatus = {
  history: { phase: 'idle', startedAt: 0 },
  scene: { phase: 'idle', startedAt: 0 }
}

function applyHistoryStatus (phase) {
  const el = document.getElementById('history')
  if (!el) return
  paneStatus.history.phase = phase
  el.classList.remove('loading-soft', 'updating-soft')
  if (phase === 'evaluating' || phase === 'summarizing') {
    el.classList.add('loading-soft')
    if (!el.dataset.originalTitle) el.dataset.originalTitle = el.title || ''
    el.title = 'Updating story summary…'
  } else if (phase === 'updated') {
    el.classList.add('updating-soft')
    setTimeout(() => el.classList.remove('updating-soft'), 1200)
    el.title = el.dataset.originalTitle || ''
  } else if (['unchanged', 'cancelled', 'error'].includes(phase)) {
    el.title = el.dataset.originalTitle || ''
  }
}

function applySceneStatus (phase) {
  const container = document.getElementById('illustration')
  if (!container) return
  paneStatus.scene.phase = phase
  container.classList.remove('loading-soft', 'updating-soft')
  if (['evaluating', 'describing', 'imaging'].includes(phase)) {
    container.classList.add('loading-soft')
  } else if (phase === 'updated') {
    container.classList.add('updating-soft')
    setTimeout(() => container.classList.remove('updating-soft'), 1200)
  }
}

function renderPC (pc) {
  document.getElementById('pc-name').textContent = pc?.name || 'Investigator'
  const stats = document.getElementById('pc-stats')
  stats.innerHTML = ''
  const statEntries = Object.entries(pc?.stats || {})
  if (statEntries.length) {
    console.log('Rendering stats', statEntries)
    // Keep insertion order, but ensure values are rendered as numbers when possible
    statEntries.forEach(([k, v]) => {
      const d = document.createElement('div')
      d.className = 'stat'
      const nameEl = document.createElement('span')
      nameEl.textContent = k
      const valEl = document.createElement('span')
      valEl.textContent = v
      d.appendChild(nameEl)
      d.appendChild(valEl)
      stats.appendChild(d)
    })
  } else {
    console.log('No stats to render')
  }
  const skills = document.getElementById('skills')
  skills.innerHTML = ''
  let skillEntries = Object.entries(pc?.skills || {})
  if (skillEntries.length) {
    console.log('Rendering skills', skillEntries)
    // Sort by descending numeric value, then alphabetically
    skillEntries = skillEntries.sort(([aName, aVal], [bName, bVal]) => {
      const av = parseSkillValue(aVal)
      const bv = parseSkillValue(bVal)
      if (bv !== av) return bv - av
      const an = String(aName).toLowerCase()
      const bn = String(bName).toLowerCase()
      if (an < bn) return -1
      if (an > bn) return 1
      return 0
    })

    skillEntries.forEach(([k, v]) => {
      const percent = clampPct(parseSkillValue(v))
      const row = document.createElement('div')
      row.className = 'skill'
      row.style.setProperty('--pct', percent + '%')
      row.setAttribute('role', 'progressbar')
      row.setAttribute('aria-valuemin', '0')
      row.setAttribute('aria-valuemax', '100')
      row.setAttribute('aria-valuenow', String(percent))

      const label = document.createElement('div')
      label.textContent = `${k}`

      const right = document.createElement('div')
      right.style.display = 'flex'
      right.style.gap = '8px'
      right.style.alignItems = 'center'

      const val = document.createElement('span')
      val.className = 'skill-value'
      val.textContent = `${percent}%`
      val.setAttribute('aria-label', `${k} ${percent} percent`)

      const btn = document.createElement('button')
      btn.className = 'btn-roll'
      btn.textContent = 'Roll'
      btn.title = `Roll a skill check of ${k}`
      btn.addEventListener('click', async () => {
        const msg = `Roll a skill check of ${k}.`
        try {
          await sendMessageToChat(msg)
        } catch (e) {
          console.warn('Failed to send message to chat:', e)
          alert(
            'Could not reach the chat composer. Make sure the chat is loaded.'
          )
        }
      })

      right.appendChild(val)
      right.appendChild(btn)
      row.appendChild(label)
      row.appendChild(right)
      skills.appendChild(row)
    })
  }
}

function parseSkillValue (v) {
  // Accept numbers, "NN%", or strings with digits; clamp later
  if (typeof v === 'number' && isFinite(v)) return v
  const m = String(v || '').match(/([0-9]{1,3})/)
  if (m) return parseInt(m[1], 10)
  return 0
}

function clampPct (n) {
  n = Number.isFinite(n) ? n : 0
  if (n < 0) return 0
  if (n > 100) return 100
  return Math.round(n)
}

function openDiceWindow (url) {
  try {
    window.open(url, '_blank', 'width=420,height=320')
  } catch (e) {}
}

function listenEvents () {
  try {
    const es = new EventSource('/api/events')
    es.onmessage = (ev) => {
      console.log('Received SSE:', ev.data)
      try {
        const msg = JSON.parse(ev.data)
        if (msg.type === 'history') {
          renderHistory(msg.history)
        } else if (msg.type === 'clues') {
          renderClues(msg.clues)
        } else if (msg.type === 'illustration') {
          renderIllustration(msg.url)
        } else if (msg.type === 'history_status') {
          applyHistoryStatus(msg.phase)
        } else if (msg.type === 'scene_status') {
          applySceneStatus(msg.phase)
        } else if (msg.type === 'pc') {
          renderPC(msg.pc)
        } else if (msg.type === 'server_shutdown') {
          try {
            es.close()
          } catch (e) {}
          const iframe = document.querySelector('#chat iframe')
          if (iframe) iframe.src = 'about:blank'
        }
      } catch (e) {
        /* ignore parse errors */
      }
    }
    window.addEventListener('beforeunload', () => {
      try {
        es.close()
      } catch (e) {}
    })
  } catch (e) {
    console.warn('Failed to setup SSE:', e)
  }
}

function initLayout () {
  const getSizes = (key, fallback) => {
    try {
      const raw = localStorage.getItem(key)
      if (!raw) return fallback
      const arr = JSON.parse(raw)
      return Array.isArray(arr) && arr.length ? arr : fallback
    } catch {
      return fallback
    }
  }
  const saveSizes = (key, inst) => (sizes) => {
    try {
      localStorage.setItem(key, JSON.stringify(sizes))
    } catch {}
  }

  // Shared helper to create a Split with persistence
  function createSplit ({
    ids,
    direction = 'horizontal',
    key,
    defaults,
    minSize,
    gutterSize = 6,
    snapOffset = 8,
    container
  }) {
    const sizes = getSizes(key, defaults)
    const inst = Split(ids, {
      direction,
      sizes,
      minSize,
      gutterSize,
      snapOffset,
      onDragEnd: saveSizes(key)
    })

    // Accessibility + keyboard support for gutters
    makeGuttersAccessible({ container, direction, split: inst, key, defaults })
    return inst
  }

  function clamp (n, min, max) {
    return Math.max(min, Math.min(max, n))
  }

  function makeGuttersAccessible ({
    container,
    direction,
    split,
    key,
    defaults
  }) {
    if (!container) return
    const isHorizontal = direction !== 'vertical'
    const stepPct = 3 // resize step per keypress (in % of container)
    const gutters = container.querySelectorAll(
      '.gutter' + (isHorizontal ? '.gutter-horizontal' : '.gutter-vertical')
    )
    gutters.forEach((g, index) => {
      g.setAttribute('tabindex', '0')
      g.setAttribute('role', 'separator')
      g.setAttribute(
        'aria-orientation',
        isHorizontal ? 'vertical' : 'horizontal'
      )
      g.setAttribute(
        'aria-label',
        'Resize ' + (isHorizontal ? 'columns' : 'panes')
      )

      // Double-click to reset
      g.addEventListener('dblclick', () => {
        split.setSizes(defaults)
        try {
          localStorage.setItem(key, JSON.stringify(defaults))
        } catch {}
      })

      // Arrow keys to move this gutter
      g.addEventListener('keydown', (ev) => {
        const code = ev.key
        const isDec =
          (isHorizontal && code === 'ArrowLeft') ||
          (!isHorizontal && code === 'ArrowUp')
        const isInc =
          (isHorizontal && code === 'ArrowRight') ||
          (!isHorizontal && code === 'ArrowDown')
        if (!isDec && !isInc) return
        ev.preventDefault()
        const sizes = split.getSizes()
        // This gutter is between index and index+1
        const i = index
        const delta = isInc ? stepPct : -stepPct
        const left = clamp(sizes[i] + delta, 0, 100)
        const right = clamp(sizes[i + 1] - delta, 0, 100)
        const newSizes = sizes.slice()
        newSizes[i] = left
        newSizes[i + 1] = right
        // Normalize if sum drifted
        const sum = newSizes.reduce((a, b) => a + b, 0)
        if (sum !== 100) {
          const factor = 100 / sum
          for (let k = 0; k < newSizes.length; k++) { newSizes[k] = newSizes[k] * factor }
        }
        split.setSizes(newSizes)
        try {
          localStorage.setItem(key, JSON.stringify(newSizes))
        } catch {}
      })
    })
  }

  // Create splits
  let hSplit = createSplit({
    ids: ['#col-left', '#col-center', '#col-right'],
    direction: 'horizontal',
    key: 'split-horizontal',
    defaults: [22, 53, 25],
    minSize: [180, 320, 220],
    container: document.getElementById('app')
  })

  const lSplit = createSplit({
    ids: ['#left-history', '#left-clues'],
    direction: 'vertical',
    key: 'split-left',
    defaults: [50, 50],
    minSize: [120, 120],
    container: document.getElementById('left-split')
  })

  const cSplit = createSplit({
    ids: ['#illustration', '#chat'],
    direction: 'vertical',
    key: 'split-center',
    defaults: [40, 60],
    minSize: [140, 240],
    container: document.getElementById('center-split')
  })

  const rSplit = createSplit({
    ids: ['#right-stats-pane', '#right-skills-pane'],
    direction: 'vertical',
    key: 'split-right',
    defaults: [45, 55],
    minSize: [120, 140],
    container: document.getElementById('right-split')
  })

  // Toggle horizontal split for small screens (matches CSS @media)
  function toggleHorizontalSplit () {
    const narrow = window.innerWidth <= 1000
    const left = document.getElementById('col-left')
    const right = document.getElementById('col-right')
    if (narrow) {
      // Ensure split instance is destroyed so it stops sizing hidden panes
      if (hSplit && typeof hSplit.destroy === 'function') {
        try {
          hSplit.destroy()
        } catch {}
        hSplit = null
      }
    } else {
      if (!hSplit) {
        hSplit = createSplit({
          ids: ['#col-left', '#col-center', '#col-right'],
          direction: 'horizontal',
          key: 'split-horizontal',
          defaults: [22, 53, 25],
          minSize: [180, 320, 220],
          container: document.getElementById('app')
        })
      }
    }
  }
  toggleHorizontalSplit()
  window.addEventListener('resize', () => {
    toggleHorizontalSplit()
  })
}

async function init () {
  initLayout()
  renderHistory('(Progress your adventure to see your story summarized here.)') // start empty, will be updated via SSE
  renderClues([]) // start empty, will be updated via SSE
  renderIllustration(
    'https://placehold.co/900x300@3x?text=(in-game+scene+will+be+illustrated+here+as+story+progresses)'
  )
  renderPC({ name: '', stats: {}, skills: {} }) // start empty, will be updated via SSE
  listenEvents()
  // Chat handled inside the embedded Chainlit iframe
}

// Helper: send a message into the embedded Chainlit chat iframe
async function sendMessageToChat (text) {
  const iframe = document.querySelector('#chat iframe')
  if (!iframe) throw new Error('Chat iframe not found')

  // Wait until iframe document is ready
  const doc = await waitForIframeDocument(iframe, 8000)
  if (!doc) throw new Error('Chat iframe not ready')

  // Try to locate the composer input and a send button
  const { textbox, sendButton } = await findComposerElements(doc, 8000)
  if (!textbox && !sendButton) throw new Error('Chat composer not found')

  // Set the message text into the composer
  if (textbox) await setTextIntoComposer(textbox, text)

  // If there is a send button, wait for it to become enabled; if it doesn't, try nudges
  if (sendButton) {
    const enabled = await waitFor(() => isButtonEnabled(sendButton), 2000, 120)
    if (!enabled && textbox) {
      await nudgeComposer(textbox, text)
      // After nudging, wait a bit more
      await waitFor(() => isButtonEnabled(sendButton), 1500, 120)
    }
  }

  // Prefer clicking send button if present; otherwise simulate Enter in the textbox
  let sent = false
  if (sendButton) {
    try {
      sendButton.click()
      sent = true
    } catch {}
  }
  if (!sent && textbox) {
    try {
      simulateEnterKey(textbox)
      sent = true
    } catch {}
  }
  if (!sent) throw new Error('Unable to dispatch send action')
}

function waitForIframeDocument (iframe, timeoutMs = 8000) {
  return new Promise((resolve) => {
    const start = Date.now()
    const tick = () => {
      try {
        const doc = iframe.contentDocument || iframe.contentWindow?.document
        if (doc && doc.readyState !== 'loading') {
          resolve(doc)
          return
        }
      } catch (_) {
        /* cross-origin or not ready */
      }
      if (Date.now() - start > timeoutMs) return resolve(null)
      setTimeout(tick, 150)
    }
    tick()
  })
}

async function findComposerElements (doc, timeoutMs = 8000) {
  const start = Date.now()
  const isVisible = (el) => !!el && el.offsetParent !== null
  const pick = (list) => Array.from(list || []).find(isVisible) || null
  while (Date.now() - start <= timeoutMs) {
    try {
      // Candidate selectors for the text input
      const textCandidates = [
        'textarea',
        'div[role="textbox"]',
        '[contenteditable="true"]',
        'textarea[placeholder]',
        'textarea[aria-label]'
      ]
      let textbox = null
      for (const sel of textCandidates) {
        const el = pick(doc.querySelectorAll(sel))
        if (el) {
          textbox = el
          break
        }
      }

      // Candidate selectors for a send button
      const btnCandidates = [
        'button[title="Send"]',
        'button[aria-label="Send"]',
        'button[type="submit"]',
        'button:has(svg[aria-label="send"])',
        'button:has(svg[aria-label*="send"])',
        'button:has(svg[title*="send"])'
      ]
      let sendButton = null
      for (const sel of btnCandidates) {
        const el = pick(doc.querySelectorAll(sel))
        if (el) {
          sendButton = el
          break
        }
      }

      if (textbox || sendButton) return { textbox, sendButton }
    } catch (_) {
      /* ignore transient errors while app hydrates */
    }
    await new Promise((r) => setTimeout(r, 200))
  }
  return { textbox: null, sendButton: null }
}

async function setTextIntoComposer (inputEl, text) {
  if (!inputEl) return
  const isContentEditable =
    inputEl.getAttribute && inputEl.getAttribute('contenteditable') === 'true'
  if (isContentEditable) {
    inputEl.focus()
    // Prefer execCommand to mimic real typing for frameworks
    try {
      const sel = inputEl.ownerDocument.getSelection()
      if (sel) {
        sel.removeAllRanges()
        const range = inputEl.ownerDocument.createRange()
        range.selectNodeContents(inputEl)
        sel.addRange(range)
      }
      if (document.queryCommandSupported && document.execCommand) {
        document.execCommand('insertText', false, text)
      } else {
        inputEl.textContent = text
      }
    } catch {
      inputEl.textContent = text
    }
    dispatchInputEvent(inputEl, { inputType: 'insertFromPaste', data: text })
  } else {
    inputEl.focus()
    // Use native setter so React/Vue listeners get notified properly
    const tag = (inputEl.tagName || '').toUpperCase()
    const proto =
      tag === 'TEXTAREA'
        ? HTMLTextAreaElement.prototype
        : HTMLInputElement.prototype
    const valueSetter = Object.getOwnPropertyDescriptor(proto, 'value')?.set
    if (valueSetter) valueSetter.call(inputEl, text)
    else inputEl.value = text
    dispatchInputEvent(inputEl, { inputType: 'insertFromPaste', data: text })
    inputEl.dispatchEvent(new Event('change', { bubbles: true }))
  }
  // Allow frameworks to sync internal state
  await new Promise((r) => setTimeout(r, 50))
}

function simulateEnterKey (el) {
  const opts = {
    key: 'Enter',
    code: 'Enter',
    keyCode: 13,
    which: 13,
    bubbles: true
  }
  el.dispatchEvent(new KeyboardEvent('keydown', opts))
  el.dispatchEvent(new KeyboardEvent('keypress', opts))
  el.dispatchEvent(new KeyboardEvent('keyup', opts))
}

function dispatchInputEvent (el, { inputType = 'insertText', data = '' } = {}) {
  try {
    el.dispatchEvent(
      new InputEvent('input', {
        bubbles: true,
        cancelable: true,
        inputType,
        data
      })
    )
  } catch {
    el.dispatchEvent(new Event('input', { bubbles: true }))
  }
}

function isButtonEnabled (btn) {
  if (!btn) return false
  if (btn.disabled) return false
  const aria = btn.getAttribute('aria-disabled')
  if (aria === 'true') return false
  const cls = btn.className || ''
  if (/\bdisabled\b/.test(cls)) return false
  return true
}

function waitFor (predicate, timeoutMs = 1000, intervalMs = 100) {
  return new Promise((resolve) => {
    const start = Date.now()
    const tick = () => {
      try {
        if (predicate()) return resolve(true)
      } catch {
        /* ignore */
      }
      if (Date.now() - start > timeoutMs) return resolve(false)
      setTimeout(tick, intervalMs)
    }
    tick()
  })
}

async function nudgeComposer (inputEl, finalText) {
  // A series of small actions to wake up reactive listeners
  try {
    inputEl.focus()
  } catch {}
  await new Promise((r) => setTimeout(r, 30))

  const isContentEditable =
    inputEl.getAttribute && inputEl.getAttribute('contenteditable') === 'true'
  if (isContentEditable) {
    // Type a space then delete it
    try {
      document.execCommand &&
        document.execCommand('insertText', false, finalText + ' ')
    } catch {
      inputEl.textContent = (inputEl.textContent || '') + ' '
    }
    dispatchInputEvent(inputEl, { inputType: 'insertText', data: ' ' })
    await new Promise((r) => setTimeout(r, 40))
    // Remove the space
    try {
      document.execCommand && document.execCommand('delete')
    } catch {
      inputEl.textContent = (inputEl.textContent || '').replace(/\s$/, '')
    }
    dispatchInputEvent(inputEl, {
      inputType: 'deleteContentBackward',
      data: ''
    })
  } else {
    const tag = (inputEl.tagName || '').toUpperCase()
    const proto =
      tag === 'TEXTAREA'
        ? HTMLTextAreaElement.prototype
        : HTMLInputElement.prototype
    const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set
    const curr = inputEl.value || finalText || ''
    if (setter) setter.call(inputEl, curr + ' ')
    else inputEl.value = curr + ' '
    dispatchInputEvent(inputEl, { inputType: 'insertText', data: ' ' })
    await new Promise((r) => setTimeout(r, 40))
    if (setter) setter.call(inputEl, finalText)
    else inputEl.value = finalText
    dispatchInputEvent(inputEl, {
      inputType: 'deleteContentBackward',
      data: ''
    })
    inputEl.dispatchEvent(new Event('change', { bubbles: true }))
  }

  // Blur and refocus to force validations
  try {
    inputEl.blur()
  } catch {}
  await new Promise((r) => setTimeout(r, 30))
  try {
    inputEl.focus()
  } catch {}
  await new Promise((r) => setTimeout(r, 30))
}

init()
