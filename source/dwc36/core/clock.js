'use strict'

// The ONE timer of the new page: a tick every second that stops by itself.
//
//   clock.now                         reactive time (ms): a computed that reads it is drawn again every second ("12 s ago")
//   const off = every(5, fn)          fn() every 5 s while the page is awake; off() stops it
//   const off = onTick(fn)            fn(now) on every tick
//   timeNow()                         the time in ms (what ages and deadlines are measured with)
//   wake()                            the page became active / visible again: one tick at once, and the timer starts if someone listens
//
// It runs only while the page is awake (core/page-state.js) AND somebody listens; with nobody, or with the page out of sight, there
// is no timer at all. New code never calls setInterval (tests/layers.test.js): it subscribes here.

import Vue from 'vue'
import { awake } from './page-state.js'

export const TICK_MS = 1000
export const clock = Vue.observable({ now: Date.now() })

const listeners = []          // { fn, every (ticks), left }
let timer = null
let timers = { set: (fn, ms) => setInterval(fn, ms), clear: id => clearInterval(id), now: () => Date.now() }

// tests drive the time: { set, clear, now }
export function setTimers(t) {
	stop()
	timers = t || { set: (fn, ms) => setInterval(fn, ms), clear: id => clearInterval(id), now: () => Date.now() }
}

function stop() {
	if (timer !== null) {
		timers.clear(timer)
		timer = null
	}
}

function sync() {
	const wanted = listeners.length > 0 && awake()
	if (wanted && timer === null) timer = timers.set(tick, TICK_MS)
	if (!wanted) stop()
}

export function tick() {
	if (!awake()) return sync()
	clock.now = timers.now()
	listeners.slice().forEach(l => {
		l.left -= 1
		if (l.left > 0) return
		l.left = l.every
		try { l.fn(clock.now) } catch (e) { /* one listener must not stop the clock of the others */ }
	})
}

export function onTick(fn) {
	return every(1, fn)
}

export function every(seconds, fn) {
	const n = Math.max(1, Math.round(Number(seconds) || 1))
	const l = { fn, every: n, left: n }
	listeners.push(l)
	sync()
	return () => {
		const i = listeners.indexOf(l)
		if (i >= 0) listeners.splice(i, 1)
		sync()
	}
}

// the shell calls it when pageState.active / visible change
export function wake() {
	sync()
	if (awake()) clock.now = timers.now()
}

// the time every part of the data layer measures with (the same one the ticks carry; a test moves it)
export function timeNow() {
	return timers.now()
}

export function running() {
	return timer !== null
}
