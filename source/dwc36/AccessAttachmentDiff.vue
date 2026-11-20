<template>
	<!-- One side (before or after) of the change of a person or of a group, in the slots of AccessChangeDialog. A line that goes carries "-", one that arrives "+"
	     (the sign says it for whoever does not tell colors apart). Lines come from sideLines() of access-edit-view.js.
	       <access-attachment-diff side="after" kind="person" :before="before" :after="after" /> -->
	<div class="access-diff-side">
		<div v-if="absent" class="wf-help">{{ $t('plugins.WorkshopService.access.' + absent) }}</div>
		<template v-else>
			<div v-for="l in lines" :key="l.section" class="access-diff-block">
				<div class="access-rule-label">{{ $t('plugins.WorkshopService.access.' + l.label) }}</div>
				<div v-for="it in l.items" :key="l.section + ':' + it.sign + it.name" class="access-diff-line" :class="{ 'is-added': it.sign === '+', 'is-removed': it.sign === '-' }">
					<span class="access-diff-sign" aria-hidden="true">{{ it.sign || ' ' }}</span><span>{{ it.name }}</span>
				</div>
				<div v-if="!l.items.length" class="wf-help">{{ $t('plugins.WorkshopService.access.common_none') }}</div>
			</div>
		</template>
	</div>
</template>

<script>
'use strict'

import { diffAttachment } from './access-diff.js'
import { sideLines } from './access-edit-view.js'

export default {
	props: {
		side: { type: String, default: 'before' },
		kind: { type: String, default: 'person' },
		before: { type: Object, default: null },
		after: { type: Object, default: null },
		// the object does not exist on this side: a new group has no "before", a removed one no "after"
		missing: { type: Boolean, default: false }
	},
	computed: {
		diff() {
			return diffAttachment(this.before, this.after)
		},
		absent() {
			if (!this.missing) return ''
			return this.side === 'before' ? 'pedit_not_yet' : 'pedit_gone'
		},
		lines() {
			return sideLines(this.side, this.diff, this.side === 'before' ? this.before : this.after, this.kind)
		}
	}
}
</script>

<style>
.access-diff-block { margin-bottom: 8px; }
.access-diff-line { display: flex; gap: 8px; padding: 2px 6px; font-size: 13px; }
.access-diff-line.is-added { background: rgba(76, 175, 80, 0.18); }
.access-diff-line.is-removed { background: rgba(244, 67, 54, 0.18); }
.access-diff-sign { width: 12px; font-family: monospace; }
</style>
