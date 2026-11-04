'use strict'

// The camera relay (port 8090) is a process of THIS service (dsf/camera_relay.py), so its control lives here: the card of the service page
// (RelayCard.vue, in the row of the process) and the optional tile of the control bar. Camera, Vision and Workbench only use the relay; none
// of them owns it, and the control stays when any of them is not installed.
//
// One model for the whole page: the card and the tile read the same state and call the same operations (camera.status, camera.start,
// camera.stop of the central API; both are technician operations, the server decides). The state comes from the service, never from probing
// :8090. Nothing is read while nobody watches (watch(true) / watch(false) count the watchers: the card on screen, the tile on screen).
// The file has no DWC import except the API client, so it is the same file in the 3.6 and the 3.7 trees.
//
// The bar tile is handed to the control bar through window.__workshop.barTiles (the contract of src/_shared/10-registry-tiles.js in
// TallerPlugins): the bar names no plugin, it draws what is registered. It is OFF by default and the person turns it on in the gear of the bar.

import { apiText, currentIdentity, onIdentity, workshopCan, t } from './workshop-api.js'
import { signedOut } from './workshop-auth.js'

const POLL_MS = 15000; // how often camera.status is read while someone watches
const TILE_ID = 'service-camera-relay';
const COLORS = { running: '#a5d6a7', stopped: '#ef9a9a', nocam: '#ffb74d', reading: '#b0bec5', unknown: '#b0bec5' }; // green, red, amber, grey
const TILE_ICON = '<path d="M17 10.5V7c0-.55-.45-1-1-1H4c-.55 0-1 .45-1 1v10c0 .55.45 1 1 1h12c.55 0 1-.45 1-1v-3.5l4 4v-11l-4 4z"/>'; // a video camera

// ---- pure ----

// The answer of camera.status (text, maybe with a line before the JSON) -> its object, or {error}.
export function parse(text) {
	const s = String(text || '');
	const k = s.indexOf('{');
	if (k < 0) return { error: s.trim() };
	try {
		return JSON.parse(s.slice(k));
	} catch (e) {
		return { error: s.trim() };
	}
}

// 'reading' (not read yet) | 'running' | 'stopped' | 'nocam' (no camera address yet: nothing to start) | 'unknown' (the service did not answer)
export function stateOf(status) {
	if (!status) return 'reading';
	if (status.error) return 'unknown';
	if (status.running) return 'running';
	return status.configured === false ? 'nocam' : 'stopped';
}

// What each button can do now: Stop only while it runs, Start only while it is stopped; while it is being read neither, and when the service
// did not answer both are offered (the answer of the action says what went wrong).
export function canOf(state) {
	return { stop: state === 'running' || state === 'unknown', start: state === 'stopped' || state === 'unknown' };
}

// The line that tells the state, and the short one of the Hidden style of the bar. tr = the translator (key, params).
export function lineOf(state, status, tr) {
	const n = (status && status.clients) || 0;
	if (state === 'running') return { text: tr('relay_state_running', { n }), summary: tr('relay_summary_running', { n }) };
	const key = { stopped: 'stopped', nocam: 'no_camera', reading: 'reading' }[state] || 'unknown';
	return { text: tr('relay_state_' + key), summary: tr('relay_summary_' + key) };
}

// ---- the one model of the page ----

// No session: no token, or a token the service no longer accepts (it forgets them when it restarts). Same rule as the header of the pages.
function noSession() {
	const id = currentIdentity();
	return signedOut() || !!(id && id.configured && id.login_required);
}

const M = { status: null, msg: '', armed: null, subs: [], watchers: 0, timer: null, tile: null };

function emit() {
	M.subs.slice().forEach((fn) => {
		try {
			fn();
		} catch (e) {
			console.error('[WorkshopService] relay listener:', e);
		}
	});
	notifyBar();
}

// The bar (if it is loaded) draws again: it listens to window.__workshop.listeners
function notifyBar() {
	const w = window.__workshop;
	if (!w || !Array.isArray(w.listeners)) return;
	w.listeners.slice().forEach((fn) => {
		try {
			fn();
		} catch (e) {
			console.error('[WorkshopService] bar listener:', e);
		}
	});
}

export function subscribe(fn) {
	M.subs.push(fn);
	return () => {
		M.subs = M.subs.filter((f) => f !== fn);
	};
}

