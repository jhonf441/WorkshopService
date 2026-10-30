<template>
	<v-card class="mb-3">
		<!-- Configuration package (2026-10-24). API: package.export / package.preview / package.apply.
		     Settings of the pages, work zones, the person's macros and the machine modes in one zip; no secrets.
		     Importing never overwrites: it shows what it would do first and keeps what is already there. -->
		<v-card-title class="d-flex align-center flex-wrap" style="gap:8px">
			<span><v-icon size="small" class="mr-2 svx-ico">mdi-package-variant-closed</v-icon>{{ $t(T + 'title') }}</span>
		</v-card-title>
		<v-card-text>
			<div class="text-body-medium mb-3">{{ $t(T + 'intro') }}</div>
			<div v-if="msg" class="text-body-medium mb-2" :class="msgOk ? 'text-success' : 'text-error'">{{ msg }}</div>

			<!-- export -->
			<div class="text-title-small">{{ $t(T + 'export_title') }}</div>
			<div class="d-flex flex-wrap align-center" style="gap:12px">
				<v-checkbox v-for="c in categories" :key="'x' + c" v-model="chosen" :value="c" density="compact" hide-details class="mt-0 pt-0"
					:label="$t(T + 'cat_' + c)" />
			</div>
			<div class="text-body-small text-medium-emphasis mb-2">{{ $t(T + 'export_note') }}</div>
			<v-btn size="small" color="primary" :loading="exporting" :disabled="!chosen.length || !can('package.export')" @click="exportPackage()">
				<v-icon size="small" start>mdi-download</v-icon>{{ $t(T + 'download') }}
			</v-btn>
			<div v-for="s in skipped" :key="s.path" class="text-body-small text-warning mt-1">
				<code>{{ s.path }}</code> &middot; {{ $t(T + 'skipped_' + s.reason) }}
			</div>

			<v-divider class="my-4" />

			<!-- import -->
			<div class="text-title-small">{{ $t(T + 'import_title') }}</div>
			<div class="text-body-small text-medium-emphasis mb-2">{{ $t(T + 'import_note') }}</div>
			<div class="text-body-small text-medium-emphasis mb-2">{{ $t(T + 'secrets_note') }}</div>
			<v-file-input :model-value="file" density="compact" variant="outlined" hide-details accept=".zip" :label="$t(T + 'choose_file')" prepend-icon="mdi-package-down"
				:disabled="!can('package.preview')" class="mb-2" @update:model-value="onFile" />
			<template v-if="items">
				<div v-if="!items.length" class="text-medium-emphasis">{{ $t(T + 'empty') }}</div>
				<v-table v-else density="compact" class="mb-2">
					<tbody>
						<tr v-for="i in items" :key="i.path">
							<td style="width:1%">
								<v-checkbox v-if="i.action === 'conflict'" v-model="replace" :value="i.path" density="compact" hide-details class="mt-0 pt-0"
									:title="$t(T + 'replace_this')" />
							</td>
							<td><code class="text-body-small">{{ i.path }}</code></td>
							<td class="text-right" style="white-space:nowrap">
								<v-chip size="x-small" variant="outlined" :color="color(i.action)">{{ $t(T + 'act_' + i.action) }}</v-chip>
							</td>
						</tr>
					</tbody>
				</v-table>
				<div v-if="hasConflict" class="text-body-small mb-2">{{ $t(T + 'conflict_help') }}</div>
				<div v-if="hasReference" class="text-body-small mb-2">{{ $t(T + 'reference_help') }}</div>
				<v-btn size="small" color="primary" :loading="applying" :disabled="!todo || !can('package.apply')" @click="apply()">
					<v-icon size="small" start>mdi-package-down</v-icon>{{ $t(T + 'import', { n: todo }) }}
				</v-btn>
				<span v-if="!can('package.apply')" class="text-body-small text-medium-emphasis ml-2">{{ $t(T + 'admin_only') }}</span>
			</template>
		</v-card-text>
	</v-card>
</template>

<script setup>
import { computed, ref } from 'vue'
import { i18n } from './dwc-host.js'
import { api, workshopCan } from './workshop-api.js'

const T = 'plugins.WorkshopService.package.'
const categories = ['config', 'zones', 'macros', 'system']
const COLORS = { create: 'success', same: undefined, conflict: 'warning', reference: 'info', skip: undefined }

// bytes <-> base64 in slices (a big string.fromCharCode(...bytes) overflows the stack)
function toBase64(buffer) {
	const bytes = new Uint8Array(buffer)
	let s = ''
	for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000))
	return btoa(s)
}
function fromBase64(text) {
	const s = atob(text)
	const out = new Uint8Array(s.length)
	for (let i = 0; i < s.length; i++) out[i] = s.charCodeAt(i)
	return out
}

const chosen = ref(['config', 'zones', 'macros', 'system'])
const skipped = ref([])
const exporting = ref(false)
const file = ref(null)
const payload = ref('')
const items = ref(null)
const replace = ref([])
const applying = ref(false)
const msg = ref('')
const msgOk = ref(true)

const hasConflict = computed(() => (items.value || []).some(i => i.action === 'conflict'))
const hasReference = computed(() => (items.value || []).some(i => i.action === 'reference'))
// files that importing will write: the ones to create, the reference copies and the conflicts the person ticked
const todo = computed(() => (items.value || []).filter(i => i.action === 'create' || i.action === 'reference' || (i.action === 'conflict' && replace.value.includes(i.path))).length)

function can(op) { return workshopCan(op) }
function color(a) { return COLORS[a] }
function say(text, ok) { msg.value = text; msgOk.value = ok !== false }
async function exportPackage() {
	exporting.value = true
	msg.value = ''
	try {
		const r = await api('package.export', { categories: chosen.value })
		skipped.value = r.skipped || []
		const url = URL.createObjectURL(new Blob([fromBase64(r.data)], { type: 'application/zip' }))
		const a = document.createElement('a')
		a.href = url
		a.download = r.name
		document.body.appendChild(a)
		a.click()
		a.remove()
		setTimeout(() => URL.revokeObjectURL(url), 10000)
		say(i18n.t(T + 'exported', { n: r.manifest.files.length }))
	} catch (e) {
		say(e.message, false)
	} finally {
		exporting.value = false
	}
}
// Vuetify 4 file input: the model is a File, or a list of files, or null
function onFile(value) {
	file.value = value
	preview()
}
async function preview() {
	items.value = null
	replace.value = []
	msg.value = ''
	const chosenFile = Array.isArray(file.value) ? file.value[0] : file.value
	if (!chosenFile) return
	try {
		payload.value = toBase64(await chosenFile.arrayBuffer())
		const r = await api('package.preview', { data: payload.value })
		items.value = r.items
	} catch (e) {
		say(e.message, false)
	}
}
async function apply() {
	applying.value = true
	try {
		const r = await api('package.apply', { data: payload.value, replace: replace.value })
		const errors = Object.keys(r.errors || {}).length
		await preview()
		say(i18n.t(T + 'applied', { created: r.created.length, replaced: r.replaced.length, kept: r.kept.length, reference: r.reference.length }) + (errors ? ' ' + i18n.t(T + 'applied_errors', { n: errors }) : ''), !errors)
	} catch (e) {
		say(e.message, false)
	} finally {
		applying.value = false
	}
}
</script>
