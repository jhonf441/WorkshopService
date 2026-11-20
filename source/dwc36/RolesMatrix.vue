<template>
	<!-- The matrix of RolesCard: rows = capabilities by category, columns = the base roles and the own roles. It only draws and tells what was touched: the
	     card owns the draft and the calls. Props: columns, groups, tallies, damaged, draftOpen, busy, armedDelete. Emits `cell` (cap, col), `edit` (role), `remove` (role). -->
	<div class="roles-matrix">
		<div class="wf-section-head">
			<h3 class="wf-h">{{ r('matrix_title') }}</h3>
			<p class="wf-lead">{{ r('matrix_help') }}</p>
		</div>
		<div class="roles-legend mb-2" aria-hidden="true">
			<span v-for="s in legend" :key="s" class="roles-key" :class="'is-' + s"><v-icon x-small>{{ cellIcon(s) }}</v-icon>{{ cellLabel(s) }}</span>
		</div>
		<div class="roles-tools">
			<nav class="roles-index" :aria-label="r('index_label')">
				<button v-for="g in groups" :key="'i:' + g.id" type="button" class="sv-btn roles-index-chip" :class="{ 'is-active': activeId === g.id }" :aria-current="activeId === g.id ? 'true' : null" :aria-expanded="isOpen(g) ? 'true' : 'false'" :title="r('index_go')" @click="jump(g)"><v-icon x-small aria-hidden="true">mdi-link-variant</v-icon>{{ g.title }} ({{ g.caps.length }})</button>
			</nav>
			<button v-if="editingCol" type="button" class="roles-only-diff" :aria-pressed="onlyDiff ? 'true' : 'false'" @click="onlyDiff = !onlyDiff"><v-icon small aria-hidden="true">{{ onlyDiff ? 'mdi-checkbox-marked' : 'mdi-checkbox-blank-outline' }}</v-icon>{{ r('only_diff', { role: editingCol.label }) }}</button>
		</div>
		<p v-if="filtering && !shownGroups.length" class="wf-help" role="status">{{ r('only_diff_none') }}</p>
		<div class="roles-scroll">
			<table class="roles-table">
				<thead>
					<tr>
						<th class="roles-cap-head" scope="col">{{ r('col_capability') }}</th>
						<th v-for="c in columns" :key="c.key" scope="col" class="roles-col-head" :class="{ 'is-custom': c.kind === 'custom', 'is-editing': c.editing }">
							<div class="roles-col-name">{{ c.label }}</div>
							<div class="roles-col-sub">
								<template v-if="c.kind === 'base'">{{ r('base_badge') }}</template>
								<template v-else>{{ r('column_base', { base: roleName(c.def.base) }) }}<template v-if="!c.isNew"> &middot; {{ r('users_n', { n: c.role.users }, c.role.users) }}</template></template>
							</div>
							<div v-if="c.kind === 'custom' && !c.isNew" class="roles-col-actions">
								<v-btn icon small :disabled="draftOpen && !c.editing" :title="r('edit_role')" :aria-label="r('edit_role') + ': ' + c.label" @click="$emit('edit', c.role)"><v-icon small>mdi-pencil</v-icon></v-btn>
								<v-btn icon small :color="armedDelete === c.name ? 'error' : null" :disabled="busy || (draftOpen && !c.editing)" :title="armedDelete === c.name ? r('tap_again_delete') : r('delete_role')" :aria-label="(armedDelete === c.name ? r('tap_again_delete') : r('delete_role')) + ': ' + c.label" @click="$emit('remove', c.role)"><v-icon small>mdi-delete</v-icon></v-btn>
							</div>
						</th>
					</tr>
				</thead>
				<tbody v-for="g in shownGroups" :key="g.id" :id="'roles-group-' + g.id">
					<tr class="roles-group" :class="{ 'is-flash': flashId === g.id }">
						<th scope="rowgroup" class="roles-group-name">
							<button type="button" class="roles-group-btn" :aria-expanded="isOpen(g) ? 'true' : 'false'" @click="toggle(g)"><v-icon small aria-hidden="true">{{ isOpen(g) ? 'mdi-chevron-down' : 'mdi-chevron-right' }}</v-icon>{{ g.title }} ({{ g.caps.length }})</button>
						</th>
						<td v-for="c in columns" :key="'s:' + c.key" class="roles-sum" :aria-label="sumAria(g, c)" :title="sumAria(g, c)">
							<span class="roles-sum-can">{{ sumOf(g, c).can }}</span><span class="roles-sum-sep" aria-hidden="true"> &middot; </span><span class="roles-sum-part">{{ sumOf(g, c).partial }}</span><span class="roles-sum-sep" aria-hidden="true"> &middot; </span><span class="roles-sum-no">{{ sumOf(g, c).no }}</span>
						</td>
					</tr>
					<tr v-for="cap in (isOpen(g) ? g.caps : [])" :key="cap.id">
						<th scope="row" class="roles-cap">
							<div class="roles-cap-title">{{ cap.title }}</div>
							<div class="roles-cap-chips">
								<span class="wf-pill">{{ className(cap.class) }}</span>
								<span class="wf-pill" :class="{ 'roles-risk-high': cap.risk >= 3 }">{{ r('risk', { n: cap.risk }) }}</span>
							</div>
						</th>
						<td v-for="c in columns" :key="c.key" class="roles-td">
							<button
								type="button" class="roles-cell" :class="['is-' + state(cap, c), { 'is-fixed': !canEdit(cap, c) }]"
								:aria-disabled="!canEdit(cap, c)" :aria-label="cellAria(cap, c)" :title="cellWhy(state(cap, c))"
								@click="$emit('cell', cap, c)"
							>
								<v-icon small aria-hidden="true">{{ cellIcon(state(cap, c)) }}</v-icon>
								<span class="roles-cell-text">{{ cellLabel(state(cap, c)) }}</span>
							</button>
						</td>
					</tr>
				</tbody>
			</table>
		</div>
	</div>
