'use strict'

// Short history of the process metrics (CPU and heartbeat interval of each process, CPU and memory
// of the service). Kept at module level so it survives leaving and coming back to the page; it is
// only fed while the page is open, one sample every few seconds, and it stays in memory (nothing
// is stored on the Pi and nothing is asked of the board).
import Vue from 'vue'

export const MAX_SAMPLES = 120 // about 10 minutes at one sample every 5 s

export const hist = Vue.observable({ proc: {}, service: { cpu: [], mem: [] }, n: 0 })

function meter(arr, v) {
	if (v == null || isNaN(v)) return
	arr.push(Number(v))
	if (arr.length > MAX_SAMPLES) arr.splice(0, arr.length - MAX_SAMPLES)
}

// procesos: [{id, cpu_pct, interval_avg}], servicio: {cpu_pct, memory_mb} or null
export function sample(processes, service) {
	;(processes || []).forEach(p => {
		let h = hist.proc[p.id]
		if (!h) {
			h = { cpu: [], interval: [] }
			Vue.set(hist.proc, p.id, h)
		}
		meter(h.cpu, p.cpu_pct)
		meter(h.interval, p.interval_avg)
	})
	if (service) {
		meter(hist.service.cpu, service.cpu_pct)
		meter(hist.service.mem, service.memory_mb)
	}
	hist.n++
}
