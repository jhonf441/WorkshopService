'use strict'

// Client of the central API of the workshop plugins: the pages
// call named operations over the HTTP endpoint of the plugin
//   POST /machine/<WorkshopService | WorkshopRS485>/api  {op, args, confirm, origin}
// and never touch the sendCode action of DWC.
// Same logic for the JS plugins in src/_shared/01-api.js: keep them equal.
// Design: WorkshopService/docs/api/DESIGN.md; external use: docs/api/README.md.
//
//   import { api, askMotion, motionState } from './workshop-api.js'
//   const cfg = await api('lights.get')                       // result (object) or message (text)
//   await api('lights.zone', { index: 2, on: true })
//   await api('motors.disable', { axes: ['X'] }, { confirm: true })   // the page already showed its own dialog
//   if (await askMotion('WorkshopConfig', 'move')) { ...send the G-code... }
//
// Errors are thrown as ApiError {code, message, status, body}. A confirmation
// asked by the service (409 confirm_required) is shown here (level 3 / 4 dialog)
// and the call is repeated with confirm: true; cancelled -> ApiError "cancelled".

import i18n from '../../i18n'
import { idInstalled, pluginOf } from './workshop-ids.js'
import { serviceText } from './service-text.js'
import { adoptToken, askLoginNow, authHeaders, currentIdentity, ensureLogin, logoutWith, loginWith, onIdentity, recentGesture, refreshIdentity, signedOut, startKeepalive, workshopCan, workshopRole } from './workshop-auth.js'

export { currentIdentity, onIdentity, workshopCan, workshopRole }

const RETRIES = 6; // service restarting (502/503 from DWS without JSON)
const RETRY_MS = 2500;

export class ApiError extends Error {
	constructor(code, message, status, body) {
		super(message || code);
		this.code = code;
		this.status = status || 0;
		this.body = body || null;
	}
}

// English fallbacks of the texts of this client; the localized ones are
// registered by WorkshopService (plugins.WorkshopService.api.*)
const EN = {
	cancel: 'Cancel',
	continue: 'Continue',
	understood: 'I understand, continue',
	cancelled: 'Cancelled',
	outdated: 'WorkshopService has to be updated: this page uses its API.',
	unavailable: 'WorkshopService is not running.',
	confirmTitle: 'Confirm',
	checkbox: 'I understand the risk',
	pinTitle: 'Identify yourself',
	pinHint: 'Your name and PIN, given by the administrator.',
	pinName: 'Name',
	pinPin: 'PIN',
	pinEnter: 'Enter',
	pinMissing: 'Write your name and PIN.',
	pinWrong: 'Wrong name or PIN.',
	loginCancelled: 'Identification is needed to continue.',
	signInNeeded: 'This action needs you to sign in.',
	forbidden_role: 'Your role ({role}) does not allow this: {needed} is needed.',
	forbidden_mode: 'Your role cannot operate in {mode} mode: ask the administrator to enable it.',
	forbidden_mode_unknown: 'The mode of the machine is not known and your role only operates some modes.',
	forbidden_camera: 'Your role is not allowed to see the camera.',
	role_viewer: 'Visitor',
	role_operator: 'Operator',
	role_technician: 'Technician',
	role_admin: 'Administrator'
};

export function t(key, params) {
	const k = 'plugins.WorkshopService.api.' + key;
	try {
		if (i18n.te(k) || i18n.te(k, 'en')) return i18n.t(k, params);
	} catch (e) {
		/* DWC without i18n: English */
	}
	return (EN[key] || key).replace(/\{(\w+)\}/g, (m, n) => (params && params[n] !== undefined ? params[n] : m));
}

function lang() {
	try {
		return String(i18n.locale || 'en').slice(0, 2);
	} catch (e) {
		return 'en';
	}
}

// texts {es: {...}, en: {...}} sent by the service -> the ones of the DWC language
export function pick(texts) {
	if (!texts) return null;
	return texts[lang()] || texts.en || texts.es || null;
}

// DWC keeps its session inside its connector and sends it on every request
// (X-Session-Key): it is taken from there so the endpoint knows the session
// when DWC has a password (the endpoint refuses sessionless calls then).
(function captureSession() {
	if (window.__workshopSessionHook || typeof XMLHttpRequest === 'undefined') return;
	window.__workshopSessionHook = true;
	const orig = XMLHttpRequest.prototype.setRequestHeader;
	XMLHttpRequest.prototype.setRequestHeader = function (k, v) {
		if (String(k).toLowerCase() === 'x-session-key' && v) window.__workshopSession = String(v);
		return orig.apply(this, arguments);
	};
})();

