<template>
	<!-- Setup > Package: the settings of this machine in one file, to keep or to take to another. Two rows: Export (a technician: it only reads) and
	     Import (an administrator: first what it would do with each file, nothing is written until it is confirmed with a level 3 dialog). The limits
	     of the file are said BEFORE it is chosen. Prop: active. -->
	<div class="sv-setup-package">
		<section class="sv-card" aria-labelledby="sv-sp-title" data-card="package">
			<div class="sv-card-head"><h2 id="sv-sp-title"><span class="mdi mdi-package-variant-closed sv-ico" aria-hidden="true" />{{ t('setup.package_title') }}</h2></div>
			<p class="sv-lead">{{ t('package.intro') }}</p>
			<ul class="sv-rows">
				<sv-action-row below icon="mdi-export" :name="t('package.export_title')" :desc="t('package.export_note')" :action="packageExport" :permission="perm('package.export')" :stale="stale" :label="t('package.download')" @run="exportNow" @retry="exportNow">
					<div class="sv-choice-grid" role="group" :aria-label="t('package.export_title')" data-part="categories">
						<label v-for="c in categories" :key="c" class="sv-choice" :class="{ 'sv-on': chosenCats.indexOf(c) >= 0 }"><input v-model="chosenCats" type="checkbox" :value="c" :disabled="stale"><span><b>{{ t('package.cat_' + c) }}</b></span></label>
					</div>
					<p v-for="s in skipped" :key="s.path" class="sv-field-error" role="status" data-part="skipped"><span class="mdi mdi-alert-outline sv-ico sv-ico-s" aria-hidden="true" /><code class="sv-code">{{ s.path }}</code> {{ t('package.skipped_' + s.reason) }}</p>
					<template #ctl-after><span v-if="exported" class="sv-row-desc" role="status" data-part="exported">{{ tc('package.exported', exported, { n: exported }) }}</span></template>
					<template #help><help-fold v-bind="help('export', 'setup')" /></template>
				</sv-action-row>
				<sv-action-row below icon="mdi-import" :name="t('package.import_title')" :desc="t('package.import_note')" :action="packageApply" :permission="perm('package.apply')" :stale="stale" :label="todo ? t('package.import', { n: todo }) : ''" @run="askApply" @retry="askApply">
					<p class="sv-row-desc" data-part="why">{{ t('package.import_why') }}</p>
					<p class="sv-row-desc" data-part="example">{{ t('package.import_example') }}</p>
					<p class="sv-row-desc" data-part="limits">{{ t('setup.package_limits', { soft: SOFT, hard: HARD }) }}</p>
					<p v-if="fileProblem" class="sv-field-error" role="alert" data-part="file-problem"><span class="mdi mdi-alert-outline sv-ico sv-ico-s" aria-hidden="true" />{{ t('setup.file_' + fileProblem, { soft: SOFT, hard: HARD }) }}</p>
					<template #ctl-before>
							<label class="wf-btn sv-btn sv-file"><span>{{ t('package.choose_file') }}</span><input type="file" accept=".zip,application/zip" class="sv-vh" data-part="file" :disabled="!mayImport || stale" @change="pick($event.target.files && $event.target.files[0])"></label>
					</template>
					<template #body>
						<div v-if="message && message.where === 'import'" class="sv-row-out" :data-kind="message.ok ? 'done' : 'error'" :role="message.ok ? 'status' : 'alert'" data-part="message"><span class="mdi sv-ico sv-ico-s" :class="message.ok ? 'mdi-check-circle-outline' : 'mdi-close-circle-outline'" aria-hidden="true" /><span>{{ message.text }}<small v-if="message.hint" class="sv-row-desc">{{ message.hint }}</small><code v-if="message.code" class="sv-code">{{ message.code }}</code></span></div>
					</template>
					<template #help><help-fold v-bind="help('import', 'setup')" /></template>
				</sv-action-row>
			</ul>
			<lock-reason class="sv-lock" :lock="lockOf(['package.export', 'package.apply'])" />
			<p class="sv-quiet">{{ t('package.secrets_note') }}</p>

			<div v-if="items" class="sv-preview" data-part="preview">
				<p v-if="!items.length" class="sv-quiet" role="status">{{ t('package.empty') }}</p>
				<table v-else class="sv-table">
					<caption class="sv-vh">{{ t('package.import_title') }}</caption>
					<thead><tr><th scope="col">{{ t('setup.package_file') }}</th><th scope="col">{{ t('setup.package_does') }}</th></tr></thead>
					<tbody>
						<tr v-for="i in items" :key="i.path" :data-item="i.path">
							<th scope="row" :data-label="t('setup.package_file')"><code class="sv-code">{{ i.path }}</code></th>
							<td :data-label="t('setup.package_does')">
								<span class="sv-word" :data-level="LEVEL[i.action]">{{ t('package.act_' + i.action) }}</span>
								<label v-if="i.action === 'conflict'" class="sv-check"><input v-model="replace" type="checkbox" :value="i.path" :disabled="!mayImport"><span>{{ t('package.replace_this') }}</span></label>
							</td>
						</tr>
					</tbody>
				</table>
				<p v-if="hasConflict" class="sv-quiet">{{ t('package.conflict_help') }}</p>
				<p v-if="hasReference" class="sv-quiet">{{ t('package.reference_help') }}</p>
			</div>
			<div v-if="message && message.where !== 'import'" class="sv-row-out" :data-kind="message.ok ? 'done' : 'error'" :role="message.ok ? 'status' : 'alert'" data-part="message"><span class="mdi sv-ico sv-ico-s" :class="message.ok ? 'mdi-check-circle-outline' : 'mdi-close-circle-outline'" aria-hidden="true" /><span>{{ message.text }}<small v-if="message.hint" class="sv-row-desc">{{ message.hint }}</small><code v-if="message.code" class="sv-code">{{ message.code }}</code></span></div>
		</section>

		<wf-confirm :confirm="packageApply.confirm" :title="t('setup.import_title')" :text="t('setup.import_text')" :object="{ name: fileName, context: t('setup.import_context', { n: todo }) }" :effects="effects" :verb="t('package.import', { n: todo })"
			@accept="packageApply.accept()" @cancel="packageApply.cancel()" />
	</div>
