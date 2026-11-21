'use strict'

// The minimum policy of the DWC password, the same rules the server applies ALWAYS (dsf/password_policy.py; dsf/test_password_policy.py keeps the two
// lists and the limits equal). The page uses it to say, while the person types, which requirement is met; the server is the one that refuses.
// check() returns the first reason that breaks (characters, length, factory, mismatch, common, names, one_class, pattern) or ''.

export const MIN_LEN = 10
export const MAX_LEN = 60
const BAD_CHARS = ['"', "'", ';', '{', '}', '\\'].join('')

// lower case, no tail: what people choose first (and what is typed in a workshop with a Duet). Same words as COMMON of password_policy.py
export const COMMON = `
000000 00000000 0000000000 0123456789 111111 11111111 1111111111 112233 11223344 121212 12121212 123123 123123123 123321 12341234 123456 1234567
12345678 123456789 1234567890 1234abcd 1q2w3e4r 1q2w3e4r5t 1qaz2wsx 1qazxsw2 3dprint 3dprinter 654321 666666 696969 6hc 7777777 77777777 88888888
987654321 9876543210 99999999 aaaaaaaa aaaaaaaaaa abc123 abcd1234 abcdefgh abcdefghij abcdefghijkl acceso access admin administrador administrator
alejandro amazon america andrea apple argentina arsenal asdfgh asdfghjk asdfghjkl azerty barcelona barranquilla baseball baseball1 batman bienvenido
bogota buster cali cambiame carlos change changeme charlie chelsea chevrolet chile clave claves cnc colombia contrasena contrasenia cortadora creality
cutter daniel david debian default demo dragon dsf duet duet2 duet3 duet36hc duet3d duet3mb6hc duetweb duetwifi dwc ecuador ejemplo ender
example facebook ferrari football football1 fortnite fresadora futbol google guest harley hello hellohello helloworld hockey hola holahola holamundo
hunter iloveyou impresora internet invitado javier jennifer jordan jose juan klipper laser letmein linksys linux liverpool login loveyou luis machine
machine1 madrid maquina maria marlin master mb6hc medellin mercedes mexico micasa michael miclave micontrasena miguel milling minecraft mipassword
monkey mundo mustang naruto netgear network p4ssword pass passw0rd password passwort pedro peru pi pi4 plotter pokemon princess printer prueba pruebas
prusa qazwsx qazwsxedc qwerty qwertyui qwertyuiop rangers raspberry raspberrypi raspberrypi4 realmadrid reprap reprap3d repraprap robert root router
router1 rrf samsung sebastian secret secreto shadow sistemas soccer spiderman starwars sunshine superman taller temp temporal test test123 testing
thomas trustno1 tucontrasena ubuntu user usuario venezuela welcome wifi windows word workshop workshopservice yankees youtube zaq12wsx zxcvbn zxcvbnm
`