function wait(ms) {
	return new Promise(r => setTimeout(r, ms));
}

function notifyRetry(opts, n) {
	if (typeof opts.onRetry !== 'function') return;
	try {
		opts.onRetry(n, RETRIES);
	} catch (e) {
		/* a page callback must not break the retry */
	}
}

function pageOrigin() {
	const sec = String((window.location && window.location.pathname) || '').split('/').filter(Boolean);
	return (sec[sec.length - 1] || 'page').replace(/[^A-Za-z0-9_.-]/g, '').slice(0, 40);
}

// true when the DSF plugin of the workshop (key of workshop-ids.js) is in the object model with a running process
function pluginRunning(plugin) {
	try {
		const p = pluginOf(document.getElementById('app').__vue__.$store.state.machine.model.plugins, plugin);
		return !!(p && p.pid > 0);
	} catch (e) {
		return false;
	}
}

// One HTTP call, no dialogs. Resolves the JSON body (ok true or false).
// Retries are silent (service restarting). opts.onRetry(n, total), when given, is called before each wait (n = 1..total) so a page can say
// "reconnecting"; it does not change the retries or their timing, and an error thrown by it is ignored.
export async function rawCall(op, args, opts = {}) {
	const plugin = opts.plugin || (op.startsWith('rs485.') ? 'rs485' : 'service');
	const url = '/machine/' + idInstalled(plugin) + '/api';
	const headers = Object.assign({ 'Content-Type': 'application/json' }, authHeaders()); // who (session token) and which browser
	if (window.__workshopSession) headers['X-Session-Key'] = window.__workshopSession;
	const body = JSON.stringify({ op, args: args || {}, confirm: !!opts.confirm, origin: opts.origin || pageOrigin(), lang: lang() });
	for (let attempt = 0; ; attempt++) {
		let r;
		try {
			r = await fetch(url, { method: 'POST', headers, body });
		} catch (e) {
			if (attempt < RETRIES) {
				notifyRetry(opts, attempt + 1);
				await wait(RETRY_MS);
				continue;
			}
			throw new ApiError('unavailable', t('unavailable'), 0);
		}
		let j = null;
		try {
			j = await r.json();
		} catch (e) {
			j = null;
		}
		if (j && typeof j === 'object' && 'ok' in j) return Object.assign(j, { status: r.status });
		// not our JSON: DWS answered by itself
		// DWS has no such endpoint. It is an OUTDATED service only when the plugin is installed and running (a version without this
		// API); a plugin that is missing or stopped is just not available (QA 3.7 #02)
		if (r.status === 404 && pluginRunning(plugin)) throw new ApiError('service_outdated', t('outdated'), 404);
		if ([500, 502, 503].includes(r.status) && attempt < RETRIES) {
			notifyRetry(opts, attempt + 1);
			await wait(RETRY_MS);
			continue;
		}
		throw new ApiError('unavailable', t('unavailable') + ' (HTTP ' + r.status + ')', r.status);
	}
}

// A 403 reaches the pages as a clear message of their language (key plugins.WorkshopService.api.forbidden_*), not as a raw error.
function forbiddenError(e, j) {
	const reason = ['mode', 'mode_unknown', 'camera'].includes(e.reason) ? e.reason : 'role';
	const key = 'forbidden_' + reason;
	const params = { role: t('role_' + e.role), needed: t('role_' + e.needed_role), mode: String(e.mode || '').toUpperCase() };
	const err = new ApiError('forbidden', e.role ? t(key, params) : e.message, 403, j);
	err.key = 'plugins.WorkshopService.api.' + key;
	err.params = params;
	err.reason = e.reason || 'role';
	return err;
}

