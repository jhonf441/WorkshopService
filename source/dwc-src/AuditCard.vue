<template>
	<v-card class="mb-3">
		<v-card-title>
			<v-icon size="small" class="mr-2 svx-ico">mdi-clipboard-text-clock-outline</v-icon>{{ $t('plugins.WorkshopService.audit.title') }}
			<v-spacer />
			<v-btn size="small" variant="outlined" :loading="loading" @click="read"><v-icon start size="small">mdi-refresh</v-icon>{{ $t('plugins.WorkshopService.common.refresh') }}</v-btn>
		</v-card-title>
		<v-card-text>
			<div class="text-body-small text-medium-emphasis mb-3">{{ $t('plugins.WorkshopService.audit.help') }}</div>
			<v-alert v-if="!isAdmin" density="compact" variant="tonal" type="info" class="mb-0">{{ $t('plugins.WorkshopService.users.admin_only') }}</v-alert>
			<template v-else>
				<v-row density="compact" class="mb-1">
					<v-col cols="6" sm="3"><v-text-field v-model="f.from" type="date" :label="$t('plugins.WorkshopService.audit.from')" density="compact" variant="outlined" hide-details /></v-col>
					<v-col cols="6" sm="3"><v-text-field v-model="f.to" type="date" :label="$t('plugins.WorkshopService.audit.to')" density="compact" variant="outlined" hide-details /></v-col>
					<v-col cols="6" sm="3"><v-select v-model="f.user" :items="userItems" :label="$t('plugins.WorkshopService.audit.person')" density="compact" variant="outlined" hide-details clearable /></v-col>
					<v-col cols="6" sm="3"><v-text-field v-model="f.op" :label="$t('plugins.WorkshopService.audit.operation')" density="compact" variant="outlined" hide-details clearable /></v-col>
				</v-row>
				<v-checkbox v-model="f.errors" density="compact" hide-details class="mt-0 mb-2" :label="$t('plugins.WorkshopService.audit.only_refused')" />
				<v-alert v-if="error" density="compact" variant="tonal" type="error" class="mb-2">{{ error }}</v-alert>
				<v-table density="compact">
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
							<td class="text-body-small" style="white-space:nowrap">{{ r.ts.replace('T', ' ') }}</td>
							<td>
								{{ r.user || '-' }}
								<v-chip v-if="r.role" size="x-small" label variant="outlined" class="ml-1">{{ roleName(r.role) }}</v-chip>
							</td>
							<td>
								<code>{{ r.op }}</code>
								<div v-if="r.args" class="text-body-small text-medium-emphasis" style="max-width:420px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" :title="r.args">{{ r.args }}</div>
							</td>
							<td>
								<v-chip size="x-small" label variant="flat" :color="r.ok ? 'success' : 'error'">{{ r.ok ? $t('plugins.WorkshopService.audit.ok') : (r.code || $t('plugins.WorkshopService.audit.failed')) }}</v-chip>
							</td>
							<td class="text-body-small">
								<span :title="r.device">{{ (r.device || '').slice(0, 8) }}</span>
								<div class="text-medium-emphasis">{{ r.ip }}</div>
							</td>
						</tr>
						<tr v-if="!rows.length && !loading"><td colspan="5" class="text-center text-medium-emphasis">{{ $t('plugins.WorkshopService.common.no_data') }}</td></tr>
					</tbody>
				</v-table>
				<div class="d-flex align-center mt-2">
					<span class="text-body-small text-medium-emphasis">{{ $t('plugins.WorkshopService.audit.count', { shown: rows.length, total }) }}</span>
					<v-spacer />
					<v-btn size="small" variant="text" :disabled="offset === 0" @click="move(-1)"><v-icon size="small">mdi-chevron-left</v-icon></v-btn>
					<v-btn size="small" variant="text" :disabled="offset + PAGE >= total" @click="move(1)"><v-icon size="small">mdi-chevron-right</v-icon></v-btn>
				</div>
				<div class="text-body-small text-medium-emphasis mt-2">{{ $t('plugins.WorkshopService.audit.kept') }}</div>
			</template>
		</v-card-text>
	</v-card>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { i18n } from './dwc-host.js'
import { api, currentIdentity, onIdentity } from './workshop-api.js'

const PAGE = 50

function day(offsetDays) {
	const d = new Date(Date.now() - offsetDays * 86400000)
	const p = n => String(n).padStart(2, '0')
	return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate())
}

const f = ref({ from: day(7), to: day(0), user: null, op: '', errors: false })
const rows = ref([])
const total = ref(0)
const users = ref([])
const offset = ref(0)
const loading = ref(false)
const error = ref('')
const identity = ref(currentIdentity())
let off = null

const isAdmin = computed(() => !!identity.value && identity.value.role === 'admin')
const userItems = computed(() => users.value)

watch(f, () => { offset.value = 0; read() }, { deep: true })

onMounted(() => {
	off = onIdentity(i => { identity.value = i; if (isAdmin.value) read() })
	if (isAdmin.value) read()
})
onBeforeUnmount(() => { if (off) off() })

function roleName(r) { const k = 'plugins.WorkshopService.users.role_' + r; return i18n.te(k) ? i18n.t(k) : r }
function move(dir) { offset.value = Math.max(0, offset.value + dir * PAGE); read() }
async function read() {
	loading.value = true
	try {
		const q = f.value
		const r = await api('audit.list', { from: q.from || undefined, to: q.to || undefined, user: q.user || undefined, op: q.op || undefined, errors: !!q.errors, limit: PAGE, offset: offset.value }, { noLogin: true })
		rows.value = r.rows || []
		total.value = r.total || 0
		users.value = r.users || []
		error.value = ''
	} catch (e) {
		error.value = e.code === 'cancelled' ? '' : (e.message || String(e))
	}
	loading.value = false
}
</script>
