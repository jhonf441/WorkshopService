<template>
	<!-- Connections > API reference: every operation of the service, described by the service itself (nothing is written by hand per
	     operation): its arguments, who may call it, what it asks before it runs and the exact request, curl and macro line. Anybody with a
	     session reads it; each operation can be tried from here (a read with one touch, anything that changes something with two). Prop: active. -->
	<div class="sv-links-api">
		<section class="sv-card" aria-labelledby="sv-la-title" data-card="api">
			<div class="sv-card-head">
				<h2 id="sv-la-title"><span class="mdi mdi-api sv-ico" aria-hidden="true" />{{ t('links.api_title') }}</h2>
				<span v-if="ops.length" class="sv-chip">{{ tc('servicePage.n_operations', ops.length, { n: ops.length }) }}</span>
			</div>
			<p class="sv-lead">{{ t('links.api_lead') }}</p>
			<p class="sv-quiet"><a class="sv-btn sv-text" :href="nav.href({ s: 'access', t: 'keys' })" @click="follow($event)">{{ t('links.keys_link') }}</a></p>
			<sv-zone :status="status" :error="apis.error" :lock="apis.lock" :empty-title="t('links.api_none')" @retry="apis.reload()" @sign-in="signIn">
				<div class="sv-tools">
					<label class="sv-field"><span class="mdi mdi-magnify sv-ico sv-ico-s" aria-hidden="true" /><input v-model="q" type="search" :placeholder="t('links.search')" :aria-label="t('links.search')"></label>
					<span class="sv-seg" role="group" :aria-label="t('links.mode_label')">
						<button v-for="m in MODES" :key="m" type="button" :aria-pressed="mode === m ? 'true' : 'false'" :data-mode="m" @click="mode = m">{{ t('links.mode_' + m) }}</button>
					</span>
				</div>
				<div class="sv-seg sv-seg-wrap" role="group" :aria-label="t('links.cats_label')" data-part="cats">
					<button v-for="c in cats" :key="c.id" type="button" :aria-pressed="cat === c.id ? 'true' : 'false'" :data-cat="c.id" @click="pickCat(c.id)"><span class="sv-dot" aria-hidden="true" />{{ t(c.name) }} {{ c.n }}</button>
				</div>
				<div v-if="cat && subs.length > 1" class="sv-seg sv-seg-wrap" role="group" :aria-label="t('links.subs_label')" data-part="subs">
					<button type="button" :aria-pressed="!sub ? 'true' : 'false'" @click="sub = ''">{{ t('links.all') }}</button>
					<button v-for="s in subsShown" :key="s.id" type="button" :aria-pressed="sub === s.id ? 'true' : 'false'" :data-sub="s.id" :title="s.id" @click="sub = sub === s.id ? '' : s.id">{{ s.label }} {{ s.n }}</button>
					<button v-if="subsAll.length > subsShown.length || subsMore" type="button" data-act="subs-more" :aria-expanded="subsMore ? 'true' : 'false'" @click="subsMore = !subsMore">{{ subsMore ? t('links.subs_less') : t('links.subs_more', { n: subsAll.length - SUBS_SHOWN }) }}</button>
				</div>
				<p v-if="!found.length" class="sv-quiet" role="status" data-part="none">{{ t('links.api_no_match') }}</p>
				<div class="sv-legend sv-legend-inline" data-part="legend" :title="t('links.legend_colour')">
					<ul class="sv-legend-list">
						<li><span class="sv-state" data-level="ok"><span class="mdi mdi-eye-outline sv-ico sv-ico-s" aria-hidden="true" />{{ t('links.reads') }}</span><span>{{ t('links.legend_reads').split(':').slice(1).join(':').trim() }}</span></li>
						<li><span class="sv-state" data-level="warn"><span class="mdi mdi-pencil-outline sv-ico sv-ico-s" aria-hidden="true" />{{ t('links.changes') }}</span><span>{{ t('links.legend_changes').split(':').slice(1).join(':').trim() }}</span></li>
					</ul>
				</div>
				<details v-for="o in shown" :key="o.name" class="sv-fold sv-op" :data-cat="catOf(o.name)" :data-op="o.name" @toggle="e => onOpen(o.name, e.target.open)">
					<summary>
						<span class="mdi mdi-chevron-right sv-ico sv-chev" aria-hidden="true" />
						<span class="sv-fold-name"><code class="sv-code">{{ o.name }}</code></span>
						<span class="sv-fold-sum">{{ summary(o.desc) }}</span>
						<span class="sv-state" :data-level="o.read ? 'ok' : 'warn'"><span class="mdi sv-ico sv-ico-s" :class="o.read ? 'mdi-eye-outline' : 'mdi-pencil-outline'" aria-hidden="true" />{{ t(o.read ? 'links.reads' : 'links.changes') }}</span>
					</summary>
					<div v-if="opened[o.name]" class="sv-fold-body">
						<p>{{ o.desc }}</p>
						<table v-if="o.args.length" class="sv-table">
							<caption class="sv-vh">{{ t('apiDetail.what_it_sends') }}</caption>
							<thead><tr><th scope="col">{{ t('apiDetail.argument') }}</th><th scope="col">{{ t('apiDetail.type') }}</th><th scope="col">{{ t('apiDetail.rules') }}</th><th scope="col">{{ t('apiDetail.meaning') }}</th></tr></thead>
							<tbody><tr v-for="a in o.args" :key="a.name"><th scope="row" :data-label="t('apiDetail.argument')"><code class="sv-code">{{ a.name }}</code><span v-if="a.required" class="sv-tag">{{ t('apiDetail.required') }}</span></th><td :data-label="t('apiDetail.type')">{{ a.type }}</td><td :data-label="t('apiDetail.rules')">{{ rules(a) }}</td><td :data-label="t('apiDetail.meaning')">{{ a.desc || '–' }}</td></tr></tbody>
						</table>
						<p v-else class="sv-quiet">{{ t('apiDetail.no_arguments') }}</p>
						<ul class="sv-effects" data-part="facts">
							<li>{{ t('apiDetail.class_is', { c: kindName(o.kind) }) }}<template v-if="o.role"> · {{ t('links.min_role', { role: roleName(o.role) }) }}</template></li>
							<li v-if="o.confirm">{{ t('apiDetail.asks_confirmation', { n: o.confirm.level || 3 }) }}</li>
							<li v-if="o.motion">{{ t('apiDetail.asks_motion_owner', { c: o.motion }) }}</li>
							<li v-if="o.slow">{{ t('apiDetail.may_take_long') }}</li>
							<li>{{ t('links.via', { macro: t(o.macro ? 'links.yes' : 'links.no') }) }}</li>
						</ul>
						<div v-for="b in blocks(o)" :key="b.id" class="sv-code-block">
							<div class="sv-row-ctl"><span class="sv-quiet">{{ t('apiDetail.' + b.id) }}</span><sv-copy-button :kind="b.id" :label="t('apiDetail.' + b.id)" :done="copied === o.name + b.id" @copy="copy(b.text, o.name + b.id)" /></div>
							<pre class="sv-diff">{{ b.text }}</pre>
						</div>
						<div class="sv-try" data-part="try">
							<p class="sv-quiet">{{ t('links.test_title') }}<span v-if="second(o)" class="sv-field-error"> {{ t('links.test_acts') }}</span></p>
							<div class="sv-row-ctl">
								<label class="sv-field"><span class="sv-vh">{{ t('links.test_args') }}</span><input :value="code(o)" type="text" :aria-label="t('links.test_args')" data-part="args" @input="setCode(o, $event.target.value)" @keyup.enter="send(o)"></label>
								<button type="button" class="sv-btn sv-main" data-act="send" :disabled="tries[o.name] && tries[o.name].sending" @click="send(o)">{{ t(armed === o.name ? 'links.test_again' : 'links.test_send') }}</button>
							</div>
							<div v-if="result(o)" class="sv-row-out" :data-kind="result(o).ok ? 'done' : 'error'" :role="result(o).ok ? 'status' : 'alert'" data-part="result">
								<span class="mdi sv-ico sv-ico-s" :class="result(o).ok ? 'mdi-check-circle-outline' : 'mdi-close-circle-outline'" aria-hidden="true" />
								<span>{{ t(result(o).ok ? 'links.test_ok' : 'links.test_error') }} · {{ result(o).hour }} · {{ result(o).ms }} ms</span>
							</div>
							<pre v-if="result(o)" class="sv-diff">{{ result(o).text || t('common.no_response') }}</pre>
						</div>
					</div>
				</details>
				<p v-if="more" class="sv-quiet"><button type="button" class="sv-btn" data-act="more" @click="showMore">{{ t('servicePage.show_more_ops', { n: more }) }}</button></p>
			</sv-zone>
		</section>
	</div>