</template>

<script>
'use strict'

import { CELL_INFO, CLASS_KEYS, cellState, editable } from './roles-matrix.js'

const LEGEND = ['allowed', 'partial', 'blocked', 'limited', 'granted', 'denied', 'locked', 'stop']

export default {
	name: 'RolesMatrix',
	props: {
		columns: { type: Array, default: () => [] },
		groups: { type: Array, default: () => [] },
		tallies: { type: Object, default: () => ({}) },
		damaged: { type: Boolean, default: false },
		draftOpen: { type: Boolean, default: false },
		busy: { type: Boolean, default: false },
		armedDelete: { type: String, default: '' }
	},
	data() {
		return { opened: {}, onlyDiff: false, activeId: '', flashId: '', flashTimer: null }
	},
	computed: {
		legend() { return LEGEND },
		// the column being edited (a custom role in a draft): the filter "only what differs from its base role" works on it
		editingCol() { return this.columns.find(c => c.editing) || null },
		filtering() { return !!(this.editingCol && this.onlyDiff) },
		// with the filter on, only the capabilities the edited role grants or denies; a group left empty is not drawn
		shownGroups() {
			if (!this.filtering) return this.groups
			const col = this.editingCol
			return this.groups.map(g => Object.assign({}, g, { caps: g.caps.filter(cap => ['granted', 'denied'].indexOf(this.state(cap, col)) >= 0) })).filter(g => g.caps.length)
		}
	},
	beforeDestroy() {
		clearTimeout(this.flashTimer)
	},
	methods: {
		// the first group is open, the others closed, unless the person opened or closed one; with the filter on everything is open
		isOpen(g) {
			if (this.filtering) return true
			if (g.id in this.opened) return this.opened[g.id]
			return this.groups.length ? this.groups[0].id === g.id : true
		},
		toggle(g) { this.$set(this.opened, g.id, !this.isOpen(g)) },
		jump(g) {
			this.activeId = g.id
			this.flashId = g.id
			clearTimeout(this.flashTimer)
			this.flashTimer = setTimeout(() => { this.flashId = '' }, 1500)
			this.$set(this.opened, g.id, true)
			this.$nextTick(() => {
				const el = document.getElementById('roles-group-' + g.id)
				if (el && el.scrollIntoView) el.scrollIntoView({ block: 'start', behavior: 'auto' })
			})
		},
		// per group and column: how many capabilities the role has (allowed, granted, stop), partly (partial, limited) and not (blocked, denied, locked)
		sumOf(g, col) {
			const out = { can: 0, partial: 0, no: 0 }
			g.caps.forEach(cap => {
				const st = this.state(cap, col)
				if (st === 'allowed' || st === 'granted' || st === 'stop') out.can++
				else if (st === 'partial' || st === 'limited') out.partial++
				else out.no++
			})
			return out
		},
		sumAria(g, col) {
			const t = this.sumOf(g, col)
			return this.r('sum_aria', { group: g.title, role: col.label, can: t.can, partial: t.partial, no: t.no })
		},
		r(key, params, count) { return count === undefined ? this.$t('plugins.WorkshopService.roles.' + key, params) : this.$tc('plugins.WorkshopService.roles.' + key, count, params) },
		roleName(role) { return this.$t('plugins.WorkshopService.users.role_' + role) },
		className(k) { return this.r(CLASS_KEYS[k] || CLASS_KEYS.read) },
		cellIcon(s) { return CELL_INFO[s].icon },
		cellLabel(s) { return this.r(CELL_INFO[s].label) },
		cellWhy(s) { return this.r(CELL_INFO[s].why) },
		state(cap, col) { return cellState(cap, col, this.tallies) },
		canEdit(cap, col) { return editable(cap, col) && !this.damaged },
		cellAria(cap, col) {
			const s = this.state(cap, col)
			return cap.title + ', ' + col.label + ': ' + this.cellLabel(s) + '. ' + (this.canEdit(cap, col) ? this.r('cell_click_hint') : this.cellWhy(s))
		}
	}
}
</script>

