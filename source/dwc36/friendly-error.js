'use strict'

// Errors of the API as a person should read them (F3-V, 2026-10-21). The pages used to show String(e) ("ApiError: ...") or hide the
// failure and try again in silence. Here an error becomes a kind and a short text in the language of DWC:
//
//   errorKind(e)       'role' (403: the role cannot do this) | 'login' (401: needs the PIN) | 'unavailable' | 'outdated' |
//                      'conflict' | 'cancelled' | 'other'
//   errorText(e, t)    the text; t(key, params) = the translator of the shared texts (shared-t.js `ts`)
//   needsLogin(e, id)  true when the person can fix it by identifying (a 401, or a 403 while nobody is logged in)
//
// The messages of 403 / 401 / unavailable already come translated from workshop-api.js (e.message); the fallbacks below only apply
// to an error without a message. Pure logic: no imports, test/friendly-error.test.js loads it in node.

export function errorKind(e) {
	const code = e && e.code
	if (code === 'forbidden') return 'role'
	if (code === 'login_required') return 'login'
	if (code === 'unavailable') return 'unavailable'
	if (code === 'service_outdated') return 'outdated'
	if (code === 'conflict') return 'conflict'
	if (code === 'cancelled') return 'cancelled'
	return 'other'
}

// identity = currentIdentity() of workshop-auth.js (null until the service answered)
export function needsLogin(e, identity) {
	const kind = errorKind(e)
	if (kind === 'login') return true
	return kind === 'role' && !!identity && !!identity.login_required && !identity.user
}

const FALLBACK = { role: 'err_role', login: 'err_login', unavailable: 'err_unavailable', outdated: 'err_outdated' }

// raw messages of fetch() / Response.json() / JSON.parse in the browsers
const TRANSPORT = /failed to execute|failed to fetch|networkerror|load failed|unexpected (token|end of)|is not valid json|in json at position|json parse/i

function plainMessage(e) {
	const m = e && e.message ? String(e.message) : String(e || '')
	return m.replace(/^(Api)?Error:\s*/i, '').trim()
}

export function errorText(e, t) {
	const kind = errorKind(e)
	if (kind === 'cancelled') return ''
	const own = e && e.message && kind !== 'other' ? String(e.message) : ''
	if (own) return own
	if (FALLBACK[kind]) return t(FALLBACK[kind])
	const m = plainMessage(e)
	// a failure of the transport (the reply was not JSON, no network): the browser's wording is not for people
	if (TRANSPORT.test(m)) return t('err_unavailable')
	return m ? t('err_generic', { error: m }) : t('err_unknown')
}
