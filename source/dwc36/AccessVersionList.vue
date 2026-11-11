<template>
	<!-- The versions kept of a custom profile, newest first (read only). "View" shows that version in the builder and the JSON. Base profiles have none. -->
	<div class="access-versions">
		<div v-if="base" class="wf-help">{{ $t('plugins.WorkshopService.access.versions_base_none') }}</div>
		<template v-else>
			<div class="access-h">{{ $t('plugins.WorkshopService.access.versions_title', { name, max }) }}</div>
			<ul class="access-version-rows">
				<li v-for="v in versions" :key="v.n" class="access-version-row">
					<strong>v{{ v.n }}</strong>
					<v-chip v-if="v.active" small outlined label color="success">{{ $t('plugins.WorkshopService.access.versions_active') }}</v-chip>
					<span class="access-version-at">{{ date(v.at) }}</span>
					<span class="access-version-by">{{ $t('plugins.WorkshopService.access.versions_by', { who: v.by || '-' }) }}</span>
					<v-spacer />
					<v-btn small outlined class="access-touch" :disabled="viewing === v.n" @click="$emit('view', v.n)">{{ $t('plugins.WorkshopService.access.common_view') }}</v-btn>
				</li>
			</ul>
		</template>
	</div>
</template>

<script>
'use strict'

import { shortDate } from './access-profile-view.js'

export default {
	props: {
		name: { type: String, default: '' },
		base: { type: Boolean, default: false },
		versions: { type: Array, default: () => [] },
		max: { type: Number, default: 5 },
		viewing: { type: Number, default: 0 }
	},
	methods: {
		date: shortDate
	}
}
</script>

<style>
.access-version-rows { list-style: none; margin: 0; padding: 0; }
.access-version-row { display: flex; align-items: center; flex-wrap: wrap; gap: 8px 12px; min-height: 44px; border-bottom: 1px solid var(--wf-line); font-size: 13px; }
</style>
