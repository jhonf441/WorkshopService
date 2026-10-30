<template>
	<v-container fluid class="pa-0 workshop-theme svx-page" :style="{ '--wf-badge': badge }">
		<!-- backend stopped (2026-10-10, test "what if a plugin is
		     missing"): DSF keeps the data published the last time, so
		     without this notice the page looked up to date with the service stopped -->
		<v-alert v-if="!runs" outlined type="warning" dense icon="mdi-lan-disconnect" class="mb-3 notice-stopped">
			<div class="font-weight-medium">{{ $t('plugins.WorkshopService.servicePage.the_system_service_is_stopped') }}</div>
			<div class="text-body-2 mt-1">{{ $t('plugins.WorkshopService.servicePage.what_you_see_below_is_old', { list: withoutServiceList }) }}</div>
		</v-alert>
		<!-- The ONE bar of the page (design family): badge, name, one line, and the state with the count of processes -->
		<page-header icon="mdi-flash" :title="$t('plugins.WorkshopService.page.system_service')" :lead="$t('plugins.WorkshopService.page.service_lead')" loading>
			<v-chip small outlined :color="headerChip.color">
				<v-icon left x-small>{{ headerChip.icon }}</v-icon>
				{{ headerChip.text }}
			</v-chip>
		</page-header>

		<!-- No user created yet: everybody with access to DWC is an administrator (F1-A, identity by PIN) -->
		<v-alert v-if="identity && identity.compat" dense outlined type="warning" class="mb-3">
			<template v-if="identity.users_disabled">
				{{ $t('plugins.WorkshopService.users.disabled_notice') }}
				<v-btn small outlined color="warning" class="ml-2" @click="section = 'users'">{{ $t('plugins.WorkshopService.users.switch_on') }}</v-btn>
			</template>
			<template v-else>
				{{ $t('plugins.WorkshopService.users.no_users_notice') }}
				<v-btn small outlined color="warning" class="ml-2" @click="section = 'users'">{{ $t('plugins.WorkshopService.users.create_first') }}</v-btn>
			</template>
		</v-alert>
		<div class="st-layout">
		<side-tabs v-model="section" :items="sections" />
		<div class="st-body">
		<div v-show="section === 'summary'">
			<!-- Summary -->
			<v-card class="mb-3">
				<v-card-text>
					<div class="d-flex flex-wrap align-center svc-resumen">
						<v-chip v-if="!count" small outlined color="grey" class="mr-2 mb-1">
							<v-icon left small>mdi-help-circle-outline</v-icon>{{ $t('plugins.WorkshopService.procDocs.ui_summary_unavailable') }}
						</v-chip>
						<template v-else>
							<v-chip small outlined color="success" class="mr-2 mb-1">
								<v-icon left small>mdi-check-circle</v-icon>{{ $t('plugins.WorkshopService.servicePage.n_up_to_date', { n: count.ok }) }}
							</v-chip>
							<v-chip v-if="count.notice" small outlined color="warning" class="mr-2 mb-1">
								<v-icon left small>mdi-alert</v-icon>{{ $t('plugins.WorkshopService.servicePage.n_with_warnings', { n: count.notice }) }}
							</v-chip>
							<v-chip v-if="count.bad" small outlined color="error" class="mr-2 mb-1">
								<v-icon left small>mdi-close-circle</v-icon>{{ $t('plugins.WorkshopService.servicePage.n_stopped', { n: count.bad }) }}
							</v-chip>
						</template>
						<span v-if="serviceStarted" class="text-caption grey--text mb-1">{{ $t('plugins.WorkshopService.servicePage.backend_started_on', { d: serviceStarted }) }}</span>
					</div>
					<div class="text-caption grey--text mt-1">
						{{ $t('plugins.WorkshopService.servicePage.the_system_backend_workshopservice_plugin') }}
					</div>
				</v-card-text>
			</v-card>
		<!-- Setup of the whole machine: what each installed plugin still needs (nothing for plugins that are not installed) -->
		<startup-master @section="id => { section = id }" />

		<!-- Black box (2026-10-12, dsf/box_black.py): the Pi shut off without a clean close
		     (hang or power cut); last lines of the SD's log -->
		<black-box-card v-if="boxReport" :report="boxReport" :interval="boxBlack.interval_s || 5" :lowering="box.lowering" :sending="box.sending" :msg="box.msg" @download="downloadBox" @hide="hideBox" />

		<!-- Last crash (2026-10-16): fixed row. The notice above can be hidden and disappears; this one always stays when
		     there is a saved report (the file is never deleted), with its date, to download it or see it again. -->
		<v-sheet v-if="!boxReport && lastDrop" outlined rounded class="d-flex align-center flex-wrap px-3 py-1 mb-3 svc-ultima-caida">
			<v-icon small color="grey" class="mr-2">mdi-file-alert-outline</v-icon>
			<span class="text-body-2 flex-grow-1">{{ $t('plugins.WorkshopService.servicePage.last_fall') }}: <b>{{ lastDrop.last_datum || '?' }}</b></span>
			<v-btn small text color="primary" :disabled="box.sending" @click="showBox">{{ $t('plugins.WorkshopService.servicePage.view_report') }}</v-btn>
			<v-btn small text color="primary" :loading="box.lowering" @click="downloadBox">
				<v-icon small left>mdi-download</v-icon>{{ $t('plugins.WorkshopService.common.download') }}
			</v-btn>
		</v-sheet>

		<!-- Communication with the Duet (2026-10-10): through where the Pi sends its G-code.
		     It goes first, right below the header (request: "that should go at the very
		     beginning of Pi service"): without a channel nothing else works. It lists the 14
		     RRF channels; only the safe ones can be chosen (dsf/comunicacion.py). -->
		<v-card class="mb-3">
			<v-card-title>
				<v-icon small class="mr-2 svx-ico">mdi-swap-horizontal</v-icon>{{ $t('plugins.WorkshopService.servicePage.communication_with_the_duet') }}
			</v-card-title>
			<v-card-text>
				<details class="wf-more svc-explains mb-3">
					<summary>{{ $t('plugins.WorkshopService.servicePage.how_it_works') }}</summary>
						<p>{{ $t('plugins.WorkshopService.servicePage.sends_its_g_code_via_dsf') }}</p>
						<p>{{ jogVariant('plugins.WorkshopService.servicePage.inside_the_duet_each_source_of') }}</p>
						<p>{{ $t('plugins.WorkshopService.servicePage.only_the_safe_channels_can_be') }}</p>
						<p class="mb-0">{{ $t('plugins.WorkshopService.servicePage.why_aux2_with_everything_on_sbc') }}</p>
					</details>
				<div v-if="!communication" class="warning--text text-body-2">
					<span v-if="!connected">{{ $t('plugins.WorkshopService.servicePage.the_system_service_is_not_responding') }}</span>
					<span v-else>{{ $t('plugins.WorkshopService.servicePage.waiting_for_data_from_the_service') }}</span>
				</div>
				<template v-else>
					<v-row dense>
						<v-col cols="12" sm="6">
							<v-select
								:value="communication.channel_cfg" :items="optionsChannel" item-text="t" item-value="v"
								:label="$t('plugins.WorkshopService.servicePage.service_codes_lights_readings_macros')" dense outlined hide-details
								prepend-inner-icon="mdi-lock-outline" :disabled="savingChannel || !advanced" @change="v => setChannel('C', v)"
							/>
							<div class="text-caption mt-1">
								<span class="grey--text">{{ $t('plugins.WorkshopService.servicePage.in_use') }}</span> <b>{{ communication.channel }}</b>
								<span v-if="communication.channel_cfg === 'auto'" class="grey--text"> ({{ $t('plugins.WorkshopService.servicePage.automatic_x', { x: perThatService }) }})</span>
							</div>
						</v-col>
						<v-col v-if="hasJog" cols="12" sm="6">
							<v-select
								:value="communication.channel_jog_cfg" :items="optionsJog" item-text="t" item-value="v"
								:label="$t('plugins.WorkshopService.servicePage.jog_moves')" dense outlined hide-details
								prepend-inner-icon="mdi-lock-outline" :disabled="savingChannel || !advanced" @change="v => setChannel('J', v)"
							/>
							<div class="text-caption mt-1">
								<span class="grey--text">{{ $t('plugins.WorkshopService.servicePage.in_use') }}</span> <b>{{ communication.channel_jog }}</b>
								<span v-if="communication.channel_jog_cfg === 'auto'" class="grey--text"> ({{ $t('plugins.WorkshopService.servicePage.automatic_x', { x: perThatJog }) }})</span>
							</div>
						</v-col>
					</v-row>
					<div class="mt-2">
						<v-btn small text color="warning" @click="toggleAdvanced">
							<v-icon small left>{{ advancedOpen ? 'mdi-chevron-up' : 'mdi-chevron-down' }}</v-icon>{{ $t('plugins.WorkshopService.servicePage.advanced') }}
						</v-btn>
					</div>
					<v-expand-transition>
						<div v-show="advancedOpen" class="mt-1">
							<v-alert dense outlined type="warning" class="text-caption mb-2">
								{{ communication.warning || jogVariant('plugins.WorkshopService.servicePage.changing_the_channel_by_hand_can') }}
							</v-alert>
							<div class="svc-explains text-caption mb-2">
								<p class="mb-1"><b>{{ $t('plugins.WorkshopService.servicePage.what_exactly_this_option_does') }}</b> {{ $t('plugins.WorkshopService.servicePage.each_channel_is_a_g_code') }}</p>
								<p class="mb-1"><b>{{ $t('plugins.WorkshopService.servicePage.service_codes') }}</b> {{ $t('plugins.WorkshopService.servicePage.are_the_lights_the_driver_readings') }} <template v-if="hasJog"><b>{{ $t('plugins.WorkshopService.servicePage.jog') }}</b> {{ $t('plugins.WorkshopService.servicePage.are_the_g1_moves_of_the') }}</template></p>
								<p class="mb-1"><b>{{ $t('plugins.WorkshopService.servicePage.automatic') }}</b> {{ jogVariant('plugins.WorkshopService.servicePage.recommended_uses_aux2_if_it_is') }}</p>
								<p class="mb-1"><b>{{ $t('plugins.WorkshopService.servicePage.aux2_aux') }}</b>{{ $t('plugins.WorkshopService.servicePage.the_serial_port_s_own_queue') }}</p>
								<p class="mb-0"><b>{{ $t('plugins.WorkshopService.servicePage.sbc') }}</b>{{ jogVariant('plugins.WorkshopService.servicePage.the_common_queue_of_the_system') }}</p>
							</div>
							<v-btn v-if="!advanced" small outlined color="error" @click="unlockAdvanced">
								<v-icon small left>mdi-lock-open-alert</v-icon>{{ armedAdv ? $t('plugins.WorkshopService.servicePage.tap_again_to_unlock') : $t('plugins.WorkshopService.servicePage.unlock_channel_changes') }}
							</v-btn>
							<span v-else class="text-caption error--text">{{ $t('plugins.WorkshopService.servicePage.unlocked_pick_the_channel_it_locks') }}</span>
						</div>
					</v-expand-transition>
					<div v-for="(a, i) in communication.notices" :key="i" class="text-caption warning--text mt-2">
						<v-icon x-small color="warning" class="mr-1">mdi-alert</v-icon>{{ a }}
					</div>
					<div class="text-caption grey--text mt-3 mb-1">{{ $t('plugins.WorkshopService.servicePage.all_the_duet_channels') }}</div>
					<div v-for="c in channelsList" :key="c.id" class="svc-channel d-flex align-center flex-wrap" :class="{ 'svc-channel-off': !c.eligible }">
						<code class="mr-3 svc-channel-id">{{ c.id }}</code>
						<v-chip x-small label dark class="mr-2" :color="stateChannel(c).color">{{ stateChannel(c).t }}</v-chip>
						<v-chip v-if="c.id === communication.channel" x-small label outlined color="primary" class="mr-1">{{ $t('plugins.WorkshopService.servicePage.service') }}</v-chip>
						<v-chip v-if="hasJog && c.id === communication.channel_jog" x-small label outlined color="primary" class="mr-1">{{ $t('plugins.WorkshopService.servicePage.jog') }}</v-chip>
						<span class="text-caption">{{ c.usage }}</span>
						<span v-if="c.reason" class="text-caption grey--text ml-2">{{ c.reason }}</span>
					</div>
				</template>
			</v-card-text>
		</v-card>

		</div>
		<div v-show="section === 'processes'">
		<v-row dense>
			<!-- Procesos internos -->
			<v-col cols="12" md="7" class="svc-col">
				<v-card class="mb-3 svc-height">
					<v-card-title>
						<v-icon small class="mr-2 svx-ico">mdi-cogs</v-icon>{{ $t('plugins.WorkshopService.servicePage.internal_processes') }}
					</v-card-title>
					<v-card-text>
						<!-- the service itself: first row, with its state (2026-10-10) -->
						<div class="svc-proc svc-own">
							<div class="d-flex align-center flex-wrap">
								<v-icon class="mr-3 svx-ico">mdi-server</v-icon>
								<div class="svc-proc-txt">
									<div class="font-weight-medium">
										{{ $t('plugins.WorkshopService.page.system_service') }}
										<v-chip x-small label outlined color="primary" class="ml-1">WorkshopService {{ pluginModel && pluginModel.version }}</v-chip>
									</div>
									<div class="text-caption grey--text">{{ $t('plugins.WorkshopService.page.interceptorDesc') }}</div>
								</div>
								<v-spacer />
								<v-chip small label dark :color="serviceOwn.color" :title="serviceOwn.detail">
									<v-icon left x-small>{{ serviceOwn.icon }}</v-icon>{{ serviceOwn.text }}
								</v-chip>
							</div>
							<div v-if="processInfo" class="text-caption ml-10 mt-1 svc-metricas grey--text">
								<span>PID {{ processInfo.pid }}</span>
								<span>{{ $t('plugins.WorkshopService.servicePage.up_for_t', { t: duration(processInfo.age_s) }) }}</span>
								<span v-if="processInfo.memory_mb != null">{{ $t('plugins.WorkshopService.servicePage.memory_n_mb', { n: processInfo.memory_mb }) }}</span>
								<span v-if="processInfo.cpu_pct != null">CPU {{ processInfo.cpu_pct }}%</span>
								<span>{{ $t('plugins.WorkshopService.servicePage.n_threads', { n: processInfo.threads }) }}</span>
								<span>{{ $t('plugins.WorkshopService.servicePage.n_internal_processes', { n: processes.length }) }}</span>
							</div>
							<div v-else-if="serviceOwn.detail" class="text-caption ml-10 mt-1 grey--text">{{ serviceOwn.detail }}</div>
						</div>
						<div v-if="!processes.length" class="grey--text">
							{{ $t('plugins.WorkshopService.servicePage.waiting_for_backend_data_needs') }}
						</div>
						<!-- summary tiles, filters and one card per process (what it is, pace, CPU and its last minutes) -->
						<processes-summary
:service="serviceOwn" :process="processInfo" :processes="processes" :count="count"
:load="loadDuet" :ipc="ipc" :hist-service="histProc.service" :guard="guardStatus"
						/>
						<div v-if="processes.length" class="d-flex align-center flex-wrap mb-2" style="gap:6px">
							<v-chip
								v-for="c in procCategories" :key="c.cat" x-small label
								outlined :class="{ 'wf-on': procCat === c.cat }"
								@click="procCat = procCat === c.cat ? null : c.cat"
							>{{ c.cat }} ({{ c.n }})</v-chip>
							<v-spacer />
							<v-btn-toggle v-model="procFilter" dense mandatory color="primary">
								<v-btn small value="all">{{ $t('plugins.WorkshopService.procDocs.ui_filter_all') }}</v-btn>
								<v-btn small value="problems">{{ $t('plugins.WorkshopService.procDocs.ui_filter_problems') }}</v-btn>
							</v-btn-toggle>
						</div>
						<v-text-field
							v-if="processes.length > 6" v-model="procSearch" dense hide-details clearable outlined class="mb-2"
							:placeholder="$t('plugins.WorkshopService.procDocs.ui_search')" prepend-inner-icon="mdi-magnify"
						/>
						<div v-if="processes.length && !processesFiltered.length" class="text-caption grey--text mb-2">{{ $t('plugins.WorkshopService.procDocs.ui_none_match') }}</div>
						<!-- the long list, by category: each group opens by tapping its header (open by itself when it has a problem or when searching) -->
						<div v-for="g in procGroups" :key="g.cat" class="svc-group">
							<a href="#" class="svc-group-cab" @click.prevent="$set(procOpen, g.cat, !groupOpen(g))">
								<v-icon x-small>{{ groupOpen(g) ? 'mdi-chevron-down' : 'mdi-chevron-right' }}</v-icon>
								<span class="svc-group-name">{{ g.cat }}</span>
								<span class="grey--text">({{ g.items.length }})</span>
								<v-spacer />
								<v-chip v-if="g.problems" x-small label color="warning" dark>{{ g.problems }}</v-chip>
								<v-icon v-else x-small color="success">mdi-check-circle-outline</v-icon>
							</a>
							<div v-if="groupOpen(g)">
								<process-row v-for="p in g.items" :key="p.id" :p="p" :hist="histProc.proc[p.id] || null" @mode="m => changeMode(p.id, m)" />
							</div>
						</div>
						<!-- Load toward the board: what this service asks the Duet for (DuetControlServer) -->
						<div class="text-overline grey--text mt-3">{{ $t('plugins.WorkshopService.servicePage.load_this_service_puts_on_the') }}</div>
						<div class="svc-proc">
							<div class="d-flex align-center flex-wrap">
								<v-icon class="mr-3 svx-ico">mdi-speedometer</v-icon>
								<div class="svc-proc-txt">
									<div class="font-weight-medium">{{ $t('plugins.WorkshopService.servicePage.connection_with_the_board') }}</div>
									<div class="text-caption grey--text">{{ $t('plugins.WorkshopService.servicePage.the_service_reads_the_machine_state') }}</div>
								</div>
								<v-spacer />
								<v-chip small label dark :color="loadDuet.color">{{ loadDuet.text }}</v-chip>
							</div>
							<div v-if="subscription" class="text-caption ml-10 mt-1 svc-metricas grey--text">
								<span :title="$t('plugins.WorkshopService.servicePage.the_single_subscription_to_the_machine')">{{ $t('plugins.WorkshopService.servicePage.subscription_x', { x: subscription.live ? $t('plugins.WorkshopService.servicePage.alive') : $t('plugins.WorkshopService.servicePage.down') }) }}</span>
								<span :title="$t('plugins.WorkshopService.servicePage.state_changes_arriving_per_second')">{{ $t('plugins.WorkshopService.servicePage.n_changes_s', { n: subscription.patches_s }) }}</span>
								<span :title="$t('plugins.WorkshopService.servicePage.data_arriving_per_second')">{{ subscription.kb_s }} KB/s</span>
								<span v-if="subscription.age_last_s != null" :title="$t('plugins.WorkshopService.servicePage.how_long_ago_the_last_change')">{{ $t('plugins.WorkshopService.servicePage.last_t_ago', { t: sec(subscription.age_last_s) }) }}</span>
								<span :class="subscription.reconnections ? 'warning--text' : ''" :title="$t('plugins.WorkshopService.servicePage.times_the_connection_was_lost_and')">{{ $t('plugins.WorkshopService.servicePage.n_reconnections', { n: subscription.reconnections }) }}</span>
								<span>{{ $t('plugins.WorkshopService.servicePage.n_filters', { n: subscription.filters }) }}</span>
								<span v-if="subscription.error" class="warning--text">{{ subscription.error }}</span>
							</div>
							<div v-if="ipc" class="text-caption ml-10 mt-1 svc-metricas grey--text">
								<span :title="$t('plugins.WorkshopService.servicePage.calls_to_the_board_in_the')">{{ $t('plugins.WorkshopService.servicePage.n_calls_min', { n: ipc.per_min }) }}</span>
								<span :title="$t('plugins.WorkshopService.servicePage.since_the_service_started')">{{ $t('plugins.WorkshopService.servicePage.n_in_total', { n: ipc.total }) }}</span>
							</div>
							<div v-if="loadDuet.reason" class="text-caption ml-10 mt-2 svc-load-reason" :class="'svc-load-' + loadDuet.color">
								<v-icon x-small class="mr-1">mdi-information-outline</v-icon>{{ loadDuet.reason }}
							</div>
							<div v-if="ipcAreas.length" class="text-caption ml-10 mt-2">
								<div class="grey--text mb-1">{{ $t('plugins.WorkshopService.servicePage.load_by_area') }}</div>
								<div v-for="a in ipcAreas" :key="a.id" class="svc-load-row" :title="a.help">
									<span class="svc-load-name">{{ a.name }}</span>
									<v-progress-linear :value="a.pct" height="6" rounded :color="a.pct >= 40 ? 'warning' : 'primary'" background-color="grey darken-3" class="svc-load-bar" />
									<span class="svc-load-num">{{ a.n }}/min &middot; {{ a.pct }}%</span>
								</div>
							</div>
							<div v-if="ipcKinds.length" class="text-caption ml-10 mt-3">
								<div class="grey--text mb-1">{{ $t('plugins.WorkshopService.servicePage.calls_one_by_one') }}</div>
								<div v-for="t in ipcKinds" :key="t.id" class="svc-load-row" :class="t.last_min > 30 ? 'warning--text' : ''" :title="t.help">
									<span class="svc-load-name">{{ t.name }}<span class="grey--text"> &middot; {{ t.id }}</span></span>
									<v-progress-linear :value="t.pct" height="4" rounded :color="t.last_min > 30 ? 'warning' : 'primary'" background-color="grey darken-3" class="svc-load-bar" />
									<span class="svc-load-num" :title="$t('plugins.WorkshopService.servicePage.last_minute')">{{ t.last_min }}/min &middot; {{ t.pct }}%</span>
									<span class="svc-load-num grey--text" :title="$t('plugins.WorkshopService.servicePage.the_slowest')">{{ $t('plugins.WorkshopService.servicePage.max_n_ms', { n: t.max_ms }) }}</span>
								</div>
								<div class="grey--text mt-1">{{ $t('plugins.WorkshopService.servicePage.warning_rows_hint', { n: 30 }) }}</div>
							</div>
							<div v-if="lightsIpc" class="text-caption ml-10 mt-1 svc-metricas grey--text">
								<span :title="$t('plugins.WorkshopService.servicePage.what_the_lights_module_still_asks')">{{ $t('plugins.WorkshopService.servicePage.lights_ipc', { r: lightsIpc.reads_min, c: lightsIpc.commands_min, p: lightsIpc.publishes_min }) }}</span>
							</div>
						</div>
						<!-- Servicios aparte de WorkshopService (puente, plugins con proceso propio) -->
						<div v-if="external.length" class="text-overline grey--text mt-3">{{ $t('plugins.WorkshopService.servicePage.separate_services') }}</div>
						<div v-for="x in external" :key="x.id" class="svc-proc">
							<div class="d-flex align-center flex-wrap">
								<v-icon class="mr-3 svx-ico">{{ x.icon }}</v-icon>
								<div class="svc-proc-txt">
									<div class="font-weight-medium">{{ x.title }}</div>
									<div class="text-caption grey--text">{{ x.description }}</div>
									<div v-if="x.detail" class="text-caption svc-detail"><v-icon x-small class="mr-1">mdi-information-outline</v-icon>{{ x.detail }}</div>
								</div>
								<v-spacer />
								<v-chip small label dark :color="x.state.color">{{ x.state.text }}</v-chip>
							</div>
							<div class="text-caption ml-10 mt-1">
								<span v-for="b in x.buses" :key="b.id" class="mr-3" :class="b.open ? 'success--text' : (b.error ? 'warning--text' : 'grey--text')" :title="b.error || ''">
									<v-icon x-small :color="b.open ? 'success' : (b.error ? 'warning' : 'grey')">mdi-serial-port</v-icon>
									{{ b.name }}: {{ b.open ? $t('plugins.WorkshopService.servicePage.open') : (b.error ? $t('plugins.WorkshopService.servicePage.with_a_problem') : $t('plugins.WorkshopService.servicePage.closed')) }}
									<span class="grey--text">{{ $t('plugins.WorkshopService.servicePage.bus_stats', { ok: b.stats.ok, nr: b.stats.without_response, crc: b.stats.crc }) }}</span>
								</span>
								<a v-if="x.path && hasPath(x.path)" href="#" class="ml-1" @click.prevent="$router.push(x.path)">{{ $t('plugins.WorkshopService.servicePage.open_the_page') }}</a><a v-else-if="x.anchor" href="#" class="ml-1" @click.prevent="goA(x.anchor)">{{ $t('plugins.WorkshopService.servicePage.see_details_and_settings') }}</a>
							</div>
							<div class="ml-10 mt-1">
								<a href="#" class="text-caption" @click.prevent="$set(docExt, x.id, !docExt[x.id])">
									<v-icon x-small color="primary">{{ docExt[x.id] ? 'mdi-chevron-up' : 'mdi-chevron-down' }}</v-icon>
									{{ docExt[x.id] ? $t('plugins.WorkshopService.procDocs.ext_less') : $t('plugins.WorkshopService.procDocs.ext_detail') }}
								</a>
							</div>
							<div v-if="docExt[x.id]" class="svc-doc-auto ml-10 mt-1">
								<div v-for="k in ['what', 'how', 'depends', 'why']" :key="k"><b>{{ $t('plugins.WorkshopService.procDocs.ext_' + k) }}</b> {{ $t('plugins.WorkshopService.procDocs.ext_' + x.id + '_' + k) }}</div>
							</div>
						</div>
					</v-card-text>
				</v-card>

			</v-col>

			<!-- Automatismos -->
			<v-col cols="12" md="5" class="svc-col">
				<v-card class="mb-3 svc-height">
					<v-card-title>
						<v-icon small class="mr-2 svx-ico">mdi-robot</v-icon>{{ $t('plugins.WorkshopService.servicePage.automations') }}
					</v-card-title>
					<v-card-text>
						<div class="svc-auto">
							<div class="d-flex align-center">
								<v-icon class="mr-2 svx-ico">mdi-weather-windy</v-icon>
								<v-switch
									:input-value="airAssistAuto" dense hide-details class="mt-0 pt-0"
									:label="$t('plugins.WorkshopService.servicePage.automatic_air_with_the_laser')" @change="setAirAuto"
								/>
								<v-spacer />
								<v-chip x-small label dark :color="airAssist ? 'success' : 'grey'">{{ airAssist ? $t('plugins.WorkshopService.servicePage.air_on') : $t('plugins.WorkshopService.servicePage.air_off') }}</v-chip>
							</div>
							<div class="text-caption grey--text svc-sub">
								{{ $t('plugins.WorkshopService.servicePage.air_rule') }}<span v-if="!airAssistAuto"> {{ $t('plugins.WorkshopService.servicePage.used_when_automatic_mode_is_on') }}</span>
								<div class="d-flex align-center flex-wrap mt-1" style="gap:4px">
									<span>{{ $t('plugins.WorkshopService.servicePage.air_off_after') }}</span>
									<v-chip-group :value="airAssistDelay" mandatory active-class="primary--text" @change="setDelay">
										<v-chip v-for="t in delayOptions" :key="t" :value="t" small outlined filter>{{ t }} s</v-chip>
									</v-chip-group>
								</div>
							</div>
							<div class="ml-9 mt-1">
								<a href="#" class="text-caption" @click.prevent="docAuto.air = !docAuto.air">
									<v-icon x-small color="primary">{{ docAuto.air ? 'mdi-chevron-up' : 'mdi-chevron-down' }}</v-icon>
									{{ docAuto.air ? $t('plugins.WorkshopService.procDocs.ui_less') : $t('plugins.WorkshopService.procDocs.ui_more') }}
								</a>
							</div>
							<div v-if="docAuto.air" class="svc-doc-auto ml-9 mt-1">
								<div><b>{{ $t('plugins.WorkshopService.procDocs.ui_auto_what') }}</b> {{ $t('plugins.WorkshopService.procDocs.auto_air_what') }}</div>
								<div><b>{{ $t('plugins.WorkshopService.procDocs.ui_auto_when') }}</b> {{ $t('plugins.WorkshopService.procDocs.auto_air_when') }}</div>
								<div><b>{{ $t('plugins.WorkshopService.procDocs.ui_auto_note') }}</b> {{ $t('plugins.WorkshopService.procDocs.auto_air_note') }}</div>
							</div>
						</div>

						<div v-if="lightsActive" class="svc-auto">
							<div class="d-flex align-center flex-wrap" style="gap:4px 12px">
								<v-icon class="mr-2 svx-ico">mdi-led-strip-variant</v-icon>
								<!-- Read-only (request 2026-10-09): the lights are controlled in the
								     Lights page (and the quick buttons of the sidebar / jog) -->
								<span style="flex:1 1 14rem;min-width:0">{{ $t('plugins.WorkshopService.servicePage.status_lights_x', { x: statusLightAuto ? $t('plugins.WorkshopService.servicePage.automatic_f') : $t('plugins.WorkshopService.servicePage.off_lighting_uses_those_leds') }) }}</span>
								<v-spacer />
								<v-chip x-small label :color="statusLightAuto ? 'success' : 'grey'" style="flex:none">{{ statusLightAuto ? $t('plugins.WorkshopService.servicePage.auto_state_on') : $t('plugins.WorkshopService.servicePage.auto_state_off') }}</v-chip>
								<!-- the link only exists with the plugin installed and active: stopped, the route does not exist -->
								<a href="#" class="text-body-2" style="flex:none" @click.prevent="$router.push('/Plugins/Lights')">{{ $t('plugins.WorkshopService.servicePage.open_lights_and_status') }}</a>
							</div>
							<div class="ml-9 mt-1">
								<a href="#" class="text-caption" @click.prevent="docAuto.lights = !docAuto.lights">
									<v-icon x-small color="primary">{{ docAuto.lights ? 'mdi-chevron-up' : 'mdi-chevron-down' }}</v-icon>
									{{ docAuto.lights ? $t('plugins.WorkshopService.procDocs.ui_less') : $t('plugins.WorkshopService.procDocs.ui_more') }}
								</a>
							</div>
							<div v-if="docAuto.lights" class="svc-doc-auto ml-9 mt-1">
								<div><b>{{ $t('plugins.WorkshopService.procDocs.ui_auto_what') }}</b> {{ $t('plugins.WorkshopService.procDocs.auto_lights_what') }}</div>
								<div><b>{{ $t('plugins.WorkshopService.procDocs.ui_auto_when') }}</b> {{ $t('plugins.WorkshopService.procDocs.auto_lights_when') }}</div>
								<div><b>{{ $t('plugins.WorkshopService.procDocs.ui_auto_note') }}</b> {{ $t('plugins.WorkshopService.procDocs.auto_lights_note') }}</div>
							</div>
						</div>

						<div class="svc-auto">
							<div class="d-flex align-center">
								<v-icon class="mr-2 svx-ico">mdi-power-sleep</v-icon>
								<v-switch
									:input-value="powerOffOnFinish" dense hide-details class="mt-0 pt-0"
									:label="$t('plugins.WorkshopService.servicePage.turn_everything_off_when_done')" @change="setShutdown"
								/>
								<v-spacer />
								<v-chip x-small label dark :color="powerOffOnFinish ? 'warning' : 'grey'">{{ powerOffOnFinish ? $t('plugins.WorkshopService.servicePage.armed') : $t('plugins.WorkshopService.servicePage.no_caps') }}</v-chip>
							</div>
							<div class="text-caption grey--text svc-sub">
								{{ $t('plugins.WorkshopService.servicePage.when_the_job_ends_shuts_the') }}
							</div>
							<div class="ml-9 mt-1">
								<a href="#" class="text-caption" @click.prevent="docAuto.poweroff = !docAuto.poweroff">
									<v-icon x-small color="primary">{{ docAuto.poweroff ? 'mdi-chevron-up' : 'mdi-chevron-down' }}</v-icon>
									{{ docAuto.poweroff ? $t('plugins.WorkshopService.procDocs.ui_less') : $t('plugins.WorkshopService.procDocs.ui_more') }}
								</a>
							</div>
							<div v-if="docAuto.poweroff" class="svc-doc-auto ml-9 mt-1">
								<div><b>{{ $t('plugins.WorkshopService.procDocs.ui_auto_what') }}</b> {{ $t('plugins.WorkshopService.procDocs.auto_poweroff_what') }}</div>
								<div><b>{{ $t('plugins.WorkshopService.procDocs.ui_auto_when') }}</b> {{ $t('plugins.WorkshopService.procDocs.auto_poweroff_when') }}</div>
								<div><b>{{ $t('plugins.WorkshopService.procDocs.ui_auto_note') }}</b> {{ $t('plugins.WorkshopService.procDocs.auto_poweroff_note' + (hasBar ? '' : '_no_bar')) }}</div>
							</div>
						</div>

						<!-- Movement of the machine (motion_owner.py): who may move it while there is a cut. One place for the jog, the Workbench, Vision, the frame... -->
						<div class="svc-auto svc-mov">
							<div class="d-flex align-center">
								<v-icon class="mr-2 svx-ico">mdi-steering</v-icon>
								<span>{{ $t('plugins.WorkshopService.servicePage.mov_card_title') }}</span>
								<v-spacer />
								<v-chip x-small label dark :color="movFree ? 'success' : 'warning'">{{ $t('plugins.WorkshopService.servicePage.mov_state_' + movState) }}</v-chip>
							</div>
							<div class="text-caption grey--text svc-sub">{{ $t('plugins.WorkshopService.servicePage.mov_card_sub') }}</div>
							<div class="svc-mov-opts mt-2">
								<v-sheet
									v-for="o in movOptions" :key="o.value" outlined rounded class="svc-mov-opt pa-2"
									:class="{ 'svc-mov-sel': movMode === o.value }" @click="setMovMode(o.value)"
								>
									<div class="d-flex align-center">
										<v-icon small :color="movMode === o.value ? 'primary' : 'grey'">{{ movMode === o.value ? 'mdi-radiobox-marked' : 'mdi-radiobox-blank' }}</v-icon>
										<span class="font-weight-medium ml-2">{{ o.title }}</span>
									</div>
									<div class="text-caption grey--text ml-6">{{ o.detail }}</div>
								</v-sheet>
							</div>
							<div v-if="movMode === 'protected'" class="text-caption grey--text svc-sub mt-2">
								<a href="#" @click.prevent="movAdvanced = !movAdvanced">
									<v-icon x-small color="primary">{{ movAdvanced ? 'mdi-chevron-up' : 'mdi-chevron-down' }}</v-icon>{{ $t('plugins.WorkshopService.servicePage.mov_adv') }}
								</a>
								<div v-if="movAdvanced" class="mt-1">
									<div class="d-flex align-center flex-wrap" style="gap:4px">
										<span>{{ $t('plugins.WorkshopService.servicePage.mov_release_t') }}</span>
										<v-chip-group :value="movRelease" mandatory active-class="primary--text" @change="setMovRelease">
											<v-chip v-for="t in movTimes" :key="t.value" :value="t.value" small outlined filter>{{ t.text }}</v-chip>
										</v-chip-group>
									</div>
									<div>{{ $t('plugins.WorkshopService.servicePage.mov_release_d') }}</div>
								</div>
							</div>
						</div>

						<div class="svc-auto">
							<div class="d-flex align-center">
								<v-icon class="mr-2 svx-ico">mdi-laser-pointer</v-icon>
								<span>{{ $t('plugins.WorkshopService.servicePage.live_job') }}</span>
								<v-spacer />
								<v-chip x-small label dark :color="job.active ? 'success' : 'grey'">{{ job.active ? $t('plugins.WorkshopService.servicePage.running') : $t('plugins.WorkshopService.servicePage.none') }}</v-chip>
							</div>
							<div class="text-caption grey--text svc-sub">
								<template v-if="job.active">
									<b>{{ jobName }}</b>
									<span v-if="job.file"> · {{ String(job.file).split('/').pop() }}</span>
									<span v-if="job.since"> · {{ $t('plugins.WorkshopService.servicePage.since_t', { t: hourShort(job.since) }) }}</span>
									<span v-if="job.lastActivity"> · {{ $t('plugins.WorkshopService.servicePage.last_activity_t', { t: hourShort(job.lastActivity) }) }}</span>
								</template>
								<!-- 2026-10-10, requested: it should say "live job" -->
								<template v-else>{{ $t('plugins.WorkshopService.servicePage.a_program_that_sends_the_job') }}</template>
							</div>
							<!-- how a live job is considered finished (job_live.py): the program's end signal always works; this is the fallback -->
							<div class="text-caption grey--text svc-sub mt-2">
								<div>{{ $t('plugins.WorkshopService.servicePage.live_end_intro') }}</div>
								<div class="d-flex align-center flex-wrap mt-1" style="gap:4px">
									<span>{{ $t('plugins.WorkshopService.servicePage.live_end_after') }}</span>
									<v-chip-group :value="movIdle" mandatory active-class="primary--text" @change="setMovIdle">
										<v-chip v-for="t in movRests" :key="t.value" :value="t.value" small outlined filter>{{ t.text }}</v-chip>
									</v-chip-group>
								</div>
								<div class="mt-1">{{ $t('plugins.WorkshopService.servicePage.live_end_note') }}</div>
							</div>
							<div class="d-flex justify-end mt-1">
								<v-btn
									v-if="job.active" small outlined :dark="close.armed" :color="close.armed ? 'amber darken-3' : null"
									:loading="close.sending" @click="closeJob"
								>
									{{ close.armed ? $t('plugins.WorkshopService.servicePage.tap_again_close_the_job') : $t('plugins.WorkshopService.servicePage.close_job') }}
								</v-btn>
							</div>
							<div v-if="job.active && job.file" class="text-caption grey--text svc-sub">{{ $t('plugins.WorkshopService.servicePage.it_came_in_a_file_it') }}</div>
							<div v-if="close.msg" class="text-caption svc-sub">{{ close.msg }}</div>
							<div class="ml-9 mt-1">
								<a href="#" class="text-caption" @click.prevent="docAuto.job = !docAuto.job">
									<v-icon x-small color="primary">{{ docAuto.job ? 'mdi-chevron-up' : 'mdi-chevron-down' }}</v-icon>
									{{ docAuto.job ? $t('plugins.WorkshopService.procDocs.ui_less') : $t('plugins.WorkshopService.procDocs.ui_more') }}
								</a>
							</div>
							<div v-if="docAuto.job" class="svc-doc-auto ml-9 mt-1">
								<div><b>{{ $t('plugins.WorkshopService.procDocs.ui_auto_what') }}</b> {{ $t('plugins.WorkshopService.procDocs.auto_job_what') }}</div>
								<div><b>{{ $t('plugins.WorkshopService.procDocs.ui_auto_when') }}</b> {{ $t('plugins.WorkshopService.procDocs.auto_job_when') }}</div>
								<div><b>{{ $t('plugins.WorkshopService.procDocs.ui_auto_note') }}</b> {{ $t('plugins.WorkshopService.procDocs.auto_job_note') }}</div>
							</div>
						</div>
					</v-card-text>
				</v-card>
			</v-col>
		</v-row>

		</div>
		<div v-if="visited.password" v-show="section === 'password'">
		<!-- Contrasena de DWC (2026-10-10): M551 en sys/config.g (handlers/password.py) -->
		<v-card class="mb-3">
			<v-card-title>
				<v-icon small class="mr-2 svx-ico">mdi-lock</v-icon>{{ $t('plugins.WorkshopService.servicePage.dwc_password') }}
				<v-spacer />
				<v-chip small dark :color="key.has === null ? 'grey' : (key.has ? 'success' : 'warning')">
					{{ key.has === null ? $t('plugins.WorkshopService.common.no_data_2') : (key.has ? $t('plugins.WorkshopService.servicePage.set') : $t('plugins.WorkshopService.servicePage.no_password')) }}
				</v-chip>
			</v-card-title>
			<v-card-text>
				<div class="text-caption grey--text mb-2">
					{{ $t('plugins.WorkshopService.servicePage.with_a_password_dwc_asks_for') }}
				</div>
				<div class="text-caption warning--text mb-3">
					{{ $t('plugins.WorkshopService.servicePage.if_you_forget_it_dwc_won') }}
				</div>
				<v-row dense>
					<v-col cols="12" sm="5">
						<v-text-field v-model="key.newEntry" type="password" :label="$t('plugins.WorkshopService.servicePage.new_password')" dense outlined hide-details autocomplete="new-password" />
					</v-col>
					<v-col cols="12" sm="5">
						<v-text-field v-model="key.repeat" type="password" :label="$t('plugins.WorkshopService.servicePage.repeat_the_password')" dense outlined hide-details autocomplete="new-password" />
					</v-col>
					<v-col cols="12" sm="2" class="d-flex align-center">
						<v-btn small block :color="key.armed === 'set' ? 'error' : 'primary'" :loading="key.sending" :disabled="!keyValid" @click="putKey">
							{{ key.armed === 'set' ? $t('plugins.WorkshopService.servicePage.confirm_q') : (key.has ? $t('plugins.WorkshopService.servicePage.change') : $t('plugins.WorkshopService.servicePage.set_2')) }}
						</v-btn>
					</v-col>
				</v-row>
				<div v-if="key.newEntry && !keyValid" class="text-caption warning--text mt-1">{{ keyProblem }}</div>
				<div class="d-flex align-center mt-3">
					<v-btn v-if="key.has" small outlined :color="key.armed === 'clear' ? 'error' : null" :disabled="key.sending" @click="removeKey">
						{{ key.armed === 'clear' ? $t('plugins.WorkshopService.servicePage.confirm_q') : $t('plugins.WorkshopService.servicePage.remove_the_password') }}
					</v-btn>
					<span v-if="key.msg" class="text-caption ml-3">{{ key.msg }}</span>
				</div>
			</v-card-text>
		</v-card>

		</div>
		<div v-if="visited.bridge" v-show="section === 'bridge'">
		<!-- G-code bridge (Telnet): full width (separate service on the Pi, ~/workshop-bridge) -->
		<div id="svc-bridge"><bridge-card /></div>

		</div>
		<div v-if="visited.commands" v-show="section === 'commands'">
		<!-- Comandos recibidos: historial completo (unico lugar; antes habia uno en Actividad) -->
		<received-commands :color-of="rowCat" :change="lastChange" />

		</div>
		<div v-if="visited.base" v-show="section === 'base'">
		<!-- Database and backups (2026-10-11; phone notices send here) -->
		<div id="svc-base"><database /></div>
		<!-- Configuration package: settings, zones and macros of this machine in one zip (no secrets) -->
		<div id="svc-package"><config-package /></div>

		</div>
		<div v-if="visited.users" v-show="section === 'users'">
		<!-- People of the workshop: name + PIN, roles applied by the service -->
		<users-card />

		</div>
		<div v-if="visited.audit" v-show="section === 'audit'">
		<!-- Who did what (read only; nobody can delete it from here) -->
		<audit-card />

		</div>
		<div v-if="visited.api" v-show="section === 'api'">
		<div class="wf-section-head">
			<v-icon class="svx-ico">mdi-api</v-icon>
			<h2>{{ $t('plugins.WorkshopService.servicePage.api_top_title') }}</h2>
			<span v-if="handlers.length" class="wf-pill">{{ $t('plugins.WorkshopService.servicePage.n_operations', { n: handlers.length }) }}</span>
			<p class="wf-lead">{{ $t('plugins.WorkshopService.servicePage.api_top_sub') }}</p>
		</div>
		<!-- Keys of the external services -->
		<api-keys :operations="apiOps || []" />

		<!-- Referencia de comandos -->
		<v-card class="mb-3">
			<v-card-title>
				<v-icon small class="mr-2 svx-ico">mdi-book-open-variant</v-icon>{{ $t('plugins.WorkshopService.page.apiTitle') }}
			</v-card-title>
			<v-card-text>
				<details class="wf-more mb-3">
					<summary>{{ $t('plugins.WorkshopService.servicePage.how_it_works') }}</summary>
					<p>{{ $t('plugins.WorkshopService.page.apiHelp') }}</p>
				</details>
				<div class="svx-cats">
					<button v-for="c in categories" :key="c.id" type="button" class="wf-cat" :class="{ on: catFilter === c.id }" :aria-pressed="catFilter === c.id ? 'true' : 'false'" :style="{ '--wf-cat': c.color }" @click="pickCat(c.id)">
						<v-icon small>{{ c.icon }}</v-icon>
						<span>{{ c.name }}</span><small class="svx-count">{{ c.n }}</small>
					</button>
				</div>
				<div v-if="catFilter && subCats.length > 1" class="svx-subs" :style="{ '--wf-cat': catColor }">
					<button type="button" class="svx-sub" :class="{ on: !subFilter }" @click="subFilter = null">{{ $t('plugins.WorkshopService.common.all') }} <small>{{ catCount }}</small></button>
					<button v-for="s in subCats" :key="s.id" type="button" class="svx-sub" :class="{ on: subFilter === s.id }" @click="subFilter = subFilter === s.id ? null : s.id"><code>{{ s.id }}</code> <small>{{ s.n }}</small></button>
				</div>
				<div class="svx-tools">
					<v-text-field
						v-model="filter" :placeholder="$t('plugins.WorkshopService.common.find')" prepend-inner-icon="mdi-magnify" style="max-width: 280px"
					/>
					<span class="svx-label">{{ $t('plugins.WorkshopService.servicePage.show') }}</span>
					<v-btn-toggle v-model="readFilter" dense mandatory color="primary" class="svc-read-toggle">
						<v-btn small value="all">{{ $t('plugins.WorkshopService.common.all') }}</v-btn>
						<v-btn small value="always"><v-icon left small>mdi-eye-outline</v-icon>{{ $t('plugins.WorkshopService.common.read_only') }}</v-btn>
						<v-btn small value="no"><v-icon left small>mdi-pencil-outline</v-icon>{{ $t('plugins.WorkshopService.common.change_something') }}</v-btn>
					</v-btn-toggle>
				</div>
				<v-expansion-panels class="mt-3 svx-panels">
					<v-expansion-panel v-for="h in handlersFiltered" :key="h.name">
						<v-expansion-panel-header class="py-1">
							<div class="d-flex align-center">
								<span v-if="!catFilter" class="wf-cat svx-cat-tag mr-2" :style="{ '--wf-cat': catOf(h.name).color }"><v-icon small>{{ catOf(h.name).icon }}</v-icon>{{ catOf(h.name).name }}</span>
								<code>{{ h.name }}</code>
								<v-chip v-if="h.reading" x-small label outlined :color="read(h).color" class="ml-2 svc-read" :title="read(h).title">
									<v-icon left x-small>{{ read(h).icon }}</v-icon>{{ read(h).text }}
								</v-chip>
								<v-chip v-if="h.macro" x-small label outlined class="ml-2">{{ $t('plugins.WorkshopService.page.macroChip') }}</v-chip>
								<span class="text-caption grey--text ml-2">{{ summary(h.description) }}</span>
							</div>
						</v-expansion-panel-header>
						<v-expansion-panel-content>
							<div class="text-body-2 mb-2">{{ h.description }}</div>
							<api-detail :op="(apiOps || []).find(x => x.op === h.name) || null" />
							<div v-if="h.reading" class="svc-read-det mb-2">
								<v-icon small :color="read(h).color" class="mr-1">{{ read(h).icon }}</v-icon>{{ read(h).title }}
							</div>
							<div v-if="h.usage" class="d-flex align-start">
								<code
									class="d-block pa-2 svc-use svc-use-click flex-grow-1" :title="$t('plugins.WorkshopService.servicePage.tap_to_use_it_in_the')"
									@click="useExample(h)"
								>{{ h.usage.replace(/^Uso:\s*/, '') }}</code>
								<v-btn icon small class="ml-1" :title="$t('plugins.WorkshopService.servicePage.copy_the_example')" @click="copy(h.usage.replace(/^Uso:\s*/, ''), h.name)">
									<v-icon small>{{ copied === h.name ? 'mdi-check' : 'mdi-content-copy' }}</v-icon>
								</v-btn>
							</div>

							<!-- Test from here (2026-10-09) -->
							<div class="svc-prueba mt-3">
								<div class="text-caption grey--text mb-1">
									{{ $t('plugins.WorkshopService.servicePage.test') }}
									<span v-if="dangerous(h.name)" class="warning--text">{{ $t('plugins.WorkshopService.servicePage.this_command_acts_on_the_machine') }}</span>
								</div>
								<div class="d-flex align-center">
									<v-text-field
										:value="test(h).code" dense hide-details outlined class="svc-test-field" :label="$t('plugins.WorkshopService.page.argsLabel')"
										@input="v => setTest(h, { code: v })" @keyup.enter="sendTest(h)"
									/>
									<v-btn
										small class="ml-2" :loading="test(h).sending"
										:color="test(h).armed ? 'error' : (dangerous(h.name) ? 'warning' : 'primary')"
										@click="sendTest(h)"
									>
										<v-icon left small>mdi-send</v-icon>{{ test(h).armed ? $t('plugins.WorkshopService.servicePage.confirm_q') : $t('plugins.WorkshopService.servicePage.send') }}
									</v-btn>
									<v-btn icon small class="ml-1" :title="$t('plugins.WorkshopService.servicePage.copy_this_command')" @click="copy(test(h).code, h.name + ':campo')">
										<v-icon small>{{ copied === h.name + ':field' ? 'mdi-check' : 'mdi-content-copy' }}</v-icon>
									</v-btn>
								</div>
								<div v-if="test(h).result" class="svc-result mt-2">
									<div class="d-flex align-center mb-1">
										<v-chip x-small label dark :color="test(h).result.ok ? 'success' : 'error'">{{ test(h).result.ok ? $t('plugins.WorkshopService.servicePage.ok') : 'ERROR' }}</v-chip>
										<span class="text-caption grey--text ml-2">{{ test(h).result.hour }} - {{ test(h).result.ms }} ms</span>
									</div>
									<pre class="svc-res-txt">{{ test(h).result.text || $t('plugins.WorkshopService.common.no_response') }}</pre>
								</div>
							</div>
						</v-expansion-panel-content>
					</v-expansion-panel>
				</v-expansion-panels>
			</v-card-text>
		</v-card>
		</div>
		</div>
		</div>
	</v-container>
</template>

<script>
import i18n from '../../i18n'

'use strict'

import { mapActions } from 'vuex'
import { api, apiText, currentIdentity, onIdentity } from './workshop-api.js'
import { serviceTexts, serviceDefaultName } from './service-text.js'
import { pluginOf, IDS, pluginActive, pathExists } from './workshop-ids.js' // Id nuevo o viejo de cada plugin
import BridgeCard from './BridgeCard.vue'
import SideTabs from './SideTabs.vue'
import PageHeader from './PageHeader.vue'
import { pluginBadge } from './plugin-colors.js'
import { PLUGIN_ID } from './plugin-id.js'
import { copyText } from './copy.js'
import ReceivedCommands from './ReceivedCommands.vue'
import Database from './Database.vue'
import ApiKeys from './ApiKeys.vue'
import UsersCard from './UsersCard.vue'
import AuditCard from './AuditCard.vue'
import ApiDetail from './ApiDetail.vue'
import ProcessRow from './ProcessRow.vue'
import ProcessesSummary from './ProcessesSummary.vue'
import BlackBoxCard from './BlackBoxCard.vue'
import ConfigPackage from './ConfigPackage.vue'
import StartupMaster from './StartupMaster.vue'
import { matches } from './search.js'
import { hist as histProc, sample } from './processes-history.js'
// same color per LED as the rest of the interface
import { ledColor } from './LedStrip.vue'

// Icono, color y categoria de cada proceso interno (dsf/latidos.py)
// Calls to the board: warning limit (calls/min) and the area of each type of call
const IPC_LIMIT = 240;
const IPC_AREAS = {
	statusLightModes: { area: 'status_lights' }, statusLightSecs: { area: 'status_lights' }, statusLightColor: { area: 'status_lights' },
	status_light: { area: 'status_lights' }, ledStrip: { area: 'status_lights' }, lightsInfo: { area: 'status_lights' },
	motorReport: { area: 'motors' }, consumption_poller: { area: 'power' }, consumptionCurrent: { area: 'power' },
	servicesInternal: { area: 'services' }, healthPi: { area: 'health' }, camera_relay: { area: 'camera' }
};

const PROC_INFO = {
	interceptor: { icon: 'mdi-code-braces', color: '#5C6BC0', cat: 'G-code' },
	status_light: { icon: 'mdi-led-on', color: '#FFB300', cat: i18n.t('plugins.WorkshopService.servicePage.lights_and_status') },
	consumption: { icon: 'mdi-flash', color: '#8E24AA', cat: i18n.t('plugins.WorkshopService.servicePage.energy') },
	jobs: { icon: 'mdi-briefcase-outline', color: '#1E88E5', cat: i18n.t('plugins.WorkshopService.servicePage.jobs') },
	motors: { icon: 'mdi-engine', color: '#00897B', cat: i18n.t('plugins.WorkshopService.servicePage.machine') },
	jog: { icon: 'mdi-gamepad-variant', color: '#039BE5', cat: i18n.t('plugins.WorkshopService.servicePage.machine') },
	events: { icon: 'mdi-bell-alert', color: '#E53935', cat: i18n.t('plugins.WorkshopService.common.activity') },
	trace: { icon: 'mdi-vector-polyline', color: '#43A047', cat: i18n.t('plugins.WorkshopService.servicePage.jobs') },
	health: { icon: 'mdi-heart-pulse', color: '#D81B60', cat: i18n.t('plugins.WorkshopService.servicePage.system') }
};
// section of the side bar that holds each anchor (the link "see details and settings" of the processes list)
const ANCHOR_SECTION = { 'svc-bridge': 'bridge', 'svc-base': 'base' };
const PROC_OTHER = { icon: 'mdi-cog', color: '#757575', cat: i18n.t('plugins.WorkshopService.servicePage.other') };


// Commands that act on the machine or the current: testing them asks for a double tap
// (kind of the operation in api.describe: motion, power, admin)
const PELIGROSOS_KIND = ['motion', 'power', 'admin'];

// Category of each API operation (by its group)
// the sub-group of an operation: its name up to the last dot (machine.workarea.get -> machine.workarea)
function subOf(name) {
	const i = String(name || '').lastIndexOf('.');
	return i > 0 ? name.slice(0, i) : name;
}

const CATS = [
	{ id: 'machine', name: i18n.t('plugins.WorkshopService.servicePage.cat_machine'), icon: 'mdi-gamepad-variant', color: '#1E88E5', re: /^(machine|jog|motion|motors|movement|frame|pid|safety|guard|readiness|preflight|workstate)\./ },
	{ id: 'jobs', name: i18n.t('plugins.WorkshopService.servicePage.cat_jobs'), icon: 'mdi-briefcase-outline', color: '#00ACC1', re: /^(job|livejob|bigpart|air|laser)\./ },
	{ id: 'lights', name: i18n.t('plugins.WorkshopService.servicePage.lights_and_status'), icon: 'mdi-lightbulb', color: '#FFA000', re: /^(light|lights|statuslight)\./ },
	{ id: 'energy', name: i18n.t('plugins.WorkshopService.servicePage.energy'), icon: 'mdi-flash', color: '#8E24AA', re: /^(power|energy|meter)\./ },
	{ id: 'activity', name: i18n.t('plugins.WorkshopService.servicePage.cat_activity'), icon: 'mdi-history', color: '#00897B', re: /^(activity|notifications|history|risk|blackbox|trace|sound)\./ },
	{ id: 'camera', name: i18n.t('plugins.WorkshopService.servicePage.cat_cameras'), icon: 'mdi-cctv', color: '#3949AB', re: /^(camera|vision)\./ },
	{ id: 'security', name: i18n.t('plugins.WorkshopService.servicePage.cat_security'), icon: 'mdi-shield-account-outline', color: '#D81B60', re: /^(auth|users|password|keys)\./ },
	{ id: 'config', name: i18n.t('plugins.WorkshopService.servicePage.cat_config'), icon: 'mdi-tune', color: '#6D4C41', re: /^(config|settings|profile|package|modules|bridge|comms|db|api|examples|state|view)\./ },
	{ id: 'system', name: i18n.t('plugins.WorkshopService.servicePage.system'), icon: 'mdi-cog', color: '#757575', re: /./ }
];

export default {
	components: { PageHeader, BlackBoxCard: BlackBoxCard, ConfigPackage, StartupMaster, SideTabs, BridgeCard: BridgeCard, ReceivedCommands, Database: Database, ApiKeys: ApiKeys, UsersCard, AuditCard, ApiDetail: ApiDetail, ProcessRow: ProcessRow, ProcessesSummary: ProcessesSummary },
	data() {
		return {
			section: 'summary', // the section chosen in the side bar
			visited: { password: false, bridge: false, commands: false, base: false, users: false, audit: false, api: false }, // sections already opened: they stay mounted (v-show) so going back does not reload them
			identity: currentIdentity(), // who uses this page (auth.whoami): compat = no user created yet
			rs485Received: null,
			visionState: null, // GET :8095/estado de WorkshopVision (OpenCV)
			visionError: null,
			nowSvc: Date.now(),
			histProc,
			procFilter: 'all',
			procCat: null,
			procSearch: '',
			modeError: {},
			docAuto: { air: false, lights: false, poweroff: false, job: false },
			docExt: {},
			procOpen: {},
			filter: '',
			copied: null,
			catFilter: null,
			subFilter: null, // sub-group inside the chosen category (the op prefix, e.g. machine.workarea)
			readFilter: 'all',
			tests: {}, // nombre -> {codigo (JSON of the arguments), enviando, armado, resultado}
			apiOps: null, // api.describe of the service (operations with their arguments)
			savingChannel: false,
			advancedOpen: false, // Advanced section of the communication with the Duet
			advanced: false, // cambio de canales desbloqueado (doble confirmacion); vuelve a false al guardar o cerrar
			armedAdv: false,
			key: { has: null, newEntry: '', repeat: '', armed: null, sending: false, msg: '' },
			close: { armed: false, sending: false, msg: '' },
			box: { lowering: false, sending: false, msg: '' },
			movAdvanced: false // the advanced seconds of the movement card are folded by default
		};
	},
	watch: {
		// the first time a heavy section is opened it is mounted and from then on only hidden
		section(v) {
			if (v in this.visited) {
				this.visited[v] = true;
			}
		},
		// Deep link from other pages: /Plugins/WorkshopService?anchor=svc-base (page may be kept alive)
		'$route.query.anchor'(id) {
			if (id) {
				this.irAcuando(id);
			}
		},
		rs485Ts(v, old) {
			if (v && v !== old) {
				this.rs485Received = Date.now();
			}
		}
	},
	computed: {
		badge() {
			return pluginBadge(PLUGIN_ID)
		},
		// other plugins: what points to them shows only when they are installed and enabled
		hasJog() {
			return pluginActive(this.$store, 'jog');
		},
		hasBar() {
			return pluginActive(this.$store, 'bar');
		},
		// what stops working while the service is stopped, naming only the plugins that are there
		withoutServiceList() {
			const t = k => i18n.t('plugins.WorkshopService.servicePage.' + k);
			const l = [];
			if (this.hasJog) l.push(t('stopped_the_jog'));
			if (this.lightsActive) l.push(t('stopped_the_lights'));
			l.push(t('stopped_the_phone_alerts'));
			l.push(t('stopped_the_api'));
			return l.slice(0, -1).join(', ') + t('stopped_and') + l[l.length - 1];
		},
		// the page is long: its sections go in a side bar (same as the Vision and Work table bars)
		sections() {
			const t = k => i18n.t('plugins.WorkshopService.servicePage.' + k);
			return [
				{ id: 'summary', icon: 'mdi-view-dashboard-outline', label: t('nav_summary') },
				{ id: 'processes', icon: 'mdi-cogs', label: t('nav_processes') },
				{ id: 'bridge', icon: 'mdi-console-network-outline', label: t('nav_bridge') },
				{ id: 'commands', icon: 'mdi-history', label: t('nav_commands') },
				{ id: 'base', icon: 'mdi-database-outline', label: t('nav_database') },
				{ id: 'users', icon: 'mdi-account-group-outline', label: t('nav_users') },
				{ id: 'audit', icon: 'mdi-clipboard-text-clock-outline', label: t('nav_audit') },
				{ id: 'api', icon: 'mdi-api', label: t('nav_api') },
				{ id: 'password', icon: 'mdi-lock-outline', label: t('nav_password') },
			];
		},
		// "Luces y estados" (WorkshopLights) instalado y habilitado en Ajustes > Complementos
		lightsActive() {
			const st = this.$store.state;
			if (!pluginOf(st.machine.model.plugins, 'lights')) return false;
			const ms = st.machine.settings && st.machine.settings.enabledPlugins;
			const gs = st.settings && st.settings.enabledPlugins;
			if (!Array.isArray(ms) && !Array.isArray(gs)) return true; // lista aun sin cargar: no ocultar
			return IDS.lights.some(id => (ms || []).includes(id) || (gs || []).includes(id));
		},
		pluginModel() {
			const plugins = this.$store.state.machine.model.plugins;
			return pluginOf(plugins, 'service');
		},
		runs() {
			const p = this.$store.state.machine.model.plugins;
			const pm = pluginOf(p, 'service');
			return !!(pm && pm.pid > 0);
		},
		connected() {
			return this.runs && !!this.pluginData('connected');
		},
		serviceOwn() {
			if (!this.runs) {
				return { text: i18n.t('plugins.WorkshopService.servicePage.stopped'), color: 'error', icon: 'mdi-stop-circle', detail: i18n.t('plugins.WorkshopService.servicePage.the_plugin_process_is_not_running') };
			}
			if (!this.pluginData('connected')) {
				return { text: i18n.t('plugins.WorkshopService.servicePage.connecting'), color: 'warning', icon: 'mdi-lan-pending', detail: i18n.t('plugins.WorkshopService.servicePage.process_runs_not_connected') };
			}
			const bad = this.processes.filter(p => p.state.level === 2).length;
			if (bad) {
				return { text: i18n.t('plugins.WorkshopService.servicePage.with_problems_2'), color: 'warning', icon: 'mdi-alert', detail: i18n.t('plugins.WorkshopService.servicePage.n_internal_processes_with_problems', { n: bad }) };
			}
			return { text: i18n.t('plugins.WorkshopService.servicePage.running_2'), color: 'success', icon: 'mdi-check-circle', detail: i18n.t('plugins.WorkshopService.servicePage.runs_on_the_system_and_is') };
		},
		airAssist() {
			return !!this.pluginData('airAssist');
		},
		airAssistAuto() {
			const v = this.pluginData('airAssistAuto');
			return v === null || v === undefined ? true : !!v;
		},
		delayOptions() {
			const base = [0, 2, 5, 10, 30];
			return base.includes(this.airAssistDelay) ? base : base.concat(this.airAssistDelay).sort((x, y) => x - y);
		},
		airAssistDelay() {
			const v = this.pluginData('airAssistDelay');
			return v == null ? 2 : Number(v);
		},
		statusLightAuto() {
			const v = this.pluginData('statusLightAuto');
			return v === null || v === undefined ? true : !!v;
		},
		statusLightColor() {
			return this.pluginData('statusLightColor') || '#000000';
		},
		statusLightText() {
			return this.pluginData('statusLightText') || '';
		},
		// On-screen indicator (Lights and states page): the current state with its color
		// and the reason; null with a service from before the redesign.
		statusIndicator() {
			const i = this.pluginData('statusIndicator');
			return i && i.state ? i : null;
		},
		// Stretches as they are painted on the strip ([[hex, level 0..1, count], ...]);
		// with automatic off they are the LEDs the illumination took.
		statusLightSecs() {
			const s = this.pluginData('statusLightSecs');
			// also with automatic off: there the Pi publishes the illumination
			return Array.isArray(s) ? s.filter(x => x[2] > 0) : [];
		},
		// Round indicator (request 2026-10-09): each state takes its proportion
		// of the circle's LEDs, with the same colors as the strip.
		statusLightPie() {
			const total = this.statusLightSecs.reduce((t, s) => t + s[2], 0);
			if (!total) {
				return this.statusLightAuto ? this.statusLightColor : '#616161';
			}
			let pos = 0;
			const parts = this.statusLightSecs.map(s => {
				const a = (pos / total) * 360, b = ((pos + s[2]) / total) * 360;
				pos += s[2];
				return `${ledColor(s)} ${a.toFixed(1)}deg ${b.toFixed(1)}deg`;
			});
			return `conic-gradient(${parts.join(',')})`;
		},
		// Color of the first lit stretch (glow and card border)
		statusLightBrightness() {
			if (this.statusIndicator) {
				return this.statusIndicator.state.hex;
			}
			const lit = this.statusLightSecs.find(s => s[1] > 0);
			if (lit) {
				return ledColor(lit);
			}
			return this.statusLightSecs.length ? 'none' : this.statusLightColor;
		},
		powerOffOnFinish() {
			const g = this.$store.state.machine.model.global;
			return !!(g && (typeof g.get === 'function' ? g.get('powerOffOnFinish') : g.powerOffOnFinish));
		},
		job() {
			return this.pluginData('liveJob') || {};
		},
		// the default name (empty, or the default one in either language) in the language of this DWC; a given name as it is
		jobName() {
			return serviceDefaultName(this.job.name, ['live_job_default_name']);
		},
		boxBlack() {
			return this.pluginData('boxBlack') || {};
		},
		boxReport() {
			const r = this.boxBlack.report;
			return r && !r.seen ? r : null;
		},
		// last unclean shutdown that was recorded, hidden or not
		lastDrop() {
			return this.boxBlack.last_drop || null;
		},
		// movement lock settings (published by motion_owner.py in data.motion.settings)
		movAj() {
			return (this.pluginData('motion') || {}).settings || {};
		},
		movMode() {
			return this.movAj.mode === 'duet' ? 'duet' : 'protected';
		},
		movRelease() {
			return typeof this.movAj.release_s === 'number' ? this.movAj.release_s : 20;
		},
		movIdle() {
			return typeof this.movAj.idle_s === 'number' ? this.movAj.idle_s : 30;
		},
		movState() {
			const st = (this.pluginData('motion') || {}).state;
			return ['free', 'file_job', 'file_paused', 'live_active', 'live_idle', 'bridge_active', 'stopped'].includes(st) ? st : 'free';
		},
		movFree() {
			return this.movState === 'free';
		},
		// the two choices, written as what happens and not as a product name
		movOptions() {
			const T = 'plugins.WorkshopService.servicePage.';
			return [
				{ value: 'protected', title: i18n.t(T + 'mov_opt_nobody_t'), detail: i18n.t(T + 'mov_opt_nobody_d') },
				{ value: 'duet', title: i18n.t(T + 'mov_opt_me_t'), detail: i18n.t(T + 'mov_opt_me_d') }
			];
		},
		// quick values as buttons; the saved value is always one of them (a custom one is added)
		movTimes() {
			return this.optionsSeconds([8, 20, 60], this.movRelease);
		},
		movRests() {
			return this.optionsSeconds([15, 30, 60, 300, 0], this.movIdle);
		},
		// mismas reglas que handlers/password.py (_valida)
		keyProblem() {
			const c = this.key.newEntry || '';
			if (c.length < 4 || c.length > 60) return i18n.t('plugins.WorkshopService.servicePage.it_must_have_4_to_60');
			if (/[";\r\n]/.test(c) || /[\x00-\x1f]/.test(c)) return i18n.t('plugins.WorkshopService.servicePage.it_can_t_contain_quotes_semicolons');
			if (c.toLowerCase() === 'reprap') return i18n.t('plugins.WorkshopService.servicePage.reprap_is_the_factory_one_no');
			if (c !== this.key.repeat) return i18n.t('plugins.WorkshopService.servicePage.the_two_don_t_match');
			return '';
		},
		keyValid() {
			return !!this.key.newEntry && !this.keyProblem;
		},
		communication() {
			const c = this.pluginData('communication');
			return c && c.channels ? c : null;
		},
		// Channel list: with a service older than 1.9.1 only 3 come
		// (without "elegible"): it is deduced from existe/ocupado.
		channelsList() {
			const cs = (this.communication && this.communication.channels) || [];
			return cs.map(c => Object.assign({ usage: '', state: c.busy ? 'busy' : 'free' }, c, {
				eligible: c.eligible !== undefined ? c.eligible : (c.exists && !c.busy)
			}));
		},
		optionsChannel() {
			return [{ v: 'auto', t: i18n.t('plugins.WorkshopService.servicePage.automatic_aux2_aux_or_sbc_the') }].concat(this.optionsOf(this.channelsList));
		},
		optionsJog() {
			return [{ v: 'auto', t: i18n.t('plugins.WorkshopService.servicePage.automatic_aux2_if_free_otherwise_sbc') }].concat(this.optionsOf(this.channelsList));
		},
		// why automatic mode chose that channel (only shown with "auto")
		perThatJog() {
			const c = this.communication;
			if (!c) return '';
			return c.channel_jog === 'Aux2' ? i18n.t('plugins.WorkshopService.servicePage.aux2_is_free_and_gives_the') : i18n.t('plugins.WorkshopService.servicePage.aux2_is_not_free_the_jog');
		},
		perThatService() {
			const c = this.communication;
			if (!c) return '';
			return c.channel === 'SBC' ? i18n.t('plugins.WorkshopService.servicePage.aux2_and_aux_are_not_free') : i18n.t('plugins.WorkshopService.servicePage.first_free_channel_the_jog_does');
		},
		serviceStarted() {
			const v = this.pluginData('serviceStarted');
			return typeof v === 'string' ? v : null;
		},
		last() {
			return this.pluginData('lastCommands') || [];
		},
		lastChange() {
			const u = this.last[0];
			return u ? (u.hour + ' ' + u.code) : '';
		},
		// Ages in seconds as the Pi publishes them (every 5 s): they do not depend on
		// the browser's clock nor on the precision of numbers in DSF.
		// Plugins with their own backend (e.g. WorkshopRS485): read from their plugin data.
		external() {
			const plugins = this.$store.state.machine.model.plugins;
			const out = [];
			const rs = pluginOf(plugins, 'rs485');
			if (rs && pluginActive(this.$store, 'rs485')) {
				const d = rs.data ? (typeof rs.data.get === 'function' ? rs.data.get('rs485') : rs.data.rs485) : null;
				const running = rs.pid > 0;
				const disps = (d && d.devices) || [];
				const bad = disps.filter(x => x.state === 'alarm' || x.state === 'without_communication').length;
				const fresh = this.rs485Received && (this.nowSvc - this.rs485Received) < 15000;
				let state = { text: i18n.t('plugins.WorkshopService.servicePage.up_to_date'), color: 'success' };
				if (!running) {
					state = { text: i18n.t('plugins.WorkshopService.servicePage.stopped'), color: 'grey' };
				} else if (!fresh) {
					state = { text: i18n.t('plugins.WorkshopService.common.no_data_2'), color: 'warning' };
				} else if (bad) {
					state = { text: i18n.t('plugins.WorkshopService.servicePage.n_with_a_fault', { n: bad }), color: 'error' };
				}
				out.push({
					id: 'WorkshopRS485', title: i18n.t('plugins.WorkshopService.servicePage.rs485_devices'), path: '/Plugins/RS485', icon: 'mdi-serial-port', color: '#00897B',
					description: i18n.t('plugins.WorkshopService.servicePage.servos_and_modbus_devices_over_rs485') + (rs.version ? ' ' + rs.version : '') + ').',
					detail: running ? i18n.t('plugins.WorkshopService.servicePage.n_devices_x', { n: disps.length, x: disps.map(x => x.name + ' ' + (x.state === 'ok' ? 'OK' : x.state.replace('_', ' '))).join(', ') || i18n.t('plugins.WorkshopService.servicePage.none_configured') }) : i18n.t('plugins.WorkshopService.servicePage.the_plugin_process_isn_t_running'),
					buses: running ? ((d && d.buses) || []) : [],
					state: state
				});
			}
			// Vision (WorkshopVision, OpenCV en :8095) -- 2026-10-10: "no veo el servicio de OpenCV"
			const vi = pluginOf(plugins, 'vision');
			if (vi && pluginActive(this.$store, 'vision')) {
				const running = vi.pid > 0;
				const e = this.visionState;
				let state = { text: i18n.t('plugins.WorkshopService.servicePage.up_to_date'), color: 'success' };
				let detail = '';
				if (!running) {
					state = { text: i18n.t('plugins.WorkshopService.servicePage.stopped'), color: 'grey' };
					detail = i18n.t('plugins.WorkshopService.servicePage.the_plugin_process_isn_t_running_2');
				} else if (!e) {
					state = { text: this.visionError ? i18n.t('plugins.WorkshopService.servicePage.not_responding') : i18n.t('plugins.WorkshopService.servicePage.reading'), color: this.visionError ? 'warning' : 'grey' };
					detail = this.visionError ? i18n.t('plugins.WorkshopService.servicePage.vision_not_responding_x', { x: this.visionError }) : '';
				} else {
					const nCal = Object.keys(e.calibs || {}).length;
					detail = 'OpenCV ' + (e.opencv || '?') + ' · ' + i18n.t('plugins.WorkshopService.servicePage.camera_on_the_x', { x: e.camera_en === 'carriage' ? i18n.t('plugins.WorkshopService.servicePage.carriage') : i18n.t('plugins.WorkshopService.servicePage.gantry') }) +
						' · ' + (nCal ? i18n.t('plugins.WorkshopService.servicePage.calibrated_n_resolutions', { n: nCal }) : i18n.t('plugins.WorkshopService.servicePage.not_calibrated_lc'));
					if (!nCal) state = { text: i18n.t('plugins.WorkshopService.servicePage.not_calibrated'), color: 'warning' };
				}
				out.push({
					id: 'WorkshopVision', title: i18n.t('plugins.WorkshopService.servicePage.vision_opencv'), path: '/Plugins/Vision', icon: 'mdi-eye-outline', color: '#1976D2',
					description: i18n.t('plugins.WorkshopService.servicePage.measures_parts_holes_marks', { v: vi.version ? ' ' + vi.version : '' }),
					detail: detail, buses: [], state: state
				});
			}
			const health = this.pluginData('healthPi') || {};
			// Service database (2026-10-10: "add the database service in Pi
			// service"); the detail is in Pi health
			const b = health.base;
			if (b) {
				const rs = b.backup;
				const ok = !b.error && b.check === 'ok' && !(rs && (rs.late || (rs.failures && rs.failures.length)));
				const filas = (b.tables || []).reduce((s, x) => s + (x.rows || 0), 0);
				const last = String(b.modified || '').replace('T', ' ').slice(5, 16);
				out.push({
					id: 'base', title: i18n.t('plugins.WorkshopService.servicePage.database_sqlite'), anchor: 'svc-base', icon: 'mdi-database', color: '#00897B',
					description: i18n.t('plugins.WorkshopService.servicePage.stores_activity_energy_and_received_commands'),
					detail: b.error ? i18n.t('plugins.WorkshopService.servicePage.could_not_read_x', { x: b.error }) : i18n.t('plugins.WorkshopService.servicePage.db_detail', { mb: b.mb, rows: filas, t: last }) + (b.check !== 'ok' ? ' · ' + i18n.t('plugins.WorkshopService.servicePage.check_x', { x: b.check }) : '') +
						(rs ? ' · ' + i18n.t('plugins.WorkshopService.servicePage.backups_x', { x: !rs.active ? i18n.t('plugins.WorkshopService.servicePage.backups_off_lc') : rs.failures && rs.failures.length ? i18n.t('plugins.WorkshopService.servicePage.backups_failing_lc') : rs.late ? i18n.t('plugins.WorkshopService.servicePage.backups_late_lc') : i18n.t('plugins.WorkshopService.servicePage.backups_on_lc') }) + (rs.last ? ' ' + i18n.t('plugins.WorkshopService.servicePage.last_paren_x', { x: String(rs.last.date || '').replace('T', ' ').slice(5, 16) }) : '') : ''),
					buses: [],
					state: b.error ? { text: i18n.t('plugins.WorkshopService.common.no_data_2'), color: 'grey' } : ok ? { text: i18n.t('plugins.WorkshopService.servicePage.up_to_date'), color: 'success' } : { text: i18n.t('plugins.WorkshopService.servicePage.check'), color: 'warning' }
				});
			}
			const svc = (health.services || []).find(x => x.unit === 'workshop-gcode-bridge' || x.unit === 'workshop-bridge');
			if (svc) {
				const clients = health.bridge_clients;
				out.unshift({
					id: 'bridge', title: i18n.t('plugins.WorkshopService.bridgeCard.g_code_bridge_telnet'), anchor: 'svc-bridge',
					icon: 'mdi-lan-connect', color: '#5E35B1',
					description: i18n.t('plugins.WorkshopService.servicePage.lets_programs_send_g_code_to') + svc.unit + ').',
					detail: svc.active ? (clients != null ? i18n.t('plugins.WorkshopService.servicePage.n_programs_connected', { n: clients }) : '') : i18n.t('plugins.WorkshopService.servicePage.the_service_is_not_running') + svc.state + ').',
					buses: [],
					state: svc.active ? { text: i18n.t('plugins.WorkshopService.servicePage.up_to_date'), color: 'success' } : { text: i18n.t('plugins.WorkshopService.servicePage.stopped'), color: 'error' }
				});
			}
			out.forEach(x => { x.level = x.state.color === 'success' ? 0 : (x.state.color === 'error' ? 2 : 1); });
			return out;
		},
		rs485Ts() {
			const plugins = this.$store.state.machine.model.plugins;
			const rs = pluginOf(plugins, 'rs485');
			const d = rs && rs.data ? (typeof rs.data.get === 'function' ? rs.data.get('rs485') : rs.data.rs485) : null;
			return d ? (d.seq != null ? d.seq : d.ts) : null;
		},
		subscription() {
			return (this.pluginData('servicesInternal') || {}).subscription || null;
		},
		ipc() {
			return (this.pluginData('servicesInternal') || {}).ipc || null;
		},
		lightsIpc() {
			return (this.pluginData('servicesInternal') || {}).lights || null;
		},
		// calls to the board by type, most frequent first, with their area, share of the total and what they do
		ipcKinds() {
			const t = (this.ipc && this.ipc.types) || {};
			const total = (this.ipc && this.ipc.per_min) || 0;
			return Object.keys(t).map(id => {
				const nombre = id.split('|')[1] || id;
				const inf = IPC_AREAS[nombre] || IPC_AREAS[id] || { area: 'other' };
				return Object.assign({
					id: id.replace('|', ' · '), name: i18n.t('plugins.WorkshopService.servicePage.ipc_area_' + inf.area), area: inf.area,
					pct: total ? Math.round(100 * t[id].last_min / total) : 0,
					help: i18n.t('plugins.WorkshopService.servicePage.ipc_help', { total: t[id].ms, n: t[id].last_min })
				}, t[id]);
			}).sort((a, b) => b.last_min - a.last_min).slice(0, 14);
		},
		// the same load grouped by area (status lights, motors, power usage...)
		ipcAreas() {
			const t = (this.ipc && this.ipc.types) || {};
			const total = (this.ipc && this.ipc.per_min) || 0;
			const by = {};
			Object.keys(t).forEach(id => {
				const inf = IPC_AREAS[id.split('|')[1] || id] || IPC_AREAS[id] || { area: 'other' };
				by[inf.area] = (by[inf.area] || 0) + t[id].last_min;
			});
			return Object.keys(by).map(a => ({
				id: a, n: by[a], pct: total ? Math.round(100 * by[a] / total) : 0,
				name: i18n.t('plugins.WorkshopService.servicePage.ipc_area_' + a),
				help: i18n.t('plugins.WorkshopService.servicePage.ipc_area_help_' + a)
			})).sort((a, b) => b.n - a.n);
		},
		loadDuet() {
			const s = this.subscription, i = this.ipc;
			if (!s) return { color: 'grey', text: i18n.t('plugins.WorkshopService.common.no_data'), reason: '' };
			if (!s.live) return { color: 'error', text: i18n.t('plugins.WorkshopService.servicePage.subscription_down'), reason: i18n.t('plugins.WorkshopService.servicePage.reason_subscription_down') };
			const n = i ? i.per_min : 0;
			if (n > IPC_LIMIT) {
				const top = this.ipcAreas[0];
				return {
					color: 'warning', text: i18n.t('plugins.WorkshopService.servicePage.n_calls_min', { n }),
					reason: i18n.t('plugins.WorkshopService.servicePage.reason_over_limit', { n, limit: IPC_LIMIT }) +
						(top ? ' ' + i18n.t('plugins.WorkshopService.servicePage.reason_top_area', { area: top.name, pct: top.pct, n: top.n }) : '')
				};
			}
			return { color: 'success', text: 'normal', reason: i18n.t('plugins.WorkshopService.servicePage.reason_normal', { n, limit: IPC_LIMIT }) };
		},
		guardStatus() {
			return this.pluginData('guardStatus') || null;
		},
		processInfo() {
			return (this.pluginData('servicesInternal') || {}).process || null;
		},
		processes() {
			const raw = (this.pluginData('servicesInternal') || {}).processes || {};
			return Object.keys(raw).map(id => {
				const p = Object.assign({ id }, raw[id]);
				p.info = PROC_INFO[id] || PROC_OTHER;
				p.errorRecent = p.age_error_s != null && p.age_error_s < 3600;
				p.module = ((this.pluginData('servicesInternal') || {}).modules || {})[id] || null;
				p.modeError = this.modeError[id] || '';
				p.state = this.stateProcess(p);
				return p;
			});
		},
		procCategories() {
			const by = {};
			this.processes.forEach(p => {
				const c = p.info.cat;
				by[c] = by[c] || { cat: c, color: p.info.color, n: 0 };
				by[c].n++;
			});
			return Object.keys(by).map(k => by[k]);
		},
		procGroups() {
			const by = {};
			this.processesFiltered.forEach(p => {
				const c = p.info.cat;
				by[c] = by[c] || { cat: c, color: p.info.color, items: [], problems: 0 };
				by[c].items.push(p);
				if (p.state.level > 0 || (p.restarts || 0) > 0) by[c].problems++;
			});
			return Object.keys(by).map(k => by[k]);
		},
		processesFiltered() {
			return this.processes.filter(p =>
				(this.procFilter === 'all' || p.state.level > 0 || (p.restarts || 0) > 0) &&
				(!this.procCat || p.info.cat === this.procCat) &&
				matches(this.textSearch(p), this.procSearch));
		},
		// ONE list for every number of the strip, the chips and the header: the internal processes plus the separate services (bridge,
		// database, RS485, Vision), each with its level (0 fine, 1 warning, 2 problem). While the service is not connected the page
		// holds the last data it saw (or nothing): the counts are then null ("not available"), never zeros or old warnings.
		count() {
			if (!this.connected) return null;
			const levels = this.processes.map(p => p.state.level).concat(this.external.map(x => x.level));
			return {
				ok: levels.filter(n => n === 0).length,
				notice: levels.filter(n => n === 1).length,
				bad: levels.filter(n => n === 2).length
			};
		},
		// the chip next to the title: the same counts, worded as the strip words them
		headerChip() {
			const c = this.count;
			if (!this.connected) return { color: 'error', icon: 'mdi-lan-disconnect', text: this.$t('plugins.WorkshopService.servicePage.backend_disconnected') };
			if (c.bad) return { color: 'error', icon: 'mdi-close-circle', text: this.$t('plugins.WorkshopService.servicePage.n_with_problems', { n: c.bad }) };
			if (c.notice) return { color: 'warning', icon: 'mdi-alert', text: this.$t('plugins.WorkshopService.servicePage.n_with_warnings', { n: c.notice }) };
			return { color: 'success', icon: 'mdi-check-circle', text: this.$t('plugins.WorkshopService.servicePage.all_working') };
		},
		// API operations (api.describe): name, description, example of the arguments
		handlers() {
			return (this.apiOps || []).map(o => {
				const ej = {};
				Object.keys(o.args || {}).forEach(k => {
					const a = o.args[k];
					if (!a.required) return;
					ej[k] = a.choices ? a.choices[0] : ({ int: 0, num: 0, bool: true, obj: {}, list: [] })[a.type] !== undefined ? ({ int: 0, num: 0, bool: true, obj: {}, list: [] })[a.type] : '';
				});
				const args = Object.keys(o.args || {}).map(k => k + ': ' + o.args[k].type + (o.args[k].required ? ' *' : '')).join(', ');
				return {
					name: o.op, description: o.desc + (args ? ' (' + args + ')' : ''), usage: JSON.stringify(ej),
					reading: o.kind === 'read' ? 'always' : 'no', reading_actions: null, kind: o.kind, macro: !!o.macro
				};
			});
		},
		categories() {
			return CATS.map(c => Object.assign({}, c, { n: this.handlers.filter(h => this.catOf(h.name).id === c.id).length }))
				.filter(c => c.n > 0);
		},
		catColor() {
			return (CATS.find(c => c.id === this.catFilter) || CATS[0]).color;
		},
		catOps() {
			return this.handlers.filter(h => this.catOf(h.name).id === this.catFilter);
		},
		catCount() {
			return this.catOps.length;
		},
		subCats() {
			const by = {};
			this.catOps.forEach(h => { const k = subOf(h.name); by[k] = (by[k] || 0) + 1; });
			return Object.keys(by).sort().map(k => ({ id: k, n: by[k] }));
		},
		handlersFiltered() {
			const f = (this.filter || '').toLowerCase().trim();
			return this.handlers.filter(x =>
				(this.readFilter === 'all' || (this.readFilter === 'always' ? x.reading === 'always' : x.reading !== 'always')) &&
				(!this.catFilter || this.catOf(x.name).id === this.catFilter) &&
				(!this.subFilter || subOf(x.name) === this.subFilter) &&
				(!f || (x.name + ' ' + x.description).toLowerCase().includes(f)));
		}
	},
	mounted() {
		this._clockSvc = setInterval(() => { this.nowSvc = Date.now(); }, 3000);
		this._sampling = setInterval(() => { sample(this.processes, this.processInfo); }, 5000);
		sample(this.processes, this.processInfo);
		this.readVision();
		// only with the page in view (visible tab and active page: DWC keeps it alive with keep-alive)
		this._clockVision = setInterval(() => { if (!document.hidden && this.$el && this.$el.isConnected !== false) this.readVision(); }, 10000);
		this.readKey();
		this._offIdentity = onIdentity(i => { this.identity = i; });
		this.loadApiOps(0);
		if (this.$route && this.$route.query && this.$route.query.anchor) {
			this.irAcuando(this.$route.query.anchor);
		}
	},
	beforeDestroy() {
		this._apiOpsGone = true;
		clearTimeout(this._apiOpsT);
		clearInterval(this._clockVision);
		clearInterval(this._clockSvc);
		clearInterval(this._sampling);
		clearTimeout(this._closeT);
		if (this._offIdentity) this._offIdentity();
	},
	methods: {
		// api.describe fills the reference and the key permissions: if the service was busy or restarting when the page opened, try again
		// until it answers (an empty list for good left the reference blank)
		loadApiOps(n) {
			api('api.describe', {}, { quiet: true }).then(d => {
				this.apiOps = (d && d.ops) || [];
			}).catch(() => {
				if (!this.apiOps) this.apiOps = [];
				if (this._apiOpsGone || n >= 40) return;
				this._apiOpsT = setTimeout(() => this.loadApiOps(n + 1), Math.min(30000, 3000 * (n + 1)));
			});
		},
		pickCat(id) {
			this.catFilter = this.catFilter === id ? null : id;
			this.subFilter = null;
		},
		hasPath(path) {
			return pathExists(this.$router, path);
		},
		// help text that names the jog: its variant without the jog when that plugin is not there
		jogVariant(key) {
			return this.$t(this.hasJog ? key : key + '_no_jog');
		},
		readVision() {
			const vi = pluginOf(this.$store.state.machine.model.plugins, 'vision');
			if (!vi || !(vi.pid > 0)) {
				this.visionState = null;
				return;
			}
			// through the service API (vision.get), not the port from the browser: with users on, Vision refuses a call without a session
			api('vision.get', { path: '/state' }, { noLogin: true, quiet: true })
				.then(d => (d && d.ok === false ? Promise.reject(new Error(d.error && d.error.message ? d.error.message : String(d.error || 'Vision')) ) : d))
				.then(d => { this.visionState = d; this.visionError = null; })
				.catch(e => { this.visionState = null; this.visionError = e.message || String(e); });
		},
		...mapActions('machine', ['sendCode']),
		pluginData(key) {
			if (!this.pluginModel || !this.pluginModel.data) {
				return null;
			}
			const data = this.pluginModel.data;
			// The declared type is Map<string, any> but at runtime it arrives as a
			// plain object -- support both forms in case it changes in the future.
			// The texts come as {key, params}: they are shown in the language of this DWC.
			return serviceTexts((typeof data.get === 'function') ? data.get(key) : data[key]);
		},
		// API of the service: the text the old commands answered (JSON text, message or "Error: ...")
		send(op, args, opts) {
			return apiText(op, args || {}, opts || {});
		},
		setAirAuto(v) {
			return this.send('air.auto', { on: !!v });
		},
		setDelay(v) {
			if (typeof v !== 'number') return;
			return this.send('air.delay', { seconds: v });
		},
		hourShort(iso) {
			const m = /T(\d\d:\d\d)/.exec(String(iso || ''));
			return m ? m[1] : String(iso || '');
		},
		optionsSeconds(base, current) {
			const v = base.includes(current) ? base : base.concat(current).sort((a, b) => (a || 1e9) - (b || 1e9));
			return v.map(x => ({ value: x, text: x === 0 ? i18n.t('plugins.WorkshopService.servicePage.never') : (x >= 60 ? (x / 60) + ' min' : x + ' s') }));
		},
		setMovMode(v) {
			return this.send('movement.lock', { mode: v === 'duet' ? 'duet' : 'protected' });
		},
		setMovRelease(v) {
			if (typeof v !== 'number') return;
			return this.send('movement.lock', { release_s: v });
		},
		setMovIdle(v) {
			if (typeof v !== 'number') return;
			return this.send('movement.lock', { idle_s: v });
		},
		// double tap (DISENO.md): the first arms, the second closes; 4 s to confirm
		async closeJob() {
			if (!this.close.armed) {
				this.close.armed = true;
				this.close.msg = '';
				clearTimeout(this._closeT);
				this._closeT = setTimeout(() => { this.close.armed = false; }, 4000);
				return;
			}
			clearTimeout(this._closeT);
			this.close.armed = false;
			this.close.sending = true;
			try {
				this.close.msg = String(await this.send('job.close') || '').trim();
			} catch (e) {
				this.close.msg = String((e && e.message) || e);
			} finally {
				this.close.sending = false;
			}
		},
		// full report from the SD (0:/sys/workshop/data/blackbox/unclean-report.txt);
		// if it cannot be read, the lines the page already has
		async downloadBox() {
			const r = this.boxReport || this.lastDrop;
			if (!r) return;
			this.box.lowering = true;
			this.box.msg = '';
			let texto = null;
			try {
				const h = {};
				if (window.__workshopSession) h['X-Session-Key'] = window.__workshopSession;
				const resp = await fetch('/machine/file/' + encodeURIComponent(r.file || '0:/sys/workshop/data/blackbox/unclean-report.txt'), { headers: h, cache: 'no-store' });
				if (resp.ok) texto = await resp.text();
			} catch (e) {
				texto = null;
			}
			if (texto === null) {
				texto = (r.lines || []).join('\n') + '\n';
				this.box.msg = i18n.t('plugins.WorkshopService.servicePage.could_not_read_the_full_report');
			}
			const a = document.createElement('a');
			a.href = URL.createObjectURL(new Blob([texto], { type: 'text/plain' }));
			a.download = 'apagado-no-limpio-' + String(r.last_datum || r.detected || '').replace(/[^0-9]/g, '').slice(0, 12) + '.txt';
			document.body.appendChild(a);
			a.click();
			setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
			this.box.lowering = false;
		},
		async showBox() {
			this.box.sending = true;
			try {
				this.box.msg = String(await this.send('blackbox.show') || '').trim();
			} catch (e) {
				this.box.msg = String((e && e.message) || e);
			} finally {
				this.box.sending = false;
			}
		},
		async hideBox() {
			this.box.sending = true;
			try {
				this.box.msg = String(await this.send('blackbox.hide') || '').trim();
			} catch (e) {
				this.box.msg = String((e && e.message) || e);
			} finally {
				this.box.sending = false;
			}
		},
		setShutdown(v) {
			return this.send('power.after_job', { armed: !!v });
		},
		optionsOf(list) {
			// the eligible ones first; the others are seen but cannot be chosen
			const op = c => ({ v: c.id, t: c.id + ' · ' + this.stateChannel(c).t, disabled: !c.eligible });
			return list.filter(c => c.eligible).map(op).concat(list.filter(c => !c.eligible).map(op));
		},
		stateChannel(c) {
			if (!c.exists) return { t: i18n.t('plugins.WorkshopService.servicePage.not_present'), color: 'grey' };
			if (c.state === 'reserved') return { t: i18n.t('plugins.WorkshopService.servicePage.cannot_be_chosen'), color: 'grey darken-1' };
			if (c.state === 'busy') return { t: i18n.t('plugins.WorkshopService.servicePage.busy'), color: 'warning' };
			if (c.state === 'shared') return { t: i18n.t('plugins.WorkshopService.servicePage.shared'), color: 'info' };
			return { t: i18n.t('plugins.WorkshopService.servicePage.free'), color: 'success' };
		},
		async readKey() {
			try {
				const r = String(await this.send('password.status') || '');
				this.key.has = /puesta/i.test(r) ? true : (/sin contrasena/i.test(r) ? false : null);
			} catch (e) {
				this.key.has = null;
			}
		},
		// double tap (DISENO.md): the first arms, the second sends; 4 s to confirm
		armKey(that) {
			if (this.key.armed === that) {
				clearTimeout(this._keyT);
				this.key.armed = null;
				return true;
			}
			this.key.armed = that;
			clearTimeout(this._keyT);
			this._keyT = setTimeout(() => { this.key.armed = null; }, 4000);
			return false;
		},
		async putKey() {
			if (!this.keyValid || !this.armKey('set')) return;
			this.key.sending = true;
			try {
				this.key.msg = String(await this.send('password.set', { password: this.key.newEntry }) || '').trim();
				this.key.newEntry = '';
				this.key.repeat = '';
			} catch (e) {
				this.key.msg = String((e && e.message) || e);
			} finally {
				this.key.sending = false;
				this.readKey();
			}
		},
		async removeKey() {
			if (!this.armKey('clear')) return;
			this.key.sending = true;
			try {
				this.key.msg = String(await this.send('password.clear') || '').trim();
			} catch (e) {
				this.key.msg = String((e && e.message) || e);
			} finally {
				this.key.sending = false;
				this.readKey();
			}
		},
		// Opens or closes the Advanced section; closing it blocks the channels again.
		toggleAdvanced() {
			this.advancedOpen = !this.advancedOpen;
			if (!this.advancedOpen) this.blockAdvanced();
		},
		blockAdvanced() {
			this.advanced = false;
			this.armedAdv = false;
			clearTimeout(this._advT);
		},
		// Double confirmation: level 4 notice of the workshop pages (mandatory
		// checkbox) or, without it, two taps in a row.
		async unlockAdvanced() {
			const t = window.__workshop && window.__workshop.confirmLevel4;
			if (t) {
				const ok = await t({
					title: i18n.t('plugins.WorkshopService.servicePage.change_the_duet_channels_by_hand'),
					notices: [
						...(this.hasJog ? [i18n.t('plugins.WorkshopService.servicePage.it_can_leave_the_jog_s')] : []),
						i18n.t('plugins.WorkshopService.servicePage.it_can_mix_the_service_s'),
						i18n.t('plugins.WorkshopService.servicePage.it_can_lose_the_g90_that'),
						i18n.t('plugins.WorkshopService.servicePage.the_automatic_channel_aux2_if_free')
					],
					understood: i18n.t('plugins.WorkshopService.servicePage.understood_i_know_what_i_am'),
					button: i18n.t('plugins.WorkshopService.servicePage.unlock')
				});
				if (ok) this.advanced = true;
				return;
			}
			if (!this.armedAdv) {
				this.armedAdv = true;
				clearTimeout(this._advT);
				this._advT = setTimeout(() => { this.armedAdv = false; }, 4000);
				return;
			}
			this.blockAdvanced();
			this.advanced = true;
		},
		async setChannel(letter, v) {
			if (!this.advanced) return; // without unlock nothing is sent (the service rejects it too)
			this.savingChannel = true;
			try {
				// the level 4 unlock of this page is the confirmation the service asks for
				await this.send('comms.set', { [letter === 'J' ? 'jog_channel' : 'plugin_channel']: v }, { confirm: true });
			} finally {
				this.savingChannel = false;
				this.blockAdvanced();
				this.advancedOpen = false;
			}
		},
		dangerous(nombre) {
			const o = (this.apiOps || []).find(x => x.op === nombre);
			return !!o && PELIGROSOS_KIND.includes(o.kind);
		},
		test(h) {
			return this.tests[h.name] || { code: h.usage || '{}', sending: false, armed: false, result: null };
		},
		setTest(h, patch) {
			this.$set(this.tests, h.name, Object.assign({}, this.test(h), patch));
		},
		// the example arguments of the operation go to the test field
		useExample(h) {
			this.setTest(h, { code: h.usage || '{}', armed: false });
		},
		async sendTest(h) {
			const p = this.test(h);
			const code = (p.code || '').trim();
			if (!code || p.sending) return;
			if (this.dangerous(h.name) && !p.armed) {
				this.setTest(h, { armed: true });
				clearTimeout(this._armT);
				this._armT = setTimeout(() => this.setTest(h, { armed: false }), 3000);
				return;
			}
			clearTimeout(this._armT);
			this.setTest(h, { sending: true, armed: false });
			const t0 = performance.now();
			let ok = true, text = '';
			try {
				const args = code ? JSON.parse(code) : {};
				const r = await api(h.name, args);
				text = typeof r === 'string' ? r : JSON.stringify(r, null, 1);
			} catch (e) {
				ok = false;
				text = String((e && e.message) || e);
			}
			this.setTest(h, {
				sending: false,
				result: { ok, text: text, ms: Math.round(performance.now() - t0), hour: new Date().toTimeString().slice(0, 8) }
			});
		},
		catOf(nombre) {
			return CATS.find(c => c.re.test(nombre || '')) || CATS[CATS.length - 1];
		},
		// history rows: "op {args}"
		cmdName(c) {
			return String(c.code || '').split(' ')[0];
		},
		rowCat(f) {
			return this.cmdCat({ code: f.code });
		},
		cmdCat(c) {
			return this.catOf(this.cmdName(c));
		},
		async copy(text, key) {
			const ok = await copyText(text || '');
			this.copied = ok ? key : null;
			if (ok) {
				setTimeout(() => { if (this.copied === key) { this.copied = null; } }, 1500);
			}
		},
		// Scroll to an anchor once the page has rendered it (cards load after the first paint). The cards live in
		// sections of the side bar and only exist while their section is shown: the section is chosen first.
		irAcuando(id) {
			const sec = ANCHOR_SECTION[id];
			if (sec && this.section !== sec) {
				this.section = sec;
			}
			let n = 0;
			const t = setInterval(() => {
				const el = document.getElementById(id);
				if (el || ++n > 20) {
					clearInterval(t);
					if (el) {
						el.scrollIntoView({ behavior: 'smooth', block: 'start' });
					}
				}
			}, 250);
		},
		goA(id) {
			this.irAcuando(id);
		},
		// the user's choice of when a process runs (config "modulos" of the service)
		// everything a person may type to find a process: its name, what it does, its category and the explanations of its detail
		textSearch(p) {
			const D = 'plugins.WorkshopService.procDocs.'
			const docs = ['what', 'why', 'fails', 'uses', 'where'].map(k => (this.$te(D + p.id + '_' + k) ? this.$t(D + p.id + '_' + k) : '')).join(' ')
			return [p.title, p.description, p.id, p.info.cat, docs].join(' ')
		},
		groupOpen(g) {
			if (this.procOpen[g.cat] !== undefined) return this.procOpen[g.cat];
			// by itself: open with a problem, or while looking for something
			return g.problems > 0 || !!this.procSearch || !!this.procCat || this.procFilter === 'problems';
		},
		async changeMode(id, modo) {
			this.$set(this.modeError, id, '');
			try {
				await api('modules.set', { process: id, mode: modo });
			} catch (e) {
				this.$set(this.modeError, id, i18n.t('plugins.WorkshopService.servicePage.mode_failed', { msg: String((e && e.message) || e) }));
			}
		},
		stateProcess(p) {
			if (p.idle) {
				return { level: 0, color: 'grey', icon: 'mdi-sleep', text: i18n.t('plugins.WorkshopService.servicePage.resting'), detail: i18n.t('plugins.WorkshopService.servicePage.resting_detail') };
			}
			if (!p.live) {
				return { level: 2, color: 'error', icon: 'mdi-close-circle', text: i18n.t('plugins.WorkshopService.servicePage.stopped'), detail: i18n.t('plugins.WorkshopService.servicePage.crashed_and_is_restarting') };
			}
			if (p.age_ok_s == null) {
				return { level: 1, color: 'warning', icon: 'mdi-timer-sand', text: i18n.t('plugins.WorkshopService.common.no_data_2'), detail: i18n.t('plugins.WorkshopService.servicePage.hasn_t_completed_a_loop_yet') };
			}
			if (p.age_ok_s > p.expected_s * 3) {
				return { level: 1, color: 'warning', icon: 'mdi-clock-alert', text: i18n.t('plugins.WorkshopService.servicePage.late'), detail: i18n.t('plugins.WorkshopService.servicePage.last_heartbeat_t', { t: this.age(p.age_ok_s) }) };
			}
			if (p.errorRecent && p.age_error_s < p.age_ok_s + 5) {
				return { level: 1, color: 'warning', icon: 'mdi-alert', text: i18n.t('plugins.WorkshopService.servicePage.with_errors'), detail: p.error };
			}
			return { level: 0, color: 'success', icon: 'mdi-check-circle', text: i18n.t('plugins.WorkshopService.servicePage.up_to_date'), detail: i18n.t('plugins.WorkshopService.servicePage.last_heartbeat_t', { t: this.age(p.age_ok_s) }) };
		},
		sec(v) {
			return v < 1 ? Math.round(v * 1000) + ' ms' : (v < 60 ? v.toFixed(1) + ' s' : Math.round(v / 60) + ' min');
		},
		duration(s) {
			if (s == null) {
				return '';
			}
			if (s < 60) {
				return s + ' s';
			}
			if (s < 3600) {
				return Math.round(s / 60) + ' min';
			}
			if (s < 86400) {
				return Math.floor(s / 3600) + ' h ' + Math.round((s % 3600) / 60) + ' min';
			}
			return Math.floor(s / 86400) + ' d ' + Math.round((s % 86400) / 3600) + ' h';
		},
		age(s) {
			s = Math.max(0, Math.round(s));
			if (s < 3) return i18n.t('plugins.WorkshopService.servicePage.now');
			if (s < 60) return i18n.t('plugins.WorkshopService.servicePage.ago_t', { t: s + ' s' });
			if (s < 3600) return i18n.t('plugins.WorkshopService.servicePage.ago_t', { t: Math.round(s / 60) + ' min' });
			if (s < 86400) return i18n.t('plugins.WorkshopService.servicePage.ago_t', { t: Math.floor(s / 3600) + ' h ' + Math.round((s % 3600) / 60) + ' min' });
			return i18n.t('plugins.WorkshopService.servicePage.ago_n_days', { n: Math.round(s / 86400) });
		},
		// Read-only (2026-10-10, "an elegant way to see that it is read-only")
		read(h) {
			if (h.reading === 'always') {
				return { text: i18n.t('plugins.WorkshopService.common.read_only'), icon: 'mdi-eye-outline', color: 'teal', hex: '#26A69A', title: i18n.t('plugins.WorkshopService.servicePage.only_reads_changes_nothing_on_the') };
			}
			if (h.reading === 'according') {
				const a = h.reading_actions || {};
				const acc = (a.actions || []).map(v => a.letter + '"' + v + '"').join(', ');
				return { text: i18n.t('plugins.WorkshopService.servicePage.reads_or_changes'), icon: 'mdi-eye-settings-outline', color: 'blue', hex: '#42A5F5', title: i18n.t('plugins.WorkshopService.servicePage.reads_only_x_else_changes', { x: acc ? i18n.t('plugins.WorkshopService.servicePage.with_x', { x: acc }) + (a.actions.length ? i18n.t('plugins.WorkshopService.servicePage.or_without_x', { x: a.letter }) : '') : i18n.t('plugins.WorkshopService.servicePage.without_x', { x: a.letter }) }) };
			}
			return { text: i18n.t('plugins.WorkshopService.common.changes_something'), icon: 'mdi-pencil-outline', color: 'orange darken-2', hex: '#F57C00', title: i18n.t('plugins.WorkshopService.servicePage.changes_something_settings_sd_files_the') };
		},
		summary(d) {
			d = d || '';
			return d.length > 90 ? d.slice(0, 90) + '...' : d;
		}
	}
};
</script>

<style>
/* Everything that is the look of the page (bar, menu, cards, buttons, chips, notes) is the design family (family.css, imported by theme.css).
   Here only what is the CONTENT of this page. */
.svx-page .svx-ico { color: var(--wf-icon); }
</style>

<style scoped>
.svc-mov-opts { display: flex; flex-wrap: wrap; gap: 8px; }
.svc-mov-opt { flex: 1 1 260px; cursor: pointer; }
.svc-mov-sel { border-color: var(--v-primary-base) !important; }
.svc-detail { margin-top: 2px; opacity: 0.8; }
.svc-metricas span { margin-left: 10px; white-space: nowrap; }
/* phone: the long lines wrap instead of pushing the page sideways (Processes: the readings per minute; API: the header of each operation and its example) */
@media (max-width: 599px) {
	.svc-metricas span { white-space: normal; overflow-wrap: anywhere; display: inline-block; margin-left: 0; margin-right: 10px; }
	.svc-metricas { margin-left: 0 !important; }
	.svx-panels .v-expansion-panel-header > .d-flex { flex-wrap: wrap; min-width: 0; max-width: 100%; }
	.svx-panels .v-expansion-panel-header code { overflow-wrap: anywhere; }
	.svx-panels .v-expansion-panel-header .text-caption { flex: 1 1 100%; margin-left: 0 !important; overflow-wrap: anywhere; }
	.svx-panels .svc-use, .svx-panels .svc-test-field { min-width: 0; overflow-wrap: anywhere; }
}
.svc-height { flex: 1 1 auto; }
.svc-col { display: flex; flex-direction: column; }
.svc-group { margin-bottom: 4px; }
.svc-group-cab { display: flex; align-items: center; gap: 6px; padding: 6px 4px; font-size: 13px; text-decoration: none; color: inherit; border-bottom: 1px solid var(--wf-line); }
.svc-group-name { font-weight: 600; }
/* a row of the lists (process, automation): a divider, no side bar, no tint */
.svc-proc, .svc-auto { padding: 10px 0; border-top: 1px solid var(--wf-line); }
.svc-proc-txt { min-width: 0; flex: 1 1 200px; }
/* the title row wraps instead of pushing its chip out of the card in a narrow column or a long translation */
.svc-auto > .d-flex.align-center { flex-wrap: wrap; gap: 2px 8px; }
.svc-auto > .d-flex.align-center > .v-chip, .svc-auto > .d-flex.align-center > .v-icon { flex: none; }
.svc-sub { margin-left: 36px; }
.svc-doc-auto { border-top: 1px solid var(--wf-line); padding-top: 6px; font-size: 12px; line-height: 1.45; }
.svc-doc-auto b { display: block; font-weight: 600; opacity: 0.75; margin-top: 4px; }
.svc-channel { padding: 4px 0; }
.svc-channel-id { min-width: 76px; }
.svc-channel-off { opacity: 0.6; }
.svc-explains p { margin-bottom: 8px; font-size: 13px; line-height: 1.45; }
.svc-use { white-space: pre-wrap; font-size: 12px; }
.svc-use-click { cursor: pointer; }
.svc-use-click:hover { outline: 1px dashed var(--wf-line-strong); }
.svc-test-field { font-family: var(--tp-font-mono, monospace); font-size: 13px; }
.svc-result { padding: 8px 10px; border: 1px solid var(--wf-line); border-radius: 8px; }
.svc-res-txt { margin: 0; white-space: pre-wrap; word-break: break-word; font-size: 12px; max-height: 260px; overflow: auto; }
.svc-read { min-width: 0; }
.svc-read-det { padding: 4px 0; font-size: 12px; opacity: 0.85; }
.svc-load-row { display: flex; align-items: center; gap: 8px; min-height: 20px; }
.svc-load-name { flex: 0 1 240px; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.svc-load-bar { flex: 1 1 80px; min-width: 40px; }
.svc-load-num { flex: none; min-width: 84px; text-align: right; white-space: nowrap; }
.svc-load-reason { line-height: 1.4; }
.svc-load-warning { color: var(--wf-warn); }
.svc-load-error { color: var(--wf-err); }
/* API: the category filters are the family pills (.wf-cat); the sub-group filter below them stays as it was */
.svx-cats { display: flex; flex-wrap: wrap; gap: 8px; margin: 8px 0 12px; }
.svx-cats .wf-cat { min-height: 32px; padding: 2px 12px; }
.svx-count { font-size: 12px; font-weight: 400; opacity: 0.8; }
.svx-cat-tag { cursor: default; font-size: 11px; padding: 0 8px; }
.svx-subs { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin: -4px 0 12px; }
.svx-sub { display: inline-flex; align-items: center; gap: 6px; min-height: 28px; padding: 2px 10px; border: 1px solid var(--wf-line-strong); border-radius: 999px; background: transparent; color: inherit; font: inherit; font-size: 12px; cursor: pointer; }
.svx-sub:hover { background: color-mix(in srgb, var(--wf-cat) 14%, transparent); border-color: var(--wf-cat); }
.svx-sub.on { background: var(--wf-cat); border-color: var(--wf-cat); color: #fff; font-weight: 600; }
.svx-sub.on small { opacity: 0.9; }
.svx-sub code, .svx-cats code, .svx-tools code, .svx-panels .v-expansion-panel-title code { background: transparent; box-shadow: none; padding: 0; color: inherit; font-size: inherit; }
.svx-sub small { font-size: 12px; opacity: 0.75; }
.svx-tools { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.svx-label { font-size: 13px; opacity: 0.8; }
.svx-hint { margin-top: 12px; padding: 14px; border-radius: 8px; border: 1px dashed var(--wf-line-strong); text-align: center; font-size: 14px; opacity: 0.8; }
</style>
