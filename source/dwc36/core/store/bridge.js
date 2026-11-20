'use strict'

// The G-code bridge as the page sees it. The bridge is a separate service of the Pi that talks to the page through three files (its state, its
// settings and an order file the page writes), plus two operations of the service for its systemd unit.
//
//   bridge.e / bridge.status    the state file as read ('loading' | 'ready' | 'missing' (not installed) | 'unreadable'), readFails, readCause, received (ms)
//   bridge.unit                 { installed, active, enabled, can_control } of the unit of this Pi, null until read
//   bridge.act                  the last order: { key, state: 'idle' | 'sending' | 'done' | 'error', result, text }
//   watchBridge()               starts reading every 3 s (slower while the file is missing, never while the page rests); returns the stop function
//   readState() / readUnit()
//   sendAction(data, key)       writes the order file and waits for the bridge to answer with the same seq (8 s)
//   loadConfig() / saveConfig(apply)    the settings file, read whole and written whole (apply(current) changes what it must)

import Vue from 'vue'
import { call } from '../api/call.js'
import { can } from './session.js'
import { readJson, writeJson } from '../api/files.js'
import { every, timeNow } from '../clock.js'
import { READ_FAILS, READ_MS, ACTION_WAIT_MS, UNIT_EVERY, readDelayMs } from '../../bridge-view.js'
import { STATE_FILE, CONFIG_FILE, ACTION_FILE } from '../../bridge-io.js'

export const bridge = Vue.observable({ e: null, status: 'loading', readFails: 0, readCause: '', received: 0, missing: 0, unit: null, act: { key: '', state: 'idle', result: null, text: '' } })

let lastSeq = null
let waiting = null
let turn = 0
let skip = 0

// a state file the service wrote: seq moves while the bridge runs, so a file whose seq does not move is a file that is getting old
export async function readState() {
	const r = await readJson(STATE_FILE)
	if (r.status === 404) {
		bridge.missing = Math.min(bridge.missing + 1, 6)
		bridge.status = 'missing'
		return
	}
	bridge.missing = 0
	if (r.status !== 200) {
		bridge.readFails = Math.min(bridge.readFails + 1, 99)
		bridge.readCause = r.error
		if (!bridge.e && bridge.readFails >= READ_FAILS) bridge.status = 'unreadable'
		return
	}
	bridge.readFails = 0
	bridge.readCause = ''
	if (r.data.seq !== lastSeq || !bridge.received) {
		lastSeq = r.data.seq
		bridge.received = timeNow()
	}
	bridge.e = r.data
	bridge.status = 'ready'
	checkAction()
}

function checkAction() {
	if (!waiting) return
	const r = bridge.e && bridge.e.action
	if (r && r.seq === waiting.seq) {
		bridge.act = { key: waiting.key, state: r.ok ? 'done' : 'error', result: r, text: '' }
		waiting = null
	} else if (timeNow() > waiting.until) {
		bridge.act = { key: waiting.key, state: 'error', result: null, text: 'no_answer' }
		waiting = null
	}
}

export async function sendAction(data, key) {
	const seq = Date.now() % 1000000000
	bridge.act = { key, state: 'sending', result: null, text: '' }
	try {
		await writeJson(ACTION_FILE, Object.assign({ seq }, data))
		waiting = { seq, key, until: timeNow() + ACTION_WAIT_MS }
	} catch (e) {
		bridge.act = { key, state: 'error', result: null, text: 'not_sent:' + ((e && e.message) || '') }
	}
}

export async function readUnit() {
	if (can('bridge.service').state !== 'ok') return
	try {
		const r = await call('bridge.service', {}, { quiet: true })
		if (r.data && typeof r.data.installed === 'boolean') bridge.unit = r.data
	} catch (e) { /* the unit stays as it was: the card says nothing about what it could not read */ }
}

// reads while somebody looks: every READ_MS seconds, and farther apart while the file is missing; the unit once every UNIT_EVERY turns
export function watchBridge() {
	turn = 0
	skip = 0
	readUnit()
	readState()
	return every(Math.round(READ_MS / 1000), () => {
		if (skip > 0) { skip -= 1; return }
		skip = Math.max(0, Math.round(readDelayMs(bridge.missing) / READ_MS) - 1)
		turn += 1
		if (turn % UNIT_EVERY === 0) readUnit()
		readState()
	})
}

export async function loadConfig() {
	return (await readJson(CONFIG_FILE)).data || {}
}

export async function saveConfig(apply) {
	const current = (await readJson(CONFIG_FILE)).data || {}
	await writeJson(CONFIG_FILE, apply(current))
}
