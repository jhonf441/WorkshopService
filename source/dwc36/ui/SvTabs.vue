<template>
	<!-- The second level of a section: one row of tabs that wraps (never arrows, never a sideways scroll).
	     Props: tabs ([{ id, name, href }]), value (the id shown), label (accessible name of the row), panel (id of the panel they control).
	     Event: input (id). Each tab is a real link (href: opening it in another tab of the browser works); a plain click or Enter
	     only tells the page. Left / Right move the focus, Home / End go to the ends. Nothing is drawn for fewer than two tabs. -->
	<div v-if="several" class="sv-tabs" role="tablist" :aria-label="label">
		<a v-for="t in tabs" :key="t.id" :ref="'tab-' + t.id" class="sv-tab" role="tab" :id="tabId(t.id)" :href="t.href || '#'" :data-tab="t.id"
			:aria-selected="t.id === value ? 'true' : 'false'" :aria-controls="panel || null" :tabindex="t.id === value ? 0 : -1"
			@click="pick($event, t.id)" @keydown="onKey($event, t.id)">{{ t.name }}</a>
	</div>
</template>

<script>
export default {
	name: 'SvTabs',
	props: {
		tabs: { type: Array, default: () => [] },
		value: { type: String, default: '' },
		label: { type: String, default: '' },
		panel: { type: String, default: '' }
	},
	computed: {
		several() {
			return this.tabs.length > 1
		}
	},
	methods: {
		// the id of a tab: its panel names it (aria-labelledby)
		tabId(id) {
			return (this.panel || 'sv-panel') + '-tab-' + id
		},
		// a click with a modifier key (new tab, new window) is the browser's; a plain one stays in the page
		pick(e, id) {
			if (e && (e.ctrlKey || e.metaKey || e.shiftKey || e.altKey || e.button > 0)) return
			if (e && typeof e.preventDefault === 'function') e.preventDefault()
			if (id !== this.value) this.$emit('input', id)
		},
		onKey(e, id) {
			const ids = this.tabs.map(t => t.id)
			const at = ids.indexOf(id)
			const to = e.key === 'ArrowRight' ? ids[(at + 1) % ids.length] : e.key === 'ArrowLeft' ? ids[(at - 1 + ids.length) % ids.length]
				: e.key === 'Home' ? ids[0] : e.key === 'End' ? ids[ids.length - 1] : null
			if (!to) return
			e.preventDefault()
			const el = this.$refs['tab-' + to]
			const node = Array.isArray(el) ? el[0] : el
			if (node && typeof node.focus === 'function') node.focus()
			this.$emit('input', to)
		}
	}
}
</script>
