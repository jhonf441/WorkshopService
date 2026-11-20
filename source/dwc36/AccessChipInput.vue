<template>
	<!-- A list of short texts (operations, targets) with a field to add one. `validate(text)` answers the key of a sentence (area `access`) when the text is not
	     acceptable, or ''. The service has the last word; this only keeps typing mistakes out.
	       <access-chip-input :items="[...]" :suggestions="[...]" :validate="fn" :placeholder="..." @add="t => ..." @remove="t => ..." /> -->
	<div class="access-chips">
		<span v-for="e in items" :key="e" class="access-op access-chip" :title="titleOf(e)">{{ e }}<button type="button" class="access-chip-x access-touch" :aria-label="$t('plugins.WorkshopService.access.common_remove') + ' ' + e" @click="$emit('remove', e)"><v-icon small aria-hidden="true">mdi-close</v-icon></button></span>
		<span v-if="!noField" class="access-chip-add">
			<span class="access-chip-combo">
				<v-text-field v-model="text" dense outlined hide-details clearable class="access-chip-field" :placeholder="placeholder" :aria-label="placeholder" :list="options.length ? null : listId" role="combobox" :aria-expanded="showList ? 'true' : 'false'" aria-autocomplete="list" @focus="focused = true" @blur="blur" @keyup.enter="add()" @keydown.esc="focused = false" />
				<datalist v-if="!options.length && suggestions.length" :id="listId"><option v-for="s in suggestions" :key="s" :value="s" /></datalist>
				<ul v-if="showList" class="sv-select-list access-chip-list" role="listbox" :aria-label="placeholder">
					<template v-for="g in groups">
						<li :key="'g:' + g.name" class="sv-select-group" role="presentation">{{ g.name }}</li>
						<li v-for="o in g.items" :key="o.value" role="option" :aria-selected="items.indexOf(o.value) >= 0 ? 'true' : 'false'" @mousedown.prevent="pick(o)"><span><code>{{ o.value }}</code> <small class="access-chip-meaning">{{ o.label }}</small></span><span v-if="items.indexOf(o.value) >= 0" class="mdi mdi-check sv-ico sv-ico-s" aria-hidden="true" /></li>
					</template>
				</ul>
			</span>
			<v-btn small outlined class="access-touch" :disabled="!text.trim()" @click="add()">{{ $t('plugins.WorkshopService.access.builder_loose_add') }}</v-btn>
		</span>
		<div v-if="problem" class="access-problem" role="alert">{{ $t('plugins.WorkshopService.access.' + problem, { entry: text }) }}</div>
	</div>
</template>

<script>
'use strict'

let counter = 0

export default {
	props: {
		items: { type: Array, default: () => [] },
		suggestions: { type: Array, default: () => [] },
		placeholder: { type: String, default: '' },
		validate: { type: Function, default: null },
		options: { type: Array, default: () => [] },   // [{ value, label, group }]: what is valid, with its meaning; the field then searches them
		noField: { type: Boolean, default: false }     // only the chips (something else adds)
	},
	data() {
		counter++
		return { text: '', problem: '', focused: false, listId: 'access-chip-list-' + counter }
	},
	computed: {
		matches() {
			const q = String(this.text || '').trim().toLowerCase()
			return this.options.filter(o => !q || o.value.toLowerCase().indexOf(q) >= 0 || String(o.label || '').toLowerCase().indexOf(q) >= 0).slice(0, 40)
		},
		groups() {
			const by = {}
			this.matches.forEach(o => { (by[o.group] = by[o.group] || []).push(o) })
			return Object.keys(by).sort().map(name => ({ name, items: by[name] }))
		},
		showList() {
			return this.focused && this.options.length > 0 && this.matches.length > 0
		}
	},
	methods: {
		titleOf(e) {
			const o = this.options.find(x => x.value === e)
			return o ? o.label : null
		},
		blur() {
			this.focused = false
		},
		pick(o) {
			this.text = o.value
			this.add()
		},
		add() {
			const t = this.text.trim()
			if (!t) return
			this.problem = this.validate ? this.validate(t) : ''
			if (this.problem) return
			this.$emit('add', t)
			this.text = ''
		}
	}
}
</script>

<style>
.access-chips { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; }
.access-chip { display: inline-flex; align-items: center; gap: 2px; }
.access-chip-x { min-width: 40px; background: transparent; border: 0; color: inherit; cursor: pointer; }
.access-chip-add { display: inline-flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.access-chip-field { min-width: 220px; }
.access-chip-combo { position: relative; display: inline-block; }
.access-chip-list { max-height: 320px; }
.sv-select-group { min-height: 32px; padding: 6px 12px 0; font-size: 12px; font-weight: 600; opacity: 0.7; cursor: default; }
.access-chip-meaning { opacity: 0.75; white-space: normal; }
.access-problem { flex-basis: 100%; font-size: 12px; color: var(--v-error-base, #d32f2f); }
</style>
