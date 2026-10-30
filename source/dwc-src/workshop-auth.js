'use strict'

// Identity of the person using this browser (F1-A of the redesign, 2026-10-21). The roles are applied by the SERVICE; this
// file only keeps the session token, tells the pages what to hide, and runs the PIN dialog when the service asks for it.
// Same logic for the JS plugins in src/_shared/01-api-auth.js: keep them equal.
//
//   authHeaders()               {'X-Workshop-Token', 'X-Workshop-Device'} for every call to the API
//   workshopCan('lights.save')  false when the role cannot call it (hide the button; the service refuses it anyway)
//   currentIdentity()           the last auth.whoami answer ({role, user, table, ...}) or null
//   onIdentity(fn)              fn(identity) when the person logs in, out or the role changes; returns the off function
//
// Owner decision: ONE session per browser. The session token lives in localStorage (so every tab and a reload of the kiosk keep
// the sign-in) until the service ends it (idle timeout or logout); it is NOT in sessionStorage. The id of the browser (also
// localStorage) is not a secret: it only tells the audit which browser did it. All the plugins of a page share ONE state through
// window.__workshopAuth.

import { pinDialog } from './pin-dialog.js'

const TOKEN_KEY = 'workshop-token'
const DEVICE_KEY = 'workshop-device'
const KEEPALIVE_MS = 60000
const GESTURE_MS = 1500 // a call that fails this soon after a touch is the person's action: it asks even in the quiet period
const CANCEL_QUIET_MS = 600000 // after cancelling the PIN dialog, calls fail quietly this long instead of asking again

function watchGestures(s) {
	if (s.gestures || typeof document === 'undefined' || typeof document.addEventListener !== 'function') return
	s.gestures = 1
	;['pointerdown', 'keydown', 'touchstart'].forEach(ev => {
		document.addEventListener(ev, e => {
			if (e.target && e.target.closest && e.target.closest('[data-tp-pin]')) return
			s.gestureAt = Date.now()
		}, { capture: true, passive: true })
	})
}

function shared() {
	if (!window.__workshopAuth) window.__workshopAuth = { identity: null, token: '', listeners: [], flight: null, quietUntil: 0, device: '', keepalive: 0 }
	watchGestures(window.__workshopAuth)
	return window.__workshopAuth
}

// One sign-in is valid for every tab of this browser; the service still ends the session when it expires or on logout
function tokenStore() {
	return store('localStorage')
}

function store(kind) {
	try {
		return window[kind]
	} catch (e) {
		return null
	}
}

export function deviceId() {
	const s = shared()
	if (s.device) return s.device
	let id = ''
	try {
		id = store('localStorage').getItem(DEVICE_KEY) || ''
	} catch (e) {
		id = ''
	}
	if (!/^[A-Za-z0-9_-]{8,40}$/.test(id)) {
		const a = new Uint8Array(12)
		try {
			window.crypto.getRandomValues(a)
		} catch (e) {
			for (let i = 0; i < a.length; i++) a[i] = Math.floor(Math.random() * 256)
		}
		id = 'b' + Array.from(a, x => x.toString(16).padStart(2, '0')).join('')
		try {
			store('localStorage').setItem(DEVICE_KEY, id)
		} catch (e) {
			/* private window: the id lives as long as the page */
		}
	}
	s.device = id
	return id
}

export function getToken() {
	const s = shared()
	if (s.token) return s.token
	try {
		s.token = tokenStore().getItem(TOKEN_KEY) || ''
	} catch (e) {
		s.token = ''
	}
	return s.token
}

export function setToken(token) {
	const s = shared()
	s.token = token || ''
	try {
		if (token) tokenStore().setItem(TOKEN_KEY, token)
		else tokenStore().removeItem(TOKEN_KEY)
	} catch (e) {
		/* the memory copy is enough */
	}
}

export function authHeaders() {
	const h = { 'X-Workshop-Device': deviceId() }
	const t = getToken()
	if (t) h['X-Workshop-Token'] = t
	return h
}

export function currentIdentity() {
	return shared().identity
}

export function setIdentity(w) {
	const s = shared()
	s.identity = w || null
	s.listeners.slice().forEach(fn => {
		try {
			fn(s.identity)
		} catch (e) {
			/* a listener must not break the others */
		}
	})
}

export function onIdentity(fn) {
	const s = shared()
	s.listeners.push(fn)
	return () => {
		s.listeners = s.listeners.filter(x => x !== fn)
	}
}

const RANK = { viewer: 0, operator: 1, technician: 2, admin: 3 }

