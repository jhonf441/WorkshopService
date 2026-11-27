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
	const wrap = el('label', 'display:block;margin-top:12px;font-size:12px;font-weight:500;letter-spacing:0.4px;text-transform:uppercase;color:#b0bec5;')
	wrap.appendChild(document.createTextNode(label))
	const input = el('input', 'display:block;width:100%;box-sizing:border-box;margin-top:4px;padding:6px 12px;font-size:16px;min-height:var(--wf-field-h, 40px);' +
		'background:#263238;color:#eceff1;border:1px solid rgba(255,255,255,0.23);border-radius:4px;outline:none;text-transform:none;letter-spacing:normal;font-family:inherit;')
	input.type = type
	if (mode) input.setAttribute('inputmode', mode)
	// Accent border while the field has the focus, red while the sign shows an error (paintError)
	input.addEventListener('focus', () => {
		input.style.borderColor = 'var(--wf-accent, #1976d2)'
	})
	input.addEventListener('blur', () => {
		input.style.borderColor = input.getAttribute('data-bad') ? '#ef9a9a' : 'rgba(255,255,255,0.23)'
	})
	// On the kiosk (squeekboard) the keyboard only comes out for a touch on the field; a field that already has the focus from
	// code gets no second chance, so each touch takes the focus away and gives it back.
	input.addEventListener('pointerup', () => {
		if (input.readOnly || document.activeElement !== input) return
		input.blur()
		input.focus()
	})
	wrap.appendChild(input)
	return { wrap, input }
}

