'use strict'

// Reads the lines of the black box (one every 5 s, dsf/box_black.py) of the last unclean shutdown into numbers the card can draw.
// Pure: no DOM, no i18n (the card writes the words). tests/black-box.test.js (TallerPlugins) runs it.
//
// line:  2026-10-16 00:10:17 up=53171 load=0.40/0.45/0.77 cpu=6 svc=1 ram=23 temp=49.7 dsf=0.3s ipc=2 machine=idle lock=bridge:804s slow=status_light:729s,motores:838s
// other lines (the "top -" snapshots the box also keeps) are counted but not drawn.

const line = /^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) up=(\d+) load=([\d.]+)\/([\d.]+)\/([\d.]+) cpu=(\d+) svc=(\d+) ram=(\d+) temp=([\d.]+) dsf=([\d.]+)s ipc=(\d+) machine=(\S+)(?: lock=(\S+))?(?: slow=(\S+))?/

// seconds a lock or a slow task has to last, in the last line, to say the service was stuck
export const STUCK_S = 60

// "bridge:804s,motors:838s" -> [{ nombre, s }]
export function pairs(text) {
	if (!text || text === '-') return []
	return String(text).split(',').map(p => {
		const i = p.lastIndexOf(':')
		return i > 0 ? { name: p.slice(0, i), s: parseFloat(p.slice(i + 1)) || 0 } : null
	}).filter(Boolean)
}

function span(values) {
	if (!values.length) return { min: null, max: null, last: null }
	return { min: Math.min.apply(null, values), max: Math.max.apply(null, values), last: values[values.length - 1] }
}

// What the last minutes say about the cause, from numbers only (a guess the card words as such):
//   calor      temperature reached 80 C            carga     CPU at 90 % or more in the last samples
//   memoria    memory at 90 % or more              trabajo   (extra, not a cause) the machine was running a job
//   trabado    (new 2026-10-18) the last line shows a lock held or a task slow for TRABADO_S or more: the service was stuck before the cut
//   tranquilo  everything calm up to the last line: points to a power cut or an unplugged cable, not to an overload
//   without_data  fewer than two samples
export function verdict(r) {
	if (r.samples.length < 2) return 'without_data'
	if (r.temp.max >= 80) return 'heat'
	const last = r.samples.slice(-3)
	if (last.every(m => m.cpu >= 90)) return 'load'
	if (r.ram.max >= 90) return 'memory'
	const u = r.last
	if (u && u.locks.concat(u.slow).some(x => x.s >= STUCK_S)) return 'stuck'
	if (r.cpu.max < 60 && r.ram.max < 85 && r.temp.max < 75) return 'calm'
	return 'mixed'
}

export function analyzeBox(lines) {
	const samples = []
	let other = 0
	;(lines || []).forEach(l => {
		const m = line.exec(String(l))
		if (!m) {
			if (String(l).trim()) other++
			return
		}
		samples.push({
			when: m[1], up: +m[2], load: [+m[3], +m[4], +m[5]], cpu: +m[6], svc: +m[7], ram: +m[8], temp: +m[9], dsf: +m[10], ipc: +m[11],
			machine: m[12], locks: pairs(m[13]), slow: pairs(m[14])
		})
	})
	const col = k => samples.map(m => m[k])
	const r = {
		samples: samples,
		other: other,
		cpu: span(col('cpu')),
		ram: span(col('ram')),
		temp: span(col('temp')),
		load1: span(samples.map(m => m.load[0])),
		dsf: span(col('dsf')),
		last: samples.length ? samples[samples.length - 1] : null,
		first: samples.length ? samples[0] : null
	}
	r.inJob = !!(r.last && /^(processing|paused|pausing|resuming|simulating|busy)$/.test(r.last.machine))
	r.verdict = verdict(r)
	return r
}

// "2026-10-16 00:10:17" (local time of the Pi) -> Date, or null
export function dateOf(text) {
	const m = /^(\d{4})-(\d\d)-(\d\d) (\d\d):(\d\d):(\d\d)/.exec(String(text || ''))
	return m ? new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6]) : null
}
