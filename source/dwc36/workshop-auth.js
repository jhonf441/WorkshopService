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
// One sign-in is valid for every tab of this browser: the token lives in localStorage, as does the id of the browser in localStorage (it is not a secret: it only
// tells the audit which browser did it). All the plugins of a page share ONE state through window.__workshopAuth.

import { pinDialog } from './pin-dialog.js'
import { sessionStateOf, isSignedOutState, accessStateOf, sessionActionOf } from './session-state.js'

const TOKEN_KEY = 'workshop-token'
const DEVICE_KEY = 'workshop-device'
const KEEPALIVE_MS = 60000
const GESTURE_MS = 1500 // a call that fails this soon after a touch is the person's action: it asks even in the quiet period
const CANCEL_QUIET_MS = 600000 // after cancelling the PIN dialog, calls fail quietly this long instead of asking again
const AFTER_LOGOUT_MS = 20000 // after signing out, a failing call does not open the PIN dialog by itself this long

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

// The session state changed without a new answer of the service (the PIN dialog opened or closed, the PIN got locked): tell the views to redraw
function notifyState() {
	const s = shared()
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

function listed(list, op) {
	return Array.isArray(list) && list.includes(op)
}

// Is this operation blocked by the person's own (custom) role? True only for an operation the role denies although its base role allows it.
export function workshopDenied(op) {
	const id = shared().identity
	return !!(id && id.table && listed(id.deny, op) && !(id.table.stop || []).includes(op))
}

// The name of the person's custom role ('' for a base role or when unknown)
export function workshopRoleName() {
	const id = shared().identity
	return id && id.role_name && id.role_name !== id.role ? String(id.role_name) : ''
}

// Can the current person call this operation? Without an answer from the service yet (or without users) it says yes: hiding is
// only a courtesy, the service decides. ctx: { mode: 'laser' | 'cnc' | 'fff', args: {...} } for the rules that depend on it.
export function workshopCan(op, ctx = {}) {
	const id = shared().identity
	if (!id || !id.table) return true
	// The service has users and nobody is signed in (role null): the person is a VISITOR, who can only look and stop. It used to
	// say yes to everything here, so a signed-out page looked fully usable and every button failed with a 401.
	if (!id.role && !id.configured) return true
	const t = id.table
	if ((t.stop || []).includes(op)) return true
	// A custom role (auth.whoami allow / deny, exact operation names): a denial wins, a grant adds what the base role cannot do. Without the lists
	// (an older service, a base role) nothing changes. The service decides again on every call.
	if (listed(id.deny, op)) return false
	const granted = listed(id.allow, op)
	const role = id.role || 'viewer'
	let need = (t.ops || {})[op] || 'admin'
	const esc = (t.escalate || {})[op] // some operations need more when their arguments change settings
	if (esc) {
		const v = (ctx.args || {})[esc.arg]
		const hit = esc.when_present ? !!v : !(esc.unless_in || []).includes(String(v || ''))
		if (hit && RANK[esc.role] > RANK[need]) need = esc.role
	}
	if (role === 'viewer' && (t.camera || []).includes(op)) return !!(id.user && id.user.camera)
	if (RANK[role] === undefined) return false
	const escalated = need !== ((t.ops || {})[op] || 'admin') // a grant never lifts what the arguments escalated
	if (RANK[role] < RANK[need] && !(granted && !escalated)) return false
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
	let j = null
	try {
		j = await call('auth.whoami', {})
	} catch (e) {
		j = null
	}
	// the service did not answer: the session stays unknown, but it is not "resolving" any more (no view waits for an answer that is not coming)
	shared().whoamiFailed = !(j && j.ok)
	if (j && j.ok) setIdentity(j.result)
	return j && j.ok ? j.result : null
}

// A sign-in on a browser that still holds an accepted session is a CHANGE of person ("Change role", 2026-11-09): the session that was there is kept
// until the service accepts the new name and PIN; only then is it closed (with its own token, still in the headers) and the new one adopted. A
// refused or cancelled attempt leaves the current session as it was.
export async function loginWith(call, name, pin) {
	const before = getToken()
	const j = await call('auth.login', { name, pin })
	if (!j.ok) return j
	if (before && before !== j.result.token) {
		try {
			await call('auth.logout', {})
		} catch (e) {
			/* the previous session ends by itself when it expires */
		}
	}
	setToken(j.result.token)
	await refreshIdentity(call)
	return j
}

export async function logoutWith(call) {
	// The tap on "sign out" is a touch, and signing out makes the pages reload what they show: those reads fail (nobody is signed in)
	// inside the window of that touch and used to open the PIN dialog again, so the session seemed never to close. After signing out the
	// touch is forgotten and nothing opens the dialog by itself for a while; the "sign in" button and a later touch still do.
	const s = shared()
	s.gestureAt = 0
	s.quietUntil = Date.now() + AFTER_LOGOUT_MS
	try {
		await call('auth.logout', {})
	} finally {
		setToken('')
		s.gestureAt = 0
		await refreshIdentity(call)
	}
}

// The service has users and this browser has no session (a visitor, or nothing allowed yet).
export function signedOut() {
	return isSignedOutState(sessionState())
}

// 'resolving' | 'signed-out' | 'signing-in' | 'active' | 'expired' | 'pin-locked' (session-state.js): the one answer the views ask
export function sessionState() {
	const s = shared()
	return sessionStateOf({ identity: s.identity, token: getToken(), flight: s.flight, lockUntil: s.lockUntil, unreachable: s.whoamiFailed }, Date.now())
}

// 'resolving' | 'ok' | 'session' | 'role' for one operation (what a view draws: nothing yet, nothing, the sign-in notice, the role notice)
export function accessState(op, ctx) {
	return accessStateOf(sessionState(), workshopCan(op, ctx))
}

// Why the person cannot do something: '' (they can), 'signed_out' (nobody is signed in: signing in may fix it) or 'role' (signed in,
// but the role is too low: only another role fixes it). The pages say which one next to the thing that does not move.
export function accessReason(op, ctx) {
	const a = accessState(op, ctx)
	return a === 'session' ? 'signed_out' : a === 'role' ? 'role' : ''
}

// The word of the button next to a lock: 'sign-in' (nobody is signed in), 'change-role' (someone is, with a role that is too low: another
// person signs in, the current session stays until that succeeds) or '' (nothing blocks). Both words open the ONE dialog: askLogin() of workshop-api.js.
export function sessionAction(op, ctx) {
	return sessionActionOf(accessState(op, ctx))
}

// The person touched the page a moment ago: what fails now is probably their action (so it is worth telling them).
export function recentGesture() {
	return Date.now() - (shared().gestureAt || 0) < GESTURE_MS
}

// Asks the person for name and PIN (one dialog for all the callers: "Sign in" and "Change role" are the same dialog). Resolves true when logged in,
// false when cancelled. The session this browser has (if any) is NOT touched here: it is kept until loginWith() adopts the new one, so a cancelled
// or refused "Change role" leaves the person signed in as before.
export function ensureLogin(call, t) {
	const s = shared()
	if (s.flight) return s.flight
	// Nothing opens the dialog by itself (a poll, a refresh, not even a touch on a locked control): only the "sign in" button does.
	// A refused touch makes the sign-in chip blink instead (session-attention.js).
	if (!shared().forceAsk) return Promise.resolve(false)
	if (shared().forceAsk) s.quietUntil = 0
	// after cancelling, not even a touch brings it back: the refusal message and the "sign in" button tell what to do
	if (Date.now() < s.quietUntil) return Promise.resolve(false)
	s.flight = pinDialog(async (name, pin) => {
		const j = await loginWith(call, name, pin)
		if (j.ok) {
			s.lockUntil = 0
			return null
		}
		const e = j.error || {}
		// the service asks to wait (too many wrong PINs): the views can say "PIN locked" while it lasts
		s.lockUntil = e.wait_s > 0 ? Date.now() + e.wait_s * 1000 : 0
		notifyState()
		return { code: e.code, message: e.message, wait_s: e.wait_s }
	}, t)
		.then(ok => {
			if (!ok) s.quietUntil = Date.now() + CANCEL_QUIET_MS
			return ok
		})
		.finally(() => {
			s.flight = null
			notifyState()
		})
	notifyState()
	return s.flight
}

// The person pressed "Sign in" or "Change role" (not a call that failed): the dialog opens even if it was cancelled a moment ago. The ONE entry point
// of every button that asks for a name and a PIN (askLogin() of workshop-api.js wraps it with the real call).
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

// The page was in the background (another tab or window) while the person signed in or out there: the storage event can be missed (a throttled or frozen
// tab, a page restored from the back/forward cache), and the page kept saying "no session". When it comes back to the front the token of the browser
// is compared with the one this page knows, and who the service says the person is is asked again when that disagrees with the token.
function reconcileSession(call) {
	const s = shared()
	let stored = ''
	try {
		stored = tokenStore().getItem(TOKEN_KEY) || ''
	} catch (e) {
		stored = s.token || ''
	}
	const staleAnswer = !!(s.token && s.identity && s.identity.login_required)
	if (stored !== (s.token || '') || staleAnswer) {
		s.token = stored
		refreshIdentity(call).catch(() => {})
	}
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
		window.addEventListener('focus', () => reconcileSession(call))
		window.addEventListener('pageshow', e => {
			if (e.persisted) reconcileSession(call)
		})
	}
	if (typeof document.addEventListener === 'function') {
		document.addEventListener('visibilitychange', () => {
			if (document.visibilityState === 'visible') reconcileSession(call)
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
