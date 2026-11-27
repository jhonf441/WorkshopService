<template>
	<!-- A reader of a long text (candidate for the family): a wide sheet with ONE vertical scroll, line numbers, wrapped lines (a switch turns it off),
	     a search with next / previous, copy and download. The rows are drawn by pieces of 400 as the person scrolls, so a big file never builds
	     thousands of elements at once. A wait shows a bar and a text; after 10 s it says it is taking longer and offers to try again.
	     Props: open, title, rows [{ n (number or null), text, flag ('same' | 'changed' | 'added' | 'factory' | 'gap'), count (for a gap), block (id of the block the workshop manages that holds the row, or ''), blockStart (the first row of a block: its label is drawn above), comment (a comment line) }], loading, error (a sentence),
	     gapText (function(count) -> sentence). Slots: head (what is above the toolbar), tools (more controls in the same row of tools), legend (under the toolbar), foot-left. Methods: jumpToRange(from, to) / jumpToLine(n). Events: close, retry, copy, download. -->
	<wf-sheet :open="open" :title="title" wide @close="$emit('close')">
		<div class="sv-sheet-flow">
		<div class="sv-tv-head"><slot name="head" /></div>
		<!-- the frame never changes: the same tools and the same box whether it is waiting, failed or showing the text (no jump of layout) -->
		<div class="sv-tv-bar" role="toolbar" :aria-label="kt('view_tools')" :aria-busy="loading ? 'true' : null">
			<div class="sv-tv-find">
				<label class="sv-field"><span class="mdi mdi-magnify sv-ico sv-ico-s" aria-hidden="true" /><input v-model="q" type="search" :disabled="idle" :placeholder="kt('view_search')" :aria-label="kt('view_search')" @keyup.enter="step(1)"></label>
				<span class="sv-seg" role="group" :aria-label="kt('view_search')">
					<button type="button" data-act="prev" :disabled="!hits.length" :aria-label="kt('view_prev')" :title="kt('view_prev')" @click="step(-1)"><span class="mdi mdi-chevron-up sv-ico" aria-hidden="true" /></button>
					<button type="button" data-act="next" :disabled="!hits.length" :aria-label="kt('view_next')" :title="kt('view_next')" @click="step(1)"><span class="mdi mdi-chevron-down sv-ico" aria-hidden="true" /></button>
				</span>
				<span class="sv-quiet sv-tv-hits" data-part="hits" role="status">{{ q ? (hits.length ? kt('view_hits', { at: cur + 1, n: hits.length }) : kt('view_no_hits')) : '' }}</span>
				<slot name="tools" />
			</div>
			<div class="sv-tv-acts">
				<span class="sv-tv-wrap" :title="kt('view_wrap_help')" data-part="wrap"><span class="mdi mdi-wrap sv-ico sv-ico-s" aria-hidden="true" /><sv-switch :checked="wrap" :word="kt('view_wrap')" :label="kt('view_wrap')" :disabled="idle" @toggle="wrap = !wrap" /></span>
				<button type="button" class="wf-btn sv-btn" data-act="copy" :disabled="idle" @click="$emit('copy')"><span class="mdi mdi-content-copy sv-ico sv-ico-s" aria-hidden="true" />{{ kt('view_copy') }}</button>
				<button type="button" class="wf-btn sv-btn" data-act="download" :disabled="idle" @click="$emit('download')"><span class="mdi mdi-download sv-ico sv-ico-s" aria-hidden="true" />{{ kt('view_download') }}</button>
			</div>
		</div>
		<span class="sv-vh" role="status" aria-live="polite" data-part="said">{{ said }}</span>
		<slot name="legend" />
		<p v-if="legend && hasBlocks" class="sv-tv-legend" data-part="legend"><span class="sv-tv-swatch" aria-hidden="true" />{{ legend }}</p>
		<div class="sv-tv-frame">
			<!-- waiting: ONE thin line at the top that moves for ever; it shows after 400 ms and stays 400 ms at least (ui/sv-busy.js), so it never blinks -->
			<span v-if="busyHeld" class="sv-tv-progress" role="status" data-part="loading"><i /><span class="sv-vh">{{ kt('view_loading') }}</span></span>
			<div v-if="loading" class="sv-tv-wait" data-part="waiting">
				<template v-if="slow"><span class="sv-tv-wait-text">{{ kt('view_slow') }}</span><button type="button" class="wf-btn sv-btn" data-act="retry" @click="$emit('retry')">{{ kt('retry') }}</button></template>
			</div>
			<p v-else-if="error" class="sv-field-error sv-tv-wait" role="alert" data-part="error"><span class="mdi mdi-alert-outline sv-ico sv-ico-s" aria-hidden="true" />{{ error }} <button type="button" class="wf-btn sv-btn sv-text" data-act="retry" @click="$emit('retry')">{{ kt('retry') }}</button></p>
			<div v-else ref="scroller" class="sv-tv sv-tv-in" :class="{ 'sv-nowrap': !wrap }" tabindex="0" role="region" :aria-label="title" data-part="body" @scroll="onScroll">
				<template v-for="(r, i) in shown">
					<div v-if="r.flag === 'gap'" :key="i" class="sv-tv-gap" :data-row="i">{{ gapText ? gapText(r.count) : r.count }}</div>
					<template v-else>
						<div v-if="r.blockStart" :key="'b' + i" class="sv-tv-block-label" data-part="block-label"><span class="mdi mdi-lock-outline sv-ico sv-ico-s" aria-hidden="true" />{{ blockText ? blockText(r.block) : r.block }}</div>
						<div :key="i" class="sv-tv-row" :class="['d-' + r.flag, { 'sv-hit': isHit(i), 'sv-cur': hits[cur] === i, 'sv-flash': isFlash(i), 'sv-flash-first': i === flash[0], 'sv-flash-last': i === flash[1], 'sv-managed': !!r.block, 'sv-comment': !r.block && r.comment }]" :data-row="i" :data-block="r.block || null"><span class="sv-tv-n" :data-mark="MARKS[r.flag] || null" :title="MARKS[r.flag] ? markTitles[r.flag] || null : null" aria-hidden="true">{{ r.n === null ? '' : r.n }}</span><span class="sv-tv-t">{{ r.text }}</span></div>
					</template>
				</template>
				<p v-if="shown.length < rows.length" class="sv-quiet sv-tv-more" role="status">{{ kt('view_more', { shown: shown.length, total: rows.length }) }}</p>
			</div>
		</div>
		</div>
		<template #foot><slot name="foot-left" /><button type="button" class="wf-btn sv-btn" data-wf-autofocus @click="$emit('close')">{{ kt('close') }}</button></template>
	</wf-sheet>
