<template>
	<div v-if="op" class="svc-api-det mb-3">
		<div class="text-body-small text-medium-emphasis mb-1">{{ $t('plugins.WorkshopService.apiDetail.what_it_sends') }}</div>
		<v-table v-if="args.length" density="compact" class="mb-2">
			<thead>
				<tr>
					<th>{{ $t('plugins.WorkshopService.apiDetail.argument') }}</th>
					<th>{{ $t('plugins.WorkshopService.apiDetail.type') }}</th>
					<th>{{ $t('plugins.WorkshopService.apiDetail.rules') }}</th>
					<th>{{ $t('plugins.WorkshopService.apiDetail.meaning') }}</th>
				</tr>
			</thead>
			<tbody>
				<tr v-for="a in args" :key="a.name">
					<td><code>{{ a.name }}</code><v-chip v-if="a.required" size="x-small" label color="error" variant="flat" class="ml-1">{{ $t('plugins.WorkshopService.apiDetail.required') }}</v-chip></td>
					<td>{{ kind(a.type) }}</td>
					<td class="text-body-small">{{ rules(a) }}</td>
					<td class="text-body-small">{{ a.desc || '-' }}</td>
				</tr>
			</tbody>
		</v-table>
		<div v-else class="text-body-medium mb-2">{{ $t('plugins.WorkshopService.apiDetail.no_arguments') }}</div>

		<div class="text-body-small text-medium-emphasis mb-1">{{ $t('plugins.WorkshopService.apiDetail.who_can_call') }}</div>
		<div class="mb-2">
			<v-chip size="x-small" label class="mr-1" color="primary" variant="flat">{{ $t('plugins.WorkshopService.apiDetail.via_session') }}</v-chip>
			<v-chip size="x-small" label class="mr-1" :color="admin ? 'grey' : 'success'" variant="flat">{{ $t('plugins.WorkshopService.apiDetail.via_local_key') }}{{ admin ? ': ' + $t('plugins.WorkshopService.apiDetail.no') : '' }}</v-chip>
			<v-chip size="x-small" label class="mr-1" :color="admin ? 'grey' : 'success'" variant="flat">{{ $t('plugins.WorkshopService.apiDetail.via_service_key') }}{{ admin ? ': ' + $t('plugins.WorkshopService.apiDetail.no') : '' }}</v-chip>
			<v-chip size="x-small" label class="mr-1" :color="op.macro ? 'success' : 'grey'" variant="flat">{{ $t('plugins.WorkshopService.apiDetail.via_macro') }}{{ op.macro ? '' : ': ' + $t('plugins.WorkshopService.apiDetail.no') }}</v-chip>
		</div>
		<div class="text-body-small mb-2">
			<div>{{ $t('plugins.WorkshopService.apiDetail.class_is', { c: op.kind }) }}</div>
			<div v-if="op.confirm">{{ $t('plugins.WorkshopService.apiDetail.asks_confirmation', { n: op.confirm.level || 3 }) }}</div>
			<div v-if="op.motion">{{ $t('plugins.WorkshopService.apiDetail.asks_motion_owner', { c: op.motion }) }}</div>
			<div v-if="op.slow">{{ $t('plugins.WorkshopService.apiDetail.may_take_long') }}</div>
			<div v-if="op.extra_args">{{ $t('plugins.WorkshopService.apiDetail.extra_args') }}</div>
		</div>

		<div class="text-body-small text-medium-emphasis mb-1">{{ $t('plugins.WorkshopService.apiDetail.request') }}</div>
		<pre class="pa-2 svc-use" style="white-space:pre-wrap;word-break:break-all">{{ request }}</pre>
		<div class="text-body-small text-medium-emphasis mb-1 mt-2">{{ $t('plugins.WorkshopService.apiDetail.curl') }}</div>
		<pre class="pa-2 svc-use" style="white-space:pre-wrap;word-break:break-all">{{ curl }}</pre>
		<template v-if="op.macro">
			<div class="text-body-small text-medium-emphasis mb-1 mt-2">{{ $t('plugins.WorkshopService.apiDetail.from_a_macro') }}</div>
			<pre class="pa-2 svc-use" style="white-space:pre-wrap;word-break:break-all">{{ macro }}</pre>
		</template>
		<div class="text-body-small text-medium-emphasis mt-2">{{ $t('plugins.WorkshopService.apiDetail.answer') }}</div>
		<pre class="pa-2 svc-use" style="white-space:pre-wrap">{{ response }}</pre>
	</div>
</template>

<script setup>
import { computed } from 'vue'
import { i18n } from './dwc-host.js'

// Detail of one API operation, built from api.describe (nothing is written by hand per operation):
// the arguments with their rules, who can call it, what it asks before running and the exact
// request / curl / macro line to use it.
const props = defineProps({
	op: { type: Object, default: null }
})

const admin = computed(() => !!props.op && props.op.kind === 'admin')
const args = computed(() => {
	const a = (props.op && props.op.args) || {}
	return Object.keys(a).map(k => Object.assign({ name: k }, a[k]))
})
const example = computed(() => {
	const out = {}
	args.value.forEach(a => {
		if (!a.required) return
		if (a.choices && a.choices.length) out[a.name] = a.choices[0]
		else out[a.name] = ({ int: 0, num: 0, bool: true, obj: {}, list: [], any: '' })[a.type] !== undefined ? ({ int: 0, num: 0, bool: true, obj: {}, list: [], any: '' })[a.type] : 'text'
	})
	return out
})
const request = computed(() => JSON.stringify({ op: props.op.op, args: example.value, origin: 'external:my-service' }, null, 2))
const curl = computed(() => {
	const host = (typeof location !== 'undefined' && location.host) || 'duet3.local'
	const body = JSON.stringify({ op: props.op.op, args: example.value })
	return "curl -s -X POST http://" + host + "/machine/WorkshopService/api \\n  -H 'X-Workshop-Key: wk_...' -H 'Content-Type: application/json' \\n  -d '" + body + "'"
})
const macro = computed(() => {
	const kv = Object.keys(example.value).map(k => k + '=' + (typeof example.value[k] === 'object' ? '...' : example.value[k])).join(',')
	return 'M98 P"0:/sys/workshop/macros/service-call.g" S"' + props.op.op + '"' + (kv ? ' A"' + kv + '"' : '') + ' Q1'
})
const response = computed(() => '{ "ok": true, "op": "' + props.op.op + '", "result": ..., "message": null }\n{ "ok": false, "op": "' + props.op.op + '", "error": { "code": "invalid_args | forbidden | confirm_required | motion_denied | failed | busy", "message": "..." } }')

function kind(t) {
	const k = 'plugins.WorkshopService.apiDetail.type_' + t
	return i18n.te(k) ? i18n.t(k) : t
}
function rules(a) {
	const r = []
	if (a.choices && a.choices.length) r.push(i18n.t('plugins.WorkshopService.apiDetail.one_of') + ' ' + a.choices.join(' | '))
	if (a.min !== undefined) r.push('>= ' + a.min)
	if (a.max !== undefined) r.push('<= ' + a.max)
	if (a.default !== undefined) r.push(i18n.t('plugins.WorkshopService.apiDetail.default') + ': ' + JSON.stringify(a.default))
	return r.join('; ') || '-'
}
</script>
