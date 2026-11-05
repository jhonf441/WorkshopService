<template>
	<!-- the time range of a search, like the one of CloudWatch: quick ranges, "the last N units" and an absolute range from a date and time to another -->
	<v-menu v-model="open" :close-on-content-click="false" offset-y min-width="320" max-width="420">
		<template #activator="{ on, attrs }">
			<v-btn v-bind="attrs" small outlined class="range-picker-button" :aria-label="ts('range_label')" v-on="on">
				<v-icon small left>mdi-calendar-range</v-icon>{{ shown }}
			</v-btn>
		</template>
		<v-card class="pa-3 range-picker">
			<v-btn v-if="clearable" small :outlined="!!value" :color="value ? undefined : 'primary'" class="mb-2" @click="pickAll">{{ ts('range_all') }}</v-btn>
			<div class="text-subtitle-2">{{ ts('range_quick') }}</div>
			<div class="d-flex flex-wrap mt-1" style="gap:6px">
				<v-btn v-for="q in quick" :key="q.amount + q.unit" x-small :outlined="!isQuick(q)" :color="isQuick(q) ? 'primary' : undefined" @click="pickQuick(q)">
					{{ ts(word('range_short_', q.unit), { n: q.amount }) }}
				</v-btn>
			</div>

			<v-btn-toggle v-model="tab" mandatory dense color="primary" class="mt-3">
				<v-btn small value="relative">{{ ts('range_relative') }}</v-btn>
				<v-btn small value="absolute">{{ ts('range_absolute') }}</v-btn>
			</v-btn-toggle>

			<div v-if="tab === 'relative'" class="mt-3">
				<div class="text-caption grey--text">{{ ts('range_relative_help') }}</div>
				<div class="d-flex align-center flex-wrap mt-2" style="gap:8px">
					<input v-model.number="amount" type="number" min="1" :max="maxAmount" step="1" class="field amount" :aria-label="ts('range_amount')" />
					<v-btn v-for="u in units" :key="u" x-small :outlined="unit !== u" :color="unit === u ? 'primary' : undefined" @click="unit = u">{{ ts(word('range_unit_', u)) }}</v-btn>
				</div>
			</div>
			<div v-else class="mt-3">
				<div class="text-caption grey--text">{{ ts('range_absolute_help') }}</div>
				<div class="d-flex align-center flex-wrap mt-2" style="gap:8px">
					<span class="text-body-2 range-word">{{ ts('range_from') }}</span>
					<input v-model="fromDay" type="date" class="field date" :aria-label="ts('range_from')" />
					<input v-model="fromTime" type="time" class="field time" :aria-label="ts('range_from_time')" />
				</div>
				<div class="d-flex align-center flex-wrap mt-2" style="gap:8px">
					<span class="text-body-2 range-word">{{ ts('range_to') }}</span>
					<input v-model="toDay" type="date" class="field date" :aria-label="ts('range_to')" />
					<input v-model="toTime" type="time" class="field time" :aria-label="ts('range_to_time')" />
				</div>
			</div>

			<div v-if="problem" class="text-caption error--text mt-2">{{ ts(word('range_err_', problem)) }}</div>
			<div v-else-if="preview" class="text-caption grey--text mt-2">{{ preview }}</div>

			<div class="d-flex align-center mt-3" style="gap:8px">
				<v-spacer />
				<v-btn small text @click="open = false">{{ ts('range_cancel') }}</v-btn>
				<v-btn small color="primary" :disabled="!!problem" @click="apply">{{ ts('range_apply') }}</v-btn>
			</div>
		</v-card>
	</v-menu>
</template>

<script>
'use strict'

// <range-picker v-model="range" />   range: { type: 'relative', amount, unit } | { type: 'absolute', from, to } (range-picker.js);
// the page asks resolve(range, new Date()) for the two moments each time it searches, so "the last 3 hours" moves with the clock.

import { ts } from './shared-t.js'
import { QUICK, UNITS, MAX_AMOUNT, check, resolve, quickOf, relative, absolute, localText } from './range-picker.js'

// the text of a family of keys (range_unit_hours, range_err_order...): the key is built here
const word = (family, id) => family + id

export default {
	model: { prop: 'value', event: 'input' },
	props: {
		value: { type: Object, default: null }, // null: no limit in time (only with `clearable`)
		clearable: { type: Boolean, default: false }
	},
	data() {
		return {
			quick: QUICK, units: UNITS, maxAmount: MAX_AMOUNT,
			open: false, tab: 'relative', amount: 1, unit: 'hours',
			fromDay: '', fromTime: '00:00', toDay: '', toTime: '23:59'
		}
	},
	computed: {
		draft() {
			return this.tab === 'relative'
				? relative(Number(this.amount), this.unit)
				: absolute(this.fromDay + 'T' + (this.fromTime || '00:00'), this.toDay + 'T' + (this.toTime || '23:59'))
		},
		problem() {
			const c = check(this.draft)
			return c.ok ? '' : c.why
		},
		preview() {
			const r = resolve(this.draft, new Date())
			return r ? this.text(r.from) + '  ->  ' + this.text(r.to) : ''
		},
		// what the button says: "Last 3 h" or the two moments
		shown() {
			const v = this.value
			if (!v) return ts('range_all')
			if (v.type === 'absolute') return String(v.from).replace('T', ' ') + '  ->  ' + String(v.to).replace('T', ' ')
			return ts('range_last', { span: ts(word('range_short_', v.unit), { n: v.amount }) })
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
		word,
		load() {
			const v = this.value || relative(1, 'days')
			if (v.type === 'absolute') {
				this.tab = 'absolute'
				const a = String(v.from).split('T')
				const b = String(v.to).split('T')
				this.fromDay = a[0]
				this.fromTime = a[1] || '00:00'
				this.toDay = b[0]
				this.toTime = b[1] || '23:59'
			} else {
				this.tab = 'relative'
				this.amount = v.amount
				this.unit = v.unit
				this.fromDay = this.toDay = localText(new Date()).split('T')[0]
			}
		},
		text(d) {
			return localText(d).replace('T', ' ')
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
			this.$emit('input', this.draft)
			this.open = false
		}
	}
}
</script>

<style scoped>
.field {
	padding: 2px 5px;
	border: 1px solid rgba(128, 128, 128, 0.45);
	border-radius: 4px;
	color: inherit;
	background: transparent;
	color-scheme: light dark;
}
.field.amount {
	width: 72px;
}
.range-word {
	min-width: 44px;
}
</style>
