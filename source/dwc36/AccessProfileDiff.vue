<template>
	<!-- One side (before or after) of the difference between two documents of a profile, from diffProfile() of access-diff.js. Added lines carry "+", removed "-",
	     changed "~": the sign says it for whoever does not tell colors apart. Presentation only.
	       <access-profile-diff :diff="diffProfile(a, b)" side="before" :is-new="false" /> -->
	<div class="access-diff">
		<div v-if="!rows.length" class="wf-help">{{ $t('plugins.WorkshopService.access.' + (side === 'before' && isNew ? 'diff_before_none' : 'diff_none')) }}</div>
		<div v-for="r in rows" :key="r.id" class="access-diff-rule" :class="'is-' + mark(r)">
			<div class="access-diff-head">
				<span class="access-diff-sign" aria-hidden="true">{{ sign(r) }}</span>
				<strong>{{ $t('plugins.WorkshopService.access.diff_rule', { id: r.id }) }}</strong>
				<v-chip small outlined label :color="doc(r).decision === 'allow' ? 'success' : 'error'">{{ $t('plugins.WorkshopService.access.builder_decision_' + doc(r).decision) }}</v-chip>
				<span v-if="r.status === 'same'" class="wf-help">{{ $t('plugins.WorkshopService.access.diff_none') }}</span>
			</div>
			<div v-for="(l, i) in lines(r)" :key="i" class="access-diff-line" :class="l.mark ? 'is-' + l.mark : ''"><span class="access-diff-sign" aria-hidden="true">{{ l.sign }}</span><code>{{ l.text }}</code></div>
		</div>
	</div>
</template>

<script>
'use strict'

export default {
	props: {
		diff: { type: Object, required: true },
		side: { type: String, default: 'after' },
		isNew: { type: Boolean, default: false }
	},
	computed: {
		rows() {
			return this.diff.rules.filter(r => (this.side === 'before' ? r.status !== 'added' : r.status !== 'removed'))
		}
	},
	methods: {
		doc(r) {
			return (this.side === 'before' ? r.before : r.after) || {}
		},
		mark(r) {
			if (r.status === 'same') return 'same'
			if (r.status === 'changed') return 'changed'
			return this.side === 'before' ? 'removed' : 'added'
		},
		sign(r) {
			return { same: ' ', changed: '~', removed: '-', added: '+' }[this.mark(r)]
		},
		// the lines of a rule: its operations, targets and conditions, each marked when it was added (after), removed (before) or changed
		lines(r) {
			const after = this.side === 'after'
			const d = this.doc(r)
			const gone = after ? [] : r.operations.removed
			const fresh = after ? r.operations.added : []
			const out = []
			;(d.operations || []).forEach(e => {
				const m = fresh.indexOf(e) >= 0 || (r.status === 'added' && after) ? 'added' : (gone.indexOf(e) >= 0 || (r.status === 'removed' && !after) ? 'removed' : '')
				out.push({ text: e, mark: m, sign: m === 'added' ? '+' : m === 'removed' ? '-' : ' ' })
			})
			const tm = after ? r.targets.added : r.targets.removed
			;(d.targets || []).forEach(t => out.push({ text: t, mark: tm.indexOf(t) >= 0 ? (after ? 'added' : 'removed') : '', sign: tm.indexOf(t) >= 0 ? (after ? '+' : '-') : ' ' }))
			const w = d.when || {}
			Object.keys(w).forEach(k => {
				const hit = (after ? r.when.added : r.when.removed).indexOf(k) >= 0
				const changed = r.when.changed.indexOf(k) >= 0
				out.push({ text: k + ': ' + JSON.stringify(w[k]), mark: hit ? (after ? 'added' : 'removed') : (changed ? 'changed' : ''), sign: hit ? (after ? '+' : '-') : (changed ? '~' : ' ') })
			})
			return out
		}
	}
}
</script>

<style>
.access-diff-rule { margin-bottom: 8px; padding: 6px 8px; border: 1px solid var(--wf-line); border-radius: 8px; font-size: 13px; }
.access-diff-head { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; min-height: 32px; }
.access-diff-sign { display: inline-block; width: 14px; font-family: monospace; font-weight: 700; }
.access-diff-line { font-size: 12px; }
.access-diff-line.is-added, .access-diff-rule.is-added { background: rgba(76, 175, 80, 0.16); }
.access-diff-line.is-removed, .access-diff-rule.is-removed { background: rgba(244, 67, 54, 0.16); }
.access-diff-line.is-changed { background: rgba(255, 152, 0, 0.16); }
</style>