// Can the current person call this operation? Without an answer from the service yet (or without users) it says yes: hiding is
// only a courtesy, the service decides. ctx: { mode: 'laser' | 'cnc' | 'fff', args: {...} } for the rules that depend on it.
export function workshopCan(op, ctx = {}) {
	const id = shared().identity
	if (!id || !id.table || !id.role) return true
	const t = id.table
	if ((t.stop || []).includes(op)) return true
	const role = id.role
	let need = (t.ops || {})[op] || 'admin'
	const esc = (t.escalate || {})[op] // some operations need more when their arguments change settings
	if (esc) {
		const v = (ctx.args || {})[esc.arg]
		const hit = esc.when_present ? !!v : !(esc.unless_in || []).includes(String(v || ''))
		if (hit && RANK[esc.role] > RANK[need]) need = esc.role
	}
	if (role === 'viewer' && (t.camera || []).includes(op)) return !!(id.user && id.user.camera)
	if (RANK[role] === undefined || RANK[role] < RANK[need]) return false
	if (role === 'operator' && (t.mode_gated || []).includes(op) && ctx.mode) {
		const modes = (id.user && id.user.modes) || []
		return modes.length >= (t.modes || []).length || modes.includes(String(ctx.mode).toLowerCase())
	}
	return true
}

export function workshopRole() {
	const id = shared().identity
	return id && id.role ? id.role : ''
}

// ---- login flow ----
// call(op, args) must resolve the JSON body of the API ({ok, result, error}) and never ask for a login itself.

export async function refreshIdentity(call) {
	const j = await call('auth.whoami', {})
	if (j && j.ok) setIdentity(j.result)
	return j && j.ok ? j.result : null
}

export async function loginWith(call, name, pin) {
	const j = await call('auth.login', { name, pin })
	if (!j.ok) return j
	setToken(j.result.token)
	await refreshIdentity(call)
	return j
}

export async function logoutWith(call) {
	try {
		await call('auth.logout', {})
	} finally {
		setToken('')
		await refreshIdentity(call)
	}
}

// The service has users and this browser has no session (a visitor, or nothing allowed yet).
export function signedOut() {
	const id = shared().identity
	return !!(id && id.configured && !getToken())
}

// The person touched the page a moment ago: what fails now is probably their action (so it is worth telling them).
export function recentGesture() {
	return Date.now() - (shared().gestureAt || 0) < GESTURE_MS
}

// Asks the person for name and PIN (one dialog for all the callers). Resolves true when logged in, false when cancelled.
export function ensureLogin(call, t) {
	const s = shared()
	if (s.flight) return s.flight
	// Nothing opens the dialog by itself (a poll, a refresh): only a touch just before the failed call, or the "sign in" button
	if (!shared().forceAsk && Date.now() - (s.gestureAt || 0) >= GESTURE_MS) return Promise.resolve(false)
	if (shared().forceAsk) s.quietUntil = 0
	// after cancelling, not even a touch brings it back: the refusal message and the "sign in" button tell what to do
	if (Date.now() < s.quietUntil) return Promise.resolve(false)
	setToken('')
	s.flight = pinDialog(async (name, pin) => {
		const j = await loginWith(call, name, pin)
		if (j.ok) return null
		const e = j.error || {}
		return { code: e.code, message: e.message, wait_s: e.wait_s }
	}, t)
		.then(ok => {
			if (!ok) s.quietUntil = Date.now() + CANCEL_QUIET_MS
			return ok
		})
		.finally(() => {
			s.flight = null
		})
	return s.flight
}

// The person pressed "log in" (not a call that failed): the dialog opens even if it was cancelled a moment ago.
export function askLoginNow(call, t) {
	shared().forceAsk = true
	try {
		return ensureLogin(call, t)
	} finally {
		shared().forceAsk = false
	}
}

// A token the service gave in another answer (the first administrator just created): use it from now on.
export async function adoptToken(call, token) {
	setToken(token)
	return refreshIdentity(call)
}

// Tells the service the person is still there (real use only), at most once a minute.
export function startKeepalive(call) {
	const s = shared()
	if (s.keepalive || typeof document === 'undefined') return
	s.keepalive = 1
	// a sign-in or a logout made in another tab arrives here: this tab follows it without asking again
	if (typeof window !== 'undefined' && typeof window.addEventListener === 'function') {
		window.addEventListener('storage', e => {
			if (e.key !== TOKEN_KEY) return
			s.token = e.newValue || ''
			refreshIdentity(call).catch(() => {})
		})
	}
	let last = 0
	const ping = () => {
		const now = Date.now()
		if (!getToken() || now - last < KEEPALIVE_MS) return
		last = now
		call('auth.keepalive', {}).catch(() => {})
	}
	;['pointerdown', 'keydown', 'touchstart'].forEach(ev => document.addEventListener(ev, ping, { capture: true, passive: true }))
}
