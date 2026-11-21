<template>
	<!-- The targets a rule is limited to, as a list of its own under the builder: one row per target with a sentence in plain words (plugin, kind, name) and the technical
	     pattern small and grey, 44 px high, and a button with a trash icon AND the word "Remove" (a tooltip alone is not there on a touch screen). Removing is not asked
	     twice: a notice with "Undo" stays for a few seconds. Emits change(list) with a new list.
	       <access-target-list :targets="rule.targets" :decision="'allow'" @change="list => ..." /> -->
	<div class="access-target-list" data-part="target-list">
		<div class="access-h" data-part="target-list-title">{{ $t('plugins.WorkshopService.access.target_list_' + (decision === 'deny' ? 'deny' : 'allow'), { n: targets.length }) }}</div>
		<div v-if="!targets.length" class="wf-help" data-part="target-list-empty">{{ $t('plugins.WorkshopService.access.target_list_empty') }}</div>
		<ul v-else class="access-target-rows">
			<li v-for="(p, i) in targets" :key="p" class="access-target-row-item" :data-target="p">
				<span class="access-target-text"><span class="access-target-desc">{{ say(p).text }}</span><code class="access-target-code">{{ p }}</code></span>
				<v-btn small outlined class="access-touch access-target-x" :aria-label="$t('plugins.WorkshopService.access.target_remove_label', { what: say(p).text })" :title="$t('plugins.WorkshopService.access.target_remove_label', { what: say(p).text })" @click="remove(i)"><v-icon left small aria-hidden="true">mdi-delete-outline</v-icon>{{ $t('plugins.WorkshopService.access.common_remove') }}</v-btn>
			</li>
		</ul>
		<div v-if="undo" class="access-target-undo" role="status" data-part="target-undo">
			<span>{{ $t('plugins.WorkshopService.access.target_removed', { what: undo.text }) }}</span>
			<v-btn small outlined class="access-touch" data-part="target-undo-btn" @click="restore">{{ $t('plugins.WorkshopService.access.target_undo') }}</v-btn>
		</div>
	</div>
</template>

<script>
'use strict'

import { describeTarget, kindsToName, targetOptions } from './access-target-lists.js'

const UNDO_MS = 8000

export default {
	props: {
		targets: { type: Array, default: () => [] },
		decision: { type: String, default: 'allow' }
	},
	data() {
		return { names: {}, undo: null }
	},
	watch: {
		targets: { immediate: true, handler(list) { this.learn(list) } }
	},
	beforeDestroy() {
		clearTimeout(this.timer)
	},
	methods: {
		t(key, params) {
			return this.$t('plugins.WorkshopService.access.' + key, params)
		},
		say(p) {
			return describeTarget(p, this.t, this.names)
		},
		// the names of the things the list holds (a profile by its name, a scene by its title): asked once per kind, the sentence uses the id until they arrive
		learn(list) {
			kindsToName(list).forEach(([plugin, type]) => {
				const key = plugin + ':' + type
				if (this.names[key]) return
				targetOptions(plugin, type, this.t).then(rows => {
					if (!rows) return
					const m = {}
					rows.forEach(r => { m[r.id] = r.name })
					this.$set(this.names, key, m)
				})
			})
		},
		remove(i) {
			const item = this.targets[i]
			this.undo = { item, index: i, text: this.say(item).text }
			clearTimeout(this.timer)
			this.timer = setTimeout(() => { this.undo = null }, UNDO_MS)
			this.$emit('change', this.targets.filter((x, k) => k !== i))
		},
		restore() {
			if (!this.undo) return
			const at = Math.min(this.undo.index, this.targets.length)
			const list = this.targets.slice()
			if (list.indexOf(this.undo.item) < 0) list.splice(at, 0, this.undo.item)
			this.undo = null
			clearTimeout(this.timer)
			this.$emit('change', list)
		}
	}
}
</script>

<style>
.access-target-list { margin-top: 16px; }
.access-target-rows { margin: 8px 0 0; padding: 0; list-style: none; }
.access-target-row-item { display: flex; align-items: center; gap: 8px 16px; min-height: 44px; padding: 4px 12px; border: 1px solid var(--wf-line); border-radius: 8px; }
.access-target-row-item + .access-target-row-item { margin-top: 8px; }
.access-target-text { display: flex; flex: 1 1 auto; flex-direction: column; min-width: 0; }
.access-target-code { align-self: flex-start; font-size: 12px; opacity: 0.6; overflow-wrap: anywhere; }
.access-target-undo { display: flex; align-items: center; flex-wrap: wrap; gap: 8px 12px; margin-top: 8px; }
</style>
