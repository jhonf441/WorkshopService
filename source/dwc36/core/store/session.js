'use strict'

// The session as the new page sees it: a reactive mirror of workshop-auth.js (family twin, shared by every plugin of the browser).
// The screens ask only this module; they never import workshop-auth.js or workshop-api.js.
//
//   session.state        'resolving' | 'signed-out' | 'signing-in' | 'active' | 'expired' | 'pin-locked'   (session-state.js)
//   session.name / role / roleName / configured / damaged     who the person is ('' when nobody)
//   session.usersOff / networkOpen   the roles are switched off (everybody is an administrator) / the camera and Vision are open on the network
//   session.loginRequired  nobody is signed in and this machine lets nobody look without a session: every read would be a 401
//   session.idleMinutes    the session closes after this long without use (null: not known, or no sessions here)
//   session.unknown        the service did not say who the person is (auth.whoami failed): nothing is enabled until it does
//   recheckSession()       ask the service again who the person is (after a 401, or when the first answer never came)
//   session.generation   grows every time the PERSON changes (sign in, sign out, another person, expiry): what came from the old
//                        session is thrown away by whoever watches it (resources, actions)
//   can(op, ctx)         { state: 'resolving' | 'ok' | 'session' | 'role', allowed, cause, neededRole, text, fixed }
//                        fixed: nothing the person can do from the page lifts it (the file of people is damaged): no button is offered
//                        the ONE question a screen asks before it enables a control or sends a read; a stop is always allowed
//   want(ops)            ask the service about these operations in one batch (people governed by profiles: the table of whoami
//                        is not the whole truth); the answers correct can() when they arrive
//   onSessionChange(fn)  fn() after the person changed, and once when the service first says who the person is; returns the function that stops listening
//   signIn() / signOut() the one name + PIN dialog of the family, and the sign-out. Nothing else opens the dialog.
//   startSession()       called once by the shell; returns the function that stops it
//
// Without a session the page calls only auth.whoami (the twin) and auth.can (want): nothing here sends anything else.

import Vue from 'vue'
import { t, te } from '../dwc.js'
import { askLogin, currentIdentity, logout, onIdentity, whoami } from '../../workshop-api.js'
import { onSessionLost } from '../api/call.js'
import { accessState, sessionState, workshopDenied } from '../../workshop-auth.js'
import { canStore } from '../../reason-mixin.js'
import { lockReasonOp } from '../../lock-reason.js'
import { STOP_OPS, causeOfDecision } from '../../access-reason.js'

export const session = Vue.observable({
	state: 'resolving', name: '', role: '', roleName: '', configured: false, damaged: false, usersOff: false, networkOpen: false,
	loginRequired: false, idleMinutes: null, unknown: false, generation: 0, answers: 0
})

const listeners = []
let personKey = null
let stops = null

function keyOf(id, state) {
	if (!id) return 'unknown'
	const signed = state === 'active' ? 'in' : 'out'
	return [id.configured ? 'users' : 'open', signed, id.role || '', (id.user && id.user.name) || ''].join('|')
}

// reads the twin again and tells who watches when the person is another one
export function syncSession() {
	const id = currentIdentity()
	const state = sessionState()
	session.state = state
	session.unknown = !id && state !== 'resolving'
	session.name = (id && id.user && id.user.name) || ''
	session.role = (id && id.role) || ''
	session.roleName = (id && id.role_name) || session.role
	session.configured = !!(id && id.configured)
	session.damaged = !!(id && id.damaged)
	session.usersOff = !!(id && id.users_disabled)
	session.networkOpen = !!(id && id.network_open)
	session.loginRequired = !!(id && id.login_required)
	session.idleMinutes = id && typeof id.idle_minutes === 'number' ? id.idle_minutes : null
	const key = keyOf(id, state)
	if (key === 'unknown' || key === personKey) return
	// the first answer of the service is not a change of person, but who waited for it (a screen already on) is told as well
	if (personKey !== null) session.generation += 1
	personKey = key
	listeners.slice().forEach(fn => { try { fn() } catch (e) { /* one listener must not stop the others */ } })
}

export function startSession() {
	if (stops) return stopSession
	syncSession()
	const offIdentity = onIdentity(syncSession)
	const offCan = canStore().onChange(() => { session.answers += 1 })
	// a call came back without a session (expired, closed from another place): the service is asked who the person is NOW
	stops = [offIdentity, offCan, onSessionLost(() => { recheckSession() })]
	// the twin asks who the person is when it loads; if that answer never came it tells nobody: ask once and look
	if (!currentIdentity()) recheckSession()
	return stopSession
}