// Number pad of the dialog for the kiosk (the same as src/_shared/01-api-pin.js): 1-9, clear, 0, backspace. The buttons never take the focus.
function keypad(input) {
	const grid = el('div', 'display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:12px;')
	;['1', '2', '3', '4', '5', '6', '7', '8', '9', 'C', '0', '<'].forEach(c => {
		const b = el('button', 'min-height:52px;font-size:20px;font-weight:600;font-family:inherit;color:#eceff1;background:#37474f;border:0;border-radius:8px;cursor:pointer;', c === '<' ? '⌫' : c)
		b.type = 'button'
		b.setAttribute('tabindex', '-1')
		b.addEventListener('pointerdown', ev => {
			ev.preventDefault()
			const a = document.activeElement
			if (a && a !== document.body && a.blur) a.blur() // the name field's keyboard goes away: only this pad is left
		})
		b.addEventListener('click', () => {
			if (c === 'C') input.value = ''
			else if (c === '<') input.value = input.value.slice(0, -1)
			else input.value += c
			input.dispatchEvent(new Event('input', { bubbles: true }))
		})
		grid.appendChild(b)
	})
	return grid
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

// the veil never covers an emergency stop (owner's safety rule 2026-11-23; twin of workshopVeilClear, src/_shared/45-layers.js): it starts under
// DWC's top bar (its Emergency stop) and ends left of the control bar (getInset of the notices center)
function veilClear(back) {
	const bar = document.querySelector('header.v-app-bar') || document.querySelector('.v-app-bar')
	const r = bar && typeof bar.getBoundingClientRect === 'function' ? bar.getBoundingClientRect() : null
	const c = window.__workshopNotices
	back.style.top = (r && r.height > 0 && r.bottom > 0 ? Math.ceil(r.bottom) : 0) + 'px'
	back.style.right = (c && typeof c.getInset === 'function' ? Number(c.getInset('right')) || 0 : 0) + 'px'
	back.setAttribute('data-wf-veil-clear', '1')
}

export function pinDialog(login, t) {
	return new Promise(resolve => {
		const back = el('div', 'position:fixed;inset:0;z-index:2147483647;background:rgba(0,0,0,0.55);display:flex;align-items:flex-start;justify-content:center;padding:16px;overflow:auto;')
		back.setAttribute('data-tp-panel', '1')
		back.setAttribute('data-tp-pin', '1'); veilClear(back) // its own touches are not the person's action (workshop-auth.js); never over a stop
		const box = el('div', 'background:#1e272c;color:#eceff1;border:1px solid rgba(255,255,255,0.12);border-radius:8px;margin:auto 0;font-family:Roboto,Helvetica,Arial,sans-serif;' +
			'max-width:360px;width:100%;padding:16px 18px 14px;font-size:13px;line-height:1.45;box-shadow:0 8px 30px rgba(0,0,0,0.5);')
		box.setAttribute('role', 'dialog')
		box.setAttribute('aria-modal', 'true')
		const head = el('div', 'display:flex;align-items:center;gap:12px;')
		const badge = el('div', 'width:40px;height:40px;border-radius:50%;background:rgba(25,118,210,0.2);display:flex;align-items:center;justify-content:center;flex:none;')
		badge.appendChild(icon(LOCK, 22, 'var(--wf-n-session, #1e88e5)'))
		const titles = el('div', 'min-width:0;')
		titles.appendChild(el('div', 'font-size:14px;font-weight:600;color:var(--wf-n-session-text, #90caf9);', t('pinTitle')))
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
		const eye = el('button', 'position:absolute;right:2px;bottom:0;width:var(--wf-hit, 40px);height:var(--wf-hit, 40px);background:transparent;border:0;border-radius:4px;cursor:pointer;display:flex;align-items:center;justify-content:center;padding:0;')
		eye.type = 'button'
		eye.setAttribute('tabindex', '-1')
		eye.appendChild(icon(EYE, 20, '#b0bec5'))
		eye.addEventListener('pointerdown', ev => ev.preventDefault()) // does not take the focus (and the keyboard) away from the PIN
		eye.addEventListener('click', () => {
			const shown = pn.input.style.getPropertyValue('-webkit-text-security') === 'none'
			pn.input.style.setProperty('-webkit-text-security', shown ? 'disc' : 'none')
			eye.firstChild.style.fill = shown ? '#b0bec5' : 'var(--wf-n-session-text, #90caf9)'
		})
		pn.wrap.style.position = 'relative'
		pn.wrap.appendChild(eye)
		// Kiosk (page on the Pi itself): the keyboard helper can only raise the FULL layout and a PIN is digits, so the dialog draws its own number pad;
		// the PIN field is read only there (inputmode none was not enough) and the helper leaves it alone (data-wf-own-keypad, 02-kiosk-keyboard.js).
		const host = window.location && window.location.hostname
		let pad = null
		if (host === 'localhost' || host === '127.0.0.1') {
			pn.input.setAttribute('inputmode', 'none')
			pn.input.setAttribute('data-wf-own-keypad', '1')
			pn.input.readOnly = true
			pad = keypad(pn.input)
		}
		const msg = el('div', 'min-height:20px;margin-top:10px;font-size:12px;color:#ef9a9a;')
		const row = el('div', 'display:flex;gap:8px;justify-content:flex-end;margin-top:6px;')
		const bc = el('button', 'position:relative;background:transparent;color:#eceff1;border:0;border-radius:6px;padding:6px 16px;min-height:var(--wf-size-s, 32px);font-size:13px;font-weight:500;text-transform:uppercase;letter-spacing:0.4px;cursor:pointer;font-family:inherit;', t('cancel'))
		const bo = el('button', 'position:relative;background:var(--wf-accent, #1976d2);color:#fff;border:0;border-radius:6px;padding:6px 20px;min-height:var(--wf-size-m, 36px);font-size:13px;font-weight:600;text-transform:uppercase;letter-spacing:0.4px;cursor:pointer;font-family:inherit;', t('pinEnter'))
		bc.className = bo.className = 'wf-hit'; bc.type = bo.type = 'button' // seen s 32 / m 36, touched 40 (the scale, family.css .wf-hit)
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
			if (!pad) pn.input.focus()
		}
		const key = ev => {
			if (ev.key === 'Escape') end(false)
			else if (pad && ev.target !== nm.input && (/^\d$/.test(ev.key) || ev.key === 'Backspace')) {
				// read-only PIN (kiosk): a physical keyboard types into it through here
				pn.input.value = ev.key === 'Backspace' ? pn.input.value.slice(0, -1) : pn.input.value + ev.key
				pn.input.dispatchEvent(new Event('input', { bubbles: true }))
				ev.preventDefault()
			} else if (ev.key === 'Enter') {
				// From the name Enter goes on to the PIN; from the PIN it signs in
				if (ev.target === nm.input && !pn.input.value) {
					// with the number pad the PIN is typed there next, so the keyboard of the name goes away
					if (pad) nm.input.blur()
					else pn.input.focus()
				} else submit()
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
		;[nm.wrap, pn.wrap, pad, msg, row].forEach(x => x && box.appendChild(x))
		back.appendChild(box)
		;(document.fullscreenElement || document.body).appendChild(back)
		// The first empty field gets the focus; on the kiosk the keyboard comes out through the helper (02-kiosk-keyboard.js)
		if (!nm.input.value) nm.input.focus()
		// with the number pad the PIN is typed there: nothing to focus
		else if (!pad) pn.input.focus()
	})
}