const COMMON_SET = new Set(COMMON.split(/\s+/).filter(Boolean))
const TAIL = /[0-9!@#$%^&*._\-+=?]+$/
const ROWS = ['qwertyuiop', 'asdfghjkl', 'zxcvbnm', '1234567890', 'qazwsxedcrfvtgbyhnujmikolp', 'abcdefghijklmnopqrstuvwxyz', 'azertyuiop', 'qsdfghjklm']

const isLetter = c => c.toLowerCase() !== c.toUpperCase()
const isDigit = c => c >= '0' && c <= '9'

export function kinds(p) {
	const chars = Array.from(p)
	return [chars.some(isLetter), chars.some(isDigit), chars.some(c => !isLetter(c) && !isDigit(c))].filter(Boolean).length
}

const normal = p => p.toLowerCase().replace(/ /g, '').replace(/-/g, '')

export function isCommon(p) {
	const low = p.toLowerCase().trim()
	const squeezed = normal(p)
	return [low, squeezed, low.replace(TAIL, ''), squeezed.replace(TAIL, '')].some(c => c && (COMMON_SET.has(c) || COMMON_SET.has(c.replace(/[0-9]+$/, '')) || COMMON_SET.has(c.replace(/^[0-9]+/, ''))))
}

function repeatedBlock(p) {
	const n = p.length
	for (let size = 1; size <= Math.floor(n / 2); size++) if (n % size === 0 && p.slice(0, size).repeat(n / size) === p) return true
	return false
}

function sequenceShare(p) {
	const low = p.toLowerCase()
	const n = low.length
	const covered = new Array(n).fill(false)
	const code = i => low.charCodeAt(i)
	for (let i = 0; i < n - 1;) {
		const step = code(i + 1) - code(i)
		if (step === 1 || step === -1) {
			let j = i + 1
			while (j + 1 < n && code(j + 1) - code(j) === step) j++
			if (j - i + 1 >= 4) for (let k = i; k <= j; k++) covered[k] = true
			i = j
		} else i++
	}
	ROWS.forEach(row => {
		;[row, row.split('').reverse().join('')].forEach(r => {
			for (let size = Math.min(n, r.length); size > 3; size--) {
				for (let start = 0; start + size <= r.length; start++) {
					const piece = r.slice(start, start + size)
					for (let pos = low.indexOf(piece); pos >= 0; pos = low.indexOf(piece, pos + 1)) for (let k = pos; k < pos + size; k++) covered[k] = true
				}
			}
		})
	})
	return n ? covered.filter(Boolean).length / n : 0
}

export function hasPattern(p) {
	const low = p.toLowerCase()
	return new Set(low).size < 4 || repeatedBlock(low) || sequenceShare(p) >= 0.6
}

export function badCharacters(p) {
	return Array.from(p).some(c => BAD_CHARS.indexOf(c) >= 0 || c.charCodeAt(0) < 32 || c.charCodeAt(0) === 127) || p !== p.trim()
}

// names: what it must not be equal to (the person, the machine): the page only knows the person that is signed in; the server knows the rest
export function check(password, repeat, names) {
	const p = typeof password === 'string' ? password : ''
	if (badCharacters(p)) return 'characters'
	if (p.length < MIN_LEN || p.length > MAX_LEN) return 'length'
	if (p.toLowerCase() === 'reprap') return 'factory'
	if (repeat !== undefined && repeat !== null && repeat !== p) return 'mismatch'
	if (isCommon(p)) return 'common'
	const low = p.toLowerCase()
	for (const name of names || []) {
		const n = String(name || '').trim().toLowerCase()
		if (n.length >= 3 && (low === n || low.replace(TAIL, '') === n || low.replace(/[0-9]+$/, '') === n)) return 'names'
	}
	if (kinds(p) < 2) return 'one_class'
	if (hasPattern(p)) return 'pattern'
	return ''
}

// 0 very weak, 1 weak, 2 acceptable, 3 strong (the meter). Under the minimum policy it never goes above 1.
export function strength(password) {
	const p = password || ''
	if (check(p) !== '') return p.length < MIN_LEN || hasPattern(p) || isCommon(p) ? 0 : 1
	if ((p.length >= 14 && kinds(p) >= 2) || p.length >= 20 || (p.length >= 12 && kinds(p) >= 3)) return 3
	return 2
}

// The list the page draws while the person types: [{ id, ok }]. Nothing is shown as met until something is typed.
// length, chars (no character that breaks config.g), mix (not only letters or digits), plain (not common, not a repetition or a sequence, not the person), match
export function requirements(password, repeat, names) {
	const p = password || ''
	const typed = p.length > 0
	const reason = check(p, undefined, names)
	return [
		{ id: 'length', ok: typed && p.length >= MIN_LEN && p.length <= MAX_LEN },
		{ id: 'chars', ok: typed && !badCharacters(p) },
		{ id: 'mix', ok: typed && kinds(p) >= 2 },
		{ id: 'plain', ok: typed && !['common', 'names', 'pattern', 'factory'].includes(reason) },
		{ id: 'match', ok: typed && repeat === p }
	]
}

// the reason that keeps the button off, or '' when the password can be set
export function blocker(password, repeat, names) {
	if (!password) return 'empty'
	return check(password, repeat || '', names)
}

// ---- the PIN of a person: a NEW or CHANGED PIN only (the PINs already saved keep working) ----
// The same rules as check_pin of dsf/password_policy.py (dsf/test_pin_policy.py keeps the list and the limits equal); the server refuses, the page says it while typing.
// checkPin returns the first reason that breaks (digits, length, mismatch, common, repeated, sequence, date) or ''.

export const PIN_MIN_LEN = 6
export const PIN_MAX_LEN = 12

export const PIN_COMMON = `
000000 0000000 00000000 000111 001122 002200 007007 010101 010203 012345 0123456 01234567 012345678 0123456789 100200 101010 102030 111000 111111
111222 112211 112233 121212 121314 123000 123123 123123123 123321 123456 1234567 12345678 123456789 1234567890 123654 123789 131313 142536 147258
147258369 159159 159357 159753 192837 200000 202020 223344 232323 246810 252525 292929 321321 333333 369369 445566 456123 456456 456789 520520 555555
654123 654321 666666 696969 741852 753159 777777 778899 789456 789789 888888 898989 987456 987654 987654321 9876543210 999999
`
const PIN_COMMON_SET = new Set(PIN_COMMON.split(/\s+/).filter(Boolean))

function realDate(day, month, year) {
	if (year < 1930 || year > 2030 || month < 1 || month > 12 || day < 1) return false
	return day <= new Date(year, month, 0).getDate()
}

export function pinIsDate(p) {
	const n = p.length
	const num = (a, b) => Number(p.slice(a, b))
	if (n === 8) return realDate(num(0, 2), num(2, 4), num(4, 8)) || realDate(num(6, 8), num(4, 6), num(0, 4))
	if (n === 6) return realDate(num(0, 2), num(2, 4), num(4, 6) >= 30 ? 1900 + num(4, 6) : 2000 + num(4, 6))
	return false
}

export function pinLongestRun(p) {
	let best = 1
	;[1, 9].forEach(want => {
		let run = 1
		for (let i = 0; i + 1 < p.length; i++) {
			run = (Number(p[i + 1]) - Number(p[i]) + 10) % 10 === want ? run + 1 : 1
			best = Math.max(best, run)
		}
	})
	return best
}

export const pinIsSequence = p => pinLongestRun(p) >= Math.max(5, p.length - 1)
export const pinIsRepeated = p => new Set(p).size <= 2 || repeatedBlock(p)

export function checkPin(pin, repeat) {
	const p = typeof pin === 'string' ? pin : ''
	if (!/^[0-9]+$/.test(p)) return 'digits'
	if (p.length < PIN_MIN_LEN || p.length > PIN_MAX_LEN) return 'length'
	if (repeat !== undefined && repeat !== null && repeat !== p) return 'mismatch'
	if (PIN_COMMON_SET.has(p)) return 'common'
	if (pinIsRepeated(p)) return 'repeated'
	if (pinIsSequence(p)) return 'sequence'
	if (pinIsDate(p)) return 'date'
	return ''
}

// What the form draws while the person types: [{ id, ok }]. Nothing is shown as met until something is typed.
// digits, length, plain (not a common PIN, not a repetition or a run of consecutive numbers), date (not a probable date), match (when a second entry exists)
export function pinRequirements(pin, repeat) {
	const p = pin || ''
	const typed = p.length > 0
	const reason = typed ? checkPin(p) : ''
	return [
		{ id: 'digits', ok: typed && /^[0-9]+$/.test(p) },
		{ id: 'length', ok: typed && p.length >= PIN_MIN_LEN && p.length <= PIN_MAX_LEN },
		{ id: 'plain', ok: typed && !['common', 'repeated', 'sequence'].includes(reason) },
		{ id: 'date', ok: typed && reason !== 'date' },
		{ id: 'match', ok: typed && repeat === p }
	]
}

// the reason that keeps the button off, or '' when the PIN can be set
export function pinBlocker(pin, repeat) {
	if (!pin) return 'empty'
	return checkPin(pin, repeat === undefined ? undefined : repeat)
}