let checking = null

export function recheckSession() {
	if (checking) return checking
	checking = Promise.resolve().then(() => whoami()).catch(() => null).then(() => { checking = null; syncSession() })
	return checking
}

export function stopSession() {
	(stops || []).forEach(off => { if (typeof off === 'function') off() })
	stops = null
}

export function onSessionChange(fn) {
	listeners.push(fn)
	return () => {
		const i = listeners.indexOf(fn)
		if (i >= 0) listeners.splice(i, 1)
	}
}

const OK = Object.freeze({ state: 'ok', allowed: true, cause: '', neededRole: '', text: '' })
const RESOLVING = Object.freeze({ state: 'resolving', allowed: false, cause: '', neededRole: '', text: '' })

function neededRole(op) {
	const id = currentIdentity()
	const ops = id && id.table && id.table.ops
	return (ops && ops[op]) || ''
}

const BASE_ROLES = ['viewer', 'operator', 'technician', 'admin']

// "Needs the role Technician. Your role: Operator.": role names as the catalogs write them (capital first), also inside a sentence
// what the operation is for a person (area `ops_action`): the sentence of a lock says WHAT asks for the role; an operation without a name is "This"
export function actionOf(op) {
	const key = 'ops_action.' + String(op || '').replace(/\./g, '_')
	return te(key) ? t(key) : t('ops_action._other')
}

function roleSentence(op, ctx) {
	const need = neededRole(op)
	const id = currentIdentity() || {}
	if (BASE_ROLES.indexOf(need) < 0) return lockReasonOp(op, need || undefined, ctx)
	const mine = id.role_name && BASE_ROLES.indexOf(id.role_name) < 0 ? id.role_name : BASE_ROLES.indexOf(id.role) >= 0 ? t('api.role_' + id.role) : String(id.role || '')
	return t('shell.lock_role', { action: actionOf(op), needed: t('api.role_' + need), role: mine })
}

export function can(op, ctx) {
	void session.generation
	void session.answers
	void session.state
	void session.damaged          // these two change what is allowed without changing who the person is
	void session.loginRequired
	// a stop is never locked: not signed out, not with a damaged file, not while the session is unknown (the service never refuses one)
	const me = currentIdentity()
	const stopsNow = (me && me.table && me.table.stop) || []
	if (!op || STOP_OPS.indexOf(op) >= 0 || stopsNow.indexOf(op) >= 0) return OK
	void session.unknown
	if (!me && sessionState() !== 'resolving') return { state: 'session', allowed: false, cause: 'unknown', neededRole: '', text: t('shell.session_unknown_text'), fixed: true }
	const access = accessState(op, ctx)
	if (access === 'resolving') return RESOLVING
	// the table of roles says what a viewer may do, but here nobody may look without a session: the service would answer 401
	const id = currentIdentity()
	// the file of people is damaged: nobody can sign in, so the lock offers no way in (`fixed`) and says where it is repaired
	if (id && id.damaged && sessionState() !== 'active') return { state: 'session', allowed: false, cause: 'damaged', neededRole: '', text: t('shell.cover_damaged_text'), fixed: true }
	if (access === 'session' || (id && id.login_required && sessionState() !== 'active')) return { state: 'session', allowed: false, cause: 'session', neededRole: neededRole(op), text: sessionState() === 'expired' ? t('kit.session_closed') : lockReasonOp(op, neededRole(op) || undefined, ctx) }
	// the answer of the service for this person (auth.can) wins over the table; a call whose arguments escalate it is judged by the table
	const answer = ctx && ctx.args ? null : canStore().get(op)
	const allowed = answer ? !!answer.allowed : access === 'ok'
	if (allowed) return OK
	const cause = answer ? causeOfDecision(answer.reason) : workshopDenied(op) ? 'denied' : 'role'
	return { state: 'role', allowed: false, cause, neededRole: neededRole(op), text: cause === 'role' ? roleSentence(op, ctx) : lockReasonOp(op, neededRole(op) || undefined, ctx) }
}

export function want(ops) {
	const list = (ops || []).filter(op => op && STOP_OPS.indexOf(op) < 0)
	return list.length ? canStore().want(list) : Promise.resolve()
}

export function signIn() {
	return askLogin()
}

export function signOut() {
	return logout()
}
