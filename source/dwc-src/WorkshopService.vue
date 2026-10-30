<template>
	<v-container ref="root" fluid class="pa-0 workshop-theme svx-page" :style="{ '--wf-badge': badge }">
		<!-- backend stopped (2026-10-10, test "what if a plugin is
		     missing"): DSF keeps the data published the last time, so
		     without this notice the page looked up to date with the service stopped -->
		<v-alert v-if="!runs" variant="outlined" type="warning" density="compact" icon="mdi-lan-disconnect" class="mb-3 notice-stopped">
			<div class="font-weight-medium">{{ $t('plugins.WorkshopService.servicePage.the_system_service_is_stopped') }}</div>
			<div class="text-body-medium mt-1">{{ $t('plugins.WorkshopService.servicePage.what_you_see_below_is_old', { list: withoutServiceList }) }}</div>
		</v-alert>
		<!-- The ONE bar of the page (design family): badge, name, one line, and the state with the count of processes -->
		<page-header icon="mdi-flash" :title="$t('plugins.WorkshopService.page.system_service')" :lead="$t('plugins.WorkshopService.page.service_lead')" loading>
			<v-chip size="small" variant="outlined" :color="headerChip.color">
				<v-icon start size="x-small">{{ headerChip.icon }}</v-icon>
				{{ headerChip.text }}
			</v-chip>
		</page-header>

		<!-- No user created yet: everybody with access to DWC is an administrator (F1-A, identity by PIN) -->
		<v-alert v-if="identity && identity.compat" density="compact" variant="outlined" type="warning" class="mb-3">
			<template v-if="identity.users_disabled">
				{{ $t('plugins.WorkshopService.users.disabled_notice') }}
				<v-btn size="small" variant="outlined" color="warning" class="ml-2" @click="section = 'users'">{{ $t('plugins.WorkshopService.users.switch_on') }}</v-btn>
			</template>
			<template v-else>
				{{ $t('plugins.WorkshopService.users.no_users_notice') }}
				<v-btn size="small" variant="outlined" color="warning" class="ml-2" @click="section = 'users'">{{ $t('plugins.WorkshopService.users.create_first') }}</v-btn>
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
						<v-chip v-if="!count" size="small" variant="outlined" color="grey" class="mr-2 mb-1">
							<v-icon start size="small">mdi-help-circle-outline</v-icon>{{ $t('plugins.WorkshopService.procDocs.ui_summary_unavailable') }}
						</v-chip>
						<template v-else>
							<v-chip size="small" variant="outlined" color="success" class="mr-2 mb-1">
								<v-icon start size="small">mdi-check-circle</v-icon>{{ $t('plugins.WorkshopService.servicePage.n_up_to_date', { n: count.ok }) }}
							</v-chip>
							<v-chip v-if="count.notice" size="small" variant="outlined" color="warning" class="mr-2 mb-1">
								<v-icon start size="small">mdi-alert</v-icon>{{ $t('plugins.WorkshopService.servicePage.n_with_warnings', { n: count.notice }) }}
							</v-chip>
							<v-chip v-if="count.bad" size="small" variant="outlined" color="error" class="mr-2 mb-1">
								<v-icon start size="small">mdi-close-circle</v-icon>{{ $t('plugins.WorkshopService.servicePage.n_stopped', { n: count.bad }) }}
							</v-chip>
						</template>
						<span v-if="serviceStarted" class="text-body-small text-medium-emphasis mb-1">{{ $t('plugins.WorkshopService.servicePage.backend_started_on', { d: serviceStarted }) }}</span>
					</div>
					<div class="text-body-small text-medium-emphasis mt-1">
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
		<v-sheet v-if="!boxReport && lastDrop" border rounded class="d-flex align-center flex-wrap px-3 py-1 mb-3 svc-ultima-caida">
			<v-icon size="small" color="grey" class="mr-2">mdi-file-alert-outline</v-icon>
			<span class="text-body-medium flex-grow-1">{{ $t('plugins.WorkshopService.servicePage.last_fall') }}: <b>{{ lastDrop.last_datum || '?' }}</b></span>
			<v-btn size="small" variant="text" color="primary" :disabled="box.sending" @click="showBox">{{ $t('plugins.WorkshopService.servicePage.view_report') }}</v-btn>
			<v-btn size="small" variant="text" color="primary" :loading="box.lowering" @click="downloadBox">
				<v-icon size="small" start>mdi-download</v-icon>{{ $t('plugins.WorkshopService.common.download') }}
			</v-btn>
		</v-sheet>

		<!-- Communication with the Duet (2026-10-10): through where the Pi sends its G-code.
		     It goes first, right below the header (request: "that should go at the very
		     beginning of Pi service"): without a channel nothing else works. It lists the 14
		     RRF channels; only the safe ones can be chosen (dsf/comunicacion.py). -->
		<v-card class="mb-3">
			<v-card-title>
				<v-icon size="small" class="mr-2 svx-ico">mdi-swap-horizontal</v-icon>{{ $t('plugins.WorkshopService.servicePage.communication_with_the_duet') }}
			</v-card-title>
			<v-card-text>
				<details class="wf-more svc-explains mb-3">
					<summary>{{ $t('plugins.WorkshopService.servicePage.how_it_works') }}</summary>
						<p>{{ $t('plugins.WorkshopService.servicePage.sends_its_g_code_via_dsf') }}</p>
						<p>{{ jogVariant('plugins.WorkshopService.servicePage.inside_the_duet_each_source_of') }}</p>
						<p>{{ $t('plugins.WorkshopService.servicePage.only_the_safe_channels_can_be') }}</p>
						<p class="mb-0">{{ $t('plugins.WorkshopService.servicePage.why_aux2_with_everything_on_sbc') }}</p>
					</details>
				<div v-if="!communication" class="text-warning text-body-medium">
					<span v-if="!connected">{{ $t('plugins.WorkshopService.servicePage.the_system_service_is_not_responding') }}</span>
					<span v-else>{{ $t('plugins.WorkshopService.servicePage.waiting_for_data_from_the_service') }}</span>
				</div>
				<template v-else>
					<v-row density="compact">
						<v-col cols="12" sm="6">
							<v-select
								:model-value="communication.channel_cfg" :items="optionsChannel" item-title="t" item-value="v" :item-props="channelItemProps"
								:label="$t('plugins.WorkshopService.servicePage.service_codes_lights_readings_macros')" density="compact" variant="outlined" hide-details
								prepend-inner-icon="mdi-lock-outline" :disabled="savingChannel || !advanced" @update:model-value="v => setChannel('C', v)"
							/>
							<div class="text-body-small mt-1">
								<span class="text-medium-emphasis">{{ $t('plugins.WorkshopService.servicePage.in_use') }}</span> <b>{{ communication.channel }}</b>
								<span v-if="communication.channel_cfg === 'auto'" class="text-medium-emphasis"> ({{ $t('plugins.WorkshopService.servicePage.automatic_x', { x: perThatService }) }})</span>
							</div>
						</v-col>
						<v-col v-if="hasJog" cols="12" sm="6">
							<v-select
								:model-value="communication.channel_jog_cfg" :items="optionsJog" item-title="t" item-value="v" :item-props="channelItemProps"
								:label="$t('plugins.WorkshopService.servicePage.jog_moves')" density="compact" variant="outlined" hide-details
								prepend-inner-icon="mdi-lock-outline" :disabled="savingChannel || !advanced" @update:model-value="v => setChannel('J', v)"
							/>
							<div class="text-body-small mt-1">
								<span class="text-medium-emphasis">{{ $t('plugins.WorkshopService.servicePage.in_use') }}</span> <b>{{ communication.channel_jog }}</b>
								<span v-if="communication.channel_jog_cfg === 'auto'" class="text-medium-emphasis"> ({{ $t('plugins.WorkshopService.servicePage.automatic_x', { x: perThatJog }) }})</span>
							</div>
						</v-col>
					</v-row>
					<div class="mt-2">
						<v-btn size="small" variant="text" color="warning" @click="toggleAdvanced">
							<v-icon size="small" start>{{ advancedOpen ? 'mdi-chevron-up' : 'mdi-chevron-down' }}</v-icon>{{ $t('plugins.WorkshopService.servicePage.advanced') }}
						</v-btn>
					</div>
					<ExpandTransition>
						<div v-show="advancedOpen" class="mt-1">
							<v-alert density="compact" variant="outlined" type="warning" class="text-body-small mb-2">
								{{ communication.warning || jogVariant('plugins.WorkshopService.servicePage.changing_the_channel_by_hand_can') }}
							</v-alert>
							<div class="svc-explains text-body-small mb-2">
								<p class="mb-1"><b>{{ $t('plugins.WorkshopService.servicePage.what_exactly_this_option_does') }}</b> {{ $t('plugins.WorkshopService.servicePage.each_channel_is_a_g_code') }}</p>
								<p class="mb-1"><b>{{ $t('plugins.WorkshopService.servicePage.service_codes') }}</b> {{ $t('plugins.WorkshopService.servicePage.are_the_lights_the_driver_readings') }} <template v-if="hasJog"><b>{{ $t('plugins.WorkshopService.servicePage.jog') }}</b> {{ $t('plugins.WorkshopService.servicePage.are_the_g1_moves_of_the') }}</template></p>
								<p class="mb-1"><b>{{ $t('plugins.WorkshopService.servicePage.automatic') }}</b> {{ jogVariant('plugins.WorkshopService.servicePage.recommended_uses_aux2_if_it_is') }}</p>
								<p class="mb-1"><b>{{ $t('plugins.WorkshopService.servicePage.aux2_aux') }}</b>{{ $t('plugins.WorkshopService.servicePage.the_serial_port_s_own_queue') }}</p>
								<p class="mb-0"><b>{{ $t('plugins.WorkshopService.servicePage.sbc') }}</b>{{ jogVariant('plugins.WorkshopService.servicePage.the_common_queue_of_the_system') }}</p>
							</div>
							<v-btn v-if="!advanced" size="small" variant="outlined" color="error" @click="unlockAdvanced">
								<v-icon size="small" start>mdi-lock-open-alert</v-icon>{{ armedAdv ? $t('plugins.WorkshopService.servicePage.tap_again_to_unlock') : $t('plugins.WorkshopService.servicePage.unlock_channel_changes') }}
							</v-btn>
							<span v-else class="text-body-small text-error">{{ $t('plugins.WorkshopService.servicePage.unlocked_pick_the_channel_it_locks') }}</span>
						</div>
					</ExpandTransition>
					<div v-for="(a, i) in communication.notices" :key="i" class="text-body-small text-warning mt-2">
						<v-icon size="x-small" color="warning" class="mr-1">mdi-alert</v-icon>{{ a }}
					</div>
					<div class="text-body-small text-medium-emphasis mt-3 mb-1">{{ $t('plugins.WorkshopService.servicePage.all_the_duet_channels') }}</div>
					<div v-for="c in channelsList" :key="c.id" class="svc-channel d-flex align-center flex-wrap" :class="{ 'svc-channel-off': !c.eligible }">
						<code class="mr-3 svc-channel-id">{{ c.id }}</code>
						<v-chip size="x-small" label variant="flat" class="mr-2" :color="stateChannel(c).color">{{ stateChannel(c).t }}</v-chip>
						<v-chip v-if="c.id === communication.channel" size="x-small" label variant="outlined" color="primary" class="mr-1">{{ $t('plugins.WorkshopService.servicePage.service') }}</v-chip>
						<v-chip v-if="hasJog && c.id === communication.channel_jog" size="x-small" label variant="outlined" color="primary" class="mr-1">{{ $t('plugins.WorkshopService.servicePage.jog') }}</v-chip>
						<span class="text-body-small">{{ c.usage }}</span>
						<span v-if="c.reason" class="text-body-small text-medium-emphasis ml-2">{{ c.reason }}</span>
					</div>
				</template>
			</v-card-text>
		</v-card>

		</div>
		<div v-show="section === 'processes'">
		<v-row density="compact">
			<!-- Procesos internos -->
			<v-col cols="12" md="7" class="svc-col">
				<v-card class="mb-3 svc-height">
					<v-card-title>
						<v-icon size="small" class="mr-2 svx-ico">mdi-cogs</v-icon>{{ $t('plugins.WorkshopService.servicePage.internal_processes') }}
					</v-card-title>
					<v-card-text>
						<!-- the service itself: first row, with its state (2026-10-10) -->
						<div class="svc-proc svc-own">
							<div class="d-flex align-center flex-wrap">
								<v-icon class="mr-3 svx-ico">mdi-server</v-icon>
								<div class="svc-proc-txt">
									<div class="font-weight-medium">
										{{ $t('plugins.WorkshopService.page.system_service') }}
										<v-chip size="x-small" label variant="outlined" color="primary" class="ml-1">WorkshopService {{ pluginModel && pluginModel.version }}</v-chip>
									</div>
									<div class="text-body-small text-medium-emphasis">{{ $t('plugins.WorkshopService.page.interceptorDesc') }}</div>
								</div>
								<v-spacer />
								<v-chip size="small" label variant="flat" :color="serviceOwn.color" :title="serviceOwn.detail">
									<v-icon start size="x-small">{{ serviceOwn.icon }}</v-icon>{{ serviceOwn.text }}
								</v-chip>
							</div>
							<div v-if="processInfo" class="text-body-small ml-10 mt-1 svc-metricas text-medium-emphasis">
								<span>PID {{ processInfo.pid }}</span>
								<span>{{ $t('plugins.WorkshopService.servicePage.up_for_t', { t: duration(processInfo.age_s) }) }}</span>
								<span v-if="processInfo.memory_mb != null">{{ $t('plugins.WorkshopService.servicePage.memory_n_mb', { n: processInfo.memory_mb }) }}</span>
								<span v-if="processInfo.cpu_pct != null">CPU {{ processInfo.cpu_pct }}%</span>
								<span>{{ $t('plugins.WorkshopService.servicePage.n_threads', { n: processInfo.threads }) }}</span>
								<span>{{ $t('plugins.WorkshopService.servicePage.n_internal_processes', { n: processes.length }) }}</span>
							</div>
							<div v-else-if="serviceOwn.detail" class="text-body-small ml-10 mt-1 text-medium-emphasis">{{ serviceOwn.detail }}</div>
						</div>
						<div v-if="!processes.length" class="text-medium-emphasis">
							{{ $t('plugins.WorkshopService.servicePage.waiting_for_backend_data_needs') }}
						</div>
						<!-- summary tiles, filters and one card per process (what it is, pace, CPU and its last minutes) -->
						<processes-summary
:service="serviceOwn" :process="processInfo" :processes="processes" :count="count"
:load="loadDuet" :ipc="ipc" :hist-service="histProc.service" :guard="guardStatus"
						/>
						<div v-if="processes.length" class="d-flex align-center flex-wrap mb-2" style="gap:6px">
							<v-chip
								v-for="c in procCategories" :key="c.cat" size="x-small" label
								variant="outlined" :class="{ 'wf-on': procCat === c.cat }"
								@click="procCat = procCat === c.cat ? null : c.cat"
							>{{ c.cat }} ({{ c.n }})</v-chip>
							<v-spacer />
							<v-btn-toggle v-model="procFilter" density="compact" mandatory color="primary">
								<v-btn size="small" value="all">{{ $t('plugins.WorkshopService.procDocs.ui_filter_all') }}</v-btn>
								<v-btn size="small" value="problems">{{ $t('plugins.WorkshopService.procDocs.ui_filter_problems') }}</v-btn>
							</v-btn-toggle>
						</div>
						<v-text-field
							v-if="processes.length > 6" v-model="procSearch" density="compact" hide-details clearable variant="outlined" class="mb-2"
							:placeholder="$t('plugins.WorkshopService.procDocs.ui_search')" prepend-inner-icon="mdi-magnify"
						/>
						<div v-if="processes.length && !processesFiltered.length" class="text-body-small text-medium-emphasis mb-2">{{ $t('plugins.WorkshopService.procDocs.ui_none_match') }}</div>
						<!-- the long list, by category: each group opens by tapping its header (open by itself when it has a problem or when searching) -->
						<div v-for="g in procGroups" :key="g.cat" class="svc-group">
							<a href="#" class="svc-group-cab" @click.prevent="procOpen[g.cat] = !groupOpen(g)">
								<v-icon size="x-small">{{ groupOpen(g) ? 'mdi-chevron-down' : 'mdi-chevron-right' }}</v-icon>
								<span class="svc-group-name">{{ g.cat }}</span>
								<span class="text-medium-emphasis">({{ g.items.length }})</span>
								<v-spacer />
								<v-chip v-if="g.problems" size="x-small" label color="warning" variant="flat">{{ g.problems }}</v-chip>
								<v-icon v-else size="x-small" color="success">mdi-check-circle-outline</v-icon>
							</a>
							<div v-if="groupOpen(g)">
								<process-row v-for="p in g.items" :key="p.id" :p="p" :hist="histProc.proc[p.id] || null" @mode="m => changeMode(p.id, m)" />
							</div>
						</div>
						<!-- Load toward the board: what this service asks the Duet for (DuetControlServer) -->
						<div class="text-label-small text-medium-emphasis mt-3">{{ $t('plugins.WorkshopService.servicePage.load_this_service_puts_on_the') }}</div>
						<div class="svc-proc">
							<div class="d-flex align-center flex-wrap">
								<v-icon class="mr-3 svx-ico">mdi-speedometer</v-icon>
								<div class="svc-proc-txt">
									<div class="font-weight-medium">{{ $t('plugins.WorkshopService.servicePage.connection_with_the_board') }}</div>
									<div class="text-body-small text-medium-emphasis">{{ $t('plugins.WorkshopService.servicePage.the_service_reads_the_machine_state') }}</div>
								</div>
								<v-spacer />
								<v-chip size="small" label variant="flat" :color="loadDuet.color">{{ loadDuet.text }}</v-chip>
							</div>
							<div v-if="subscription" class="text-body-small ml-10 mt-1 svc-metricas text-medium-emphasis">
								<span :title="$t('plugins.WorkshopService.servicePage.the_single_subscription_to_the_machine')">{{ $t('plugins.WorkshopService.servicePage.subscription_x', { x: subscription.live ? $t('plugins.WorkshopService.servicePage.alive') : $t('plugins.WorkshopService.servicePage.down') }) }}</span>
								<span :title="$t('plugins.WorkshopService.servicePage.state_changes_arriving_per_second')">{{ $t('plugins.WorkshopService.servicePage.n_changes_s', { n: subscription.patches_s }) }}</span>
								<span :title="$t('plugins.WorkshopService.servicePage.data_arriving_per_second')">{{ subscription.kb_s }} KB/s</span>
								<span v-if="subscription.age_last_s != null" :title="$t('plugins.WorkshopService.servicePage.how_long_ago_the_last_change')">{{ $t('plugins.WorkshopService.servicePage.last_t_ago', { t: sec(subscription.age_last_s) }) }}</span>
								<span :class="subscription.reconnections ? 'text-warning' : ''" :title="$t('plugins.WorkshopService.servicePage.times_the_connection_was_lost_and')">{{ $t('plugins.WorkshopService.servicePage.n_reconnections', { n: subscription.reconnections }) }}</span>
								<span>{{ $t('plugins.WorkshopService.servicePage.n_filters', { n: subscription.filters }) }}</span>
								<span v-if="subscription.error" class="text-warning">{{ subscription.error }}</span>
							</div>
							<div v-if="ipc" class="text-body-small ml-10 mt-1 svc-metricas text-medium-emphasis">
								<span :title="$t('plugins.WorkshopService.servicePage.calls_to_the_board_in_the')">{{ $t('plugins.WorkshopService.servicePage.n_calls_min', { n: ipc.per_min }) }}</span>
								<span :title="$t('plugins.WorkshopService.servicePage.since_the_service_started')">{{ $t('plugins.WorkshopService.servicePage.n_in_total', { n: ipc.total }) }}</span>
							</div>
							<div v-if="loadDuet.reason" class="text-body-small ml-10 mt-2 svc-load-reason" :class="'svc-load-' + loadDuet.color">
								<v-icon size="x-small" class="mr-1">mdi-information-outline</v-icon>{{ loadDuet.reason }}
							</div>
							<div v-if="ipcAreas.length" class="text-body-small ml-10 mt-2">
								<div class="text-medium-emphasis mb-1">{{ $t('plugins.WorkshopService.servicePage.load_by_area') }}</div>
								<div v-for="a in ipcAreas" :key="a.id" class="svc-load-row" :title="a.help">
									<span class="svc-load-name">{{ a.name }}</span>
									<v-progress-linear :model-value="a.pct" height="6" rounded :color="a.pct >= 40 ? 'warning' : 'primary'" bg-color="grey-darken-3" class="svc-load-bar" />
									<span class="svc-load-num">{{ a.n }}/min &middot; {{ a.pct }}%</span>
								</div>
							</div>
							<div v-if="ipcKinds.length" class="text-body-small ml-10 mt-3">
								<div class="text-medium-emphasis mb-1">{{ $t('plugins.WorkshopService.servicePage.calls_one_by_one') }}</div>
								<div v-for="t in ipcKinds" :key="t.id" class="svc-load-row" :class="t.last_min > 30 ? 'text-warning' : ''" :title="t.help">
									<span class="svc-load-name">{{ t.name }}<span class="text-medium-emphasis"> &middot; {{ t.id }}</span></span>
									<v-progress-linear :model-value="t.pct" height="4" rounded :color="t.last_min > 30 ? 'warning' : 'primary'" bg-color="grey-darken-3" class="svc-load-bar" />
									<span class="svc-load-num" :title="$t('plugins.WorkshopService.servicePage.last_minute')">{{ t.last_min }}/min &middot; {{ t.pct }}%</span>
									<span class="svc-load-num text-medium-emphasis" :title="$t('plugins.WorkshopService.servicePage.the_slowest')">{{ $t('plugins.WorkshopService.servicePage.max_n_ms', { n: t.max_ms }) }}</span>
								</div>
								<div class="text-medium-emphasis mt-1">{{ $t('plugins.WorkshopService.servicePage.warning_rows_hint', { n: 30 }) }}</div>
							</div>
							<div v-if="lightsIpc" class="text-body-small ml-10 mt-1 svc-metricas text-medium-emphasis">
								<span :title="$t('plugins.WorkshopService.servicePage.what_the_lights_module_still_asks')">{{ $t('plugins.WorkshopService.servicePage.lights_ipc', { r: lightsIpc.reads_min, c: lightsIpc.commands_min, p: lightsIpc.publishes_min }) }}</span>
							</div>
						</div>
						<!-- Servicios aparte de WorkshopService (puente, plugins con proceso propio) -->
						<div v-if="external.length" class="text-label-small text-medium-emphasis mt-3">{{ $t('plugins.WorkshopService.servicePage.separate_services') }}</div>
						<div v-for="x in external" :key="x.id" class="svc-proc">
							<div class="d-flex align-center flex-wrap">
								<v-icon class="mr-3 svx-ico">{{ x.icon }}</v-icon>
								<div class="svc-proc-txt">
									<div class="font-weight-medium">{{ x.title }}</div>
									<div class="text-body-small text-medium-emphasis">{{ x.description }}</div>
									<div v-if="x.detail" class="text-body-small svc-detail"><v-icon size="x-small" class="mr-1">mdi-information-outline</v-icon>{{ x.detail }}</div>
								</div>
								<v-spacer />
								<v-chip size="small" label variant="flat" :color="x.state.color">{{ x.state.text }}</v-chip>
							</div>
							<div class="text-body-small ml-10 mt-1">
								<span v-for="b in x.buses" :key="b.id" class="mr-3" :class="b.open ? 'text-success' : (b.error ? 'text-warning' : 'text-medium-emphasis')" :title="b.error || ''">
									<v-icon size="x-small" :color="b.open ? 'success' : (b.error ? 'warning' : 'grey')">mdi-serial-port</v-icon>
									{{ b.name }}: {{ b.open ? $t('plugins.WorkshopService.servicePage.open') : (b.error ? $t('plugins.WorkshopService.servicePage.with_a_problem') : $t('plugins.WorkshopService.servicePage.closed')) }}
									<span class="text-medium-emphasis">{{ $t('plugins.WorkshopService.servicePage.bus_stats', { ok: b.stats.ok, nr: b.stats.without_response, crc: b.stats.crc }) }}</span>
								</span>
								<a v-if="x.path && hasPath(x.path)" href="#" class="ml-1" @click.prevent="goTo(x.path)">{{ $t('plugins.WorkshopService.servicePage.open_the_page') }}</a><a v-else-if="x.anchor" href="#" class="ml-1" @click.prevent="goAnchor(x.anchor)">{{ $t('plugins.WorkshopService.servicePage.see_details_and_settings') }}</a>
							</div>
							<div class="ml-10 mt-1">
								<a href="#" class="text-body-small" @click.prevent="docExt[x.id] = !docExt[x.id]">
									<v-icon size="x-small" color="primary">{{ docExt[x.id] ? 'mdi-chevron-up' : 'mdi-chevron-down' }}</v-icon>
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
						<v-icon size="small" class="mr-2 svx-ico">mdi-robot</v-icon>{{ $t('plugins.WorkshopService.servicePage.automations') }}
					</v-card-title>
					<v-card-text>
						<div class="svc-auto">
							<div class="d-flex align-center">
								<v-icon class="mr-2 svx-ico">mdi-weather-windy</v-icon>
								<v-switch
									:model-value="airAssistAuto" density="compact" hide-details color="primary"
									:label="$t('plugins.WorkshopService.servicePage.automatic_air_with_the_laser')" @update:model-value="setAirAuto"
								/>
								<v-spacer />
								<v-chip size="x-small" label variant="flat" :color="airAssist ? 'success' : 'grey'">{{ airAssist ? $t('plugins.WorkshopService.servicePage.air_on') : $t('plugins.WorkshopService.servicePage.air_off') }}</v-chip>
							</div>
							<div class="text-body-small text-medium-emphasis svc-sub">
								{{ $t('plugins.WorkshopService.servicePage.air_rule') }}<span v-if="!airAssistAuto"> {{ $t('plugins.WorkshopService.servicePage.used_when_automatic_mode_is_on') }}</span>
								<div class="d-flex align-center flex-wrap mt-1" style="gap:4px">
									<span>{{ $t('plugins.WorkshopService.servicePage.air_off_after') }}</span>
									<v-chip-group :model-value="airAssistDelay" mandatory selected-class="text-primary" @update:model-value="setDelay">
										<v-chip v-for="t in delayOptions" :key="t" :value="t" size="small" variant="outlined" filter>{{ t }} s</v-chip>
									</v-chip-group>
								</div>
							</div>
							<div class="ml-9 mt-1">
								<a href="#" class="text-body-small" @click.prevent="docAuto.air = !docAuto.air">
									<v-icon size="x-small" color="primary">{{ docAuto.air ? 'mdi-chevron-up' : 'mdi-chevron-down' }}</v-icon>
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
								<v-chip size="x-small" label :color="statusLightAuto ? 'success' : 'grey'" style="flex:none">{{ statusLightAuto ? $t('plugins.WorkshopService.servicePage.auto_state_on') : $t('plugins.WorkshopService.servicePage.auto_state_off') }}</v-chip>
								<!-- the link only exists with the plugin installed and active: stopped, the route does not exist -->
								<a href="#" class="text-body-medium" style="flex:none" @click.prevent="goTo('/Plugins/Lights')">{{ $t('plugins.WorkshopService.servicePage.open_lights_and_status') }}</a>
							</div>
							<div class="ml-9 mt-1">
								<a href="#" class="text-body-small" @click.prevent="docAuto.lights = !docAuto.lights">
									<v-icon size="x-small" color="primary">{{ docAuto.lights ? 'mdi-chevron-up' : 'mdi-chevron-down' }}</v-icon>
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
									:model-value="powerOffOnFinish" density="compact" hide-details color="primary"
									:label="$t('plugins.WorkshopService.servicePage.turn_everything_off_when_done')" @update:model-value="setShutdown"
								/>
								<v-spacer />
								<v-chip size="x-small" label variant="flat" :color="powerOffOnFinish ? 'warning' : 'grey'">{{ powerOffOnFinish ? $t('plugins.WorkshopService.servicePage.armed') : $t('plugins.WorkshopService.servicePage.no_caps') }}</v-chip>
							</div>
							<div class="text-body-small text-medium-emphasis svc-sub">
								{{ $t('plugins.WorkshopService.servicePage.when_the_job_ends_shuts_the') }}
							</div>
							<div class="ml-9 mt-1">
								<a href="#" class="text-body-small" @click.prevent="docAuto.poweroff = !docAuto.poweroff">
									<v-icon size="x-small" color="primary">{{ docAuto.poweroff ? 'mdi-chevron-up' : 'mdi-chevron-down' }}</v-icon>
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
								<v-chip size="x-small" label variant="flat" :color="movFree ? 'success' : 'warning'">{{ $t('plugins.WorkshopService.servicePage.mov_state_' + movState) }}</v-chip>
							</div>
							<div class="text-body-small text-medium-emphasis svc-sub">{{ $t('plugins.WorkshopService.servicePage.mov_card_sub') }}</div>
							<div class="svc-mov-opts mt-2">
								<v-sheet
									v-for="o in movOptions" :key="o.value" border rounded class="svc-mov-opt pa-2"
									:class="{ 'svc-mov-sel': movMode === o.value }" @click="setMovMode(o.value)"
								>
									<div class="d-flex align-center">
										<v-icon size="small" :color="movMode === o.value ? 'primary' : 'grey'">{{ movMode === o.value ? 'mdi-radiobox-marked' : 'mdi-radiobox-blank' }}</v-icon>
										<span class="font-weight-medium ml-2">{{ o.title }}</span>
									</div>
									<div class="text-body-small text-medium-emphasis ml-6">{{ o.detail }}</div>
								</v-sheet>
							</div>
							<div v-if="movMode === 'protected'" class="text-body-small text-medium-emphasis svc-sub mt-2">
								<a href="#" @click.prevent="movAdvanced = !movAdvanced">
									<v-icon size="x-small" color="primary">{{ movAdvanced ? 'mdi-chevron-up' : 'mdi-chevron-down' }}</v-icon>{{ $t('plugins.WorkshopService.servicePage.mov_adv') }}
								</a>
								<div v-if="movAdvanced" class="mt-1">
									<div class="d-flex align-center flex-wrap" style="gap:4px">
										<span>{{ $t('plugins.WorkshopService.servicePage.mov_release_t') }}</span>
										<v-chip-group :model-value="movRelease" mandatory selected-class="text-primary" @update:model-value="setMovRelease">
											<v-chip v-for="t in movTimes" :key="t.value" :value="t.value" size="small" variant="outlined" filter>{{ t.text }}</v-chip>
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
								<v-chip size="x-small" label variant="flat" :color="job.active ? 'success' : 'grey'">{{ job.active ? $t('plugins.WorkshopService.servicePage.running') : $t('plugins.WorkshopService.servicePage.none') }}</v-chip>
							</div>
							<div class="text-body-small text-medium-emphasis svc-sub">
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
							<div class="text-body-small text-medium-emphasis svc-sub mt-2">
								<div>{{ $t('plugins.WorkshopService.servicePage.live_end_intro') }}</div>
								<div class="d-flex align-center flex-wrap mt-1" style="gap:4px">
									<span>{{ $t('plugins.WorkshopService.servicePage.live_end_after') }}</span>
									<v-chip-group :model-value="movIdle" mandatory selected-class="text-primary" @update:model-value="setMovIdle">
										<v-chip v-for="t in movRests" :key="t.value" :value="t.value" size="small" variant="outlined" filter>{{ t.text }}</v-chip>
									</v-chip-group>
								</div>
								<div class="mt-1">{{ $t('plugins.WorkshopService.servicePage.live_end_note') }}</div>
							</div>
							<div class="d-flex justify-end mt-1">
								<v-btn
									v-if="job.active" size="small" :variant="close.armed ? 'flat' : 'outlined'" :color="close.armed ? 'amber-darken-3' : undefined"
									:loading="close.sending" @click="closeJob"
								>
									{{ close.armed ? $t('plugins.WorkshopService.servicePage.tap_again_close_the_job') : $t('plugins.WorkshopService.servicePage.close_job') }}
								</v-btn>
							</div>
							<div v-if="job.active && job.file" class="text-body-small text-medium-emphasis svc-sub">{{ $t('plugins.WorkshopService.servicePage.it_came_in_a_file_it') }}</div>
							<div v-if="close.msg" class="text-body-small svc-sub">{{ close.msg }}</div>
							<div class="ml-9 mt-1">
								<a href="#" class="text-body-small" @click.prevent="docAuto.job = !docAuto.job">
									<v-icon size="x-small" color="primary">{{ docAuto.job ? 'mdi-chevron-up' : 'mdi-chevron-down' }}</v-icon>
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
				<v-icon size="small" class="mr-2 svx-ico">mdi-lock</v-icon>{{ $t('plugins.WorkshopService.servicePage.dwc_password') }}
				<v-spacer />
				<v-chip size="small" variant="flat" :color="key.has === null ? 'grey' : (key.has ? 'success' : 'warning')">
					{{ key.has === null ? $t('plugins.WorkshopService.common.no_data_2') : (key.has ? $t('plugins.WorkshopService.servicePage.set') : $t('plugins.WorkshopService.servicePage.no_password')) }}
				</v-chip>
			</v-card-title>
			<v-card-text>
				<div class="text-body-small text-medium-emphasis mb-2">
					{{ $t('plugins.WorkshopService.servicePage.with_a_password_dwc_asks_for') }}
				</div>
				<div class="text-body-small text-warning mb-3">
					{{ $t('plugins.WorkshopService.servicePage.if_you_forget_it_dwc_won') }}
				</div>
				<v-row density="compact">
					<v-col cols="12" sm="5">
						<v-text-field v-model="key.newEntry" type="password" :label="$t('plugins.WorkshopService.servicePage.new_password')" density="compact" variant="outlined" hide-details autocomplete="new-password" />
					</v-col>
					<v-col cols="12" sm="5">
						<v-text-field v-model="key.repeat" type="password" :label="$t('plugins.WorkshopService.servicePage.repeat_the_password')" density="compact" variant="outlined" hide-details autocomplete="new-password" />
					</v-col>
					<v-col cols="12" sm="2" class="d-flex align-center">
						<v-btn size="small" block :color="key.armed === 'set' ? 'error' : 'primary'" :loading="key.sending" :disabled="!keyValid" @click="putKey">
							{{ key.armed === 'set' ? $t('plugins.WorkshopService.servicePage.confirm_q') : (key.has ? $t('plugins.WorkshopService.servicePage.change') : $t('plugins.WorkshopService.servicePage.set_2')) }}
						</v-btn>
					</v-col>
				</v-row>
				<div v-if="key.newEntry && !keyValid" class="text-body-small text-warning mt-1">{{ keyProblem }}</div>
				<div class="d-flex align-center mt-3">
					<v-btn v-if="key.has" size="small" variant="outlined" :color="key.armed === 'clear' ? 'error' : null" :disabled="key.sending" @click="removeKey">
						{{ key.armed === 'clear' ? $t('plugins.WorkshopService.servicePage.confirm_q') : $t('plugins.WorkshopService.servicePage.remove_the_password') }}
					</v-btn>
					<span v-if="key.msg" class="text-body-small ml-3">{{ key.msg }}</span>
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
				<v-icon size="small" class="mr-2 svx-ico">mdi-book-open-variant</v-icon>{{ $t('plugins.WorkshopService.page.apiTitle') }}
			</v-card-title>
			<v-card-text>
				<details class="wf-more mb-3">
					<summary>{{ $t('plugins.WorkshopService.servicePage.how_it_works') }}</summary>
					<p>{{ $t('plugins.WorkshopService.page.apiHelp') }}</p>
				</details>
				<div class="svx-cats">
					<button v-for="c in categories" :key="c.id" type="button" class="wf-cat" :class="{ on: catFilter === c.id }" :aria-pressed="catFilter === c.id ? 'true' : 'false'" :style="{ '--wf-cat': c.color }" @click="pickCat(c.id)">
						<v-icon size="small">{{ c.icon }}</v-icon>
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
					<v-btn-toggle v-model="readFilter" density="compact" mandatory color="primary" class="svc-read-toggle">
						<v-btn size="small" value="all">{{ $t('plugins.WorkshopService.common.all') }}</v-btn>
						<v-btn size="small" value="always"><v-icon size="small" start>mdi-eye-outline</v-icon>{{ $t('plugins.WorkshopService.common.read_only') }}</v-btn>
						<v-btn size="small" value="no"><v-icon size="small" start>mdi-pencil-outline</v-icon>{{ $t('plugins.WorkshopService.common.change_something') }}</v-btn>
					</v-btn-toggle>
				</div>
				<v-expansion-panels class="mt-3 svx-panels">
					<v-expansion-panel v-for="h in handlersFiltered" :key="h.name">
						<v-expansion-panel-title class="py-1">
							<div class="d-flex align-center">
								<span v-if="!catFilter" class="wf-cat svx-cat-tag mr-2" :style="{ '--wf-cat': catOf(h.name).color }"><v-icon size="small">{{ catOf(h.name).icon }}</v-icon>{{ catOf(h.name).name }}</span>
								<code>{{ h.name }}</code>
								<v-chip v-if="h.reading" size="x-small" label variant="outlined" :color="read(h).color" class="ml-2 svc-read" :title="read(h).title">
									<v-icon start size="x-small">{{ read(h).icon }}</v-icon>{{ read(h).text }}
								</v-chip>
								<v-chip v-if="h.macro" size="x-small" label variant="outlined" class="ml-2">{{ $t('plugins.WorkshopService.page.macroChip') }}</v-chip>
								<span class="text-body-small text-medium-emphasis ml-2">{{ summary(h.description) }}</span>
							</div>
						</v-expansion-panel-title>
						<v-expansion-panel-text>
							<div class="text-body-medium mb-2">{{ h.description }}</div>
							<api-detail :op="(apiOps || []).find(x => x.op === h.name) || null" />
							<div v-if="h.reading" class="svc-read-det mb-2">
								<v-icon size="small" :color="read(h).color" class="mr-1">{{ read(h).icon }}</v-icon>{{ read(h).title }}
							</div>
							<div v-if="h.usage" class="d-flex align-start">
								<code
									class="d-block pa-2 svc-use svc-use-click flex-grow-1" :title="$t('plugins.WorkshopService.servicePage.tap_to_use_it_in_the')"
									@click="useExample(h)"
								>{{ h.usage.replace(/^Uso:\s*/, '') }}</code>
								<v-btn variant="text" icon size="small" class="ml-1" :title="$t('plugins.WorkshopService.servicePage.copy_the_example')" @click="copy(h.usage.replace(/^Uso:\s*/, ''), h.name)">
									<v-icon size="small">{{ copied === h.name ? 'mdi-check' : 'mdi-content-copy' }}</v-icon>
								</v-btn>
							</div>

							<!-- Test from here (2026-10-09) -->
							<div class="svc-prueba mt-3">
								<div class="text-body-small text-medium-emphasis mb-1">
									{{ $t('plugins.WorkshopService.servicePage.test') }}
									<span v-if="dangerous(h.name)" class="text-warning">{{ $t('plugins.WorkshopService.servicePage.this_command_acts_on_the_machine') }}</span>
								</div>
								<div class="d-flex align-center">
									<v-text-field
										:model-value="test(h).code" density="compact" hide-details variant="outlined" class="svc-test-field" :label="$t('plugins.WorkshopService.page.argsLabel')"
										@update:model-value="v => setTest(h, { code: v })" @keyup.enter="sendTest(h)"
									/>
									<v-btn
										size="small" class="ml-2" :loading="test(h).sending"
										:color="test(h).armed ? 'error' : (dangerous(h.name) ? 'warning' : 'primary')"
										@click="sendTest(h)"
									>
										<v-icon start size="small">mdi-send</v-icon>{{ test(h).armed ? $t('plugins.WorkshopService.servicePage.confirm_q') : $t('plugins.WorkshopService.servicePage.send') }}
									</v-btn>
									<v-btn variant="text" icon size="small" class="ml-1" :title="$t('plugins.WorkshopService.servicePage.copy_this_command')" @click="copy(test(h).code, h.name + ':field')">
										<v-icon size="small">{{ copied === h.name + ':field' ? 'mdi-check' : 'mdi-content-copy' }}</v-icon>
									</v-btn>
								</div>
								<div v-if="test(h).result" class="svc-result mt-2">
									<div class="d-flex align-center mb-1">
										<v-chip size="x-small" label variant="flat" :color="test(h).result.ok ? 'success' : 'error'">{{ test(h).result.ok ? $t('plugins.WorkshopService.servicePage.ok') : 'ERROR' }}</v-chip>
										<span class="text-body-small text-medium-emphasis ml-2">{{ test(h).result.hour }} - {{ test(h).result.ms }} ms</span>
									</div>
									<pre class="svc-res-txt">{{ test(h).result.text || $t('plugins.WorkshopService.common.no_response') }}</pre>
								</div>
							</div>
						</v-expansion-panel-text>
					</v-expansion-panel>
				</v-expansion-panels>
			</v-card-text>
		</v-card>
		</div>
		</div>
		</div>
	</v-container>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { i18n, machineModel, modelPlugins, enabledPlugins } from './dwc-host.js'
import { api, apiText, currentIdentity, onIdentity } from './workshop-api.js'
import { serviceTexts, serviceDefaultName } from './service-text.js'
import { pluginOf, dataOf, IDS, pluginActive, pathExists } from './workshop-ids.js'
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
import { ExpandTransition } from './expand-transition.js'
import { matches } from './search.js'
import { hist as histProc, sample } from './processes-history.js'
// same color per LED as the rest of the interface
import { ledColor } from './LedStrip.vue'

// Icon, color and category of each internal process (dsf/heartbeats.py)
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
const DANGEROUS_KINDS = ['motion', 'power', 'admin'];

// Category of each API operation (by its group)
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

const route = useRoute()
const router = useRouter()

const root = ref(null)
const section = ref('summary') // the section chosen in the side bar
// sections already opened: they stay mounted (v-show) so going back does not reload them
const visited = ref({ password: false, bridge: false, commands: false, base: false, users: false, audit: false, api: false })
const identity = ref(currentIdentity()) // who uses this page (auth.whoami): compat = no user created yet
const rs485Received = ref(null)
const visionState = ref(null) // GET :8095/state of WorkshopVision (OpenCV), through the service
const visionError = ref(null)
const nowSvc = ref(Date.now())
const procFilter = ref('all')
const procCat = ref(null)
const procSearch = ref('')
const modeError = ref({})
const docAuto = ref({ air: false, lights: false, poweroff: false, job: false })
const docExt = ref({})
const procOpen = ref({})
const filter = ref('')
const copied = ref(null)
const catFilter = ref(null)
const subFilter = ref(null) // sub-group inside the chosen category (the op prefix, e.g. machine.workarea)
const readFilter = ref('all')
const tests = ref({}) // name -> { code (JSON of the arguments), sending, armed, result }
const apiOps = ref(null) // api.describe of the service (operations with their arguments)
const savingChannel = ref(false)
const advancedOpen = ref(false) // Advanced section of the communication with the Duet
const advanced = ref(false) // channel changes unlocked (double confirmation); false again when saved or closed
const armedAdv = ref(false)
const key = ref({ has: null, newEntry: '', repeat: '', armed: null, sending: false, msg: '' })
const close = ref({ armed: false, sending: false, msg: '' })
const box = ref({ lowering: false, sending: false, msg: '' })
const movAdvanced = ref(false) // the advanced seconds of the movement card are folded by default

// timers that are not shown
let clockSvc = null
let sampling = null
let clockVision = null
let closeTimer = null
let keyTimer = null
let advTimer = null
let armTimer = null
let offIdentity = null

// the first time a heavy section is opened it is mounted and from then on only hidden
watch(section, v => {
	if (v in visited.value) {
		visited.value[v] = true
	}
})
// Deep link from other pages: /Plugins/WorkshopService?anchor=svc-base (page may be kept alive)
watch(() => route.query.anchor, id => {
	if (id) {
		goWhenReady(id)
	}
})

// ---- the plugin data the service publishes
const pluginModel = computed(() => pluginOf(modelPlugins(), 'service'))
const runs = computed(() => {
	const pm = pluginModel.value
	return !!(pm && pm.pid > 0)
})
// The declared type is Map<string, any> in DWC 3.7 (a plain object in 3.6): dataOf accepts both.
// The texts come as {key, params}: they are shown in the language of this DWC.
function pluginData(name) {
	if (!pluginModel.value || !pluginModel.value.data) {
		return null
	}
	return serviceTexts(dataOf(pluginModel.value, name))
}

// other plugins: what points to them shows only when they are installed and enabled
const hasJog = computed(() => pluginActive('jog'))
const hasBar = computed(() => pluginActive('bar'))
// "Lights and states" (WorkshopLights) installed and enabled in Settings > Plugins
const lightsActive = computed(() => {
	if (!pluginOf(modelPlugins(), 'lights')) return false
	const enabled = enabledPlugins()
	if (!enabled) return true // list not loaded yet: do not hide
	return IDS.lights.some(id => enabled.includes(id))
})
// what stops working while the service is stopped, naming only the plugins that are there
const withoutServiceList = computed(() => {
	const t = k => i18n.t('plugins.WorkshopService.servicePage.' + k)
	const l = []
	if (hasJog.value) l.push(t('stopped_the_jog'))
	if (lightsActive.value) l.push(t('stopped_the_lights'))
	l.push(t('stopped_the_phone_alerts'))
	l.push(t('stopped_the_api'))
	return l.slice(0, -1).join(', ') + t('stopped_and') + l[l.length - 1]
})
// the page is long: its sections go in a side bar (same as the Vision and Work table bars)
const sections = computed(() => {
	const t = k => i18n.t('plugins.WorkshopService.servicePage.' + k)
	return [
		{ id: 'summary', icon: 'mdi-view-dashboard-outline', label: t('nav_summary') },
		{ id: 'processes', icon: 'mdi-cogs', label: t('nav_processes') },
		{ id: 'bridge', icon: 'mdi-console-network-outline', label: t('nav_bridge') },
		{ id: 'commands', icon: 'mdi-history', label: t('nav_commands') },
		{ id: 'base', icon: 'mdi-database-outline', label: t('nav_database') },
		{ id: 'users', icon: 'mdi-account-group-outline', label: t('nav_users') },
		{ id: 'audit', icon: 'mdi-clipboard-text-clock-outline', label: t('nav_audit') },
		{ id: 'api', icon: 'mdi-api', label: t('nav_api') },
		{ id: 'password', icon: 'mdi-lock-outline', label: t('nav_password') }
	]
})
// color of the badge of the page bar and default color of the sections (plugin-colors.js)
const badge = pluginBadge(PLUGIN_ID)
const connected = computed(() => runs.value && !!pluginData('connected'))
const serviceOwn = computed(() => {
	if (!runs.value) {
		return { text: i18n.t('plugins.WorkshopService.servicePage.stopped'), color: 'error', icon: 'mdi-stop-circle', detail: i18n.t('plugins.WorkshopService.servicePage.the_plugin_process_is_not_running') }
	}
	if (!pluginData('connected')) {
		return { text: i18n.t('plugins.WorkshopService.servicePage.connecting'), color: 'warning', icon: 'mdi-lan-pending', detail: i18n.t('plugins.WorkshopService.servicePage.process_runs_not_connected') }
	}
	const bad = processes.value.filter(p => p.state.level === 2).length
	if (bad) {
		return { text: i18n.t('plugins.WorkshopService.servicePage.with_problems_2'), color: 'warning', icon: 'mdi-alert', detail: i18n.t('plugins.WorkshopService.servicePage.n_internal_processes_with_problems', { n: bad }) }
	}
	return { text: i18n.t('plugins.WorkshopService.servicePage.running_2'), color: 'success', icon: 'mdi-check-circle', detail: i18n.t('plugins.WorkshopService.servicePage.runs_on_the_system_and_is') }
})
const airAssist = computed(() => !!pluginData('airAssist'))
const airAssistAuto = computed(() => {
	const v = pluginData('airAssistAuto')
	return v === null || v === undefined ? true : !!v
})
const airAssistDelay = computed(() => {
	const v = pluginData('airAssistDelay')
	return v == null ? 2 : Number(v)
})
const delayOptions = computed(() => {
	const base = [0, 2, 5, 10, 30]
	return base.includes(airAssistDelay.value) ? base : base.concat(airAssistDelay.value).sort((x, y) => x - y)
})
const statusLightAuto = computed(() => {
	const v = pluginData('statusLightAuto')
	return v === null || v === undefined ? true : !!v
})
const statusLightColor = computed(() => pluginData('statusLightColor') || '#000000')
const statusLightText = computed(() => pluginData('statusLightText') || '')
// On-screen indicator (Lights and states page): the current state with its color
// and the reason; null with a service from before the redesign.
const statusIndicator = computed(() => {
	const i = pluginData('statusIndicator')
	return i && i.state ? i : null
})
// Stretches as they are painted on the strip ([[hex, level 0..1, count], ...]);
// with automatic off they are the LEDs the illumination took.
const statusLightSecs = computed(() => {
	const s = pluginData('statusLightSecs')
	// also with automatic off: there the Pi publishes the illumination
	return Array.isArray(s) ? s.filter(x => x[2] > 0) : []
})
// Round indicator (request 2026-10-09): each state takes its proportion
// of the circle's LEDs, with the same colors as the strip.
const statusLightPie = computed(() => {
	const total = statusLightSecs.value.reduce((t, s) => t + s[2], 0)
	if (!total) {
		return statusLightAuto.value ? statusLightColor.value : '#616161'
	}
	let pos = 0
	const parts = statusLightSecs.value.map(s => {
		const a = (pos / total) * 360, b = ((pos + s[2]) / total) * 360
		pos += s[2]
		return `${ledColor(s)} ${a.toFixed(1)}deg ${b.toFixed(1)}deg`
	})
	return `conic-gradient(${parts.join(',')})`
})
// Color of the first lit stretch (glow and card border)
const statusLightBrightness = computed(() => {
	if (statusIndicator.value) {
		return statusIndicator.value.state.hex
	}
	const lit = statusLightSecs.value.find(s => s[1] > 0)
	if (lit) {
		return ledColor(lit)
	}
	return statusLightSecs.value.length ? 'none' : statusLightColor.value
})
const powerOffOnFinish = computed(() => {
	const g = machineModel().global
	return !!(g && (typeof g.get === 'function' ? g.get('powerOffOnFinish') : g.powerOffOnFinish))
})
const job = computed(() => pluginData('liveJob') || {})
// the default name (empty, or the default one in either language) in the language of this DWC; a given name as it is
const jobName = computed(() => serviceDefaultName(job.value.name, ['live_job_default_name']))
const boxBlack = computed(() => pluginData('boxBlack') || {})
const boxReport = computed(() => {
	const r = boxBlack.value.report
	return r && !r.seen ? r : null
})
// last unclean shutdown that was recorded, hidden or not
const lastDrop = computed(() => boxBlack.value.last_drop || null)
// movement lock settings (published by motion_owner.py in data.motion.settings)
const movAj = computed(() => (pluginData('motion') || {}).settings || {})
const movMode = computed(() => movAj.value.mode === 'duet' ? 'duet' : 'protected')
const movRelease = computed(() => typeof movAj.value.release_s === 'number' ? movAj.value.release_s : 20)
const movIdle = computed(() => typeof movAj.value.idle_s === 'number' ? movAj.value.idle_s : 30)
const movState = computed(() => {
	const st = (pluginData('motion') || {}).state
	return ['free', 'file_job', 'file_paused', 'live_active', 'live_idle', 'bridge_active', 'stopped'].includes(st) ? st : 'free'
})
const movFree = computed(() => movState.value === 'free')
// the two choices, written as what happens and not as a product name
const movOptions = computed(() => {
	const T = 'plugins.WorkshopService.servicePage.'
	return [
		{ value: 'protected', title: i18n.t(T + 'mov_opt_nobody_t'), detail: i18n.t(T + 'mov_opt_nobody_d') },
		{ value: 'duet', title: i18n.t(T + 'mov_opt_me_t'), detail: i18n.t(T + 'mov_opt_me_d') }
	]
})
// quick values as buttons; the saved value is always one of them (a custom one is added)
const movTimes = computed(() => optionsSeconds([8, 20, 60], movRelease.value))
const movRests = computed(() => optionsSeconds([15, 30, 60, 300, 0], movIdle.value))
// same rules as handlers/password.py (_valida)
const keyProblem = computed(() => {
	const c = key.value.newEntry || ''
	if (c.length < 4 || c.length > 60) return i18n.t('plugins.WorkshopService.servicePage.it_must_have_4_to_60')
	if (/[";\r\n]/.test(c) || /[\x00-\x1f]/.test(c)) return i18n.t('plugins.WorkshopService.servicePage.it_can_t_contain_quotes_semicolons')
	if (c.toLowerCase() === 'reprap') return i18n.t('plugins.WorkshopService.servicePage.reprap_is_the_factory_one_no')
	if (c !== key.value.repeat) return i18n.t('plugins.WorkshopService.servicePage.the_two_don_t_match')
	return ''
})
const keyValid = computed(() => !!key.value.newEntry && !keyProblem.value)
const communication = computed(() => {
	const c = pluginData('communication')
	return c && c.channels ? c : null
})
// Channel list: with a service older than 1.9.1 only 3 come
// (without "eligible"): it is deduced from exists / busy.
const channelsList = computed(() => {
	const cs = (communication.value && communication.value.channels) || []
	return cs.map(c => Object.assign({ usage: '', state: c.busy ? 'busy' : 'free' }, c, {
		eligible: c.eligible !== undefined ? c.eligible : (c.exists && !c.busy)
	}))
})
const optionsChannel = computed(() => [{ v: 'auto', t: i18n.t('plugins.WorkshopService.servicePage.automatic_aux2_aux_or_sbc_the') }].concat(optionsOf(channelsList.value)))
const optionsJog = computed(() => [{ v: 'auto', t: i18n.t('plugins.WorkshopService.servicePage.automatic_aux2_if_free_otherwise_sbc') }].concat(optionsOf(channelsList.value)))
// the channels that cannot be chosen are listed but disabled
const channelItemProps = item => ({ disabled: !!item.disabled })
// why automatic mode chose that channel (only shown with "auto")
const perThatJog = computed(() => {
	const c = communication.value
	if (!c) return ''
	return c.channel_jog === 'Aux2' ? i18n.t('plugins.WorkshopService.servicePage.aux2_is_free_and_gives_the') : i18n.t('plugins.WorkshopService.servicePage.aux2_is_not_free_the_jog')
})
const perThatService = computed(() => {
	const c = communication.value
	if (!c) return ''
	return c.channel === 'SBC' ? i18n.t('plugins.WorkshopService.servicePage.aux2_and_aux_are_not_free') : i18n.t('plugins.WorkshopService.servicePage.first_free_channel_the_jog_does')
})
const serviceStarted = computed(() => {
	const v = pluginData('serviceStarted')
	return typeof v === 'string' ? v : null
})
const last = computed(() => pluginData('lastCommands') || [])
const lastChange = computed(() => {
	const u = last.value[0]
	return u ? (u.hour + ' ' + u.code) : ''
})
// Ages in seconds as the Pi publishes them (every 5 s): they do not depend on
// the browser's clock nor on the precision of numbers in DSF.
// Plugins with their own backend (e.g. WorkshopRS485): read from their plugin data.
const external = computed(() => {
	const plugins = modelPlugins()
	const out = []
	const rs = pluginOf(plugins, 'rs485')
	if (rs && pluginActive('rs485')) {
		const d = rs.data ? dataOf(rs, 'rs485') : null
		const running = rs.pid > 0
		const devices = (d && d.devices) || []
		const bad = devices.filter(x => x.state === 'alarm' || x.state === 'without_communication').length
		const fresh = rs485Received.value && (nowSvc.value - rs485Received.value) < 15000
		let state = { text: i18n.t('plugins.WorkshopService.servicePage.up_to_date'), color: 'success' }
		if (!running) {
			state = { text: i18n.t('plugins.WorkshopService.servicePage.stopped'), color: 'grey' }
		} else if (!fresh) {
			state = { text: i18n.t('plugins.WorkshopService.common.no_data_2'), color: 'warning' }
		} else if (bad) {
			state = { text: i18n.t('plugins.WorkshopService.servicePage.n_with_a_fault', { n: bad }), color: 'error' }
		}
		out.push({
			id: 'WorkshopRS485', title: i18n.t('plugins.WorkshopService.servicePage.rs485_devices'), path: '/Plugins/RS485', icon: 'mdi-serial-port', color: '#00897B',
			description: i18n.t('plugins.WorkshopService.servicePage.servos_and_modbus_devices_over_rs485') + (rs.version ? ' ' + rs.version : '') + ').',
			detail: running ? i18n.t('plugins.WorkshopService.servicePage.n_devices_x', { n: devices.length, x: devices.map(x => x.name + ' ' + (x.state === 'ok' ? 'OK' : x.state.replace('_', ' '))).join(', ') || i18n.t('plugins.WorkshopService.servicePage.none_configured') }) : i18n.t('plugins.WorkshopService.servicePage.the_plugin_process_isn_t_running'),
			buses: running ? ((d && d.buses) || []) : [],
			state: state
		})
	}
	// Vision (WorkshopVision, OpenCV on :8095) -- 2026-10-10: "I do not see the OpenCV service"
	const vi = pluginOf(plugins, 'vision')
	if (vi && pluginActive('vision')) {
		const running = vi.pid > 0
		const e = visionState.value
		let state = { text: i18n.t('plugins.WorkshopService.servicePage.up_to_date'), color: 'success' }
		let detail = ''
		if (!running) {
			state = { text: i18n.t('plugins.WorkshopService.servicePage.stopped'), color: 'grey' }
			detail = i18n.t('plugins.WorkshopService.servicePage.the_plugin_process_isn_t_running_2')
		} else if (!e) {
			state = { text: visionError.value ? i18n.t('plugins.WorkshopService.servicePage.not_responding') : i18n.t('plugins.WorkshopService.servicePage.reading'), color: visionError.value ? 'warning' : 'grey' }
			detail = visionError.value ? i18n.t('plugins.WorkshopService.servicePage.vision_not_responding_x', { x: visionError.value }) : ''
		} else {
			const nCal = Object.keys(e.calibs || {}).length
			detail = 'OpenCV ' + (e.opencv || '?') + ' · ' + i18n.t('plugins.WorkshopService.servicePage.camera_on_the_x', { x: e.camera_en === 'carriage' ? i18n.t('plugins.WorkshopService.servicePage.carriage') : i18n.t('plugins.WorkshopService.servicePage.gantry') }) +
				' · ' + (nCal ? i18n.t('plugins.WorkshopService.servicePage.calibrated_n_resolutions', { n: nCal }) : i18n.t('plugins.WorkshopService.servicePage.not_calibrated_lc'))
			if (!nCal) state = { text: i18n.t('plugins.WorkshopService.servicePage.not_calibrated'), color: 'warning' }
		}
		out.push({
			id: 'WorkshopVision', title: i18n.t('plugins.WorkshopService.servicePage.vision_opencv'), path: '/Plugins/Vision', icon: 'mdi-eye-outline', color: '#1976D2',
			description: i18n.t('plugins.WorkshopService.servicePage.measures_parts_holes_marks', { v: vi.version ? ' ' + vi.version : '' }),
			detail: detail, buses: [], state: state
		})
	}
	const health = pluginData('healthPi') || {}
	// Service database (2026-10-10: "add the database service in Pi
	// service"); the detail is in Pi health
	const b = health.base
	if (b) {
		const rs2 = b.backup
		const ok = !b.error && b.check === 'ok' && !(rs2 && (rs2.late || (rs2.failures && rs2.failures.length)))
		const rowCount = (b.tables || []).reduce((s, x) => s + (x.rows || 0), 0)
		const lastWrite = String(b.modified || '').replace('T', ' ').slice(5, 16)
		out.push({
			id: 'base', title: i18n.t('plugins.WorkshopService.servicePage.database_sqlite'), anchor: 'svc-base', icon: 'mdi-database', color: '#00897B',
			description: i18n.t('plugins.WorkshopService.servicePage.stores_activity_energy_and_received_commands'),
			detail: b.error ? i18n.t('plugins.WorkshopService.servicePage.could_not_read_x', { x: b.error }) : i18n.t('plugins.WorkshopService.servicePage.db_detail', { mb: b.mb, rows: rowCount, t: lastWrite }) + (b.check !== 'ok' ? ' · ' + i18n.t('plugins.WorkshopService.servicePage.check_x', { x: b.check }) : '') +
				(rs2 ? ' · ' + i18n.t('plugins.WorkshopService.servicePage.backups_x', { x: !rs2.active ? i18n.t('plugins.WorkshopService.servicePage.backups_off_lc') : rs2.failures && rs2.failures.length ? i18n.t('plugins.WorkshopService.servicePage.backups_failing_lc') : rs2.late ? i18n.t('plugins.WorkshopService.servicePage.backups_late_lc') : i18n.t('plugins.WorkshopService.servicePage.backups_on_lc') }) + (rs2.last ? ' ' + i18n.t('plugins.WorkshopService.servicePage.last_paren_x', { x: String(rs2.last.date || '').replace('T', ' ').slice(5, 16) }) : '') : ''),
			buses: [],
			state: b.error ? { text: i18n.t('plugins.WorkshopService.common.no_data_2'), color: 'grey' } : ok ? { text: i18n.t('plugins.WorkshopService.servicePage.up_to_date'), color: 'success' } : { text: i18n.t('plugins.WorkshopService.servicePage.check'), color: 'warning' }
		})
	}
	const svc = (health.services || []).find(x => x.unit === 'workshop-gcode-bridge' || x.unit === 'workshop-bridge')
	if (svc) {
		const clients = health.bridge_clients
		out.unshift({
			id: 'bridge', title: i18n.t('plugins.WorkshopService.bridgeCard.g_code_bridge_telnet'), anchor: 'svc-bridge',
			icon: 'mdi-lan-connect', color: '#5E35B1',
			description: i18n.t('plugins.WorkshopService.servicePage.lets_programs_send_g_code_to') + svc.unit + ').',
			detail: svc.active ? (clients != null ? i18n.t('plugins.WorkshopService.servicePage.n_programs_connected', { n: clients }) : '') : i18n.t('plugins.WorkshopService.servicePage.the_service_is_not_running') + svc.state + ').',
			buses: [],
			state: svc.active ? { text: i18n.t('plugins.WorkshopService.servicePage.up_to_date'), color: 'success' } : { text: i18n.t('plugins.WorkshopService.servicePage.stopped'), color: 'error' }
		})
	}
	out.forEach(x => { x.level = x.state.color === 'success' ? 0 : (x.state.color === 'error' ? 2 : 1) })
	return out
})
const rs485Ts = computed(() => {
	const rs = pluginOf(modelPlugins(), 'rs485')
	const d = rs && rs.data ? dataOf(rs, 'rs485') : null
	return d ? (d.seq != null ? d.seq : d.ts) : null
})
watch(rs485Ts, (v, old) => {
	if (v && v !== old) {
		rs485Received.value = Date.now()
	}
})
const subscription = computed(() => (pluginData('servicesInternal') || {}).subscription || null)
const ipc = computed(() => (pluginData('servicesInternal') || {}).ipc || null)
const lightsIpc = computed(() => (pluginData('servicesInternal') || {}).lights || null)
// calls to the board by type, most frequent first, with their area, share of the total and what they do
const ipcKinds = computed(() => {
	const t = (ipc.value && ipc.value.types) || {}
	const total = (ipc.value && ipc.value.per_min) || 0
	return Object.keys(t).map(id => {
		const name = id.split('|')[1] || id
		const inf = IPC_AREAS[name] || IPC_AREAS[id] || { area: 'other' }
		return Object.assign({
			id: id.replace('|', ' · '), name: i18n.t('plugins.WorkshopService.servicePage.ipc_area_' + inf.area), area: inf.area,
			pct: total ? Math.round(100 * t[id].last_min / total) : 0,
			help: i18n.t('plugins.WorkshopService.servicePage.ipc_help', { total: t[id].ms, n: t[id].last_min })
		}, t[id])
	}).sort((a, b) => b.last_min - a.last_min).slice(0, 14)
})
// the same load grouped by area (status lights, motors, power usage...)
const ipcAreas = computed(() => {
	const t = (ipc.value && ipc.value.types) || {}
	const total = (ipc.value && ipc.value.per_min) || 0
	const by = {}
	Object.keys(t).forEach(id => {
		const inf = IPC_AREAS[id.split('|')[1] || id] || IPC_AREAS[id] || { area: 'other' }
		by[inf.area] = (by[inf.area] || 0) + t[id].last_min
	})
	return Object.keys(by).map(a => ({
		id: a, n: by[a], pct: total ? Math.round(100 * by[a] / total) : 0,
		name: i18n.t('plugins.WorkshopService.servicePage.ipc_area_' + a),
		help: i18n.t('plugins.WorkshopService.servicePage.ipc_area_help_' + a)
	})).sort((a, b) => b.n - a.n)
})
const loadDuet = computed(() => {
	const s = subscription.value, i = ipc.value
	if (!s) return { color: 'grey', text: i18n.t('plugins.WorkshopService.common.no_data'), reason: '' }
	if (!s.live) return { color: 'error', text: i18n.t('plugins.WorkshopService.servicePage.subscription_down'), reason: i18n.t('plugins.WorkshopService.servicePage.reason_subscription_down') }
	const n = i ? i.per_min : 0
	if (n > IPC_LIMIT) {
		const top = ipcAreas.value[0]
		return {
			color: 'warning', text: i18n.t('plugins.WorkshopService.servicePage.n_calls_min', { n }),
			reason: i18n.t('plugins.WorkshopService.servicePage.reason_over_limit', { n, limit: IPC_LIMIT }) +
				(top ? ' ' + i18n.t('plugins.WorkshopService.servicePage.reason_top_area', { area: top.name, pct: top.pct, n: top.n }) : '')
		}
	}
	return { color: 'success', text: 'normal', reason: i18n.t('plugins.WorkshopService.servicePage.reason_normal', { n, limit: IPC_LIMIT }) }
})
const guardStatus = computed(() => pluginData('guardStatus') || null)
const processInfo = computed(() => (pluginData('servicesInternal') || {}).process || null)
const processes = computed(() => {
	const raw = (pluginData('servicesInternal') || {}).processes || {}
	return Object.keys(raw).map(id => {
		const p = Object.assign({ id }, raw[id])
		p.info = PROC_INFO[id] || PROC_OTHER
		p.errorRecent = p.age_error_s != null && p.age_error_s < 3600
		p.module = ((pluginData('servicesInternal') || {}).modules || {})[id] || null
		p.modeError = modeError.value[id] || ''
		p.state = stateProcess(p)
		return p
	})
})
const procCategories = computed(() => {
	const by = {}
	processes.value.forEach(p => {
		const c = p.info.cat
		by[c] = by[c] || { cat: c, color: p.info.color, n: 0 }
		by[c].n++
	})
	return Object.keys(by).map(k => by[k])
})
const processesFiltered = computed(() => processes.value.filter(p =>
	(procFilter.value === 'all' || p.state.level > 0 || (p.restarts || 0) > 0) &&
	(!procCat.value || p.info.cat === procCat.value) &&
	matches(textSearch(p), procSearch.value)))
const procGroups = computed(() => {
	const by = {}
	processesFiltered.value.forEach(p => {
		const c = p.info.cat
		by[c] = by[c] || { cat: c, color: p.info.color, items: [], problems: 0 }
		by[c].items.push(p)
		if (p.state.level > 0 || (p.restarts || 0) > 0) by[c].problems++
	})
	return Object.keys(by).map(k => by[k])
})
// ONE list for every number of the strip, the chips and the header: the internal processes plus the separate services (bridge,
// database, RS485, Vision), each with its level (0 fine, 1 warning, 2 problem). While the service is not connected what the page
// holds is the last data it saw (or nothing): the counts are then null ("not available"), never zeros or old warnings.
const levelList = computed(() => processes.value.map(p => p.state.level).concat(external.value.map(x => x.level)))
const count = computed(() => {
	if (!connected.value) return null
	const levels = levelList.value
	return {
		ok: levels.filter(n => n === 0).length,
		notice: levels.filter(n => n === 1).length,
		bad: levels.filter(n => n === 2).length
	}
})
// the chip next to the title: the same counts, worded as the strip words them
const headerChip = computed(() => {
	const t = k => i18n.t('plugins.WorkshopService.servicePage.' + k)
	const c = count.value
	if (!connected.value) return { color: 'error', icon: 'mdi-lan-disconnect', text: t('backend_disconnected') }
	if (c.bad) return { color: 'error', icon: 'mdi-close-circle', text: i18n.t('plugins.WorkshopService.servicePage.n_with_problems', { n: c.bad }) }
	if (c.notice) return { color: 'warning', icon: 'mdi-alert', text: i18n.t('plugins.WorkshopService.servicePage.n_with_warnings', { n: c.notice }) }
	return { color: 'success', icon: 'mdi-check-circle', text: t('all_working') }
})
// API operations (api.describe): name, description, example of the arguments
const handlers = computed(() => (apiOps.value || []).map(o => {
	const example = {}
	Object.keys(o.args || {}).forEach(k => {
		const a = o.args[k]
		if (!a.required) return
		example[k] = a.choices ? a.choices[0] : ({ int: 0, num: 0, bool: true, obj: {}, list: [] })[a.type] !== undefined ? ({ int: 0, num: 0, bool: true, obj: {}, list: [] })[a.type] : ''
	})
	const args = Object.keys(o.args || {}).map(k => k + ': ' + o.args[k].type + (o.args[k].required ? ' *' : '')).join(', ')
	return {
		name: o.op, description: o.desc + (args ? ' (' + args + ')' : ''), usage: JSON.stringify(example),
		reading: o.kind === 'read' ? 'always' : 'no', reading_actions: null, kind: o.kind, macro: !!o.macro
	}
}))
const categories = computed(() => CATS.map(c => Object.assign({}, c, { n: handlers.value.filter(h => catOf(h.name).id === c.id).length }))
	.filter(c => c.n > 0))
// the sub-group of an operation: its name up to the last dot (machine.workarea.get -> machine.workarea)
function subOf(name) {
	const i = String(name || '').lastIndexOf('.')
	return i > 0 ? name.slice(0, i) : name
}
function pickCat(id) {
	catFilter.value = catFilter.value === id ? null : id
	subFilter.value = null
}
const catColor = computed(() => (CATS.find(c => c.id === catFilter.value) || CATS[0]).color)
const catOps = computed(() => handlers.value.filter(h => catOf(h.name).id === catFilter.value))
const catCount = computed(() => catOps.value.length)
const subCats = computed(() => {
	const by = {}
	catOps.value.forEach(h => { const k = subOf(h.name); by[k] = (by[k] || 0) + 1 })
	return Object.keys(by).sort().map(k => ({ id: k, n: by[k] }))
})
const handlersFiltered = computed(() => {
	const f = (filter.value || '').toLowerCase().trim()
	return handlers.value.filter(x =>
		(readFilter.value === 'all' || (readFilter.value === 'always' ? x.reading === 'always' : x.reading !== 'always')) &&
		(!catFilter.value || catOf(x.name).id === catFilter.value) &&
		(!subFilter.value || subOf(x.name) === subFilter.value) &&
		(!f || (x.name + ' ' + x.description).toLowerCase().includes(f)))
})

// api.describe fills the reference and the key permissions: if the service was busy or restarting when the page opened, try again
// until it answers (an empty list for good left the reference blank)
let apiOpsTimer = null
let apiOpsGone = false
function loadApiOps(n = 0) {
	api('api.describe', {}, { quiet: true }).then(d => {
		apiOps.value = (d && d.ops) || []
	}).catch(() => {
		if (!apiOps.value) apiOps.value = []
		if (apiOpsGone || n >= 40) return
		apiOpsTimer = setTimeout(() => loadApiOps(n + 1), Math.min(30000, 3000 * (n + 1)))
	})
}
onMounted(() => {
	clockSvc =setInterval(() => { nowSvc.value = Date.now() }, 3000)
	sampling = setInterval(() => { sample(processes.value, processInfo.value) }, 5000)
	sample(processes.value, processInfo.value)
	readVision()
	// only with the page in view (visible tab and active page: DWC keeps it alive with keep-alive)
	clockVision = setInterval(() => { if (!document.hidden && !(root.value && root.value.$el && root.value.$el.isConnected === false)) readVision() }, 10000)
	readKey()
	offIdentity = onIdentity(i => { identity.value = i })
	loadApiOps()
	if (route && route.query && route.query.anchor) {
		goWhenReady(route.query.anchor)
	}
})
onBeforeUnmount(() => {
	apiOpsGone = true
	clearTimeout(apiOpsTimer)
	clearInterval(clockVision)
	clearInterval(clockSvc)
	clearInterval(sampling)
	clearTimeout(closeTimer)
	clearTimeout(keyTimer)
	clearTimeout(advTimer)
	clearTimeout(armTimer)
	if (offIdentity) offIdentity()
})

function hasPath(path) {
	return pathExists(router, path)
}
function goTo(path) {
	router.push(path).catch(() => {})
}
// help text that names the jog: its variant without the jog when that plugin is not there
function jogVariant(k) {
	return i18n.t(hasJog.value ? k : k + '_no_jog')
}
function readVision() {
	const vi = pluginOf(modelPlugins(), 'vision')
	if (!vi || !(vi.pid > 0)) {
		visionState.value = null
		return
	}
	// through the service API (vision.get), not the port from the browser: with users on, Vision refuses a call without a session
	api('vision.get', { path: '/state' }, { noLogin: true, quiet: true })
		.then(d => (d && d.ok === false ? Promise.reject(new Error(d.error && d.error.message ? d.error.message : String(d.error || 'Vision'))) : d))
		.then(d => { visionState.value = d; visionError.value = null })
		.catch(e => { visionState.value = null; visionError.value = e.message || String(e) })
}
// API of the service: the text the old commands answered (JSON text, message or "Error: ...")
function send(op, args, opts) {
	return apiText(op, args || {}, opts || {})
}
function setAirAuto(v) {
	return send('air.auto', { on: !!v })
}
function setDelay(v) {
	if (typeof v !== 'number') return
	return send('air.delay', { seconds: v })
}
function hourShort(iso) {
	const m = /T(\d\d:\d\d)/.exec(String(iso || ''))
	return m ? m[1] : String(iso || '')
}
function optionsSeconds(base, current) {
	const v = base.includes(current) ? base : base.concat(current).sort((a, b) => (a || 1e9) - (b || 1e9))
	return v.map(x => ({ value: x, text: x === 0 ? i18n.t('plugins.WorkshopService.servicePage.never') : (x >= 60 ? (x / 60) + ' min' : x + ' s') }))
}
function setMovMode(v) {
	return send('movement.lock', { mode: v === 'duet' ? 'duet' : 'protected' })
}
function setMovRelease(v) {
	if (typeof v !== 'number') return
	return send('movement.lock', { release_s: v })
}
function setMovIdle(v) {
	if (typeof v !== 'number') return
	return send('movement.lock', { idle_s: v })
}
// double tap (DISENO.md): the first arms, the second closes; 4 s to confirm
async function closeJob() {
	if (!close.value.armed) {
		close.value.armed = true
		close.value.msg = ''
		clearTimeout(closeTimer)
		closeTimer = setTimeout(() => { close.value.armed = false }, 4000)
		return
	}
	clearTimeout(closeTimer)
	close.value.armed = false
	close.value.sending = true
	try {
		close.value.msg = String(await send('job.close') || '').trim()
	} catch (e) {
		close.value.msg = String((e && e.message) || e)
	} finally {
		close.value.sending = false
	}
}
// full report from the SD (0:/sys/workshop/data/blackbox/unclean-report.txt);
// if it cannot be read, the lines the page already has
async function downloadBox() {
	const r = boxReport.value || lastDrop.value
	if (!r) return
	box.value.lowering = true
	box.value.msg = ''
	let text = null
	try {
		const h = {}
		if (window.__workshopSession) h['X-Session-Key'] = window.__workshopSession
		const resp = await fetch('/machine/file/' + encodeURIComponent(r.file || '0:/sys/workshop/data/blackbox/unclean-report.txt'), { headers: h, cache: 'no-store' })
		if (resp.ok) text = await resp.text()
	} catch (e) {
		text = null
	}
	if (text === null) {
		text = (r.lines || []).join('\n') + '\n'
		box.value.msg = i18n.t('plugins.WorkshopService.servicePage.could_not_read_the_full_report')
	}
	const a = document.createElement('a')
	a.href = URL.createObjectURL(new Blob([text], { type: 'text/plain' }))
	a.download = 'apagado-no-limpio-' + String(r.last_datum || r.detected || '').replace(/[^0-9]/g, '').slice(0, 12) + '.txt'
	document.body.appendChild(a)
	a.click()
	setTimeout(() => { URL.revokeObjectURL(a.href); a.remove() }, 1000)
	box.value.lowering = false
}
async function showBox() {
	box.value.sending = true
	try {
		box.value.msg = String(await send('blackbox.show') || '').trim()
	} catch (e) {
		box.value.msg = String((e && e.message) || e)
	} finally {
		box.value.sending = false
	}
}
async function hideBox() {
	box.value.sending = true
	try {
		box.value.msg = String(await send('blackbox.hide') || '').trim()
	} catch (e) {
		box.value.msg = String((e && e.message) || e)
	} finally {
		box.value.sending = false
	}
}
function setShutdown(v) {
	return send('power.after_job', { armed: !!v })
}
function optionsOf(list) {
	// the eligible ones first; the others are seen but cannot be chosen
	const op = c => ({ v: c.id, t: c.id + ' · ' + stateChannel(c).t, disabled: !c.eligible })
	return list.filter(c => c.eligible).map(op).concat(list.filter(c => !c.eligible).map(op))
}
function stateChannel(c) {
	if (!c.exists) return { t: i18n.t('plugins.WorkshopService.servicePage.not_present'), color: 'grey' }
	if (c.state === 'reserved') return { t: i18n.t('plugins.WorkshopService.servicePage.cannot_be_chosen'), color: 'grey-darken-1' }
	if (c.state === 'busy') return { t: i18n.t('plugins.WorkshopService.servicePage.busy'), color: 'warning' }
	if (c.state === 'shared') return { t: i18n.t('plugins.WorkshopService.servicePage.shared'), color: 'info' }
	return { t: i18n.t('plugins.WorkshopService.servicePage.free'), color: 'success' }
}
async function readKey() {
	try {
		const r = String(await send('password.status') || '')
		key.value.has = /puesta/i.test(r) ? true : (/sin contrasena/i.test(r) ? false : null)
	} catch (e) {
		key.value.has = null
	}
}
// double tap (DISENO.md): the first arms, the second sends; 4 s to confirm
function armKey(that) {
	if (key.value.armed === that) {
		clearTimeout(keyTimer)
		key.value.armed = null
		return true
	}
	key.value.armed = that
	clearTimeout(keyTimer)
	keyTimer = setTimeout(() => { key.value.armed = null }, 4000)
	return false
}
async function putKey() {
	if (!keyValid.value || !armKey('set')) return
	key.value.sending = true
	try {
		key.value.msg = String(await send('password.set', { password: key.value.newEntry }) || '').trim()
		key.value.newEntry = ''
		key.value.repeat = ''
	} catch (e) {
		key.value.msg = String((e && e.message) || e)
	} finally {
		key.value.sending = false
		readKey()
	}
}
async function removeKey() {
	if (!armKey('clear')) return
	key.value.sending = true
	try {
		key.value.msg = String(await send('password.clear') || '').trim()
	} catch (e) {
		key.value.msg = String((e && e.message) || e)
	} finally {
		key.value.sending = false
		readKey()
	}
}
// Opens or closes the Advanced section; closing it blocks the channels again.
function toggleAdvanced() {
	advancedOpen.value = !advancedOpen.value
	if (!advancedOpen.value) blockAdvanced()
}
function blockAdvanced() {
	advanced.value = false
	armedAdv.value = false
	clearTimeout(advTimer)
}
// Double confirmation: level 4 notice of the workshop pages (mandatory
// checkbox) or, without it, two taps in a row.
async function unlockAdvanced() {
	const confirmLevel4 = window.__workshop && window.__workshop.confirmLevel4
	if (confirmLevel4) {
		const ok = await confirmLevel4({
			title: i18n.t('plugins.WorkshopService.servicePage.change_the_duet_channels_by_hand'),
			notices: [
				...(hasJog.value ? [i18n.t('plugins.WorkshopService.servicePage.it_can_leave_the_jog_s')] : []),
				i18n.t('plugins.WorkshopService.servicePage.it_can_mix_the_service_s'),
				i18n.t('plugins.WorkshopService.servicePage.it_can_lose_the_g90_that'),
				i18n.t('plugins.WorkshopService.servicePage.the_automatic_channel_aux2_if_free')
			],
			understood: i18n.t('plugins.WorkshopService.servicePage.understood_i_know_what_i_am'),
			button: i18n.t('plugins.WorkshopService.servicePage.unlock')
		})
		if (ok) advanced.value = true
		return
	}
	if (!armedAdv.value) {
		armedAdv.value = true
		clearTimeout(advTimer)
		advTimer = setTimeout(() => { armedAdv.value = false }, 4000)
		return
	}
	blockAdvanced()
	advanced.value = true
}
async function setChannel(letter, v) {
	if (!advanced.value) return // without unlock nothing is sent (the service rejects it too)
	savingChannel.value = true
	try {
		// the level 4 unlock of this page is the confirmation the service asks for
		await send('comms.set', { [letter === 'J' ? 'jog_channel' : 'plugin_channel']: v }, { confirm: true })
	} finally {
		savingChannel.value = false
		blockAdvanced()
		advancedOpen.value = false
	}
}
function dangerous(name) {
	const o = (apiOps.value || []).find(x => x.op === name)
	return !!o && DANGEROUS_KINDS.includes(o.kind)
}
function test(h) {
	return tests.value[h.name] || { code: h.usage || '{}', sending: false, armed: false, result: null }
}
function setTest(h, patch) {
	tests.value[h.name] = Object.assign({}, test(h), patch)
}
// the example arguments of the operation go to the test field
function useExample(h) {
	setTest(h, { code: h.usage || '{}', armed: false })
}
async function sendTest(h) {
	const p = test(h)
	const code = (p.code || '').trim()
	if (!code || p.sending) return
	if (dangerous(h.name) && !p.armed) {
		setTest(h, { armed: true })
		clearTimeout(armTimer)
		armTimer = setTimeout(() => setTest(h, { armed: false }), 3000)
		return
	}
	clearTimeout(armTimer)
	setTest(h, { sending: true, armed: false })
	const t0 = performance.now()
	let ok = true, text = ''
	try {
		const args = code ? JSON.parse(code) : {}
		const r = await api(h.name, args)
		text = typeof r === 'string' ? r : JSON.stringify(r, null, 1)
	} catch (e) {
		ok = false
		text = String((e && e.message) || e)
	}
	setTest(h, {
		sending: false,
		result: { ok, text: text, ms: Math.round(performance.now() - t0), hour: new Date().toTimeString().slice(0, 8) }
	})
}
function catOf(name) {
	return CATS.find(c => c.re.test(name || '')) || CATS[CATS.length - 1]
}
// history rows: "op {args}"
function cmdName(c) {
	return String(c.code || '').split(' ')[0]
}
function rowCat(f) {
	return cmdCat({ code: f.code })
}
function cmdCat(c) {
	return catOf(cmdName(c))
}
async function copy(text, id) {
	const ok = await copyText(text || '')
	copied.value = ok ? id : null
	if (ok) {
		setTimeout(() => { if (copied.value === id) { copied.value = null } }, 1500)
	}
}
// Scroll to an anchor once the page has rendered it (cards load after the first paint). The cards live in
// sections of the side bar and only exist while their section is shown: the section is chosen first.
function goWhenReady(id) {
	const target = ANCHOR_SECTION[id]
	if (target && section.value !== target) {
		section.value = target
	}
	let n = 0
	const t = setInterval(() => {
		const el = document.getElementById(id)
		if (el || ++n > 20) {
			clearInterval(t)
			if (el) {
				el.scrollIntoView({ behavior: 'smooth', block: 'start' })
			}
		}
	}, 250)
}
function goAnchor(id) {
	goWhenReady(id)
}
// everything a person may type to find a process: its name, what it does, its category and the explanations of its detail
function textSearch(p) {
	const D = 'plugins.WorkshopService.procDocs.'
	const docs = ['what', 'why', 'fails', 'uses', 'where'].map(k => (i18n.te(D + p.id + '_' + k) ? i18n.t(D + p.id + '_' + k) : '')).join(' ')
	return [p.title, p.description, p.id, p.info.cat, docs].join(' ')
}
function groupOpen(g) {
	if (procOpen.value[g.cat] !== undefined) return procOpen.value[g.cat]
	// by itself: open with a problem, or while looking for something
	return g.problems > 0 || !!procSearch.value || !!procCat.value || procFilter.value === 'problems'
}
// the user's choice of when a process runs (config "modules" of the service)
async function changeMode(id, mode) {
	modeError.value[id] = ''
	try {
		await api('modules.set', { process: id, mode: mode })
	} catch (e) {
		modeError.value[id] = i18n.t('plugins.WorkshopService.servicePage.mode_failed', { msg: String((e && e.message) || e) })
	}
}
function stateProcess(p) {
	if (p.idle) {
		return { level: 0, color: 'grey', icon: 'mdi-sleep', text: i18n.t('plugins.WorkshopService.servicePage.resting'), detail: i18n.t('plugins.WorkshopService.servicePage.resting_detail') }
	}
	if (!p.live) {
		return { level: 2, color: 'error', icon: 'mdi-close-circle', text: i18n.t('plugins.WorkshopService.servicePage.stopped'), detail: i18n.t('plugins.WorkshopService.servicePage.crashed_and_is_restarting') }
	}
	if (p.age_ok_s == null) {
		return { level: 1, color: 'warning', icon: 'mdi-timer-sand', text: i18n.t('plugins.WorkshopService.common.no_data_2'), detail: i18n.t('plugins.WorkshopService.servicePage.hasn_t_completed_a_loop_yet') }
	}
	if (p.age_ok_s > p.expected_s * 3) {
		return { level: 1, color: 'warning', icon: 'mdi-clock-alert', text: i18n.t('plugins.WorkshopService.servicePage.late'), detail: i18n.t('plugins.WorkshopService.servicePage.last_heartbeat_t', { t: age(p.age_ok_s) }) }
	}
	if (p.errorRecent && p.age_error_s < p.age_ok_s + 5) {
		return { level: 1, color: 'warning', icon: 'mdi-alert', text: i18n.t('plugins.WorkshopService.servicePage.with_errors'), detail: p.error }
	}
	return { level: 0, color: 'success', icon: 'mdi-check-circle', text: i18n.t('plugins.WorkshopService.servicePage.up_to_date'), detail: i18n.t('plugins.WorkshopService.servicePage.last_heartbeat_t', { t: age(p.age_ok_s) }) }
}
function sec(v) {
	return v < 1 ? Math.round(v * 1000) + ' ms' : (v < 60 ? v.toFixed(1) + ' s' : Math.round(v / 60) + ' min')
}
function duration(s) {
	if (s == null) return ''
	if (s < 60) return s + ' s'
	if (s < 3600) return Math.round(s / 60) + ' min'
	if (s < 86400) return Math.floor(s / 3600) + ' h ' + Math.round((s % 3600) / 60) + ' min'
	return Math.floor(s / 86400) + ' d ' + Math.round((s % 86400) / 3600) + ' h'
}
function age(s) {
	s = Math.max(0, Math.round(s))
	if (s < 3) return i18n.t('plugins.WorkshopService.servicePage.now')
	if (s < 60) return i18n.t('plugins.WorkshopService.servicePage.ago_t', { t: s + ' s' })
	if (s < 3600) return i18n.t('plugins.WorkshopService.servicePage.ago_t', { t: Math.round(s / 60) + ' min' })
	if (s < 86400) return i18n.t('plugins.WorkshopService.servicePage.ago_t', { t: Math.floor(s / 3600) + ' h ' + Math.round((s % 3600) / 60) + ' min' })
	return i18n.t('plugins.WorkshopService.servicePage.ago_n_days', { n: Math.round(s / 86400) })
}
// Read-only (2026-10-10, "an elegant way to see that it is read-only")
function read(h) {
	if (h.reading === 'always') {
		return { text: i18n.t('plugins.WorkshopService.common.read_only'), icon: 'mdi-eye-outline', color: 'teal', hex: '#26A69A', title: i18n.t('plugins.WorkshopService.servicePage.only_reads_changes_nothing_on_the') }
	}
	if (h.reading === 'according') {
		const a = h.reading_actions || {}
		const acc = (a.actions || []).map(v => a.letter + '"' + v + '"').join(', ')
		return { text: i18n.t('plugins.WorkshopService.servicePage.reads_or_changes'), icon: 'mdi-eye-settings-outline', color: 'blue', hex: '#42A5F5', title: i18n.t('plugins.WorkshopService.servicePage.reads_only_x_else_changes', { x: acc ? i18n.t('plugins.WorkshopService.servicePage.with_x', { x: acc }) + (a.actions.length ? i18n.t('plugins.WorkshopService.servicePage.or_without_x', { x: a.letter }) : '') : i18n.t('plugins.WorkshopService.servicePage.without_x', { x: a.letter }) }) }
	}
	return { text: i18n.t('plugins.WorkshopService.common.changes_something'), icon: 'mdi-pencil-outline', color: 'orange-darken-2', hex: '#F57C00', title: i18n.t('plugins.WorkshopService.servicePage.changes_something_settings_sd_files_the') }
}
function summary(d) {
	d = d || ''
	return d.length > 90 ? d.slice(0, 90) + '...' : d
}
</script>

<style>
/* Everything that is the look of the page (bar, menu, cards, buttons, chips, notes) is the design family (family.css, imported by theme.css).
   Here only what is the CONTENT of this page. */
.svx-page .svx-ico { color: var(--wf-icon); }
</style>

<style scoped>
.svc-mov-opts { display: flex; flex-wrap: wrap; gap: 8px; }
.svc-mov-opt { flex: 1 1 260px; cursor: pointer; }
.svc-mov-sel { border-color: rgb(var(--v-theme-primary)) !important; }
.svc-detail { margin-top: 2px; opacity: 0.8; }
.svc-metricas span { margin-left: 10px; white-space: nowrap; }
/* phone: the long lines wrap instead of pushing the page sideways (Processes: the readings per minute; API: the header of each operation and its example) */
@media (max-width: 599px) {
	.svc-metricas span { white-space: normal; overflow-wrap: anywhere; display: inline-block; margin-left: 0; margin-right: 10px; }
	.svc-metricas { margin-left: 0 !important; }
	.svx-panels .v-expansion-panel-title > .d-flex { flex-wrap: wrap; min-width: 0; max-width: 100%; }
	.svx-panels .v-expansion-panel-title code { overflow-wrap: anywhere; }
	.svx-panels .v-expansion-panel-title .text-caption { flex: 1 1 100%; margin-left: 0 !important; overflow-wrap: anywhere; }
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
