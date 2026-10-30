<template>
	<div v-if="op" class="svc-api-det mb-3">
		<div class="text-caption grey--text mb-1">{{ $t('plugins.WorkshopService.apiDetail.what_it_sends') }}</div>
		<v-simple-table v-if="args.length" dense class="mb-2">
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
					<td><code>{{ a.name }}</code><v-chip v-if="a.required" x-small label color="error" dark class="ml-1">{{ $t('plugins.WorkshopService.apiDetail.required') }}</v-chip></td>
					<td>{{ kind(a.type) }}</td>
					<td class="text-caption">{{ rules(a) }}</td>
					<td class="text-caption">{{ a.desc || '-' }}</td>
				</tr>
			</tbody>
		</v-simple-table>
		<div v-else class="text-body-2 mb-2">{{ $t('plugins.WorkshopService.apiDetail.no_arguments') }}</div>

		<div class="text-caption grey--text mb-1">{{ $t('plugins.WorkshopService.apiDetail.who_can_call') }}</div>
		<div class="mb-2">
			<v-chip x-small label class="mr-1" color="primary" dark>{{ $t('plugins.WorkshopService.apiDetail.via_session') }}</v-chip>
			<v-chip x-small label class="mr-1" :color="admin ? 'grey' : 'success'" dark>{{ $t('plugins.WorkshopService.apiDetail.via_local_key') }}{{ admin ? ': ' + $t('plugins.WorkshopService.apiDetail.no') : '' }}</v-chip>
			<v-chip x-small label class="mr-1" :color="admin ? 'grey' : 'success'" dark>{{ $t('plugins.WorkshopService.apiDetail.via_service_key') }}{{ admin ? ': ' + $t('plugins.WorkshopService.apiDetail.no') : '' }}</v-chip>
			<v-chip x-small label class="mr-1" :color="op.macro ? 'success' : 'grey'" dark>{{ $t('plugins.WorkshopService.apiDetail.via_macro') }}{{ op.macro ? '' : ': ' + $t('plugins.WorkshopService.apiDetail.no') }}</v-chip>
		</div>
		<div class="text-caption mb-2">
			<div>{{ $t('plugins.WorkshopService.apiDetail.class_is', { c: op.kind }) }}</div>
			<div v-if="op.confirm">{{ $t('plugins.WorkshopService.apiDetail.asks_confirmation', { n: op.confirm.level || 3 }) }}</div>
			<div v-if="op.motion">{{ $t('plugins.WorkshopService.apiDetail.asks_motion_owner', { c: op.motion }) }}</div>
			<div v-if="op.slow">{{ $t('plugins.WorkshopService.apiDetail.may_take_long') }}</div>
			<div v-if="op.extra_args">{{ $t('plugins.WorkshopService.apiDetail.extra_args') }}</div>
		</div>

		<div class="d-flex align-center mb-1" style="gap:8px">
			<span class="text-caption grey--text">{{ $t('plugins.WorkshopService.apiDetail.request') }}</span>
			<v-btn x-small text :aria-label="$t('plugins.WorkshopService.apiDetail.copy_what', { what: $t('plugins.WorkshopService.apiDetail.request') })" @click="doCopy(request, 'request')">
				<v-icon x-small left>{{ copied === 'request' ? 'mdi-check' : 'mdi-content-copy' }}</v-icon>{{ copied === 'request' ? $t('plugins.WorkshopService.apiDetail.copied') : $t('plugins.WorkshopService.apiDetail.copy') }}
			</v-btn>
		</div>
		<pre class="pa-2 svc-use" style="white-space:pre-wrap;word-break:break-all">{{ request }}</pre>
		<div class="d-flex align-center mb-1 mt-2" style="gap:8px">
			<span class="text-caption grey--text">{{ $t('plugins.WorkshopService.apiDetail.curl') }}</span>
			<v-btn x-small text :aria-label="$t('plugins.WorkshopService.apiDetail.copy_what', { what: $t('plugins.WorkshopService.apiDetail.curl') })" @click="doCopy(curl, 'curl')">
				<v-icon x-small left>{{ copied === 'curl' ? 'mdi-check' : 'mdi-content-copy' }}</v-icon>{{ copied === 'curl' ? $t('plugins.WorkshopService.apiDetail.copied') : $t('plugins.WorkshopService.apiDetail.copy') }}
			</v-btn>
		</div>
		<pre class="pa-2 svc-use" style="white-space:pre-wrap;word-break:break-all">{{ curl }}</pre>
		<template v-if="op.macro">
		<div class="d-flex align-center mb-1 mt-2" style="gap:8px">
			<span class="text-caption grey--text">{{ $t('plugins.WorkshopService.apiDetail.from_a_macro') }}</span>
			<v-btn x-small text :aria-label="$t('plugins.WorkshopService.apiDetail.copy_what', { what: $t('plugins.WorkshopService.apiDetail.from_a_macro') })" @click="doCopy(macro, 'macro')">
				<v-icon x-small left>{{ copied === 'macro' ? 'mdi-check' : 'mdi-content-copy' }}</v-icon>{{ copied === 'macro' ? $t('plugins.WorkshopService.apiDetail.copied') : $t('plugins.WorkshopService.apiDetail.copy') }}
			</v-btn>
		</div>
			<pre class="pa-2 svc-use" style="white-space:pre-wrap;word-break:break-all">{{ macro }}</pre>
		</template>
		<div class="text-caption grey--text mt-2">{{ $t('plugins.WorkshopService.apiDetail.answer') }}</div>
		<pre class="pa-2 svc-use" style="white-space:pre-wrap">{{ response }}</pre>
	</div>
