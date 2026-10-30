'use strict'

// Floating sign that asks for name and PIN (F1-A of the redesign, 2026-10-21). It appears only when the service answers
// 401 login_required; one dialog serves every caller (workshop-auth.js ensureLogin). Look of the floating panels of DESIGN.md:
// dark window #1e272c, text #eceff1, secondary #b0bec5, main button #1976d2, error text #ef9a9a. Same code for the JS plugins in
// src/_shared/46-pin-dialog.js: keep them equal.
//
//   pinDialog(login, t) -> Promise<boolean>   login(name, pin) resolves null (logged in) or { message, wait_s } (refused)

const NAME_KEY = 'workshop-last-user'
// Length of the PIN each person typed the last time it worked, in this browser only: when that many digits are typed the sign
// enters by itself (no Enter). The service is never asked "how long is the PIN"; a wrong automatic try forgets the length.
// The length of each user's PIN is remembered in this browser ONLY so the dialog can send the PIN as soon as the last digit is typed
// (touch kiosk). It is not a credential, but it narrows a guess: the service's own lock-out is what protects the PIN.
const LEN_KEY = 'workshop-pin-len:'

function el(tag, css, text) {
	const e = document.createElement(tag)
	if (css) e.style.cssText = css
	if (text !== undefined) e.textContent = text
	return e
}

const LOCK = 'M12,17A2,2 0 0,0 14,15C14,13.89 13.1,13 12,13A2,2 0 0,0 10,15A2,2 0 0,0 12,17M18,8A2,2 0 0,1 20,10V20A2,2 0 0,1 18,22H6A2,2 0 0,1 4,20V10C4,8.89 4.9,8 6,8H7V6A5,5 0 0,1 12,1A5,5 0 0,1 17,6V8H18M12,3A3,3 0 0,0 9,6V8H15V6A3,3 0 0,0 12,3Z'
const EYE = 'M12,9A3,3 0 0,0 9,12A3,3 0 0,0 12,15A3,3 0 0,0 15,12A3,3 0 0,0 12,9M12,17A5,5 0 0,1 7,12A5,5 0 0,1 12,7A5,5 0 0,1 17,12A5,5 0 0,1 12,17M12,4.5C7,4.5 2.73,7.61 1,12C2.73,16.39 7,19.5 12,19.5C17,19.5 21.27,16.39 23,12C21.27,7.61 17,4.5 12,4.5Z'

function icon(path, size, color) {
	const s = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
	s.setAttribute('viewBox', '0 0 24 24')
	s.setAttribute('width', size)
	s.setAttribute('height', size)
	s.style.cssText = 'fill:' + color + ';flex:none;'
	const p = document.createElementNS('http://www.w3.org/2000/svg', 'path')
	p.setAttribute('d', path)
	s.appendChild(p)
	return s
}

function field(label, type, mode) {
	const wrap = el('label', 'display:block;margin-top:12px;font-size:11px;font-weight:500;letter-spacing:0.4px;text-transform:uppercase;color:#b0bec5;')
	wrap.appendChild(document.createTextNode(label))
	const input = el('input', 'display:block;width:100%;box-sizing:border-box;margin-top:4px;padding:8px 12px;font-size:16px;min-height:44px;' +
		'background:#263238;color:#eceff1;border:1px solid rgba(255,255,255,0.23);border-radius:4px;outline:none;text-transform:none;letter-spacing:normal;font-family:inherit;')
	input.type = type
	if (mode) input.setAttribute('inputmode', mode)
	// Accent border while the field has the focus, red while the sign shows an error (paintError)
	input.addEventListener('focus', () => {
		input.style.borderColor = '#1976d2'
	})
	input.addEventListener('blur', () => {
		input.style.borderColor = input.getAttribute('data-bad') ? '#ef9a9a' : 'rgba(255,255,255,0.23)'
	})
	// On the kiosk (squeekboard) the keyboard only comes out for a touch on the field; a field that already has the focus from
	// code gets no second chance, so each touch takes the focus away and gives it back.
	input.addEventListener('pointerup', () => {
		if (document.activeElement !== input) return
		input.blur()
		input.focus()
	})
	wrap.appendChild(input)
	return { wrap, input }
}

