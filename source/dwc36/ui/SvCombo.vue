<template>
	<!-- A box with a list: type to search, pick one, or (allowFree) write a value of your own such as a pattern. The list is ALWAYS offered (focus or the arrow opens it); the readable name
	     comes first and the technical value small and grey. A typed value is kept on Enter or when the focus leaves; picking sets it at once. `inline` draws the list open under the box
	     (for a panel that is only a picker). The kit carries no text of its own: every sentence comes in props.
	     Props: value, options [{ value, label, hint?, group? }] (hint defaults to the value), allowFree, inline, placeholder, ariaLabel, id, noneText (nothing matches), clearLabel (the first row of the list that gives ''), emptyText.
	     Event: input (the value), as v-model. -->
	<div class="sv-combo" :class="{ 'is-inline': inline }" @focusout="onFocusOut">
		<span class="sv-field sv-combo-field"><input :id="id" ref="box" type="text" class="sv-combo-input" role="combobox" autocomplete="off" :value="text" :placeholder="placeholder" :aria-label="ariaLabel || null" aria-autocomplete="list" :aria-expanded="shown ? 'true' : 'false'" :aria-controls="uid" :aria-activedescendant="shown && rows.length ? uid + '-' + active : null" @input="typed" @focus="show" @mouseup="show" @keydown="onKey"></span>
		<ul v-if="shown" :id="uid" class="sv-combo-list sv-select-list" role="listbox" :aria-label="ariaLabel || null">
			<li v-if="clearLabel && value" class="sv-combo-row sv-combo-clear" role="option" aria-selected="false" @mousedown.prevent="choose('')">{{ clearLabel }}</li>
			<template v-for="(r, i) in rows">
				<li v-if="r.heading" :key="'g:' + r.heading" class="sv-select-group" role="presentation">{{ r.heading }}</li>
				<li v-else :id="uid + '-' + r.at" :key="'o:' + r.value" class="sv-combo-row" role="option" :aria-selected="r.value === value ? 'true' : 'false'" :data-active="r.at === active ? 'true' : null" :data-value="r.value" @mousedown.prevent="choose(r.value)">
					<span class="sv-combo-name">{{ r.label }}</span><code v-if="r.hint !== r.label" class="sv-combo-hint">{{ r.hint }}</code>
				</li>
			</template>
			<li v-if="!count" class="sv-quiet sv-combo-none" role="presentation">{{ noneText }}</li>
		</ul>
	</div>
</template>

<script>
let serial = 0
const MAX = 60

export default {
	name: 'SvCombo',
	model: { prop: 'value', event: 'input' },
	props: {
		value: { type: String, default: '' },
		options: { type: Array, default: () => [] },
		allowFree: { type: Boolean, default: false },
		inline: { type: Boolean, default: false },
		placeholder: { type: String, default: '' },
		ariaLabel: { type: String, default: '' },
		id: { type: String, default: null },
		noneText: { type: String, default: '' },
		clearLabel: { type: String, default: '' }
	},
	data() {
		serial += 1
		return { q: null, open: false, active: 0, uid: 'sv-combo-' + serial }
	},
	computed: {
		shown() {
			return this.inline || this.open
		},
		// what the box says: what is being typed, else the name of the value picked (or the value itself when it is free text)
		text() {
			if (this.q !== null) return this.q
			const o = this.options.find(x => x.value === this.value)
			return o ? o.label : this.value
		},
		// the rows (group headings between the options), the options that fit what is typed; `at` is the index among options only
		rows() {
			const q = (this.q || '').trim().toLowerCase()
			const fit = this.options.filter(o => !q || (o.label + ' ' + (o.hint || o.value) + ' ' + (o.group || '')).toLowerCase().indexOf(q) >= 0).slice(0, MAX)
			const out = []
			let last = null
			let at = 0
			fit.forEach(o => {
				if (o.group && o.group !== last) { out.push({ heading: o.group }); last = o.group }
				out.push({ value: o.value, label: o.label, hint: o.hint || o.value, at: at++ })
			})
			return out
		},
		count() {
			return this.rows.filter(r => !r.heading).length
		}
	},
	methods: {
		show() {
			this.open = true
		},
		typed(e) {
			this.q = e.target.value
			this.active = 0
			this.open = true
		},
		choose(v) {
			this.q = null
			this.open = false
			if (v !== this.value) this.$emit('input', v)
		},
		// a value written by hand (a pattern like lights.*) is kept on Enter or on leaving the box
		commit() {
			if (this.q === null) return
			const t = this.q.trim()
			this.q = null
			this.open = false
			if (!this.allowFree) return
			if (t !== this.value) this.$emit('input', t)
		},
		onKey(e) {
			const k = e.key
			const n = this.count
			if (k === 'Escape') { if (this.open && !this.inline) { this.open = false; this.q = null; e.stopPropagation(); e.preventDefault() } return }
			if (k === 'ArrowDown' || k === 'ArrowUp') {
				e.preventDefault()
				if (!this.open) { this.open = true; return }
				if (n) this.active = (this.active + (k === 'ArrowDown' ? 1 : n - 1)) % n
				return
			}
			if (k === 'Enter') {
				e.preventDefault()
				const row = this.rows.find(r => !r.heading && r.at === this.active)
				const typedPattern = this.q !== null && this.q.indexOf('*') >= 0 // a pattern is kept as written, not replaced by the first row that fits
				if (this.allowFree && (typedPattern || !row)) return this.commit()
				if (row) return this.choose(row.value)
				this.commit()
			}
		},
		onFocusOut(e) {
			if (this.$el.contains(e.relatedTarget)) return
			this.commit()
			this.open = false
			this.q = null
		}
	}
}
</script>
