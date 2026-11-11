<template>
	<v-card class="mb-3 svc-startup-section">
		<!-- ONE "Puesta en marcha" (2026-11): the steps of each plugin and the changes of the files of the SD card in a single card, with one title,
		     one total and one refresh button. Each part keeps its own logic and its own session handling; here they are only drawn together. -->
		<v-card-title class="d-flex align-center flex-wrap" style="gap:8px">
			<span><v-icon small class="mr-2 svx-ico">mdi-rocket-launch-outline</v-icon>{{ $t(T + 'title') }}</span>
			<v-chip small outlined :color="color" class="svc-ss-total" :title="detail">{{ chipText }}</v-chip>
			<v-spacer />
			<v-btn small text class="svc-ss-touch svc-ss-refresh" :loading="sum.loading" @click="refresh"><v-icon small left>mdi-refresh</v-icon>{{ $t(T + 'refresh') }}</v-btn>
		</v-card-title>
		<v-card-text>
			<section v-show="steps.rows > 0" class="svc-ss-part svc-ss-steps">
				<div class="svc-ss-head"><span>{{ $t(T + 'part_steps') }}</span></div>
				<startup-master ref="master" embedded @section="id => $emit('section', id)" @state="s => { steps = s }" />
			</section>
			<section class="svc-ss-part svc-ss-files">
				<div class="svc-ss-head d-flex align-center flex-wrap" style="gap:8px">
					<span>{{ $t(T + 'part_files') }}</span>
					<v-spacer />
					<sd-files-dialog />
				</div>
				<startup-wizard ref="wizard" embedded @state="s => { files = s }" />
			</section>
		</v-card-text>
	</v-card>
</template>

<script>
'use strict'

import StartupMaster from './StartupMaster.vue'
import StartupWizard from './StartupWizard.vue'
import SdFilesDialog from './SdFilesDialog.vue'
import { total, KIND_COLOR, EMPTY_STEPS, EMPTY_FILES } from './startup-total.js'

export default {
	name: 'StartupSection',
	components: { StartupMaster, StartupWizard, SdFilesDialog },
	data() {
		return { T: 'plugins.WorkshopService.startup_section.', steps: Object.assign({}, EMPTY_STEPS), files: Object.assign({}, EMPTY_FILES) };
	},
	computed: {
		sum() { return total(this.steps, this.files); },
		color() { return KIND_COLOR[this.sum.kind]; },
		chipText() {
			const s = this.sum;
			if (s.kind === 'login') return this.$t(this.T + 'sum_login');
			if (s.kind === 'pending') return this.$t(this.T + 'sum_pending', { n: s.n });
			if (s.kind === 'unchecked') return this.$t(this.T + 'sum_unchecked', { n: s.unchecked });
			return this.$t(this.T + 'sum_ready');
		},
		detail() { return this.sum.kind === 'pending' ? this.$t(this.T + 'sum_pending_detail', { steps: this.sum.stepsPending, files: this.sum.filesPending }) : ''; }
	},
	methods: {
		// both parts read again; each one keeps its own guard against a stale answer
		refresh() {
			if (this.$refs.master) this.$refs.master.read();
			if (this.$refs.wizard) this.$refs.wizard.read();
		}
	}
};
</script>

<style scoped>
.svc-ss-touch { min-height: 44px; }
.svc-ss-part + .svc-ss-part { margin-top: 18px; }
.svc-ss-head { font-size: 14px; font-weight: 600; padding-bottom: 6px; margin-bottom: 8px; border-bottom: 1px solid var(--wf-line); }
</style>
