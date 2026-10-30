'use strict'

// Search of the lists of the Services page (processes...). Pure; tests/search.test.js (TallerPlugins) runs it.
// A person types what they think the thing is called: "luz" must find "Luces de estado", "gcode" must find "G-code", and accents and
// capitals do not matter. Every word typed has to appear (in any order); each word also matches its plural / singular form and z <-> c
// (luz / luces), and a word of the query matches inside longer words ("lu" finds "lights").

export function normalizeText(s) {
	return String(s == null ? '' : s)
		.normalize('NFD')
		.replace(/[̀-ͯ]/g, '')
		.toLowerCase()
		.replace(/[^a-z0-9]+/g, ' ')
		.trim()
}

// the forms of one typed word that are also accepted: itself, without a plural ending, z written as c
function shapes(w) {
	const out = [w]
	if (w.length > 3 && /es$/.test(w)) out.push(w.slice(0, -2))
	if (w.length > 2 && /s$/.test(w)) out.push(w.slice(0, -1))
	if (/z$/.test(w)) out.push(w.slice(0, -1) + 'c')
	return out
}

export function matches(text, query) {
	const q = normalizeText(query)
	if (!q) return true
	const has = ' ' + normalizeText(text) + ' '
	const withoutSpaces = has.replace(/ /g, '') // "gcode" finds "g code" (the hyphen of G-code)
	return q.split(' ').every(w => shapes(w).some(f => has.indexOf(f) >= 0 || (f.length > 2 && withoutSpaces.indexOf(f) >= 0)))
}