function paintError(fields, on) {
	fields.forEach(i => {
		if (on) i.setAttribute('data-bad', '1')
		else i.removeAttribute('data-bad')
		i.style.borderColor = on ? '#ef9a9a' : 'rgba(255,255,255,0.23)'
	})
}

function lastName() {
	try {
		return window.localStorage.getItem(NAME_KEY) || ''
	} catch (e) {
		return ''
	}
}

function pinLength(name) {
	try {
		return parseInt(window.localStorage.getItem(LEN_KEY + String(name).trim().toLowerCase()), 10) || 0
	} catch (e) {
		return 0
	}
}

function rememberLength(name, len) {
	try {
		const k = LEN_KEY + String(name).trim().toLowerCase()
		if (len) window.localStorage.setItem(k, String(len))
		else window.localStorage.removeItem(k)
	} catch (e) {
		/* not important */
	}
}

function rememberName(n) {
	try {
		window.localStorage.setItem(NAME_KEY, n)
	} catch (e) {
		/* not important */
	}
}

export function pinDialog(login, t) {
	return new Promise(resolve => {
		const back = el('div', 'position:fixed;inset:0;z-index:2147483647;background:rgba(0,0,0,0.55);display:flex;align-items:flex-start;justify-content:center;padding:16px;overflow:auto;')
		back.setAttribute('data-tp-panel', '1')
		back.setAttribute('data-tp-pin', '1') // its own touches do not count as the person's action (workshop-auth.js)
		const box = el('div', 'background:#1e272c;color:#eceff1;border:1px solid rgba(255,255,255,0.12);border-radius:8px;margin:auto 0;font-family:Roboto,Helvetica,Arial,sans-serif;' +
			'max-width:360px;width:100%;padding:16px 18px 14px;font-size:13px;line-height:1.45;box-shadow:0 8px 30px rgba(0,0,0,0.5);')
		box.setAttribute('role', 'dialog')
		box.setAttribute('aria-modal', 'true')
		const head = el('div', 'display:flex;align-items:center;gap:12px;')
		const badge = el('div', 'width:40px;height:40px;border-radius:50%;background:rgba(25,118,210,0.2);display:flex;align-items:center;justify-content:center;flex:none;')
		badge.appendChild(icon(LOCK, 22, '#90caf9'))
		const titles = el('div', 'min-width:0;')
		titles.appendChild(el('div', 'font-size:14px;font-weight:600;color:#90caf9;', t('pinTitle')))
		titles.appendChild(el('div', 'color:#b0bec5;font-size:12px;', t('pinHint')))
		head.appendChild(badge)
		head.appendChild(titles)
		box.appendChild(head)
		const nm = field(t('pinName'), 'text')
		nm.input.setAttribute('autocomplete', 'username')
		nm.input.setAttribute('autocapitalize', 'none')
		nm.input.setAttribute('autocorrect', 'off')
		nm.input.setAttribute('spellcheck', 'false')
		nm.input.setAttribute('enterkeyhint', 'next')
		nm.input.value = lastName()
		// A PIN is digits only (the service refuses anything else): the field is a numeric one (inputmode numeric, so the kiosk keyboard is
		// the number pad). It is a text field hidden with CSS, not type=password: a password field makes the keyboard ask for the full layout.
		const pn = field(t('pinPin'), 'text', 'numeric')
		pn.input.style.setProperty('-webkit-text-security', 'disc')
		pn.input.setAttribute('pattern', '[0-9]*')
		pn.input.setAttribute('autocomplete', 'off')
		pn.input.setAttribute('enterkeyhint', 'go')
		pn.input.style.paddingRight = '48px'
		// Eye to see the PIN being typed (own PIN, own screen)
		const eye = el('button', 'position:absolute;right:2px;bottom:0;width:44px;height:44px;background:transparent;border:0;border-radius:4px;cursor:pointer;display:flex;align-items:center;justify-content:center;padding:0;')
		eye.type = 'button'
		eye.setAttribute('tabindex', '-1')
		eye.appendChild(icon(EYE, 20, '#b0bec5'))
		eye.addEventListener('pointerdown', ev => ev.preventDefault()) // does not take the focus (and the keyboard) away from the PIN
		eye.addEventListener('click', () => {
			const shown = pn.input.style.getPropertyValue('-webkit-text-security') === 'none'
			pn.input.style.setProperty('-webkit-text-security', shown ? 'disc' : 'none')
			eye.firstChild.style.fill = shown ? '#b0bec5' : '#90caf9'
		})
		pn.wrap.style.position = 'relative'
		pn.wrap.appendChild(eye)
		const msg = el('div', 'min-height:20px;margin-top:10px;font-size:12px;color:#ef9a9a;')
		const row = el('div', 'display:flex;gap:8px;justify-content:flex-end;margin-top:6px;')
		const bc = el('button', 'background:transparent;color:#eceff1;border:0;border-radius:6px;padding:8px 16px;min-height:44px;font-size:13px;font-weight:500;text-transform:uppercase;letter-spacing:0.4px;cursor:pointer;font-family:inherit;', t('cancel'))
		const bo = el('button', 'background:#1976d2;color:#fff;border:0;border-radius:6px;padding:8px 20px;min-height:44px;font-size:13px;font-weight:600;text-transform:uppercase;letter-spacing:0.4px;cursor:pointer;font-family:inherit;', t('pinEnter'))
		bc.type = bo.type = 'button'
		const inputs = [nm.input, pn.input]
		let busy = false
		const end = v => {
			document.removeEventListener('keydown', key, true)
			if (back.parentNode) back.parentNode.removeChild(back)
			resolve(v)
		}
		const submit = async () => {
			if (busy) return
			const name = nm.input.value.trim()
			if (!name || !pn.input.value) {
				msg.textContent = t('pinMissing')
				paintError(inputs, true)
				return
			}
			busy = true
			bo.disabled = true
			bo.style.opacity = '0.5'
			msg.textContent = ''
			paintError(inputs, false)
			const typed = pn.input.value
			let err = null
			try {
				err = await login(name, typed)
			} catch (e) {
				err = { message: t('unavailable') }
			}
			busy = false
			bo.disabled = false
			bo.style.opacity = '1'
			if (!err) {
				rememberName(name)
				rememberLength(name, typed.length)
				end(true)
				return
			}
			rememberLength(name, 0)
			pn.input.value = ''
			msg.textContent = err.message || t('pinWrong')
			paintError(inputs, true)
			pn.input.focus()
		}
		const key = ev => {
			if (ev.key === 'Escape') end(false)
			else if (ev.key === 'Enter') {
				// From the name Enter goes on to the PIN; from the PIN it signs in
				if (ev.target === nm.input && !pn.input.value) pn.input.focus()
				else submit()
			}
		}
		pn.input.addEventListener('input', () => {
			const digits = pn.input.value.replace(/\D/g, '')
			if (digits !== pn.input.value) pn.input.value = digits // digits only
			const want = pinLength(nm.input.value)
			if (want && pn.input.value.length === want) submit()
		})
		bc.addEventListener('click', () => end(false))
		bo.addEventListener('click', submit)
		document.addEventListener('keydown', key, true)
		row.appendChild(bc)
		row.appendChild(bo)
		;[nm.wrap, pn.wrap, msg, row].forEach(x => box.appendChild(x))
		back.appendChild(box)
		;(document.fullscreenElement || document.body).appendChild(back)
		// The first empty field gets the focus; on the kiosk the keyboard comes out through the helper (02-kiosk-keyboard.js)
		;(nm.input.value ? pn.input : nm.input).focus()
	})
}
