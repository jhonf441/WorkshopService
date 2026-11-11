'use strict'

// ONE answer to "what is the session right now" (ESTANDAR 2, Agent A of 2026-11-05). Pure logic: workshop-auth.js passes what it knows, so
// tests/session-state.test.js loads this file in node. Twin for the JS plugins: src/_shared/01-session-state.js (keep them equal).
//
//   sessionStateOf({ identity, token, flight, lockUntil, unreachable }, now)
//        'resolving'   the service has not told who the person is yet (nothing colored, nothing decided)
//        'pin-locked'  too many wrong PINs: the service asked to wait (lockUntil = ms epoch)
//        'signing-in'  the PIN dialog is open or its login call is in flight
//        'expired'     there is a token but the service no longer accepts it (login_required)
//        'signed-out'  users exist and this browser has no session (a visitor)
//        'active'      signed in, or the machine has no users (everybody is admin)
//   isSignedOutState(state)           true for the four states in which signing in may fix what does not work
//   accessStateOf(state, allowed)     'resolving' | 'ok' | 'session' | 'role'  (allowed = the role rule said yes)
//   sessionActionOf(access)           'sign-in' | 'change-role' | '': the word of the button next to a lock (the same name + PIN dialog serves both)
//
// A session that the service accepts stays 'active' while the name + PIN dialog is open or a wrong PIN locked it: that dialog is "Change role"
// (another person signs in on this browser, 2026-11-09) and the current session is kept until the new sign-in succeeds, so nothing on the page
// may look signed out meanwhile (the pages reset what they show on 'signed-out').

export const SESSION_STATES = ['resolving', 'signed-out', 'signing-in', 'active', 'expired', 'pin-locked']

export function sessionStateOf(s, now) {
	const x = s || {}
	const id = x.identity
	// no answer yet: 'resolving'; the service did not answer (unreachable): the session stays unknown but nothing waits for it, like workshopCan (it says yes)
	if (!id) return x.unreachable ? 'active' : 'resolving'
	if (!id.configured) return 'active'
	if (x.token && !id.login_required) return 'active'
	if (x.lockUntil && x.lockUntil > (now || Date.now())) return 'pin-locked'
	if (x.flight) return 'signing-in'
	if (x.token && id.login_required) return 'expired'
	return 'signed-out'
}

export function sessionActionOf(access) {
	return access === 'session' ? 'sign-in' : access === 'role' ? 'change-role' : ''
}

export function isSignedOutState(state) {
	return state === 'signed-out' || state === 'signing-in' || state === 'expired' || state === 'pin-locked'
}

export function accessStateOf(state, allowed) {
	if (state === 'resolving') return 'resolving'
	if (allowed) return 'ok'
	return isSignedOutState(state) ? 'session' : 'role'
}
