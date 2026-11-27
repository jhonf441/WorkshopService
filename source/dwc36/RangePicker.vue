<template>
	<!-- the time range of a search, like the one of CloudWatch: quick ranges, "the last N units" and an absolute range from a day and time to another, chosen on a calendar of its own
	     (the native date and time fields opened with difficulty, painted their popup black and did not follow the theme) -->
	<v-menu v-model="open" :close-on-content-click="false" offset-y :min-width="months === 2 ? 660 : 340" :max-width="months === 2 ? 720 : 420">
		<template #activator="{ on, attrs }">
			<v-btn v-bind="attrs" small outlined class="range-picker-button" :aria-label="ts('range_label')" v-on="on">
				<v-icon small left>mdi-calendar-range</v-icon>{{ shown }}
			</v-btn>
		</template>
		<v-card class="pa-3 range-picker">
			<button v-if="clearable" type="button" class="range-chip range-all" :class="{ on: !value }" :aria-pressed="!value ? 'true' : 'false'" @click="pickAll">{{ ts('range_all') }}</button>
			<div class="range-title">{{ ts('range_quick') }}</div>
			<div class="range-row">
				<button v-for="q in quick" :key="q.amount + q.unit" type="button" class="range-chip" :class="{ on: isQuick(q) }" :aria-pressed="isQuick(q) ? 'true' : 'false'" @click="pickQuick(q)">
					{{ tsc(word('range_short_', q.unit), q.amount, { n: q.amount }) }}
				</button>
			</div>

			<div class="range-row range-tabs" role="group">
				<button v-for="t in TABS" :key="t" type="button" class="range-chip" :class="{ on: tab === t }" :aria-pressed="tab === t ? 'true' : 'false'" @click="tab = t">{{ ts(t === 'relative' ? 'range_relative' : 'range_absolute') }}</button>
			</div>

			<div v-if="tab === 'relative'">
				<div class="text-caption grey--text">{{ ts('range_relative_help') }}</div>
				<div class="range-row mt-2">
					<input v-model.number="amount" type="number" min="1" :max="maxAmount" step="1" class="field amount" :aria-label="ts('range_amount')" />
					<button v-for="u in units" :key="u" type="button" class="range-chip" :class="{ on: unit === u }" :aria-pressed="unit === u ? 'true' : 'false'" @click="unit = u">{{ ts(word('range_unit_', u)) }}</button>
				</div>
			</div>
			<div v-else class="range-abs">
				<div class="text-caption grey--text">{{ ts('range_absolute_help') }} {{ ts('range_type_hint', { format: dayFormat }) }}</div>
				<div class="range-fields">
					<div v-for="side in SIDES" :key="side" class="range-field" :data-side="side">
						<span class="text-body-2 range-word">{{ ts(side === 'from' ? 'range_from' : 'range_to') }}</span>
						<input v-model="text[side]" type="text" inputmode="numeric" autocomplete="off" class="field date" :class="{ bad: dayBad[side] }" :placeholder="dayFormat" :aria-label="ts(side === 'from' ? 'range_from' : 'range_to')" :aria-invalid="dayBad[side] ? 'true' : null" @input="typed(side)" />
						<input v-model="time[side]" type="text" inputmode="numeric" autocomplete="off" maxlength="5" class="field time" :class="{ bad: timeBad[side] }" placeholder="HH:MM" :aria-label="ts(side === 'from' ? 'range_from_time' : 'range_to_time')" :aria-invalid="timeBad[side] ? 'true' : null" />
					</div>
				</div>
				<div class="range-cals" :data-months="months">
					<div v-for="(m, k) in shownMonths" :key="m.year + '-' + m.month" class="range-cal" role="grid" :aria-label="monthTitle(m)">
						<div class="range-cal-bar">
							<button v-if="k === 0" type="button" class="range-nav" :aria-label="ts('range_prev_month')" @click="shift(-1)"><v-icon small>mdi-chevron-left</v-icon></button>
							<span v-else class="range-nav-gap"></span>
							<span class="range-cal-title" role="heading" aria-level="3">{{ monthTitle(m) }}</span>
							<button v-if="k === shownMonths.length - 1" type="button" class="range-nav" :aria-label="ts('range_next_month')" @click="shift(1)"><v-icon small>mdi-chevron-right</v-icon></button>
							<span v-else class="range-nav-gap"></span>
						</div>
						<div class="range-cal-head" aria-hidden="true"><span v-for="w in weekdays" :key="w">{{ w }}</span></div>
						<div class="range-cal-days">
							<template v-for="c in grid(m)">
								<button v-if="c.inMonth" :key="c.iso" type="button" class="range-day" :class="['kind-' + kind(c.iso), { today: c.iso === today }]" :data-iso="c.iso" :tabindex="c.iso === focusIso ? 0 : -1" :aria-label="dayLabel(c.iso)" :aria-pressed="kind(c.iso) === 'edge' ? 'true' : 'false'" :aria-current="c.iso === today ? 'date' : null" @click="choose(c.iso)" @keydown="onDayKey($event, c.iso)">{{ c.day }}</button>
								<span v-else :key="c.iso" class="range-day gap" aria-hidden="true"></span>
							</template>
						</div>
					</div>
				</div>
				<div class="text-caption grey--text">{{ picking.open ? ts('range_pick_end') : ts('range_pick_start') }}</div>
			</div>

			<div v-if="problem" class="text-caption error--text mt-2">{{ ts(word('range_err_', problem)) }}</div>
			<div v-else-if="preview" class="text-caption grey--text mt-2">{{ preview }}</div>

			<div class="range-foot">
				<button type="button" class="range-chip" @click="open = false">{{ ts('range_cancel') }}</button>
				<button type="button" class="range-chip on" :disabled="!!problem" @click="apply">{{ ts('range_apply') }}</button>
			</div>
		</v-card>
	</v-menu>