// What the card and the tile paint now
export function view() {
	const state = stateOf(M.status);
	const line = lineOf(state, M.status, t);
	// no session: the camera cannot be read nor commanded; say it (a state, not a failure) and offer nothing
	const out = noSession();
	return { state, can: out ? { stop: false, start: false } : canOf(state), text: out ? t('signedOut') : line.text, summary: out ? t('signedOut') : line.summary, color: out ? COLORS.reading : COLORS[state], armed: !!M.armed, msg: M.msg, allowed: workshopCan('camera.stop') };
}

// the person signs in or out: repaint, and read the camera now if somebody is looking (not 15 s later)
onIdentity(() => {
	emit();
	if (M.watchers > 0) load();
});

export function load() {
	// without a session the service refuses and the client would ask for the PIN at every read: do not read
	if (noSession()) {
		M.status = null;
		emit();
		return Promise.resolve();
	}
	return apiText('camera.status')
		.then(parse)
		.catch((e) => ({ error: String(e && e.message ? e.message : e) }))
		.then((s) => {
			M.status = s;
			emit();
		});
}

// camera.start / camera.stop act for EVERYONE. The state is read again 1.5 s and 4 s later (the loop of the service takes a second to open
// or close the port, so the first read can still see the old state).
function act(action) {
	M.msg = t(action === 'stop' ? 'relay_stopping' : 'relay_starting');
	emit();
	return apiText(action === 'stop' ? 'camera.stop' : 'camera.start')
		.then((txt) => {
			M.msg = String(txt || '').trim() || t(action === 'stop' ? 'relay_stopped' : 'relay_started');
		})
		.catch((e) => {
			M.msg = String(e && e.message ? e.message : e);
		})
		.then(() => {
			emit();
			[1500, 4000].forEach((ms) => setTimeout(load, ms));
		});
}

// "Stop relay" needs two taps within 4 s because it cuts the camera for everyone: the first arms it, the second stops.
export function stopTap() {
	if (!M.armed) {
		M.armed = setTimeout(() => {
			M.armed = null;
			emit();
		}, 4000);
		emit();
		return;
	}
	clearTimeout(M.armed);
	M.armed = null;
	act('stop');
}

// "Start relay": a pending "Stop relay" is let go and the relay starts (it harms nobody, so one tap).
export function startTap() {
	if (M.armed) clearTimeout(M.armed);
	M.armed = null;
	act('start');
}

// Someone is looking (true) or stopped looking (false): read now and every POLL_MS, or stop reading. Counted, so the card and the tile can both watch.
export function watch(on) {
	M.watchers = Math.max(0, M.watchers + (on ? 1 : -1));
	if (M.watchers === 1 && on) {
		load();
		M.timer = setInterval(load, POLL_MS);
	} else if (M.watchers === 0) {
		clearInterval(M.timer);
		M.timer = null;
	}
}

// ---- the optional tile of the control bar ----

export function barTile() {
	let watching = false;
	return {
		title: t('relay_tile_title'),
		icon: TILE_ICON,
		order: 10,
		help: t('relay_help'),
		plugin: 'service',
		defaultShown: false,
		visible: () => workshopCan('camera.stop'),
		state: () => {
			const v = view();
			return {
				status: v.text,
				color: v.color,
				summary: v.summary,
				railColor: v.state === 'stopped' ? '#c62828' : '#37474f', // a stopped relay is what the person has to notice
				message: v.msg,
				buttons: [
					{ id: 'stop', label: t(v.armed ? 'relay_stop_confirm' : 'relay_stop'), tone: v.armed ? 'stop' : 'warning', disabled: !v.can.stop, onTap: stopTap },
					{ id: 'start', label: t('relay_start'), tone: 'primary', disabled: !v.can.start, onTap: startTap }
				]
			};
		},
		// the bar says true while the tile is on screen and false when it is not; it can say true twice
		watch: (on) => {
			if (on === watching) return;
			watching = !!on;
			watch(watching);
		}
	};
}

// Offer the tile to the control bar. Safe to call twice; returns the function that takes it back (when the service page is unloaded).
export function registerBarTile() {
	const w = (window.__workshop = window.__workshop || {});
	if (!w.listeners) w.listeners = [];
	w.barTiles = w.barTiles || {};
	const api = barTile();
	M.tile = api;
	w.barTiles[TILE_ID] = api;
	notifyBar();
	return () => {
		if (w.barTiles && w.barTiles[TILE_ID] === api) {
			api.watch(false);
			delete w.barTiles[TILE_ID];
			notifyBar();
		}
	};
}