// Calls an operation. Resolves result (if any) or message; throws ApiError. A 401 login_required asks for name and PIN
// (one floating dialog) and repeats the call.
export async function api(op, args, opts = {}) {
	let confirm = !!opts.confirm;
	const byPerson = recentGesture() // started by a touch: if it is refused, the person is told (toast of the control bar)
	const fail = err => {
		const toast = window.__workshop && window.__workshop.toast
		if (byPerson && !opts.quiet && typeof toast === 'function') toast(err.message)
		return err
	}
	for (let round = 0; round < 3; round++) {
		const sentToken = authHeaders()['X-Workshop-Token'] || '' // the session this call goes out with
		const j = await rawCall(op, args, Object.assign({}, opts, { confirm }));
		if (j.ok) return j.result !== null && j.result !== undefined ? j.result : j.message;
		const e = j.error || {};
		// No session: a 401 or a 403 of the visitor role both mean "sign in first"
		if ((e.code === 'login_required' || (e.code === 'forbidden' && signedOut())) && !opts.noLogin) {
			// the person signed in while this call was in flight (another plugin's dialog): repeat it with the new session, do not ask twice
			const now = authHeaders()['X-Workshop-Token'] || ''
			if ((now && now !== sentToken) || await ensureLogin(rawCall, t)) continue;
			throw fail(new ApiError('login_required', t('signInNeeded'), 401, j));
		}
		if (e.code === 'forbidden') throw fail(forbiddenError(e, j));
		if (e.code === 'confirm_required' && !confirm && !opts.noDialog) {
			const ok = await confirmDialog(e.confirm || {}, e.message);
			if (!ok) throw new ApiError('cancelled', t('cancelled'), 409, j);
			confirm = true;
			continue;
		}
		const msg = e.message || e.code; // already in the language this page asked for
		throw new ApiError(e.code || 'error', msg, j.status, j);
	}
	throw new ApiError('cancelled', t('cancelled'), 409);
}

// Same as api() but resolves the text of the answer (JSON text or message);
// errors resolve as "Error: <message>".
export async function apiText(op, args, opts = {}) {
	try {
		const r = await api(op, args, opts);
		return typeof r === 'string' ? r : JSON.stringify(r);
	} catch (e) {
		if (e && e.code === 'cancelled') throw e;
		return 'Error: ' + (e && e.message ? e.message : e);
	}
}

// ---- single owner of the movement (WorkshopService motion_owner.py) ----

// data.motion published by the service (from the DWC store, no request)
export function motionState() {
	try {
		const pl = document.getElementById('app').__vue__.$store.state.machine.model.plugins;
		const p = pl && (typeof pl.get === 'function' ? pl.get(idInstalled('service')) : pl[idInstalled('service')]);
		return (p && p.data && p.data.motion) || null;
	} catch (e) {
		return null;
	}
}

// The reason to show for a state, in the language of DWC (published data: {key, params}; an API answer: text)
export function motionReason(m) {
	if (!m) return '';
	return serviceText(m.reason);
}

// Asks the owner before moving. Resolves true (allowed, after a confirmation
// if needed) or false (the person cancelled); throws ApiError motion_denied
// with the reason when it is not allowed. Without the service it resolves true
// (the page keeps its own checks).
export async function askMotion(origin, action = 'move', text = '') {
	let j;
	try {
		j = await api('motion.ask', { origin, action, text }, { noDialog: true });
	} catch (e) {
		if (e.code === 'service_outdated' || e.code === 'unavailable') return true;
		throw e;
	}
	if (j.decision === 'allow') return true;
	const reason = serviceText(j.reason);
	if (j.decision === 'confirm') {
		const ok = await confirmDialog({ level: 3, reason: j.reason }, reason);
		if (!ok) return false;
		const k = await api('motion.ask', { origin, action, text }, { confirm: true, noDialog: true });
		return k.decision === 'allow';
	}
	throw new ApiError('motion_denied', reason, 409, j);
}

// Reservation for a long sequence: { token, renew(), release() } or throws.
export async function reserveMotion(origin, action = 'sequence', text = '', seconds = 60) {
	const r = await api('motion.reserve', { origin, action, text, seconds });
	if (r.decision !== 'allow') throw new ApiError('motion_denied', serviceText(r.reason), 409, r);
	const token = r.token;
	return {
		token,
		renew: (s = seconds) => api('motion.renew', { token, seconds: s }),
		release: () => api('motion.release', { token }).catch(() => {})
	};
}

// ---- confirmation dialog (levels 3 and 4 of DESIGN.md, same look as the JS plugins) ----