</template>

<script>
'use strict'

// <range-picker v-model="range" />   range: { type: 'relative', amount, unit } | { type: 'absolute', from, to } (range-picker.js);
// the page asks resolve(range, new Date()) for the two moments each time it searches, so "the last 3 hours" moves with the clock.
// The absolute tab is a calendar of its own: two months side by side when the window is wide (one in a narrow one), the first touch starts the range and the second ends it,
// the day and the time can also be written (DD/MM/YYYY in Spanish, YYYY/MM/DD in English; HH:MM), keys move between days.

import i18n from '../../i18n'
import { ts, tsc } from './shared-t.js'
import { QUICK, UNITS, MAX_AMOUNT, check, resolve, quickOf, relative, absolute, localText, isoOf, parseDay, addDays, addMonths, weekStart, monthGrid, dayText, parseDayText, parseTimeText, pickDay, dayKind } from './range-picker.js'

// the text of a family of keys (range_unit_hours, range_err_order...): the key is built here
const word = (family, id) => family + id
const SIDES = ['from', 'to']
const TABS = ['relative', 'absolute']
const WIDE = 760   // a window this wide shows two months

function lang() {
	try {
		return String(i18n.locale || 'en').slice(0, 2)
	} catch (e) {
		return 'en'
	}
}

export default {
	model: { prop: 'value', event: 'input' },
	props: {
		value: { type: Object, default: null }, // null: no limit in time (only with `clearable`)
		clearable: { type: Boolean, default: false }
	},
	data() {
		return {
			SIDES, TABS, quick: QUICK, units: UNITS, maxAmount: MAX_AMOUNT,
			open: false, tab: 'relative', amount: 1, unit: 'hours',
			picking: { from: '', to: '', open: false },   // the days chosen on the calendar (open: the first touch was made and the last is waited for)
			text: { from: '', to: '' },                    // what is written in the day fields
			time: { from: '00:00', to: '23:59' },
			dayBad: { from: false, to: false },
			view: { year: 0, month: 0 }, focusIso: '', months: 1, today: isoOf(new Date())
		}
	},
	computed: {
		draft() {
			return this.tab === 'relative'
				? relative(Number(this.amount), this.unit)
				: absolute(this.picking.from + 'T' + (parseTimeText(this.time.from) || ''), this.picking.to + 'T' + (parseTimeText(this.time.to) || ''))
		},
		timeBad() {
			return { from: !parseTimeText(this.time.from), to: !parseTimeText(this.time.to) }
		},
		problem() {
			if (this.tab === 'absolute') {
				if (this.dayBad.from || !parseDay(this.picking.from)) return 'from'
				if (this.dayBad.to || !parseDay(this.picking.to)) return 'to'
				if (this.timeBad.from || this.timeBad.to) return 'time'
			}
			const c = check(this.draft)
			return c.ok ? '' : c.why
		},
		preview() {
			const r = resolve(this.draft, new Date())
			return r ? this.text2(r.from) + '  ->  ' + this.text2(r.to) : ''
		},
		dayFormat() {
			return this.ts('range_format')
		},
		weekdays() {
			const start = weekStart(lang())
			const f = new Intl.DateTimeFormat(lang(), { weekday: 'narrow' })
			// 2026-11-01 is a Sunday
			return Array.from({ length: 7 }, (_, i) => f.format(new Date(2026, 10, 1 + ((i + start) % 7))))
		},
		shownMonths() {
			return Array.from({ length: this.months }, (_, i) => addMonths(this.view, i))
		},
		// what the button says: "Last 3 h" or the two moments
		shown() {
			const v = this.value
			if (!v) return ts('range_all')
			if (v.type === 'absolute') return String(v.from).replace('T', ' ') + '  ->  ' + String(v.to).replace('T', ' ')
			return ts('range_last', { span: tsc(word('range_short_', v.unit), v.amount, { n: v.amount }) })
		}
	},
	watch: {
		// the form takes the value each time the menu opens (a cancelled edit is forgotten)
		open(o) {
			if (o) this.load()
		}
	},
	created() {
		this.load()
	},
	methods: {
		ts,
		tsc,
		word,
		load() {
			const v = this.value || relative(1, 'days')
			const today = isoOf(new Date())
			this.today = today
			this.months = typeof window !== 'undefined' && window.innerWidth >= WIDE ? 2 : 1
			if (v.type === 'absolute') {
				this.tab = 'absolute'
				const a = String(v.from).split('T')
				const b = String(v.to).split('T')
				this.picking = { from: a[0], to: b[0], open: false }
				this.time = { from: a[1] || '00:00', to: b[1] || '23:59' }
			} else {
				this.tab = 'relative'
				this.amount = v.amount
				this.unit = v.unit
				this.picking = { from: today, to: today, open: false }
				this.time = { from: '00:00', to: '23:59' }
			}
			this.syncText()
			const first = parseDay(this.picking.from) || new Date()
			this.view = { year: first.getFullYear(), month: first.getMonth() }
			this.focusIso = this.picking.from
		},
		syncText() {
			const l = lang()
			this.text = { from: dayText(this.picking.from, l), to: dayText(this.picking.to, l) }
			this.dayBad = { from: false, to: false }
		},
		text2(d) {
			return localText(d).replace('T', ' ')
		},
		// the person writes a day: it counts when it is a real one, and the calendar goes to it
		typed(side) {
			const iso = parseDayText(this.text[side], lang())
			this.dayBad = Object.assign({}, this.dayBad, { [side]: !iso })
			if (!iso) return
			this.picking = Object.assign({}, this.picking, { [side]: iso, open: false })
			const d = parseDay(iso)
			this.view = { year: d.getFullYear(), month: d.getMonth() }
			this.focusIso = iso
		},
		grid(m) {
			return monthGrid(m, weekStart(lang()))
		},
		kind(iso) {
			return dayKind(iso, this.picking.from, this.picking.to)
		},
		monthTitle(m) {
			return new Intl.DateTimeFormat(lang(), { month: 'long', year: 'numeric' }).format(new Date(m.year, m.month, 1))
		},
		dayLabel(iso) {
			return new Intl.DateTimeFormat(lang(), { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' }).format(parseDay(iso))
		},
		shift(n) {
			this.view = addMonths(this.view, n)
		},
		choose(iso) {
			this.picking = pickDay(this.picking, iso)
			this.focusIso = iso
			this.syncText()
		},
		// the keys of the days: arrows move by a day or a week, Home / End to the start / end of the week, PageUp / PageDown by a month
		onDayKey(e, iso) {
			const step = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 }[e.key]
			let next = step ? addDays(iso, step) : ''
			if (e.key === 'PageUp' || e.key === 'PageDown') {
				const d = parseDay(iso)
				const t = new Date(d.getFullYear(), d.getMonth() + (e.key === 'PageUp' ? -1 : 1), d.getDate())
				next = isoOf(t)
			}
			if (!next) return
			e.preventDefault()
			this.focusIso = next
			const d = parseDay(next)
			const last = addMonths(this.view, this.months - 1)
			const ym = d.getFullYear() * 12 + d.getMonth()
			if (ym < this.view.year * 12 + this.view.month) this.view = { year: d.getFullYear(), month: d.getMonth() }
			else if (ym > last.year * 12 + last.month) this.view = addMonths({ year: d.getFullYear(), month: d.getMonth() }, 1 - this.months)
			this.$nextTick(() => {
				const el = this.$el && this.$el.ownerDocument.querySelector('.range-picker [data-iso="' + next + '"]')
				if (el) el.focus()
			})
		},
		pickAll() {
			this.$emit('input', null)
			this.open = false
		},
		isQuick(q) {
			const k = quickOf(this.value)
			return !!k && k.amount === q.amount && k.unit === q.unit
		},
		pickQuick(q) {
			this.$emit('input', relative(q.amount, q.unit))
			this.open = false
		},
		apply() {
			if (this.problem) return
			this.$emit('input', this.tab === 'absolute' ? absolute(this.picking.from + 'T' + parseTimeText(this.time.from), this.picking.to + 'T' + parseTimeText(this.time.to)) : this.draft)
			this.open = false
		}
	}
}
</script>

<style scoped>
.range-picker { font-size: 14px; }
/* the chips look the same as the JS picker (src/_shared/04-range-picker.js, the one the owner chose on 2026-11-23): 44 px, 6 px radius, 13 px text, filled when chosen */
.range-chip { position: relative; box-sizing: border-box; display: inline-flex; align-items: center; justify-content: center; min-height: var(--wf-size-s, 32px); padding: 0 12px; border-radius: 6px; cursor: pointer; font: inherit; font-size: 13px; border: 1px solid rgba(128, 128, 128, 0.45); background: transparent; color: inherit; }
.range-chip::after { content: ''; position: absolute; left: 50%; top: 50%; width: max(100%, var(--wf-hit, 40px)); height: max(100%, var(--wf-hit, 40px)); transform: translate(-50%, -50%); }
.range-chip:hover { background: rgba(128, 128, 128, 0.12); }
.range-chip.on { background: var(--v-primary-base, #1976d2); border-color: var(--v-primary-base, #1976d2); color: #fff; }
.range-chip:disabled { opacity: 0.5; cursor: default; }
.range-chip:focus-visible { outline: 2px solid var(--v-primary-base, #1976d2); outline-offset: 2px; }
.range-all { margin-bottom: 8px; }
.range-title { font-weight: 600; margin-bottom: 4px; }
.range-row { display: flex; flex-wrap: wrap; align-items: center; gap: var(--wf-gap-hit, 8px); }
.range-tabs { margin: 12px 0 8px; }
.range-foot { display: flex; justify-content: flex-end; gap: 8px; margin-top: 12px; }
.field { padding: 2px 8px; min-height: var(--wf-field-h, 40px); box-sizing: border-box; border: 1px solid rgba(128, 128, 128, 0.45); border-radius: 4px; color: inherit; background: transparent; }
.field:focus { outline: 2px solid var(--v-primary-base, #1976d2); }
.field.bad { border-color: var(--v-error-base, #d32f2f); }
.field.amount { width: 72px; }
.field.date { width: 118px; }
.field.time { width: 64px; }
.range-word { min-width: var(--wf-hit, 40px); }
.range-fields { display: flex; flex-wrap: wrap; gap: 8px 16px; margin: 8px 0; }
.range-field { display: flex; align-items: center; gap: 8px; }
.range-cals { display: grid; grid-template-columns: repeat(var(--range-months, 1), minmax(0, 1fr)); gap: 0 16px; }
.range-cals[data-months='2'] { --range-months: 2; }
.range-cal-bar { display: flex; align-items: center; justify-content: space-between; min-height: var(--wf-hit, 40px); }
.range-cal-title { flex: 1; min-width: 0; text-align: center; font-weight: 600; text-transform: capitalize; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.range-nav, .range-nav-gap { width: var(--wf-hit, 40px); height: var(--wf-hit, 40px); border: 0; border-radius: 50%; background: transparent; color: inherit; cursor: pointer; }
.range-nav:hover, .range-day:hover { background: rgba(128, 128, 128, 0.2); }
.range-cal-head, .range-cal-days { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); }
.range-cal-head span { text-align: center; font-size: 12px; opacity: 0.7; line-height: 24px; }
.range-day { min-height: var(--wf-hit, 40px); border: 0; background: transparent; color: inherit; font: inherit; cursor: pointer; }
.range-day.today { font-weight: 700; text-decoration: underline; }
.range-day.kind-mid { background: rgba(128, 128, 128, 0.25); }
.range-day.kind-edge { background: var(--v-primary-base, #1976d2); color: #fff; border-radius: 22px; }
.range-day:focus-visible, .range-nav:focus-visible { outline: 2px solid var(--v-primary-base, #1976d2); outline-offset: -2px; }
</style>