<style>
/* The roles matrix: only what is its own (prefix roles-); colors are the tokens of the family (family.css), the meaning is also an icon and a word */
.roles-legend { display: flex; flex-wrap: wrap; gap: 4px 14px; font-size: 12px; }
.roles-key { display: inline-flex; align-items: center; gap: 4px; }
.roles-scroll { overflow: auto; max-height: 72vh; max-width: 100%; border: 1px solid var(--wf-line); border-radius: 8px; }
.roles-table { border-collapse: separate; border-spacing: 0; width: 100%; min-width: 640px; font-size: 13px; }
.roles-table th, .roles-table td { padding: 6px 12px; border-bottom: 1px solid var(--wf-line); text-align: left; vertical-align: middle; }
.roles-cap-head, .roles-cap { position: sticky; left: 0; z-index: 1; min-width: 150px; max-width: 220px; font-weight: 400; }
.roles-table thead th { position: sticky; top: 0; z-index: 2; }
.roles-table thead .roles-cap-head { z-index: 3; }
.roles-cap-head { font-size: 12px; font-weight: 600; text-transform: uppercase; }
.roles-col-head { min-width: 104px; text-align: center !important; vertical-align: top !important; }
.roles-col-head.is-editing { border-top: 2px solid var(--wf-accent); }
.roles-col-name { font-size: 13px; font-weight: 600; overflow-wrap: anywhere; }
.roles-col-sub { font-size: 12px; font-weight: 400; opacity: 0.8; }
.roles-col-actions { display: flex; justify-content: center; gap: 4px; margin-top: 4px; }
.roles-group th, .roles-group td { font-size: 12px; font-weight: 600; text-transform: none; }
.roles-group-name { left: 0; position: sticky; z-index: 1; }
.roles-group-btn { display: flex; align-items: center; gap: 4px; min-height: var(--sv-touch, 44px); width: 100%; padding: 0; border: 0; background: transparent; color: inherit; font: inherit; font-weight: 600; text-align: left; cursor: pointer; }
.roles-sum { text-align: center !important; font-weight: 400; white-space: nowrap; }
.roles-sum-can, .roles-sum-part { font-weight: 600; }
.roles-tools { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 16px; margin-bottom: 8px; }
.roles-index { display: flex; flex-wrap: wrap; gap: 8px; }
.roles-index-chip { flex: none; min-height: var(--sv-touch, 44px); padding: 0 12px; font-size: 12px; white-space: nowrap; }
.roles-index-chip.is-active { background: var(--wf-accent); border-color: var(--wf-accent); color: var(--sv-on-accent, #fff); font-weight: 600; }
.roles-group.is-flash > * { background-image: linear-gradient(var(--wf-c-info-bg), var(--wf-c-info-bg)); }
.roles-table tbody { scroll-margin-top: 72px; }
.roles-table thead th, .roles-cap, .roles-group-name { background-color: var(--wf-surface); box-shadow: 0 1px 0 var(--wf-line); }
.roles-group th, .roles-group td { background-color: var(--wf-surface); background-image: linear-gradient(var(--wf-soft), var(--wf-soft)); }
.sv-page[data-w='s'] .roles-index { flex-wrap: nowrap; overflow-x: auto; max-width: 100%; }
.roles-only-diff { display: inline-flex; align-items: center; gap: 8px; min-height: var(--sv-touch, 44px); padding: 0; border: 0; background: transparent; color: inherit; font: inherit; font-size: 13px; cursor: pointer; }
.roles-cap-title { font-weight: 500; overflow-wrap: anywhere; }
.roles-cap-chips { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 2px; }
.roles-cap-chips .wf-pill { padding: 0 8px; }
.roles-risk-high { border-color: var(--wf-c-warning); }
.roles-td { padding: 2px !important; text-align: center !important; }
.roles-cell { display: flex; align-items: center; justify-content: center; gap: 4px; width: 100%; min-height: 44px; padding: 2px 6px; border: 1px solid transparent; border-radius: 6px; background: transparent; color: inherit; font: inherit; font-size: 12px; cursor: pointer; }
.roles-cell:hover:not(.is-fixed) { border-color: var(--wf-line-strong); background: var(--wf-soft); }
.roles-cell.is-fixed { cursor: default; }
.roles-cell-text { overflow-wrap: anywhere; }
.roles-cell.is-allowed .v-icon, .roles-cell.is-stop .v-icon, .roles-key.is-allowed .v-icon, .roles-key.is-stop .v-icon { color: var(--wf-c-success) !important; }
.roles-cell.is-partial .v-icon, .roles-cell.is-limited .v-icon, .roles-key.is-partial .v-icon, .roles-key.is-limited .v-icon { color: var(--wf-c-warning) !important; }
.roles-cell.is-granted .v-icon, .roles-key.is-granted .v-icon { color: var(--wf-c-info) !important; }
.roles-cell.is-granted .roles-cell-text { color: var(--wf-c-info-text); font-weight: 600; }
.roles-cell.is-denied .v-icon, .roles-key.is-denied .v-icon { color: var(--wf-c-error) !important; }
.roles-cell.is-denied .roles-cell-text { color: var(--wf-c-error-text); font-weight: 600; }
.roles-cell.is-blocked, .roles-cell.is-locked { opacity: 0.75; }
</style>