export function confirmDialog(c, fallbackText) {
	const texts = pick(c.texts) || {};
	const level = c.level >= 4 ? 4 : 3;
	const reason = serviceText(c.reason);
	const title = texts.title || t('confirmTitle');
	const text = [texts.text, reason].filter(Boolean).join(' ') || fallbackText || '';
	return new Promise(resolve => {
		const back = document.createElement('div');
		back.setAttribute('data-tp-panel', '1');
		back.style.cssText = 'position:fixed;inset:0;z-index:2147483647;background:rgba(0,0,0,0.55);display:flex;align-items:center;justify-content:center;padding:16px;';
		const box = document.createElement('div');
		box.setAttribute('role', 'alertdialog');
		const color = level === 4 ? '#ef5350' : '#ff9800';
		// same look as the dialogs of DWC (the plugin install wizard): flat dark card, 20 px title, text buttons
		box.style.cssText = 'background:#1e1e1e;color:rgba(255,255,255,0.87);border-radius:4px;max-width:500px;width:100%;padding:16px 24px;font-size:14px;line-height:1.5;' +
			'box-shadow:0 11px 15px -7px rgba(0,0,0,0.2),0 24px 38px 3px rgba(0,0,0,0.14),0 9px 46px 8px rgba(0,0,0,0.12);';
		const h = document.createElement('div');
		h.style.cssText = 'font-size:20px;font-weight:500;line-height:1.6;margin-bottom:8px;color:#fff;';
		h.textContent = title;
		const p = document.createElement('div');
		p.textContent = text;
		box.appendChild(h);
		box.appendChild(p);
		let check = null;
		if (level === 4) {
			const lab = document.createElement('label');
			lab.style.cssText = 'display:flex;gap:8px;align-items:center;margin-top:10px;cursor:pointer;';
			check = document.createElement('input');
			check.type = 'checkbox';
			lab.appendChild(check);
			lab.appendChild(document.createTextNode(t('checkbox')));
			box.appendChild(lab);
		}
		const row = document.createElement('div');
		row.style.cssText = 'display:flex;gap:8px;justify-content:flex-end;margin-top:16px;';
		const bc = document.createElement('button');
		bc.type = 'button';
		bc.textContent = t('cancel');
		bc.style.cssText = 'background:transparent;color:#2196f3;border:0;border-radius:4px;padding:6px 12px;min-height:36px;font-size:14px;font-weight:500;cursor:pointer;';
		const bo = document.createElement('button');
		bo.type = 'button';
		bo.textContent = level === 4 ? t('continue') : t('understood');
		bo.style.cssText = 'background:transparent;color:' + color + ';border:0;border-radius:4px;padding:6px 12px;min-height:36px;font-size:14px;font-weight:600;cursor:pointer;';
		if (check) {
			bo.disabled = true;
			bo.style.opacity = '0.5';
			check.addEventListener('change', () => {
				bo.disabled = !check.checked;
				bo.style.opacity = check.checked ? '1' : '0.5';
			});
		}
		const end = v => {
			document.removeEventListener('keydown', key, true);
			if (back.parentNode) back.parentNode.removeChild(back);
			resolve(v);
		};
		const key = ev => {
			if (ev.key === 'Escape') end(false);
		};
		bc.addEventListener('click', () => end(false));
		bo.addEventListener('click', () => end(true));
		back.addEventListener('click', ev => {
			if (ev.target === back) end(false);
		});
		document.addEventListener('keydown', key, true);
		row.appendChild(bc);
		row.appendChild(bo);
		box.appendChild(row);
		back.appendChild(box);
		(document.fullscreenElement || document.body).appendChild(back);
	});
}

// ---- identity (workshop-auth.js keeps the session; the roles are applied by the service) ----

// Who is using this browser: { configured, role, user, login_required, table, ... } (also in currentIdentity())
export function whoami() {
	return refreshIdentity(rawCall)
}

export async function login(name, pin) {
	const j = await loginWith(rawCall, name, pin)
	if (!j.ok) throw new ApiError((j.error || {}).code || 'error', (j.error || {}).message, j.status, j)
	return currentIdentity()
}

export function logout() {
	return logoutWith(rawCall)
}

// The person pressed "log in": asks for name and PIN now. Resolves true when logged in.
export function askLogin() {
	return askLoginNow(rawCall, t)
}

export function adoptSession(token) {
	return adoptToken(rawCall, token)
}

export function changePin(oldPin, newPin) {
	return api('auth.change_pin', { old_pin: oldPin, new_pin: newPin })
}

if (typeof window !== 'undefined' && !(window.__workshopAuth && window.__workshopAuth.booted)) {
	window.__workshopAuth = Object.assign(window.__workshopAuth || { identity: null, token: '', listeners: [], flight: null, quietUntil: 0, device: '', keepalive: 0 }, { booted: true })
	startKeepalive(rawCall)
	refreshIdentity(rawCall).catch(() => {}) // so workshopCan() knows the role from the start
}