</template>

<script>
'use strict'

// Detail of one API operation, built from api.describe (nothing is written by hand per operation):
// the arguments with their rules, who can call it, what it asks before running and the exact
// request / curl / macro line to use it.
import { copyText } from './copy.js'

export default {
	name: 'ApiDetail',
	props: {
		op: { type: Object, default: null }
	},
	data() {
		return { copied: '' };
	},
	methods: {
		// the request, the curl and the macro line copy to the clipboard (copy.js works over http too)
		async doCopy(text, id) {
			if (!(await copyText(text))) return;
			this.copied = id;
			setTimeout(() => { if (this.copied === id) this.copied = ''; }, 1500);
		}
	},
	computed: {
		admin() { return !!this.op && this.op.kind === 'admin'; },
		args() {
			const a = (this.op && this.op.args) || {};
			return Object.keys(a).map(k => Object.assign({ name: k }, a[k]));
		},
		example() {
			const out = {};
			this.args.forEach(a => {
				if (!a.required) return;
				if (a.choices && a.choices.length) out[a.name] = a.choices[0];
				else out[a.name] = ({ int: 0, num: 0, bool: true, obj: {}, list: [], any: '' })[a.type] !== undefined ? ({ int: 0, num: 0, bool: true, obj: {}, list: [], any: '' })[a.type] : 'text';
			});
			return out;
		},
		request() {
			return JSON.stringify({ op: this.op.op, args: this.example, origin: 'external:my-service' }, null, 2);
		},
		curl() {
			const host = (typeof location !== 'undefined' && location.host) || 'duet3.local';
			const body = JSON.stringify({ op: this.op.op, args: this.example });
			return "curl -s -X POST http://" + host + "/machine/WorkshopService/api \\\n  -H 'X-Workshop-Key: wk_...' -H 'Content-Type: application/json' \\\n  -d '" + body + "'";
		},
		macro() {
			const kv = Object.keys(this.example).map(k => k + '=' + (typeof this.example[k] === 'object' ? '...' : this.example[k])).join(',');
			return 'M98 P"0:/sys/workshop/macros/service-call.g" S"' + this.op.op + '"' + (kv ? ' A"' + kv + '"' : '') + ' Q1';
		},
		response() {
			return '{ "ok": true, "op": "' + this.op.op + '", "result": ..., "message": null }\n{ "ok": false, "op": "' + this.op.op + '", "error": { "code": "invalid_args | forbidden | confirm_required | motion_denied | failed | busy", "message": "..." } }';
		}
	},
	methods: {
		kind(t) {
			const k = 'plugins.WorkshopService.apiDetail.type_' + t;
			return this.$te(k) ? this.$t(k) : t;
		},
		rules(a) {
			const r = [];
			if (a.choices && a.choices.length) r.push(this.$t('plugins.WorkshopService.apiDetail.one_of') + ' ' + a.choices.join(' | '));
			if (a.min !== undefined) r.push('>= ' + a.min);
			if (a.max !== undefined) r.push('<= ' + a.max);
			if (a.default !== undefined) r.push(this.$t('plugins.WorkshopService.apiDetail.default') + ': ' + JSON.stringify(a.default));
			return r.join('; ') || '-';
		}
	}
};
</script>