</template>

<script>
import { call } from '../../core/api/call.js'
import { locale, te } from '../../core/dwc.js'
import { apiOps } from '../../core/resources.js'
import { every, timeNow } from '../../core/clock.js'
import { want } from '../../core/store/session.js'
import { rowsMixin } from '../../core/rows-mixin.js'
import { copyText } from '../../copy.js'
import SvZone from '../../ui/SvZone.vue'
import SvCopyButton from '../../ui/SvCopyButton.vue'
import { CATEGORIES, FIRST, SUBS_SHOWN, categoryOf, MORE, countsOf, curlText, exampleArgs, filterOps, macroText, needsSecondTouch, opsOf, requestText, rulesOf, subsOf, summaryOf } from './api-view.js'

const MODES = ['all', 'read', 'write']
const ARM_MS = 5000

export default {
	name: 'ApiTab',
	components: { SvCopyButton, SvZone },
	mixins: [rowsMixin],
	inject: { nav: { from: 'svNav', default: () => ({ go() {}, href: () => '#' }) } },
	props: { active: { type: Boolean, default: false } },
	data() {
		return { apis: apiOps, MODES, q: '', mode: 'all', cat: '', sub: '', subsMore: false, SUBS_SHOWN, limit: FIRST, opened: {}, tries: {}, armed: '', copied: '', CATEGORIES }
	},
	computed: {
		lang() {
			return String(locale() || 'es').toLowerCase().indexOf('en') === 0 ? 'en' : 'es'
		},
		ops() {
			return opsOf(this.apis.data)
		},
		status() {
			return this.apis.status === 'ready' && !this.ops.length ? 'empty' : this.apis.status
		},
		cats() {
			return countsOf(this.ops)
		},
		subs() {
			return this.cat ? subsOf(this.ops, this.cat) : []
		},
		// the groups with their readable name (the raw prefix stays in the tooltip), alphabetical by that name
		subsAll() {
			return this.subs.map(s => Object.assign({ label: te('apiGroups.' + s.id) ? this.t('apiGroups.' + s.id) : s.id }, s)).sort((a, b) => a.label.localeCompare(b.label, locale()))
		},
		// the first ones, and the chosen one even when it is beyond them
		subsShown() {
			if (this.subsMore) return this.subsAll
			const head = this.subsAll.slice(0, SUBS_SHOWN)
			const chosen = this.subsAll.find(s => s.id === this.sub)
			return chosen && head.indexOf(chosen) < 0 ? head.concat([chosen]) : head
		},
		found() {
			return filterOps(this.ops, { q: this.q, mode: this.mode, cat: this.cat, sub: this.sub })
		},
		shown() {
			return this.found.slice(0, this.limit)
		},
		more() {
			return Math.max(0, Math.min(MORE, this.found.length - this.limit))
		}
	},
	watch: {
		// the texts of the reference come from the service in the language of the request: another language, another reading
		lang() { this.apis.reload() },
		// the texts of the reference come from the service in the language of the request: another language, another reading
		lang() { this.apis.reload() },
		active: { immediate: true, handler(on) { if (on) { want(['api.describe']); this.apis.show() } else { this.apis.hide(); this.disarm() } } },
		// the question changed: the count starts again
		q() { this.limit = FIRST },
		mode() { this.limit = FIRST },
		cat() { this.limit = FIRST },
		sub() { this.limit = FIRST }
	},
	beforeDestroy() {
		this.disarm()
	},
	methods: {
		catOf(name) {
			return categoryOf(name).id
		},
		follow(e) {
			if (e && (e.ctrlKey || e.metaKey || e.shiftKey || e.altKey || e.button > 0)) return
			if (e && typeof e.preventDefault === 'function') e.preventDefault()
			this.nav.go({ s: 'access', t: 'keys' })
		},
		pickCat(id) {
			this.cat = this.cat === id ? '' : id
			this.sub = ''
		},
		showMore() {
			this.limit += MORE
		},
		onOpen(name, open) {
			this.$set(this.opened, name, open)
		},
		summary: summaryOf,
		// the rules of an argument in ONE sentence of the language of the page: "minimum 2 · maximum 30 · by default 5"
		rules(a) {
			return rulesOf(a).map(r => this.t('links.rule_' + r.key) + ' ' + r.text.replace(/^[<>]=\s*/, '')).join(' · ') || '–'
		},
		// the class of an operation as the words of the legend (Reads / Changes something ...), never the code of the service
		kindName(kind) {
			return this.t(te('links.kind_' + kind) ? 'links.kind_' + kind : 'links.kind_other')
		},
		roleName(role) {
			return ['viewer', 'operator', 'technician', 'admin'].indexOf(role) >= 0 ? this.t('api.role_' + role) : role
		},
		second(o) {
			return needsSecondTouch(o)
		},
		blocks(o) {
			const host = typeof location !== 'undefined' ? location.host : ''
			return [{ id: 'request', text: requestText(o) }, { id: 'curl', text: curlText(o, host) }, { id: 'from_a_macro', text: macroText(o) }]
		},
		async copy(text, id) {
			if (!(await copyText(text))) return
			this.copied = id
			setTimeout(() => { if (this.copied === id) this.copied = '' }, 1500)
		},
		code(o) {
			const t = this.tries[o.name]
			return t && t.code !== undefined ? t.code : JSON.stringify(exampleArgs(o))
		},
		setCode(o, v) {
			this.$set(this.tries, o.name, Object.assign({}, this.tries[o.name], { code: v }))
		},
		result(o) {
			return (this.tries[o.name] && this.tries[o.name].result) || null
		},
		disarm() {
			this.armed = ''
			if (this.off) { this.off(); this.off = null }
		},
		// a read goes at once; anything that changes something needs the second touch within five seconds
		send(o) {
			if (this.second(o) && this.armed !== o.name) {
				this.disarm()
				this.armed = o.name
				const until = timeNow() + ARM_MS
				this.off = every(1, () => { if (timeNow() >= until) this.disarm() })
				return
			}
			this.disarm()
			return this.run(o)
		},
		async run(o) {
			const code = String(this.code(o) || '').trim()
			const mine = Object.assign({}, this.tries[o.name], { sending: true })
			this.$set(this.tries, o.name, mine)
			const t0 = Date.now()
			let ok = true
			let text = ''
			try {
				const r = await call(o.name, code ? JSON.parse(code) : {})
				text = r.data !== null && r.data !== undefined ? JSON.stringify(r.data, null, 1) : r.text
			} catch (e) {
				ok = false
				text = String((e && e.message) || e)
			}
			this.$set(this.tries, o.name, Object.assign({}, this.tries[o.name], { sending: false, result: { ok, text, ms: Date.now() - t0, hour: new Date().toTimeString().slice(0, 8) } }))
		}
	}
}
</script>
