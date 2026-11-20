<template>
	<!-- The first level of the page, in three forms with the SAME entries: a picker that opens the whole list (narrow), one row that
	     wraps (medium), a vertical rail (wide). The form follows the width of the page container through CSS (data-w on the page root);
	     this piece draws the picker and the list, the style sheet shows the one that fits.
	     Props: entries ([{ id, icon, name, count (things to fix there), lock ('session' | 'role' | ''), lockLabel ("Needs a session", "Needs the role Administrator"), href }]): a locked entry
	              keeps its icon with a small padlock on its corner (as the side bars of the family) and stays a link to its cover,
	     foldLabel, openLabel, pinLabel, unpinLabel (the buttons of the rail: fold to icons / open, keep it open / let it fold),
	            current (id of the open entry), label (accessible name), pickLabel ("Section"), countLabel(n) -> "3 notices".
	     Event: go (id). Entries are real links: back, forward and "open in a new tab" work. -->
	<nav class="sv-nav" :aria-label="label" :data-folded="folded ? '' : null">
		<button type="button" class="sv-nav-pick" aria-haspopup="dialog" @click="open = true">
			<span class="mdi mdi-menu sv-ico" aria-hidden="true" />
			<small>{{ pickLabel }}</small>
			<b>{{ currentName }}</b>
			<span v-if="total" class="sv-nav-count" :aria-label="countLabel(total)">{{ total }}</span>
		</button>
		<div class="sv-nav-list">
			<!-- only in the rail (wide): fold it to the icons and keep it open or let it fold by itself; the choice is kept in this device -->
			<div v-if="foldLabel" class="sv-nav-head" data-part="head">
				<button v-if="!folded" type="button" class="sv-nav-fold sv-nav-pin" :class="{ 'sv-pinned': pinned }" data-act="pin" :aria-pressed="pinned ? 'true' : 'false'" :title="pinned ? unpinLabel : pinLabel" @click="togglePin"><span class="mdi sv-ico sv-ico-s" :class="pinned ? 'mdi-pin' : 'mdi-pin-outline'" aria-hidden="true" /><span class="sv-nav-pin-label">{{ pinText }}</span></button>
				<button type="button" class="sv-nav-fold" data-act="fold" :aria-label="folded ? openLabel : foldLabel" :aria-expanded="folded ? 'false' : 'true'" :title="folded ? openLabel : foldLabel" @click="toggleFold"><span class="mdi sv-ico sv-ico-s" :class="folded ? 'mdi-chevron-double-right' : 'mdi-chevron-double-left'" aria-hidden="true" /></button>
			</div>
			<a v-for="e in entries" :key="e.id" class="sv-nav-item" :class="{ 'sv-locked': !!e.lock }" :href="e.href || '#'" :data-entry="e.id" :data-lock="e.lock || null" :title="e.lockLabel || (folded ? e.name : null)" :aria-label="e.lockLabel ? e.name + ': ' + e.lockLabel : (folded ? e.name : null)" :aria-current="e.id === current ? 'page' : null" @click="pick($event, e.id)">
				<span class="sv-nav-iconbox"><span class="mdi sv-ico" :class="e.icon" aria-hidden="true" /><span v-if="e.lock" class="mdi sv-lockmark" :class="e.lock === 'session' ? 'mdi-account-lock' : 'mdi-lock'" aria-hidden="true" /></span>
				<span class="sv-nav-name">{{ e.name }}</span>
				<span v-if="e.count" class="sv-nav-count" :aria-label="countLabel(e.count)">{{ e.count }}</span>
			</a>
		</div>
		<sv-sheet :open="open" :title="pickLabel" @close="open = false">
			<a v-for="e in entries" :key="e.id" class="sv-nav-item" :class="{ 'sv-locked': !!e.lock }" :href="e.href || '#'" :data-entry="e.id" :data-lock="e.lock || null" :title="e.lockLabel || null" :aria-label="e.lockLabel ? e.name + ': ' + e.lockLabel : null" :aria-current="e.id === current ? 'page' : null" :data-sv-autofocus="e.id === current ? '' : null" @click="pick($event, e.id)">
				<span class="sv-nav-iconbox"><span class="mdi sv-ico" :class="e.icon" aria-hidden="true" /><span v-if="e.lock" class="mdi sv-lockmark" :class="e.lock === 'session' ? 'mdi-account-lock' : 'mdi-lock'" aria-hidden="true" /></span>
				<span class="sv-nav-name">{{ e.name }}</span>
				<span v-if="e.count" class="sv-nav-count" :aria-label="countLabel(e.count)">{{ e.count }}</span>
			</a>
		</sv-sheet>
	</nav>
</template>

<script>
import SvSheet from './SvSheet.vue'

// the rail is open and kept open by default; what the person chooses is kept in this device (no storage: it is just not remembered)
function readStore(key) {
	try {
		const v = JSON.parse(window.localStorage.getItem(key) || 'null')
		if (v && typeof v === 'object') return { folded: v.folded === true, pinned: v.pinned !== false }
	} catch (e) { /* no storage */ }
	return { folded: false, pinned: true }
}

function writeStore(key, v) {
	try { window.localStorage.setItem(key, JSON.stringify(v)) } catch (e) { /* no storage */ }
}

export default {
	name: 'SvSectionNav',
	components: { SvSheet },
	props: {
		entries: { type: Array, default: () => [] },
		current: { type: String, default: '' },
		label: { type: String, default: '' },
		pickLabel: { type: String, default: '' },
		countLabel: { type: Function, default: n => String(n) },
		foldLabel: { type: String, default: '' },
		openLabel: { type: String, default: '' },
		pinLabel: { type: String, default: '' },
		unpinLabel: { type: String, default: '' },
		storeKey: { type: String, default: 'workshop-service-nav' }
	},
	data() {
		const saved = readStore(this.storeKey)
		return { open: false, folded: saved.folded, pinned: saved.pinned }
	},
	computed: {
		currentName() {
			const e = this.entries.find(x => x.id === this.current)
			return e ? e.name : ''
		},
		pinText() {
			return this.pinLabel
		},
		total() {
			return this.entries.reduce((n, e) => n + (e.count || 0), 0)
		}
	},
	methods: {
		toggleFold() {
			this.folded = !this.folded
			writeStore(this.storeKey, { folded: this.folded, pinned: this.pinned })
		},
		togglePin() {
			this.pinned = !this.pinned
			writeStore(this.storeKey, { folded: this.folded, pinned: this.pinned })
		},
		pick(e, id) {
			if (e && (e.ctrlKey || e.metaKey || e.shiftKey || e.altKey || e.button > 0)) return
			if (e && typeof e.preventDefault === 'function') e.preventDefault()
			this.open = false
			// not kept open: choosing a section folds the rail by itself
			const head = this.$el && this.$el.querySelector ? this.$el.querySelector('.sv-nav-head') : null
			if (!this.pinned && head && head.offsetParent !== null && !this.folded) this.toggleFold()
			this.$emit('go', id)
		}
	}
}
</script>
