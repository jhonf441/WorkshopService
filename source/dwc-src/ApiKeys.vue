<template>
	<v-card class="mb-3">
		<v-card-title>
			<v-icon size="small" class="mr-2 svx-ico">mdi-key-chain</v-icon>{{ $t('plugins.WorkshopService.keys.title') }}
			<v-spacer />
			<v-btn size="small" color="primary" variant="flat" @click="openNew"><v-icon size="small" start>mdi-plus</v-icon>{{ $t('plugins.WorkshopService.keys.new_key') }}</v-btn>
		</v-card-title>
		<v-card-text>
			<div class="wf-help mb-2">{{ $t('plugins.WorkshopService.keys.intro') }}</div>
			<details class="wf-more mb-3">
				<summary>{{ $t('plugins.WorkshopService.servicePage.how_it_works') }}</summary>
				<p>{{ $t('plugins.WorkshopService.keys.how_to_use') }}</p>
			</details>
			<v-alert v-if="error" density="compact" variant="tonal" type="error" class="mb-2">{{ error }}</v-alert>
			<div v-if="!keys.length && !loading" class="text-body-medium text-medium-emphasis">{{ $t('plugins.WorkshopService.keys.none') }}</div>
			<v-table v-else density="compact">
				<thead>
					<tr>
						<th>{{ $t('plugins.WorkshopService.keys.col_name') }}</th>
						<th>{{ $t('plugins.WorkshopService.keys.col_allows') }}</th>
						<th>{{ $t('plugins.WorkshopService.keys.col_last_use') }}</th>
						<th>{{ $t('plugins.WorkshopService.keys.col_expires') }}</th>
						<th>{{ $t('plugins.WorkshopService.keys.col_active') }}</th>
						<th />
					</tr>
				</thead>
				<tbody>
					<tr v-for="k in keys" :key="k.id" :class="{ 'text-medium-emphasis': isExpired(k) }">
						<td>
							<strong>{{ k.name }}</strong>
							<div class="text-body-small text-medium-emphasis"><code>{{ k.prefix }}...</code></div>
						</td>
						<td>
							<v-chip v-for="c in k.kinds" :key="c" size="x-small" label class="mr-1" :color="colorClass(c)" variant="flat">{{ nameClass(c) }}</v-chip>
							<div class="text-body-small text-medium-emphasis">{{ $t('plugins.WorkshopService.keys.can_call', { n: howmany(k) }) }}</div>
							<div v-if="k.ops.length" class="mt-1">
								<span class="text-body-small text-medium-emphasis mr-1">{{ $t('plugins.WorkshopService.keys.list_extra') }}</span>
								<v-chip v-for="o in k.ops" :key="'p' + o" size="x-small" label variant="outlined" class="mr-1 mb-1" :title="descriptionOp(o)"><code>{{ o }}</code></v-chip>
							</div>
							<div v-if="k.deny.length" class="mt-1">
								<span class="text-body-small text-medium-emphasis mr-1">{{ $t('plugins.WorkshopService.keys.list_refused') }}</span>
								<v-chip v-for="o in k.deny" :key="'d' + o" size="x-small" label variant="outlined" color="error" class="mr-1 mb-1" :title="descriptionOp(o)"><code>{{ o }}</code></v-chip>
							</div>
						</td>
						<td class="text-body-small">{{ k.last_used ? date(k.last_used) + ' (' + k.uses + ')' : $t('plugins.WorkshopService.keys.never_used') }}</td>
						<td class="text-body-small">
							{{ k.expires ? date(k.expires) : $t('plugins.WorkshopService.keys.no_expiry') }}
							<div v-if="isExpired(k)"><v-chip size="x-small" label color="error" variant="flat">{{ $t('plugins.WorkshopService.keys.expired') }}</v-chip></div>
							<div v-else-if="expiresSoon(k)"><v-chip size="x-small" label color="warning" variant="flat">{{ $t('plugins.WorkshopService.keys.expires_soon') }}</v-chip></div>
						</td>
						<td>
							<v-switch :model-value="k.enabled" density="compact" hide-details color="primary" :disabled="isExpired(k)" @update:model-value="v => enable(k, v)" />
							<div v-if="isExpired(k)" class="text-body-small text-medium-emphasis">{{ $t('plugins.WorkshopService.keys.expired_hint') }}</div>
						</td>
						<td class="text-right" style="white-space:nowrap">
							<v-btn variant="text" icon size="small" :title="$t('plugins.WorkshopService.keys.edit')" @click="openEdit(k)"><v-icon size="small">mdi-pencil</v-icon></v-btn>
							<v-btn variant="text" icon size="small" color="error" :title="$t('plugins.WorkshopService.keys.revoke')" @click="revoke(k)"><v-icon size="small">mdi-delete</v-icon></v-btn>
						</td>
					</tr>
				</tbody>
			</v-table>
		</v-card-text>

		<!-- create / edit -->
		<v-dialog v-model="dlg" max-width="640" scrollable>
			<v-card>
				<v-card-title class="text-title-medium">{{ form.id ? $t('plugins.WorkshopService.keys.edit_title') : $t('plugins.WorkshopService.keys.new_title') }}</v-card-title>
				<v-card-text>
					<v-text-field v-model="form.name" :label="$t('plugins.WorkshopService.keys.service_name')" density="compact" variant="outlined" counter="40" :rules="[v => !!v || '']" />
					<v-select
						v-if="!form.id" :model-value="form.preset" :items="presetItems" item-title="text" item-value="value" :label="$t('plugins.WorkshopService.keys.starting_point')"
						density="compact" variant="outlined" hide-details class="mb-3" @update:model-value="applyPreset"
					/>
					<div class="text-body-small text-medium-emphasis mb-1">{{ $t('plugins.WorkshopService.keys.classes') }}</div>
					<div class="d-flex flex-wrap mb-2">
						<v-checkbox
							v-for="c in classes" :key="c" v-model="form.kinds" :value="c" density="compact" hide-details class="mr-4 mt-0"
							:label="nameClass(c)"
						/>
					</div>
					<div class="text-body-small text-medium-emphasis mb-2">{{ $t('plugins.WorkshopService.keys.classes_help') }}</div>
					<v-combobox
						:model-value="form.ops" :items="opItems" item-title="text" item-value="value" multiple chips closable-chips
						:label="$t('plugins.WorkshopService.keys.extra_operations')" :hint="$t('plugins.WorkshopService.keys.patterns_help')"
						persistent-hint density="compact" variant="outlined" :return-object="false" @update:model-value="v => form.ops = norm(v)"
					>
						<template #item="{ props: itemProps, item }">
							<v-list-item v-bind="itemProps">
								<template #title><code>{{ item.raw.value }}</code> <span class="text-body-small text-medium-emphasis">{{ item.raw.cssClass }}</span></template>
								<template #subtitle>{{ item.raw.desc }}</template>
							</v-list-item>
						</template>
					</v-combobox>
					<v-combobox
						:model-value="form.deny" :items="opItems" item-title="text" item-value="value" multiple chips closable-chips
						:label="$t('plugins.WorkshopService.keys.refused_operations')" :hint="$t('plugins.WorkshopService.keys.patterns_help')"
						persistent-hint density="compact" variant="outlined" class="mt-2" :return-object="false" @update:model-value="v => form.deny = norm(v)"
					>
						<template #item="{ props: itemProps, item }">
							<v-list-item v-bind="itemProps">
								<template #title><code>{{ item.raw.value }}</code> <span class="text-body-small text-medium-emphasis">{{ item.raw.cssClass }}</span></template>
								<template #subtitle>{{ item.raw.desc }}</template>
							</v-list-item>
						</template>
					</v-combobox>
					<v-text-field
						v-model="form.days" type="number" min="0" :label="$t('plugins.WorkshopService.keys.valid_days')" :hint="$t('plugins.WorkshopService.keys.valid_days_help')"
						persistent-hint density="compact" variant="outlined" class="mt-2" style="max-width:280px"
					/>
					<v-alert density="compact" variant="tonal" type="info" class="mt-3 mb-0">
						{{ $t('plugins.WorkshopService.keys.preview', { n: viewPreview.length }) }}
						<div class="text-body-small" style="max-height:110px;overflow:auto">{{ viewPreview.join(', ') || '-' }}</div>
					</v-alert>
					<v-alert density="compact" variant="tonal" type="warning" class="mt-2 mb-0">{{ $t('plugins.WorkshopService.keys.never_admin') }}</v-alert>
					<v-alert v-if="errorForm" density="compact" variant="tonal" type="error" class="mt-2 mb-0">{{ errorForm }}</v-alert>
				</v-card-text>
				<v-card-actions>
					<v-spacer />
					<v-btn variant="text" @click="dlg = false">{{ $t('plugins.WorkshopService.common.cancel') }}</v-btn>
					<v-btn color="primary" :loading="saving" @click="save">{{ form.id ? $t('plugins.WorkshopService.keys.save') : $t('plugins.WorkshopService.keys.create') }}</v-btn>
				</v-card-actions>
			</v-card>
		</v-dialog>

		<!-- the key, shown once -->
		<v-dialog v-model="dlgKey" max-width="640" persistent>
			<v-card>
				<v-card-title class="text-title-medium">{{ $t('plugins.WorkshopService.keys.your_key') }}</v-card-title>
				<v-card-text>
					<v-alert density="compact" variant="tonal" type="warning">{{ $t('plugins.WorkshopService.keys.shown_once') }}</v-alert>
					<div class="d-flex align-center">
						<code class="d-block pa-2 flex-grow-1" style="word-break:break-all">{{ keyNew }}</code>
						<v-btn variant="text" icon size="small" class="ml-1" @click="copy(keyNew, 'key', $event)"><v-icon size="small">{{ copied === 'key' ? 'mdi-check' : 'mdi-content-copy' }}</v-icon></v-btn>
					</div>
					<div class="text-body-small text-medium-emphasis mt-3 mb-1">{{ $t('plugins.WorkshopService.keys.example') }}</div>
					<div class="d-flex align-start">
						<code class="d-block pa-2 flex-grow-1" style="white-space:pre-wrap;word-break:break-all">{{ exampleCurl }}</code>
						<v-btn variant="text" icon size="small" class="ml-1" @click="copy(exampleCurl, 'curl', $event)"><v-icon size="small">{{ copied === 'curl' ? 'mdi-check' : 'mdi-content-copy' }}</v-icon></v-btn>
					</div>
				</v-card-text>
				<v-card-actions>
					<v-spacer />
					<v-btn color="primary" @click="dlgKey = false; keyNew = ''">{{ $t('plugins.WorkshopService.keys.i_copied_it') }}</v-btn>
				</v-card-actions>
			</v-card>
		</v-dialog>
	</v-card>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { i18n } from './dwc-host.js'
