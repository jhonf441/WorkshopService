<template>
	<v-card class="mb-3">
		<v-card-title>
			<v-icon small class="mr-2 svx-ico">mdi-clipboard-text-clock-outline</v-icon>{{ $t('plugins.WorkshopService.audit.title') }}
			<v-spacer />
			<v-btn small outlined :loading="loading" @click="read"><v-icon left small>mdi-refresh</v-icon>{{ $t('plugins.WorkshopService.common.refresh') }}</v-btn>
		</v-card-title>
		<v-card-text>
			<div class="text-caption grey--text mb-3">{{ $t('plugins.WorkshopService.audit.help') }}</div>
			<v-alert v-if="!isAdmin" dense text type="info" class="mb-0">{{ $t('plugins.WorkshopService.users.admin_only') }}</v-alert>
			<template v-else>
				<v-row dense class="mb-1">
					<v-col cols="6" sm="3">
						<v-menu v-model="fromMenu" :close-on-content-click="false" transition="scale-transition" offset-y min-width="auto">
							<template v-slot:activator="{ on, attrs }">
								<v-text-field v-model="f.from" :label="$t('plugins.WorkshopService.audit.from')" readonly dense hide-details color="primary" v-bind="attrs" v-on="on">
									<template v-slot:prepend-inner>
										<v-icon color="primary">mdi-calendar-outline</v-icon>
									</template>
								</v-text-field>
							</template>
							<v-date-picker v-model="f.from" no-title color="primary" @input="fromMenu = false" />
						</v-menu>
					</v-col>
					<v-col cols="6" sm="3">
						<v-menu v-model="toMenu" :close-on-content-click="false" transition="scale-transition" offset-y min-width="auto">
							<template v-slot:activator="{ on, attrs }">
								<v-text-field v-model="f.to" :label="$t('plugins.WorkshopService.audit.to')" readonly dense hide-details color="primary" v-bind="attrs" v-on="on">
									<template v-slot:prepend-inner>
										<v-icon color="primary">mdi-calendar-outline</v-icon>
									</template>
								</v-text-field>
							</template>
							<v-date-picker v-model="f.to" no-title color="primary" @input="toMenu = false" />
						</v-menu>
					</v-col>
					<v-col cols="6" sm="3"><v-select v-model="f.user" :items="userItems" :label="$t('plugins.WorkshopService.audit.person')" dense hide-details clearable /></v-col>
					<v-col cols="6" sm="3"><v-text-field v-model="f.op" :label="$t('plugins.WorkshopService.audit.operation')" dense hide-details clearable /></v-col>
				</v-row>
				<v-checkbox v-model="f.errors" dense hide-details class="mt-0 mb-2" :label="$t('plugins.WorkshopService.audit.only_refused')" />
				<v-alert v-if="error" dense text type="error" class="mb-2">{{ error }}</v-alert>
				<v-simple-table dense>
					<thead>
						<tr>
							<th>{{ $t('plugins.WorkshopService.audit.when') }}</th>
							<th>{{ $t('plugins.WorkshopService.audit.person') }}</th>
							<th>{{ $t('plugins.WorkshopService.audit.operation') }}</th>
							<th>{{ $t('plugins.WorkshopService.audit.result') }}</th>
							<th>{{ $t('plugins.WorkshopService.audit.device') }}</th>
						</tr>
					</thead>
					<tbody>
						<tr v-for="r in rows" :key="r.id">
							<td class="text-caption" style="white-space:nowrap">{{ r.ts.replace('T', ' ') }}</td>
							<td>
								{{ r.user || '-' }}
								<v-chip v-if="r.role" x-small label outlined class="ml-1">{{ roleName(r.role) }}</v-chip>
							</td>
							<td>
								<code>{{ r.op }}</code>
								<div v-if="r.args" class="text-caption grey--text" style="max-width:420px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" :title="r.args">{{ r.args }}</div>
							</td>
							<td>
								<v-chip x-small label dark :color="r.ok ? 'success' : 'error'">{{ r.ok ? $t('plugins.WorkshopService.audit.ok') : (r.code || $t('plugins.WorkshopService.audit.failed')) }}</v-chip>
							</td>
							<td class="text-caption">
								<span :title="r.device">{{ (r.device || '').slice(0, 8) }}</span>
								<div class="grey--text">{{ r.ip }}</div>
							</td>
						</tr>
						<tr v-if="!rows.length && !loading"><td colspan="5" class="text-center grey--text">{{ $t('plugins.WorkshopService.common.no_data') }}</td></tr>
					</tbody>
				</v-simple-table>
				<div class="d-flex align-center mt-2">
					<span class="text-caption grey--text">{{ $t('plugins.WorkshopService.audit.count', { shown: rows.length, total }) }}</span>
					<v-spacer />
					<v-btn small text :disabled="offset === 0" @click="move(-1)"><v-icon small>mdi-chevron-left</v-icon></v-btn>
					<v-btn small text :disabled="offset + PAGE >= total" @click="move(1)"><v-icon small>mdi-chevron-right</v-icon></v-btn>
				</div>
				<div class="text-caption grey--text mt-2">{{ $t('plugins.WorkshopService.audit.kept') }}</div>
			</template>
		</v-card-text>
	</v-card>
</template>

<script>
'use strict'

import { api, currentIdentity, onIdentity } from './workshop-api.js'

const PAGE = 50;

function day(offsetDays) {
	const d = new Date(Date.now() - offsetDays * 86400000);
	const p = n => String(n).padStart(2, '0');
	return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate());
}

export default {
	name: 'AuditCard',
	data() {
		return { fromMenu: false, toMenu: false, f: { from: day(7), to: day(0), user: null, op: '', errors: false }, rows: [], total: 0, users: [], offset: 0, loading: false, error: '', identity: currentIdentity(), off: null, PAGE };
	},
	computed: {
		isAdmin() { return !!this.identity && this.identity.role === 'admin'; },
		userItems() { return this.users; }
	},
	watch: {
		f: { deep: true, handler() { this.offset = 0; this.read(); } }
	},
	mounted() {
		this.off = onIdentity(i => { this.identity = i; if (this.isAdmin) this.read(); });
		if (this.isAdmin) this.read();
	},
	beforeDestroy() { if (this.off) this.off(); },
	methods: {
		roleName(r) { const k = 'plugins.WorkshopService.users.role_' + r; return this.$te(k) ? this.$t(k) : r; },
		move(dir) { this.offset = Math.max(0, this.offset + dir * PAGE); this.read(); },
		async read() {
			this.loading = true;
			try {
				const f = this.f;
				const r = await api('audit.list', { from: f.from || undefined, to: f.to || undefined, user: f.user || undefined, op: f.op || undefined, errors: !!f.errors, limit: PAGE, offset: this.offset }, { noLogin: true });
				this.rows = r.rows || [];
				this.total = r.total || 0;
				this.users = r.users || [];
				this.error = '';
			} catch (e) {
				this.error = e.code === 'cancelled' ? '' : (e.message || String(e));
			}
			this.loading = false;
		}
	}
};
</script>
