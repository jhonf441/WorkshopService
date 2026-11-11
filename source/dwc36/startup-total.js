'use strict'

// The one "Puesta en marcha" section of the service page (StartupSection.vue): the single total of its two parts. Pure, no Vue and no imports.
//
//   steps = state of StartupMaster:  { rows, pending, unchecked, needsLogin, loading }   (pending = plugins with steps left)
//   files = state of StartupWizard:  { items, loaded, needsLogin, loading }               (items = file changes waiting for a decision)
//
// kind: 'login' (nobody is signed in on both parts) | 'pending' | 'unchecked' | 'ready'

export const EMPTY_STEPS = { rows: 0, pending: 0, unchecked: 0, needsLogin: false, loading: false }
export const EMPTY_FILES = { items: 0, loaded: false, needsLogin: false, loading: false }

export function total(steps, files) {
	const s = Object.assign({}, EMPTY_STEPS, steps)
	const f = Object.assign({}, EMPTY_FILES, files)
	const stepsPending = s.needsLogin ? 0 : s.pending
	const filesPending = f.needsLogin ? 0 : f.items
	const n = stepsPending + filesPending
	// nothing pending, but one part could not even be read: it is not "ready", it is "sign in"
	const blind = s.needsLogin || f.needsLogin
	let kind = 'ready'
	if (blind && n === 0) kind = 'login'
	else if (n > 0) kind = 'pending'
	else if (s.unchecked > 0 && !s.needsLogin) kind = 'unchecked'
	return { n, kind, stepsPending, filesPending, unchecked: s.unchecked, loading: !!(s.loading || f.loading) }
}

// Chip colour of Vuetify for each kind.
export const KIND_COLOR = { login: undefined, pending: 'warning', unchecked: undefined, ready: 'success' }