import { api } from './workshop-api.js'
import { copyText } from './copy.js'

// Same rule as Registry._key_allows / api_keys.allows (workshop_api.py): the class or a pattern allows,
// a deny pattern refuses, administration never.
function matches(pattern, name) {
	const re = new RegExp('^' + pattern.replace(/[.+^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*').replace(/\?/g, '.') + '$')
	return re.test(name)
}
const classes = ['read', 'write', 'motion', 'stop', 'power']
const colors = { read: 'blue-grey', write: 'orange', motion: 'deep-purple', stop: 'red', power: 'red-darken-3' }
const PRESETS = ['read', 'lights_air', 'notify', 'control', 'full', 'custom']

function list(txt) {
	return String(txt || '').split(/[\s,]+/).map(x => x.trim().toLowerCase()).filter(Boolean)
}
// the lists of the dialog are arrays (chips): the typed patterns are normalised like the text before
function norm(v) {
	return Array.isArray(v) ? [...new Set(v.map(x => String(x).trim().toLowerCase()).filter(Boolean))] : list(v)
}

const props = defineProps({
	// api.describe of the service: [{op, kind, desc, args...}]
	operations: { type: Array, default: () => [] }
})

const keys = ref([])
const presets = ref({})
const loading = ref(true)
const error = ref('')
const dlg = ref(false)
const saving = ref(false)
const errorForm = ref('')
const form = ref({ id: '', name: '', preset: 'read', kinds: ['read'], ops: [], deny: [], days: '' })
const dlgKey = ref(false)
const keyNew = ref('')
const copied = ref('')

const presetItems = computed(() => PRESETS.map(p => ({ value: p, text: i18n.t('plugins.WorkshopService.keys.preset_' + p) })))
const viewPreview = computed(() => {
	const rec = { kinds: form.value.kinds, ops: norm(form.value.ops), deny: norm(form.value.deny) }
	return allowed(rec)
})
// every operation of the service (except administration, never given to a key) to pick from
const opItems = computed(() => props.operations.filter(o => o.kind !== 'admin').map(o => ({ text: o.op, value: o.op, cssClass: nameClass(o.kind), desc: o.desc || '' })))
const exampleCurl = computed(() => {
	const host = (typeof location !== 'undefined' && location.host) || 'duet3.local'
	return "curl -s -X POST http://" + host + "/machine/WorkshopService/api \\\n  -H 'Content-Type: application/json' -H 'X-Workshop-Key: " + keyNew.value + "' \\\n  -d '{\"op\":\"api.ping\",\"args\":{}}'"
})

onMounted(() => { read() })

function nameClass(c) { return i18n.t('plugins.WorkshopService.keys.class_' + c) }
function colorClass(c) { return colors[c] || 'grey' }
function isExpired(k) { return !!k.expires && k.expires * 1000 < Date.now() }
function expiresSoon(k) { return !!k.expires && !isExpired(k) && k.expires * 1000 - Date.now() < 7 * 86400000 }
function date(t) { try { return new Date(t * 1000).toLocaleString(i18n.locale) } catch (e) { return String(t) } }
function allowed(rec) {
	return props.operations.filter(o => {
		if (o.kind === 'admin') return false
		if ((rec.deny || []).some(p => matches(p, o.op))) return false
		return (rec.kinds || []).includes(o.kind) || (rec.ops || []).some(p => matches(p, o.op))
	}).map(o => o.op)
}
function howmany(k) { return allowed(k).length }
// what an operation (or a pattern) is: its description, or how many operations a pattern covers
function descriptionOp(p) {
	const o = props.operations.find(x => x.op === p)
	if (o) return o.desc || p
	const n = props.operations.filter(x => x.kind !== 'admin' && matches(p, x.op)).length
	return i18n.t('plugins.WorkshopService.keys.pattern_covers', { n })
}
async function read() {
	loading.value = true
	try {
		const r = await api('keys.list')
		keys.value = (r && r.keys) || []
		presets.value = (r && r.presets) || {}
		error.value = ''
	} catch (e) {
		error.value = e.message || String(e)
	}
	loading.value = false
}
function openNew() {
	errorForm.value = ''
	form.value = { id: '', name: '', preset: 'read', kinds: ['read'], ops: [], deny: [], days: '' }
	dlg.value = true
}
function openEdit(k) {
	errorForm.value = ''
	form.value = { id: k.id, name: k.name, preset: 'custom', kinds: k.kinds.slice(), ops: k.ops.slice(), deny: k.deny.slice(), days: '' }
	dlg.value = true
}
// the starting point was chosen: it fills the classes and the extra operations
function applyPreset(p) {
	form.value.preset = p
	const d = presets.value[p]
	if (!d) return
	form.value.kinds = (d.kinds || []).slice()
	form.value.ops = (d.ops || []).slice()
}
async function save() {
	saving.value = true
	errorForm.value = ''
	const f = form.value
	try {
		if (f.id) {
			const args = { id: f.id, name: f.name, kinds: f.kinds, ops: norm(f.ops), deny: norm(f.deny) }
			if (f.days !== '' && f.days !== null) args.days = Number(f.days)
			await api('keys.update', args)
			dlg.value = false
		} else {
			const args = { name: f.name, kinds: f.kinds, ops: norm(f.ops), deny: norm(f.deny) }
			if (f.days !== '' && f.days !== null && Number(f.days) > 0) args.days = Number(f.days)
			const r = await api('keys.create', args)
			dlg.value = false
			keyNew.value = (r && r.key) || ''
			dlgKey.value = !!keyNew.value
		}
		await read()
	} catch (e) {
		if (e.code !== 'cancelled') errorForm.value = e.message || String(e)
	}
	saving.value = false
}
async function enable(k, v) {
	try {
		await api('keys.update', { id: k.id, enabled: !!v })
	} catch (e) {
		error.value = e.message || String(e)
	}
	await read()
}
async function revoke(k) {
	try {
		await api('keys.revoke', { id: k.id })
	} catch (e) {
		if (e.code !== 'cancelled') error.value = e.message || String(e)
	}
	await read()
}
// the buttons are inside a dialog: the copy happens inside it (see copy.js); only says "copied" if it was
async function copy(txt, id, ev) {
	const cont = ev && ev.currentTarget ? ev.currentTarget.closest('.v-card') : null
	const ok = await copyText(txt, cont)
	if (!ok) return
	copied.value = id
	setTimeout(() => { if (copied.value === id) copied.value = '' }, 1500)
}
</script>
