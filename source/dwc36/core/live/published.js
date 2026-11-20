'use strict'

// What the service publishes in the object model (plugins.WorkshopService.data), for the new page. The ONLY reader of that data:
// a screen asks here by name and never copies the value into its own data() (it is reactive because it is read from DWC's store
// inside a computed).
//
//   get(key)                 one published key (undefined when the service has not published it)
//   serviceRunning()         the process of the service is alive (its pid in the model is above zero)
//   serviceVersion()         the installed version
//   processes()              { id: {...} } of servicesInternal, {} when not published
//   serviceProcess()         { pid, age_s, memory_mb, cpu_pct, threads } of the service itself, or null
//   guardWatches()           the list of what the protection guard watches (vision, rs485 ...), [] when not published
//   motion() / liveJob() / shutdownTimer()
//   powerOffOnFinish()       true | false | null (not known): the global of the board, never the published copy (it can be stale
//                            after a restart of the service; the board's macro reads the global)
//   lastCommandStamp()       changes with every call the service records: "something was written somewhere"
//   noteChanges(now)         called on every tick of the clock: remembers WHEN each key last changed
//   receivedAt(key)          that moment (ms), 0 when it never changed while the page was looking
//
// Never exposed to a screen a visitor can see: notifications.config.topic (it is a secret of the phone notices) and the raw list
// of the last commands. forVisitor(key) answers whether a key may be drawn without a session.

import Vue from 'vue'
import { globalVar, plugin, published } from '../dwc.js'

const PRIVATE = ['notifications', 'lastCommands', 'lastCode', 'lastCodeTime']
const seen = new Map()          // key -> the value last seen (compared by identity: DWC replaces a published value, it does not mutate it)
const stamps = Vue.observable({ at: {} })

export const get = key => published(key)

export function forVisitor(key) {
	return PRIVATE.indexOf(key) < 0
}

export function serviceRunning() {
	const p = plugin()
	return !!(p && p.pid > 0)
}

export function serviceVersion() {
	const p = plugin()
	return (p && p.version) || ''
}

const internal = () => published('servicesInternal') || null

export function processes() {
	const s = internal()
	return (s && s.processes) || {}
}

export function serviceProcess() {
	const s = internal()
	return (s && s.process) || null
}

export function guardWatches() {
	const g = published('guardStatus')
	return (g && Array.isArray(g.watches) && g.watches) || []
}

export const motion = () => published('motion') || null
export const liveJob = () => published('liveJob') || null
export const shutdownTimer = () => published('shutdownTimer') || null

export function powerOffOnFinish() {
	const v = globalVar('powerOffOnFinish')
	return typeof v === 'boolean' ? v : null
}

export function lastCommandStamp() {
	const list = published('lastCommands')
	const last = Array.isArray(list) && list.length ? list[list.length - 1] : null
	return last ? String(last.hour || '') + '|' + String(last.code || '') + '|' + list.length : ''
}

export function noteChanges(now, keys) {
	const p = plugin()
	const data = p && p.data
	if (!data) return
	const names = keys || (typeof data.keys === 'function' ? Array.from(data.keys()) : Object.keys(data))
	names.forEach(key => {
		const value = published(key)
		if (seen.has(key) && seen.get(key) !== value) Vue.set(stamps.at, key, now)
		seen.set(key, value)
	})
}

export function receivedAt(key) {
	return stamps.at[key] || 0
}
