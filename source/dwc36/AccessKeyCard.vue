<template>
	<!-- The card of one key, read only: classes, capabilities, other operations, denied entries, how many operations it may call (the list is the
	     service's answer), uses, last use and the expiry the key already had (shown, never edited here: the API section keeps that field).
	       <access-key-card :row="keyRows(...)[0]" :now="epoch seconds" @back="..." /> -->
	<div v-if="row" class="access-key-card">
		<div class="access-view-head">
			<v-btn small outlined class="access-touch" @click="$emit('back')"><v-icon left small>mdi-arrow-left</v-icon>{{ $t('plugins.WorkshopService.access.common_back') }}</v-btn>
			<strong class="access-view-name">{{ row.name }}</strong>
			<v-chip small outlined label :color="row.enabled ? 'success' : ''">{{ $t('plugins.WorkshopService.access.keys_state_' + (row.enabled ? 'active' : 'suspended')) }}</v-chip>
			<v-chip v-if="row.unused" small outlined label color="warning" class="access-unused-mark">{{ $tc('plugins.WorkshopService.access.keys_unused_days', row.unused.days, { n: row.unused.days }) }}</v-chip>
		</div>
		<div class="wf-note mb-2" role="note"><v-icon class="wf-note-icon" aria-hidden="true">mdi-key-outline</v-icon><span>{{ $t('plugins.WorkshopService.access.keys_format_help') }}</span></div>
		<div class="access-person-line"><span class="access-rule-label">{{ $t('plugins.WorkshopService.access.keys_card_classes') }}</span>
			<v-chip v-for="k in card.classes" :key="'k:' + k" small outlined label>{{ $t('plugins.WorkshopService.' + classKey(k)) }}</v-chip>
			<span v-if="!card.classes.length">{{ $t('plugins.WorkshopService.access.common_none') }}</span>
		</div>
		<div class="access-person-line"><span class="access-rule-label">{{ $t('plugins.WorkshopService.access.keys_card_caps') }}</span>
			<v-chip v-for="c in card.capabilities" :key="'c:' + c" small outlined label>{{ entryName(c) }}<code class="access-id">{{ c }}</code></v-chip>
			<span v-if="!card.capabilities.length">{{ $t('plugins.WorkshopService.access.common_none') }}</span>
		</div>
		<div class="access-person-line"><span class="access-rule-label">{{ $t('plugins.WorkshopService.access.keys_card_ops') }}</span>
			<v-chip v-for="o in card.operations" :key="'o:' + o" small outlined label>{{ entryName(o) }}<code v-if="entryCode(o)" class="access-id">{{ o }}</code></v-chip>
			<span v-if="!card.operations.length">{{ $t('plugins.WorkshopService.access.common_none') }}</span>
		</div>
		<div class="access-person-line"><span class="access-rule-label">{{ $t('plugins.WorkshopService.access.keys_denied_list') }}</span>
			<v-chip v-for="d in card.denied" :key="'d:' + d" small outlined label color="error">{{ entryName(d) }}<code v-if="isCap(d) || entryCode(d)" class="access-id">{{ d }}</code></v-chip>
			<span v-if="!card.denied.length">{{ $t('plugins.WorkshopService.access.common_none') }}</span>
		</div>
		<div class="access-person-line"><span class="access-rule-label">{{ $t('plugins.WorkshopService.access.keys_card_uses') }}</span>
			<span>{{ $tc('plugins.WorkshopService.access.keys_card_uses_n', row.uses, { n: row.uses }) }}</span>
			<span v-if="row.lastUsed">{{ $t('plugins.WorkshopService.access.keys_card_last', { at: date(row.lastUsed) }) }}</span>
			<span v-else>{{ $t('plugins.WorkshopService.access.common_never') }}</span>
		</div>
		<div class="access-person-line access-key-expiry"><span class="access-rule-label">{{ $t('plugins.WorkshopService.access.keys_card_ends') }}</span>
			<span v-if="expiry.none">{{ $t('plugins.WorkshopService.access.keys_no_end') }}</span>
			<span v-else>{{ $t('plugins.WorkshopService.access.keys_end_' + (expiry.expired ? 'past' : 'future'), { at: expiry.at }) }}</span>
		</div>
		<div class="access-rule-label mt-2">{{ $t('plugins.WorkshopService.access.keys_card_allowed', { n: row.allowed.length }) }}</div>
		<div class="access-person-line">
			<v-chip v-for="o in shown" :key="'a:' + o" small outlined label>{{ o }}</v-chip>
			<v-btn v-if="limit < row.allowed.length" small text class="access-touch" @click="all = !all">{{ $t('plugins.WorkshopService.access.' + (all ? 'check_others_hide' : 'keys_show_all'), { n: row.allowed.length }) }}</v-btn>
		</div>
	</div>
</template>

<script>
'use strict'

import { SHOWN_OPS, dateOf, expiryOf, keyCard } from './access-keys-view.js'
import { accessApi } from './access-api.js'
import { capTitle, classKey, isCap } from './key-names.js'
import { displayNamesMixin } from './display-names-mixin.js'

export default {
	mixins: [displayNamesMixin],
	props: {
		row: { type: Object, default: null },
		now: { type: Number, default: 0 }
	},
	data() {
		return { all: false, limit: SHOWN_OPS, catalog: [] }
	},
	computed: {
		card() {
			return keyCard(this.row)
		},
		expiry() {
			return expiryOf(this.row, this.now)
		},
		shown() {
			return this.all ? this.row.allowed : this.row.allowed.slice(0, this.limit)
		}
	},
	async created() {
		// the titles of the capabilities come from the list of the service (roles.list); without it a capability shows its id
		try {
			const r = await accessApi.capabilities()
			this.catalog = (r && r.capabilities) || []
		} catch (e) {
			this.catalog = []
		}
	},
	methods: {
		classKey,
		isCap,
		entryName(e) {
			return isCap(e) ? capTitle(this.catalog, e) : this.entryText(e)
		},
		date(epoch) {
			return dateOf(epoch)
		}
	}
}
</script>