</template>

<script>
import { call } from '../../core/api/call.js'
import { saveBase64 } from '../../core/dwc.js'
import { want } from '../../core/store/session.js'
import { packageApply, packageExport } from '../../core/actions/setup.js'
import { rowsMixin } from '../../core/rows-mixin.js'
import SvActionRow from '../../ui/SvActionRow.vue'
import WfConfirm from '../../WfConfirm.vue'
import HelpFold from '../../HelpFold.vue'
import LockReason from '../../LockReason.vue'
import { PACKAGE_CATEGORIES, PACKAGE_HARD_KB, PACKAGE_SOFT_KB, packageSize, packageTodo, toBase64 } from './view.js'

const LEVEL = { create: 'ok', same: 'rest', conflict: 'warn', reference: 'rest', skip: 'rest' }

// what read_package of the service refuses (dsf/config_package.py) and the limits it keeps (MAX_ZIP, MAX_FILES, MAX_TOTAL)
const PACKAGE_CODES = ['too_big', 'not_a_package', 'unknown_format', 'too_many_files', 'bad_path', 'bad_file', 'damaged']
const PACKAGE_LIMITS = { zip: 700, files: 500, total: 8 }

export default {
	name: 'PackageTab',
	components: { SvActionRow, WfConfirm, HelpFold, LockReason },
	mixins: [rowsMixin],
	props: { active: { type: Boolean, default: false } },
	data() {
		return { packageExport, packageApply, LEVEL, categories: PACKAGE_CATEGORIES, SOFT: PACKAGE_SOFT_KB, HARD: PACKAGE_HARD_KB, chosenCats: PACKAGE_CATEGORIES.slice(), exported: 0, skipped: [], fileName: '', data: '', items: null, replace: [], fileProblem: '', message: null }
	},
	computed: {
		mayImport() {
			return this.perm('package.apply').state === 'ok'
		},
		hasConflict() {
			return (this.items || []).some(i => i.action === 'conflict')
		},
		hasReference() {
			return (this.items || []).some(i => i.action === 'reference')
		},
		todo() {
			return packageTodo(this.items, this.replace)
		},
		effects() {
			return (this.items || []).filter(i => i.action === 'create' || i.action === 'reference' || (i.action === 'conflict' && this.replace.indexOf(i.path) >= 0)).map(i => i.path)
		}
	},
	watch: {
		active: { immediate: true, handler(on) { if (on) want(['package.export', 'package.preview', 'package.apply']) } },
		'packageExport.state'(now) {
			if (now !== 'done' || !this.packageExport.data) return
			const r = this.packageExport.data
			this.skipped = r.skipped || []
			this.exported = (r.manifest && r.manifest.files && r.manifest.files.length) || 0
			if (!saveBase64(r.name, r.data, 'application/zip')) this.message = { ok: false, text: this.t('setup.download_failed') }
			else this.message = null
		},
		'packageApply.state'(now) {
			if (now === 'done') this.applied(this.packageApply.data || {})
			else if (now === 'error' && this.packageApply.error && this.packageApply.error.kind !== 'session' && this.packageApply.error.kind !== 'role') this.message = this.problem(this.packageApply.error)
		}
	},
	methods: {
		exportNow() {
			if (!this.chosenCats.length) { this.message = { ok: false, text: this.t('setup.package_none_chosen') }; return }
			this.message = null
			this.packageExport.run({ categories: this.chosenCats.slice() })
		},
		async pick(file) {
			this.items = null
			this.replace = []
			this.message = null
			this.fileProblem = ''
			if (!file) return
			this.fileName = file.name
			const size = packageSize(file.size)
			if (size === 'empty' || size === 'huge') { this.fileProblem = size; return }
			if (size === 'big') this.fileProblem = 'big'      // said, not refused: the service decides
			try {
				this.data = toBase64(await file.arrayBuffer())
				const r = await call('package.preview', { data: this.data })
				this.items = (r.data && r.data.items) || []
			} catch (e) {
				this.message = this.problem(e)
			}
		},
		// the service answers "package: <code>": a sentence of the person and what to do; a code that is not known says so and keeps the code for support
		problem(e) {
			const m = /^package:\s*([a-z_]+)/.exec((e && e.message) || '')
			const code = m && PACKAGE_CODES.indexOf(m[1]) >= 0 ? m[1] : ''
			if (code) return { ok: false, where: 'import', text: this.t('package.err_' + code, PACKAGE_LIMITS), hint: this.t('package.todo_' + code) }
			return { ok: false, where: 'import', text: this.t('package.err_other'), hint: this.t('package.todo_other'), code: m ? m[1] : ((e && e.message) || '').slice(0, 60) }
		},
		askApply() {
			if (!this.items) { this.message = { ok: false, where: 'import', text: this.t('package.err_choose') }; return }
			if (!this.todo) return
			this.packageApply.run({ data: this.data, replace: this.replace.slice() })
		},
		async applied(r) {
			const n = k => (r[k] || []).length
			const errors = Object.keys(r.errors || {}).length
			this.message = { ok: !errors, where: 'import', text: this.t('package.applied', { created: this.tc('package.applied_created', n('created'), { n: n('created') }), replaced: this.tc('package.applied_replaced', n('replaced'), { n: n('replaced') }), kept: this.tc('package.applied_kept', n('kept'), { n: n('kept') }), reference: n('reference') }) + (errors ? ' ' + this.tc('package.applied_errors', errors, { n: errors }) : '') }
			try {
				const p = await call('package.preview', { data: this.data })
				this.items = (p.data && p.data.items) || []
				this.replace = []
			} catch (e) { /* the result above stands */ }
		}
	}
}
</script>