</template>

<script>
import { svTextMixin } from './sv-text.js'
import WfSheet from '../WfSheet.vue'
import SvSwitch from './SvSwitch.vue'
import { svBusyMixin } from './sv-busy.js'
import { rowRange, scrollTopFor, wentKey } from './text-view-jump.js'

const CHUNK = 400
const MARKS = { changed: '~', added: '+', factory: '-' }   // a mark in the margin of every line that is not the same: the colour is never the only sign
const SLOW_MS = 10000
const FLASH_MS = 2000   // how long the line that was jumped to stays marked (a bar and a ring, no motion)

export default {
	name: 'SvTextView',
	components: { WfSheet, SvSwitch },
	mixins: [svTextMixin, svBusyMixin],
	props: {
		open: { type: Boolean, default: false },
		title: { type: String, default: '' },
		rows: { type: Array, default: () => [] },
		loading: { type: Boolean, default: false },
		error: { type: String, default: '' },
		gapText: { type: Function, default: null },
		blockText: { type: Function, default: null },   // (id) -> the label over a block the workshop manages
		legend: { type: String, default: '' },          // one line under the tools: what the colour means (only when there is a block)
		markTitles: { type: Object, default: () => ({}) } // flag -> what the mark in the margin means (its tooltip)
	},
	data() {
		return { MARKS, q: '', cur: 0, wrap: true, limit: CHUNK, slow: false, timer: null, flash: [-1, -1], flashTimer: null, said: '' }
	},
	computed: {
		// nothing to read yet (waiting or failed): the tools stay in place, switched off
		busyNow() {
			return this.loading
		},
		hasBlocks() {
			return this.rows.some(r => !!r.block)
		},
		idle() {
			return this.loading || !!this.error
		},
		shown() {
			return this.rows.length > this.limit ? this.rows.slice(0, this.limit) : this.rows
		},
		// the indexes of the rows that hold the search (without the case); a search of one letter is too much to be useful
		hits() {
			const q = this.q.trim().toLowerCase()
			if (q.length < 2) return []
			const out = []
			for (let i = 0; i < this.rows.length && out.length < 5000; i++) if (this.rows[i].flag !== 'gap' && String(this.rows[i].text).toLowerCase().indexOf(q) >= 0) out.push(i)
			return out
		}
	},
	watch: {
		loading: { immediate: true, handler(on) { this.watchSlow(on) } },
		open(on) { if (on) { this.limit = CHUNK; this.q = ''; this.cur = 0 } },
		rows() { this.limit = CHUNK; this.cur = 0 },
		q() { this.cur = 0; if (this.hits.length) this.show(this.hits[0]) }
	},
	beforeDestroy() {
		clearTimeout(this.timer)
		clearTimeout(this.flashTimer)
	},
	methods: {
		watchSlow(on) {
			clearTimeout(this.timer)
			this.slow = false
			if (on) this.timer = setTimeout(() => { this.slow = true }, SLOW_MS)
		},
		isFlash(i) {
			return i >= this.flash[0] && i <= this.flash[1]
		},
		isHit(i) {
			return this.hits.length > 0 && this.hits.indexOf(i) >= 0
		},
		onScroll() {
			const el = this.$refs.scroller
			if (el && el.scrollTop + el.clientHeight > el.scrollHeight - 300 && this.limit < this.rows.length) this.limit += CHUNK
		},
		step(n) {
			if (!this.hits.length) return
			this.cur = (this.cur + n + this.hits.length) % this.hits.length
			this.show(this.hits[this.cur])
		},
		// the lines `from` to `to` of the file (a chip of the changes asks for them): they are drawn, the box scrolls smoothly to leave them in the upper third and they are marked a moment;
		// the screen reader hears which lines. false when they are not among the rows drawn (the screen then shows what was hidden and asks again)
		jumpToRange(from, to) {
			const at = rowRange(this.rows, from, to)
			if (!at) return false
			const w = wentKey(from, to)
			this.said = w.key === 'view_went_one' ? this.kt('view_went_one', w.params) : this.kt('view_went_many', w.params)
			this.reveal(at[0], at[1])
			return true
		},
		jumpToLine(n) {
			return this.jumpToRange(n, n)
		},
		// draw up to the rows, bring them to the upper third (smooth, or at once when the person asks for less motion) and mark them
		reveal(first, last) {
			if (last >= this.limit) this.limit = last + CHUNK
			this.flash = [first, last]
			clearTimeout(this.flashTimer)
			this.flashTimer = setTimeout(() => { this.flash = [-1, -1] }, FLASH_MS)
			this.$nextTick(() => {
				const box = this.$refs.scroller
				const a = box && box.querySelector('[data-row="' + first + '"]')
				const z = box && box.querySelector('[data-row="' + last + '"]')
				if (!a) return
				const base = box.getBoundingClientRect().top - box.scrollTop
				const top = a.getBoundingClientRect().top - base
				const height = (z || a).getBoundingClientRect().bottom - a.getBoundingClientRect().top
				const calm = typeof window !== 'undefined' && window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches
				if (box.scrollTo) box.scrollTo({ top: scrollTopFor(top, height, box.clientHeight), behavior: calm ? 'auto' : 'smooth' })
				else box.scrollTop = scrollTopFor(top, height, box.clientHeight)
			})
		},
		// a hit of the search: the same movement and mark
		show(index) {
			this.reveal(index, index)
		}
	}
}
</script>
