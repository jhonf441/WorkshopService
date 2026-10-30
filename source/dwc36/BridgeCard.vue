<template>
	<v-card class="mb-3 pc">
		<!-- Encabezado -->
		<v-card-title class="pc-head">
			<v-icon class="mr-3 svx-ico">mdi-lan-connect</v-icon>
			<div>
				<div>{{ $t('plugins.WorkshopService.bridgeCard.g_code_bridge_telnet') }}</div>
				<div class="text-caption grey--text pc-sub">
					{{ $t('plugins.WorkshopService.bridgeCard.cutting_programs_terminals_scripts_or') }}
					<code>{{ host }}:{{ (e && e.port) || 23 }}</code>
				</div>
			</div>
			<v-spacer />
			<div class="d-flex flex-wrap align-center pc-chips">
				<v-chip v-if="e && sec" small label outlined :color="sec.password ? 'success' : 'blue-grey'" class="mr-1" :title="(sec.password ? $t('plugins.WorkshopService.bridgeCard.untrusted_connections_need_bridge_key') : $t('plugins.WorkshopService.bridgeCard.anyone_on_the_network_can_send')) + ' ' + $t('plugins.WorkshopService.bridgeCard.tap_to_go_to_the_key')" @click="goAKey()">
					<v-icon left small>{{ sec.password ? 'mdi-shield-lock' : 'mdi-shield-outline' }}</v-icon>{{ sec.local_only ? $t('plugins.WorkshopService.bridgeCard.local_network') : $t('plugins.WorkshopService.bridgeCard.chosen_ips') }} · {{ sec.password ? $t('plugins.WorkshopService.bridgeCard.with_key') : $t('plugins.WorkshopService.bridgeCard.no_key') }}
				</v-chip>
				<v-chip v-if="e" small label outlined class="mr-1" :title="t('version')">v{{ e.version }} · {{ $t('plugins.WorkshopService.bridgeCard.up_for_t', { t: dur(e.uptime_s) }) }}</v-chip>
				<v-chip small label dark :color="stateChip.color" :title="t('state')">{{ stateChip.text }}</v-chip>
				<v-btn v-if="e" icon small class="ml-1" :color="armed === 'restart' ? 'warning' : ''" :disabled="!!bridgeInUse" :loading="actionInProgress === 'restart'" :title="bridgeInUse || (armed === 'restart' ? $t('plugins.WorkshopService.bridgeCard.restart_bridge_confirm') : $t('plugins.WorkshopService.bridgeCard.restart_bridge'))" @click="restartBridge()">
					<v-icon>mdi-restart</v-icon>
				</v-btn>
				<v-btn icon small class="ml-1" :color="help ? 'primary' : ''" :title="help ? $t('plugins.WorkshopService.bridgeCard.hide_the_explanations') : $t('plugins.WorkshopService.bridgeCard.show_what_each_button_does')" @click="help = !help">
					<v-icon>{{ help ? 'mdi-help-circle' : 'mdi-help-circle-outline' }}</v-icon>
				</v-btn>
			</div>
		</v-card-title>

		<v-card-text>
			<!-- The unit of THIS Pi: start / stop it here (it keeps running after a power cut because it is enabled) -->
			<div v-if="unit && unit.installed" class="d-flex align-center flex-wrap mb-3 pc-unidad">
				<v-switch :input-value="unit.active" :disabled="unit.can_control === false || unitBusy" :loading="unitBusy" dense hide-details class="mt-0 mr-3" :label="$t('plugins.WorkshopService.bridgeCard.unit_switch')" @change="changeUnit" />
				<span class="text-caption grey--text">{{ unit.active ? (unit.enabled ? $t('plugins.WorkshopService.bridgeCard.unit_on_enabled') : $t('plugins.WorkshopService.bridgeCard.unit_on_not_enabled')) : $t('plugins.WorkshopService.bridgeCard.unit_off') }}</span>
			</div>
			<v-alert v-if="unit && unit.installed && unit.can_control === false" dense text type="info" class="mb-3">
				{{ $t('plugins.WorkshopService.bridgeCard.unit_no_permission') }}
				<div class="mt-1"><code>sudo ./install.sh control</code></div>
			</v-alert>
			<v-alert v-if="unitMsg" dense text type="warning" class="mb-3">{{ unitMsg }}</v-alert>

			<template v-if="unit && unit.installed && !unit.active">
				<div class="text-body-2 grey--text">{{ $t('plugins.WorkshopService.bridgeCard.unit_stopped_text') }}</div>
			</template>

			<template v-else-if="noInstalled">
				<v-alert dense text type="info" class="mb-0">
					{{ $t('plugins.WorkshopService.bridgeCard.new_bridge_not_installed_yet') }} <code>bridge</code> {{ $t('plugins.WorkshopService.bridgeCard.of_the_repository') }}
					<div class="mt-1"><code>sudo ./install.sh</code></div>
					<div class="text-caption mt-1">{{ $t('plugins.WorkshopService.bridgeCard.to_go_back_to_the_previous') }} <code>sudo ./install.sh rollback</code></div>
				</v-alert>
			</template>

			<template v-else-if="e && !e.schema">
				<v-alert dense text type="warning" class="mb-0">
					{{ $t('plugins.WorkshopService.bridgeCard.bridge_running_is_version_v', { v: e.version }) }} <code>bridge</code> {{ $t('plugins.WorkshopService.bridgeCard.of_the_repository') }}
					<div class="mt-1"><code>sudo ./install.sh</code></div>
				</v-alert>
			</template>

			<template v-else-if="e">
				<v-alert v-if="help" dense text color="primary" icon="mdi-help-circle" class="mb-3 text-body-2">
					{{ $t('plugins.WorkshopService.bridgeCard.help_mode_under_each_group_of') }} <b>{{ $t('plugins.WorkshopService.bridgeCard.key_word') }}</b> {{ $t('plugins.WorkshopService.bridgeCard.is_in_the_tab') }} <a @click="goAKey()">{{ $t('plugins.WorkshopService.bridgeCard.security_and_key') }}</a>. {{ $t('plugins.WorkshopService.bridgeCard.tap') }} <v-icon small>mdi-help-circle</v-icon> {{ $t('plugins.WorkshopService.bridgeCard.at_the_top_right_to_hide') }}
				</v-alert>
				<v-alert v-if="e.error" dense text type="error" class="mb-3">{{ e.error }}</v-alert>

				<!-- Control + numeros -->
				<div class="pc-top">
					<div class="pc-control" :class="e.owner ? 'pc-control-on' : ''">
						<div class="text-overline grey--text" :title="t('control')">{{ $t('plugins.WorkshopService.bridgeCard.machine_control') }}</div>
						<div v-if="help" class="pc-help mb-1">{{ t('control') }}</div>
						<template v-if="!e.exclusive">
							<div class="pc-control-name"><v-icon color="info">mdi-account-multiple</v-icon> {{ $t('plugins.WorkshopService.bridgeCard.shared') }}</div>
							<div class="text-caption grey--text">{{ $t('plugins.WorkshopService.bridgeCard.non_exclusive_mode_every_connection_can') }}</div>
						</template>
						<template v-else-if="e.owner">
							<div class="pc-control-name"><v-icon color="success">mdi-steering</v-icon> {{ e.owner }}</div>
							<div class="text-caption grey--text">
								{{ ipOf(e.owner_id) }} · {{ $t('plugins.WorkshopService.bridgeCard.has_had_it_for_t_others_only_query', { t: dur(e.owner_since_s) }) }}
							</div>
							<v-btn x-small outlined class="mt-2" :title="t('release')" :loading="actionInProgress === 'release'" @click="action({ action: 'release' }, 'release')">
								<v-icon x-small left>mdi-hand-back-left</v-icon>{{ $t('plugins.WorkshopService.bridgeCard.release_control') }}
							</v-btn>
							<div v-if="help" class="pc-help"><b>{{ $t('plugins.WorkshopService.bridgeCard.release_control_2') }}</b> {{ t('release') }}</div>
						</template>
						<template v-else>
							<div class="pc-control-name"><v-icon color="grey">mdi-steering-off</v-icon> {{ $t('plugins.WorkshopService.bridgeCard.free') }}</div>
							<div class="text-caption grey--text">{{ $t('plugins.WorkshopService.bridgeCard.the_first_connection_that_sends_a') }}</div>
						</template>
					</div>
					<div class="pc-tiles">
						<div class="pc-tile"><div class="pc-l" :title="t('connected')">{{ $t('plugins.WorkshopService.bridgeCard.connected_title') }}</div><div class="pc-v">{{ e.clients.length }}<small v-if="sec"> / {{ sec.max_connections }}</small></div><div class="pc-s">{{ $t('plugins.WorkshopService.bridgeCard.n_since_it_started', { n: e.totals.connections }) }}</div></div>
						<div class="pc-tile"><div class="pc-l" :title="t('orders')">{{ $t('plugins.WorkshopService.bridgeCard.commands_title') }}</div><div class="pc-v">{{ num(e.totals.orders) }}</div><div class="pc-s">{{ $t('plugins.WorkshopService.bridgeCard.n_queries', { n: num(e.totals.queries) }) }}</div></div>
						<div class="pc-tile" :class="e.totals.rejects ? 'pc-notice' : ''"><div class="pc-l" :title="t('rejected')">{{ $t('plugins.WorkshopService.bridgeCard.rejected_title') }}</div><div class="pc-v">{{ num(e.totals.rejects) }}</div><div class="pc-s">{{ $t('plugins.WorkshopService.bridgeCard.n_connections_m_keys', { n: e.totals.rejected_connections || 0, m: e.totals.wrong_passwords || 0 }) }}</div></div>
						<div class="pc-tile" :class="(e.duet_ms_max || 0) > 2000 ? 'pc-notice' : ''"><div class="pc-l" :title="t('response')">{{ $t('plugins.WorkshopService.bridgeCard.machine_response') }}</div><div class="pc-v">{{ e.duet_ms_avg != null ? Math.round(e.duet_ms_avg) : '--' }}<small> ms</small></div><div class="pc-s">{{ $t('plugins.WorkshopService.bridgeCard.max_n_ms_5_min', { n: Math.round(e.duet_ms_max || 0) }) }}</div></div>
						<div class="pc-tile"><div class="pc-l" :title="t('traffic')">{{ $t('plugins.WorkshopService.bridgeCard.traffic') }}</div><div class="pc-v pc-v-small">{{ bytes(e.totals.bytes_rx) }} ↓ {{ bytes(e.totals.bytes_tx) }} ↑</div><div class="pc-s">{{ $t('plugins.WorkshopService.bridgeCard.n_lines', { n: num(e.totals.lines) }) }}</div></div>
						<div class="pc-tile" :class="e.totals.duet_errors ? 'pc-notice' : ''"><div class="pc-l" :title="t('duet_errors')">{{ $t('plugins.WorkshopService.bridgeCard.errors_title') }}</div><div class="pc-v">{{ e.totals.duet_errors }}</div><div class="pc-s">{{ $t('plugins.WorkshopService.bridgeCard.n_kicked', { n: e.totals.kicked || 0 }) }}</div></div>
					</div>
				</div>
				<div v-if="e.activity" class="text-caption mt-2 pc-activity">
					<v-chip x-small label outlined :color="e.activity.live_job && e.activity.live_job.active ? 'warning' : 'grey'" :title="t('live_job')">
						{{ $t('plugins.WorkshopService.bridgeCard.live_job') }}: {{ e.activity.live_job && e.activity.live_job.active ? $t('plugins.WorkshopService.bridgeCard.active') + (e.activity.live_job.name ? ' (' + e.activity.live_job.name + ')' : '') : $t('plugins.WorkshopService.bridgeCard.no') }}
					</v-chip>
					<span class="ml-2" :title="t('last_order')">{{ $t('plugins.WorkshopService.bridgeCard.last_order_to_the_machine') }} {{ e.activity.last_order_at ? $t('plugins.WorkshopService.bridgeCard.t_ago', { t: dur(Math.max(0, Math.round((Date.now() / 1000) - e.activity.last_order_at))) }) : $t('plugins.WorkshopService.bridgeCard.none_since_it_started') }}<template v-if="e.activity.pending_orders"> · {{ $t('plugins.WorkshopService.bridgeCard.n_waiting_for_the_machine', { n: e.activity.pending_orders }) }}</template></span>
				</div>
				<div v-if="help" class="pc-help mt-2">
					<b>{{ $t('plugins.WorkshopService.bridgeCard.connected_title') }}</b>: {{ t('connected') }} <b>{{ $t('plugins.WorkshopService.bridgeCard.commands_title') }}</b>: {{ t('orders') }} <b>{{ $t('plugins.WorkshopService.bridgeCard.rejected_title') }}</b>: {{ t('rejected') }}
					<b>{{ $t('plugins.WorkshopService.bridgeCard.machine_response') }}</b>: {{ t('response') }} <b>{{ $t('plugins.WorkshopService.bridgeCard.errors_title') }}</b>: {{ t('duet_errors') }}
				</div>

				<!-- Grafico ultima hora -->
				<div v-if="e.history" class="pc-chart mt-3">
					<div class="d-flex align-center flex-wrap text-caption grey--text mb-1">
						{{ $t('plugins.WorkshopService.bridgeCard.last_hour_per_minute') }}
						<span class="pc-law ml-3"><i style="background:#7E57C2"></i>{{ $t('plugins.WorkshopService.bridgeCard.commands_lc') }}</span>
						<span class="pc-law"><i style="background:#78909C"></i>{{ $t('plugins.WorkshopService.bridgeCard.queries_lc') }}</span>
						<span class="pc-law"><i style="background:#E53935"></i>{{ $t('plugins.WorkshopService.bridgeCard.rejections_lc') }}</span>
						<v-spacer />
						<span>{{ summaryHour }}</span>
					</div>
					<svg :viewBox="`0 0 600 ${GH}`" preserveAspectRatio="none" class="pc-svg">
						<g v-for="(b, i) in bars" :key="i">
							<title>{{ b.title }}</title>
							<rect :x="i * 10 + 1" :y="GH - b.hc" width="8" :height="b.hc" fill="#78909C" />
							<rect :x="i * 10 + 1" :y="GH - b.hc - b.ho" width="8" :height="b.ho" fill="#7E57C2" />
							<rect v-if="b.r" :x="i * 10 + 1" y="0" width="8" height="3" fill="#E53935" />
							<rect :x="i * 10" y="0" width="10" :height="GH" fill="transparent" />
						</g>
					</svg>
					<div class="d-flex text-caption grey--text"><span>{{ $t('plugins.WorkshopService.bridgeCard.t_ago', { t: '60 min' }) }}</span><v-spacer /><span>{{ $t('plugins.WorkshopService.bridgeCard.now') }}</span></div>
				</div>

				<!-- Pestanas -->
				<v-tabs v-model="tab" class="mt-3" show-arrows height="40">
					<v-tab :title="t('tab_connections')"><v-icon small left>mdi-lan</v-icon>{{ $t('plugins.WorkshopService.bridgeCard.connections_n', { n: e.clients.length }) }}</v-tab>
					<v-tab :title="t('tab_activity')"><v-icon small left>mdi-history</v-icon>{{ $t('plugins.WorkshopService.common.activity') }}</v-tab>
					<v-tab :title="t('tab_commands')"><v-icon small left>mdi-console</v-icon>{{ $t('plugins.WorkshopService.bridgeCard.commands_tab') }}</v-tab>
					<v-tab :title="t('tab_safety')"><v-icon small left>mdi-shield-lock</v-icon>{{ $t('plugins.WorkshopService.bridgeCard.security_and_key') }}</v-tab>
					<v-tab :title="t('tab_config')" @click="openConfig()"><v-icon small left>mdi-cog</v-icon>{{ $t('plugins.WorkshopService.bridgeCard.configuration') }}</v-tab>
				</v-tabs>
				<div v-if="help" class="pc-help mt-1">{{ t(['tab_connections', 'tab_activity', 'tab_commands', 'tab_safety', 'tab_config'][tab] || 'tab_connections') }}</div>

				<v-tabs-items v-model="tab" class="pc-tabs-items">
					<!-- CONEXIONES -->
					<v-tab-item>
						<div v-if="!e.clients.length" class="pc-empty">
							<v-icon large color="grey">mdi-lan-disconnect</v-icon>
							<div>{{ $t('plugins.WorkshopService.bridgeCard.nobody_connected') }}</div>
							<div class="text-caption grey--text">{{ $t('plugins.WorkshopService.bridgeCard.in_the_program_duet_device_over') }} <code>{{ host }}</code>, {{ $t('plugins.WorkshopService.bridgeCard.port_lc') }} <code>{{ e.port }}</code>.</div>
						</div>
						<div v-for="cl in e.clients" :key="cl.id" class="pc-cli" :class="'pc-role-' + (cl.control ? 'control' : (cl.role || 'listener'))">
							<div class="d-flex align-center flex-wrap" style="gap:8px">
								<v-icon class="mr-3 svx-ico">{{ role(cl).icon }}</v-icon>
								<div class="pc-cli-name">
									<template v-if="editing === cl.id">
										<div class="d-flex align-center flex-wrap" style="gap:6px">
											<v-text-field v-model.trim="nameNew" dense outlined hide-details autofocus maxlength="40" style="max-width:220px" @keyup.enter="rename(cl)" @keyup.esc="editing = null" />
											<v-checkbox v-model="rememberName" dense hide-details class="mt-0" :label="$t('plugins.WorkshopService.bridgeCard.remember_for_ip', { ip: cl.ip })" :title="t('remember')" />
											<v-btn small color="primary" :loading="actionInProgress === 'ren-' + cl.id" @click="rename(cl)">{{ $t('plugins.WorkshopService.bridgeCard.save') }}</v-btn>
											<v-btn small text @click="editing = null">{{ $t('plugins.WorkshopService.bridgeCard.cancel') }}</v-btn>
										</div>
									</template>
									<template v-else>
										<span class="font-weight-medium">{{ cl.name }}</span>
										<v-btn icon x-small :title="t('rename')" @click="beginRename(cl)"><v-icon x-small>mdi-pencil</v-icon></v-btn>
										<div class="text-caption grey--text">{{ cl.id }} · {{ $t('plugins.WorkshopService.bridgeCard.connected_for_t', { t: dur(cl.connected_s) }) }} · {{ cl.idle_s > 5 ? $t('plugins.WorkshopService.bridgeCard.idle_for_t', { t: dur(cl.idle_s) }) : $t('plugins.WorkshopService.bridgeCard.active_now') }}</div>
									</template>
								</div>
								<v-chip small label dark :color="role(cl).color" :title="t('role')">{{ role(cl).text }}</v-chip>
								<v-chip v-if="cl.trusted" small label outlined color="success" :title="$t('plugins.WorkshopService.bridgeCard.sends_commands_without_a_key')"><v-icon left x-small>mdi-check-decagram</v-icon>{{ $t('plugins.WorkshopService.bridgeCard.trusted') }}</v-chip>
								<v-chip v-if="cl.name_saved" x-small label outlined :title="$t('plugins.WorkshopService.bridgeCard.the_name_is_remembered_for_this')">{{ $t('plugins.WorkshopService.bridgeCard.saved_name') }}</v-chip>
								<v-spacer />
								<div class="d-flex flex-wrap" style="gap:4px">
									<v-btn v-if="!cl.control && e.exclusive" x-small outlined color="success" :title="t('give_control')" :loading="actionInProgress === 'ctl-' + cl.id" @click="action({ action: 'give_control', client: cl.id }, 'ctl-' + cl.id)">
										<v-icon x-small left>mdi-steering</v-icon>{{ $t('plugins.WorkshopService.bridgeCard.give_it_control') }}
									</v-btn>
									<v-btn v-if="cl.control" x-small outlined :title="t('release')" :loading="actionInProgress === 'release'" @click="action({ action: 'release' }, 'release')">
										<v-icon x-small left>mdi-hand-back-left</v-icon>{{ $t('plugins.WorkshopService.common.release') }}
									</v-btn>
									<v-btn x-small outlined :color="cl.trusted ? 'grey' : 'success'" :title="t(cl.trusted ? 'remove_trust' : 'trust')" :loading="actionInProgress === 'conf-' + cl.ip" @click="action({ action: 'trust', ip: cl.ip, yes: !cl.trusted }, 'conf-' + cl.ip)">
										<v-icon x-small left>{{ cl.trusted ? 'mdi-close-octagon-outline' : 'mdi-check-decagram' }}</v-icon>{{ cl.trusted ? $t('plugins.WorkshopService.bridgeCard.remove_trust') : $t('plugins.WorkshopService.bridgeCard.trust_this_ip') }}
									</v-btn>
									<v-btn x-small :outlined="armed !== 'exp-' + cl.id" color="error" :title="t('eject')" :dark="armed === 'exp-' + cl.id" @click="eject(cl)">
										<v-icon x-small left>mdi-lan-disconnect</v-icon>{{ armed === 'exp-' + cl.id ? $t('plugins.WorkshopService.bridgeCard.sure_tap_again') : $t('plugins.WorkshopService.bridgeCard.kick') }}
									</v-btn>
									<v-btn x-small :outlined="armed !== 'blq-' + cl.ip" color="red darken-2" :dark="armed === 'blq-' + cl.ip" :title="t('block')" :loading="actionInProgress === 'blq-' + cl.ip" @click="block(cl)">
										<v-icon x-small left>mdi-cancel</v-icon>{{ armed === 'blq-' + cl.ip ? $t('plugins.WorkshopService.bridgeCard.block_tap_again') : $t('plugins.WorkshopService.bridgeCard.block') }}
									</v-btn>
								</div>
							</div>
							<div v-if="help" class="pc-help">
								<span v-if="!cl.control && e.exclusive"><b>{{ $t('plugins.WorkshopService.bridgeCard.give_it_control_2') }}</b> {{ t('give_control') }}<br></span>
								<span v-if="cl.control"><b>{{ $t('plugins.WorkshopService.common.release') }}:</b> {{ t('release') }}<br></span>
								<b>{{ cl.trusted ? $t('plugins.WorkshopService.bridgeCard.remove_trust') : $t('plugins.WorkshopService.bridgeCard.trust_this_ip') }}:</b> {{ t(cl.trusted ? 'remove_trust' : 'trust') }}<br>
								<b>{{ $t('plugins.WorkshopService.bridgeCard.kick') }}:</b> {{ t('eject') }}<br>
								<b>{{ $t('plugins.WorkshopService.bridgeCard.block') }}:</b> {{ t('block') }}<br>
								<b>{{ $t('plugins.WorkshopService.bridgeCard.pencil') }}:</b> {{ t('rename') }}<br>
								<b>{{ role(cl).text }}:</b> {{ t('role') }}
							</div>
							<div class="pc-cli-stats">
								<span><b>{{ num(cl.orders) }}</b> {{ $t('plugins.WorkshopService.bridgeCard.commands_lc') }}</span>
								<span><b>{{ num(cl.queries) }}</b> {{ $t('plugins.WorkshopService.bridgeCard.queries_lc') }}</span>
								<span :class="cl.rejects ? 'warning--text' : ''"><b>{{ cl.rejects }}</b> {{ $t('plugins.WorkshopService.bridgeCard.rejected_lc') }}</span>
								<span :title="t('cache')"><b>{{ cl.cache_hits || 0 }}</b> {{ $t('plugins.WorkshopService.bridgeCard.from_cache') }} <b>{{ cl.coalesced || 0 }}</b> {{ $t('plugins.WorkshopService.bridgeCard.shared_2') }}</span>
								<span>{{ bytes(cl.bytes_rx) }} ↓ · {{ bytes(cl.bytes_tx) }} ↑</span>
								<span v-if="cl.last" class="pc-last">{{ $t('plugins.WorkshopService.bridgeCard.last') }} <code>{{ cl.last }}</code><template v-if="cl.last_age_s != null"> {{ $t('plugins.WorkshopService.bridgeCard.t_ago', { t: dur(cl.last_age_s) }) }}</template></span>
							</div>
							<div v-if="help && sec && !sec.password" class="text-caption warning--text mt-1">
								{{ $t('plugins.WorkshopService.bridgeCard.no_key_is_enabled_now_trusting') }} <b>{{ $t('plugins.WorkshopService.bridgeCard.block') }}</b>.
							</div>
							<div v-if="cl.role === 'no_password' && !cl.control" class="text-caption warning--text mt-1">
								{{ $t('plugins.WorkshopService.bridgeCard.this_connection_can_only_query_until') }} <code>BRIDGE KEY &lt;password&gt;</code> {{ $t('plugins.WorkshopService.bridgeCard.or_mark_its_ip_as_trusted') }}
							</div>
						</div>
						<div class="text-caption grey--text mt-2">
							<b>{{ $t('plugins.WorkshopService.bridgeCard.has_control') }}</b>{{ $t('plugins.WorkshopService.bridgeCard.sends_commands_move_cut_macros') }} <b>{{ $t('plugins.WorkshopService.bridgeCard.listening') }}</b>{{ $t('plugins.WorkshopService.bridgeCard.connected_queries_only_position_temperature') }}
						</div>
					</v-tab-item>

					<!-- ACTIVIDAD -->
					<v-tab-item>
						<div class="d-flex flex-wrap my-2" style="gap:6px">
							<v-chip v-for="t in KINDS" :key="t.id" small :outlined="filterEv !== t.id" :color="t.color" :dark="filterEv === t.id" :title="$t('plugins.WorkshopService.bridgeCard.show_only_x_tap_again', { x: t.name.toLowerCase() })" @click="filterEv = filterEv === t.id ? null : t.id">
								<v-icon left small>{{ t.icon }}</v-icon>{{ t.name }} ({{ (e.events || []).filter(x => (x.type || 'info') === t.id).length }})
							</v-chip>
						</div>
						<div class="pc-events">
							<div v-for="(ev, i) in eventsFiltered" :key="i" class="pc-ev">
								<v-icon x-small :color="kind(ev).color">{{ kind(ev).icon }}</v-icon>
								<span class="grey--text">{{ ev.time }}</span> {{ eventText(ev) }}
							</div>
							<div v-if="!eventsFiltered.length" class="grey--text">{{ $t('plugins.WorkshopService.bridgeCard.no_events') }}</div>
						</div>
					</v-tab-item>

					<!-- COMANDOS -->
					<v-tab-item>
						<!-- what to paste in the sending program (Start / End G-code of its device profile) -->
						<v-alert dense text type="info" class="my-2">
							<div class="font-weight-medium mb-1">{{ $t('plugins.WorkshopService.bridgeCard.paste_in_program_title') }}</div>
							<div class="text-caption mb-2">{{ $t('plugins.WorkshopService.bridgeCard.paste_in_program_help') }}</div>
							<div v-for="g in gcodesProgram" :key="g.k" class="d-flex align-center flex-wrap mb-1" style="gap:6px">
								<span class="text-caption" style="min-width:92px">{{ g.k }}</span>
								<code class="pc-cmd-code" :title="$t('plugins.WorkshopService.bridgeCard.tap_to_copy')" @click="copy(g.v)">{{ g.v }}</code>
								<v-btn icon x-small :title="$t('plugins.WorkshopService.common.copy')" @click="copy(g.v)">
									<v-icon x-small>{{ copied === g.v ? 'mdi-check' : 'mdi-content-copy' }}</v-icon>
								</v-btn>
							</div>
							<div class="text-caption mt-1">{{ $t('plugins.WorkshopService.bridgeCard.paste_in_program_note') }}</div>
						</v-alert>
						<div class="text-caption grey--text my-2">
							{{ $t('plugins.WorkshopService.bridgeCard.they_are_typed_in_the_same') }} <b>{{ e.port }}</b>{{ $t('plugins.WorkshopService.bridgeCard.and_do_not_reach_the_duet') }}
							{{ $t('plugins.WorkshopService.bridgeCard.tap_a_command_to_copy_it') }}
						</div>
						<div v-for="c in commands" :key="c.cmd" class="pc-cmd">
							<div class="d-flex align-center flex-wrap" style="gap:6px">
								<code class="pc-cmd-code" :title="$t('plugins.WorkshopService.bridgeCard.tap_to_copy')" @click="copy(c.cmd)">{{ c.cmd }}</code>
								<v-btn icon x-small :title="$t('plugins.WorkshopService.common.copy') + ' ' + c.cmd" @click="copy(c.cmd)">
									<v-icon x-small>{{ copied === c.cmd ? 'mdi-check' : 'mdi-content-copy' }}</v-icon>
								</v-btn>
								<span class="text-caption">{{ c.desc }}</span>
								<v-spacer />
								<span v-if="!c.test" class="text-caption grey--text" :title="c.because">{{ $t('plugins.WorkshopService.bridgeCard.only_from_your_program') }}</span>
							</div>
							<div v-if="c.test" class="d-flex align-center mt-1" style="gap:6px">
								<span class="text-caption grey--text">{{ $t('plugins.WorkshopService.bridgeCard.sends') }}</span>
								<v-text-field
									:value="field(c)" dense hide-details outlined class="pc-field"
									@input="v => $set(fields, c.cmd, v)" @keyup.enter="test(c)"
								/>
								<v-btn small outlined color="primary" :title="t('test')" :loading="tests[c.cmd] && tests[c.cmd].sending" @click="test(c)">
									<v-icon small left>mdi-send</v-icon>{{ $t('plugins.WorkshopService.bridgeCard.test') }}
								</v-btn>
							</div>
							<div v-if="tests[c.cmd] && tests[c.cmd].text" class="pc-res mt-1" :class="tests[c.cmd].ok ? 'pc-res-ok' : 'pc-res-err'">
								<div class="text-caption grey--text mb-1">{{ tests[c.cmd].hour }}<template v-if="tests[c.cmd].ms != null"> · {{ tests[c.cmd].ms }} ms</template> · {{ $t('plugins.WorkshopService.bridgeCard.sent') }} <code>{{ tests[c.cmd].sent }}</code> {{ $t('plugins.WorkshopService.bridgeCard.bridge_response') }}</div>
								<pre>{{ tests[c.cmd].text }}</pre>
							</div>
						</div>
						<div class="text-caption grey--text mt-2">
							{{ $t('plugins.WorkshopService.bridgeCard.test_opens_a_short_connection') }}
							{{ $t('plugins.WorkshopService.bridgeCard.queries_only_the_bridge_commands_above') }}
						</div>
					</v-tab-item>

					<!-- SEGURIDAD -->
					<v-tab-item>
						<template v-if="sec">
							<v-alert dense text type="info" class="mt-3 mb-1 text-body-2">
								{{ $t('plugins.WorkshopService.bridgeCard.telnet_encrypts_nothing') }}
								<b>{{ $t('plugins.WorkshopService.bridgeCard.do_not_open_this_port_to') }}</b>
							</v-alert>

							<div class="pc-sec">
								<div class="pc-sec-t"><v-icon small class="mr-1">mdi-ip-network</v-icon>{{ $t('plugins.WorkshopService.bridgeCard.who_can_connect') }}</div>
								<v-radio-group v-model="secForm.modeIp" dense hide-details class="mt-1">
									<v-radio value="local" :label="$t('plugins.WorkshopService.bridgeCard.only_my_local_network_recommended')" />
									<v-radio value="list" :label="$t('plugins.WorkshopService.bridgeCard.only_these_ips_or_networks')" />
								</v-radio-group>
								<v-combobox
									v-if="secForm.modeIp === 'list'" v-model="secForm.allowed" multiple chips small-chips deletable-chips dense outlined hide-details class="mt-2"
									:label="$t('plugins.WorkshopService.bridgeCard.ips_or_networks_enter_to_add')"
								/>
								<div class="text-caption grey--text mt-1">{{ $t('plugins.WorkshopService.bridgeCard.connections_from_other_ips_are_cut') }}</div>
							</div>

							<div class="pc-sec">
								<div class="pc-sec-t"><v-icon small class="mr-1">mdi-key</v-icon>{{ $t('plugins.WorkshopService.bridgeCard.key_to_send_commands') }}
									<v-chip x-small label dark class="ml-2" :color="sec.password ? 'success' : 'grey'">{{ sec.password ? $t('plugins.WorkshopService.bridgeCard.enabled') : $t('plugins.WorkshopService.bridgeCard.no_key') }}</v-chip>
								</div>
								<div class="d-flex align-center flex-wrap mt-2" style="gap:8px">
									<v-text-field
										v-model="keyNew" :type="viewKey ? 'text' : 'password'" dense outlined hide-details style="max-width:260px"
										:label="sec.password ? $t('plugins.WorkshopService.bridgeCard.new_key') : $t('plugins.WorkshopService.bridgeCard.key_min_4_characters')" autocomplete="new-password"
										:append-icon="viewKey ? 'mdi-eye-off' : 'mdi-eye'" @click:append="viewKey = !viewKey"
									/>
									<v-btn small color="primary" :title="t('put_key')" :disabled="(keyNew || '').length < 4" :loading="actionInProgress === 'key'" @click="putKey()">
										{{ sec.password ? $t('plugins.WorkshopService.bridgeCard.change_key') : $t('plugins.WorkshopService.bridgeCard.enable_key') }}
									</v-btn>
									<v-btn v-if="sec.password" small text color="error" :title="t('remove_key')" :loading="actionInProgress === 'remove'" @click="action({ action: 'clear_password' }, 'remove')">{{ $t('plugins.WorkshopService.bridgeCard.remove_key') }}</v-btn>
								</div>
								<div v-if="help" class="pc-help"><b>{{ sec.password ? $t('plugins.WorkshopService.bridgeCard.change_key') : $t('plugins.WorkshopService.bridgeCard.enable_key') }}:</b> {{ t('put_key') }}<template v-if="sec.password"><br><b>{{ $t('plugins.WorkshopService.bridgeCard.remove_key') }}:</b> {{ t('remove_key') }}</template></div>
								<div class="text-caption grey--text mt-1">
									{{ $t('plugins.WorkshopService.bridgeCard.with_a_key_a_new_connection') }} <code>BRIDGE KEY &lt;password&gt;</code>. {{ $t('plugins.WorkshopService.bridgeCard.stored_encrypted_salted_sha256') }}
									<template v-if="!sec.trusted.length"> {{ $t('plugins.WorkshopService.bridgeCard.before_enabling_it_mark_the_program') }}</template>
								</div>
							</div>

							<div class="pc-sec">
								<div class="pc-sec-t"><v-icon small class="mr-1">mdi-check-decagram</v-icon>{{ $t('plugins.WorkshopService.bridgeCard.trusted_ips_send_commands_without_a') }}</div>
								<div class="d-flex flex-wrap align-center mt-1" style="gap:6px">
									<v-chip v-for="ip in sec.trusted" :key="ip" small close color="success" outlined :title="$t('plugins.WorkshopService.bridgeCard.the_x_removes_trust_from_this')" @click:close="action({ action: 'trust', ip, yes: false }, 'conf-' + ip)">
										{{ ip }}<span v-if="namePerIp(ip)" class="grey--text ml-1">({{ namePerIp(ip) }})</span>
									</v-chip>
									<span v-if="!sec.trusted.length" class="text-caption grey--text">{{ $t('plugins.WorkshopService.bridgeCard.none_f') }}</span>
									<v-btn v-for="cl in clientsNoTrusted" :key="'add' + cl.ip" x-small text color="success" :title="t('trust')" @click="action({ action: 'trust', ip: cl.ip, yes: true }, 'conf-' + cl.ip)">
										<v-icon x-small left>mdi-plus</v-icon>{{ cl.name }} ({{ cl.ip }})
									</v-btn>
								</div>
								<div v-if="help" class="pc-help">{{ $t('plugins.WorkshopService.bridgeCard.the_article') }} <b>X</b> {{ $t('plugins.WorkshopService.bridgeCard.on_each_ip_removes_its_trust') }} <b>{{ $t('plugins.WorkshopService.bridgeCard.plus_name_ip') }}</b> {{ $t('plugins.WorkshopService.bridgeCard.are_current_connections_not_trusted_yet') }} {{ t('trust') }}</div>
							</div>

							<div class="pc-sec">
								<div class="pc-sec-t"><v-icon small class="mr-1">mdi-speedometer</v-icon>{{ $t('plugins.WorkshopService.bridgeCard.limits') }}</div>
								<v-row dense class="mt-1">
									<v-col cols="6" sm="3"><v-text-field v-model.number="secForm.max_connections" type="number" min="1" max="50" :label="$t('plugins.WorkshopService.bridgeCard.connections_at_once')" :title="t('max_connections')" dense outlined hide-details /></v-col>
									<v-col cols="6" sm="3"><v-text-field v-model.number="secForm.attempts_key" type="number" min="1" max="50" :label="$t('plugins.WorkshopService.bridgeCard.wrong_keys_before_blocking')" :title="t('attempts_key')" dense outlined hide-details /></v-col>
									<v-col cols="6" sm="3"><v-text-field v-model.number="secForm.block_min" type="number" min="1" max="1440" :label="$t('plugins.WorkshopService.bridgeCard.block_minutes')" :title="t('block_min')" dense outlined hide-details /></v-col>
									<v-col cols="6" sm="3"><v-text-field v-model.number="secForm.wait_order" type="number" min="1" max="300" :label="$t('plugins.WorkshopService.bridgeCard.order_wait_seconds')" :title="t('wait_order')" dense outlined hide-details /></v-col>
									<v-col cols="12" sm="6"><v-switch v-model="secForm.queries_in_job" :label="$t('plugins.WorkshopService.bridgeCard.position_queries_in_job')" :title="t('queries_in_job')" dense hide-details class="mt-0" /></v-col>
								</v-row>
								<div v-if="help" class="pc-help"><b>{{ $t('plugins.WorkshopService.bridgeCard.connections_at_once_2') }}</b> {{ t('max_connections') }}<br><b>{{ $t('plugins.WorkshopService.bridgeCard.wrong_keys') }}:</b> {{ t('attempts_key') }}<br><b>{{ $t('plugins.WorkshopService.bridgeCard.block_minutes_2') }}</b> {{ t('block_min') }}<br><b>{{ $t('plugins.WorkshopService.bridgeCard.order_wait_seconds') }}:</b> {{ t('wait_order') }}<br><b>{{ $t('plugins.WorkshopService.bridgeCard.position_queries_in_job') }}:</b> {{ t('queries_in_job') }}<br><b>{{ $t('plugins.WorkshopService.bridgeCard.save_network_and_limits') }}</b> {{ t('save_sec') }}</div>
							</div>

							<div class="d-flex align-center mt-2" style="gap:8px">
								<span v-if="msgSec" class="text-caption" :class="msgSecError ? 'error--text' : 'success--text'">{{ msgSec }}</span>
								<v-spacer />
								<v-btn small color="primary" :title="t('save_sec')" :loading="savingSec" @click="saveSafety()">{{ $t('plugins.WorkshopService.bridgeCard.save_network_and_limits_2') }}</v-btn>
							</div>

							<div class="pc-sec">
								<div class="pc-sec-t"><v-icon small class="mr-1">mdi-cancel</v-icon>{{ $t('plugins.WorkshopService.bridgeCard.blocked_now') }}</div>
								<div v-for="b in sec.blocked" :key="b.ip" class="d-flex align-center text-body-2">
									<code>{{ b.ip }}</code><span v-if="b.name" class="ml-1">({{ b.name }})</span>
									<span class="grey--text ml-2">{{ b.fixed ? $t('plugins.WorkshopService.bridgeCard.blocked_from_the_page_until_unblocked') : $t('plugins.WorkshopService.bridgeCard.for_wrong_keys_t_left', { t: dur(b.remaining_s) }) }}</span>
									<v-btn x-small text color="primary" class="ml-2" :title="t('unlock')" @click="action({ action: 'unblock', ip: b.ip }, 'desb-' + b.ip)">{{ $t('plugins.WorkshopService.bridgeCard.unlock') }}</v-btn>
								</div>
								<div v-if="!sec.blocked.length" class="text-caption grey--text">{{ $t('plugins.WorkshopService.bridgeCard.none_f') }}</div>
								<div class="pc-sec-t mt-3"><v-icon small class="mr-1">mdi-shield-alert</v-icon>{{ $t('plugins.WorkshopService.bridgeCard.recently_rejected') }}</div>
								<div v-for="(r, i) in sec.rejected" :key="i" class="text-caption"><span class="grey--text">{{ r.time }}</span> <code>{{ r.ip }}</code> {{ rejectText(r) }}</div>
								<div v-if="!sec.rejected.length" class="text-caption grey--text">{{ $t('plugins.WorkshopService.bridgeCard.none_since_it_started_2') }}</div>
							</div>
						</template>
						<div v-else class="grey--text mt-3">{{ $t('plugins.WorkshopService.bridgeCard.needs_bridge_2_1') }}</div>
					</v-tab-item>

					<!-- CONFIGURACION -->
					<v-tab-item>
						<div v-if="config" class="pc-config mt-3">
							<v-row dense>
								<v-col cols="6" sm="3"><v-text-field v-model.number="config.port" type="number" min="1" max="65535" :label="$t('plugins.WorkshopService.bridgeCard.port')" :title="t('port')" dense outlined hide-details /></v-col>
								<v-col cols="12" sm="5" class="d-flex align-center"><v-switch v-model="config.exclusive" :label="$t('plugins.WorkshopService.bridgeCard.a_single_connection_with_control')" :title="t('exclusive')" dense hide-details class="mt-0" /></v-col>
								<v-col cols="12" sm="4" class="d-flex align-center"><v-switch v-model="config.extended_greeting" :label="$t('plugins.WorkshopService.bridgeCard.greeting_with_help_on_connect')" :title="t('greeting')" dense hide-details class="mt-0" /></v-col>
								<v-col cols="12" sm="12" class="d-flex align-center"><v-switch v-model="config.skip_material_macro" :label="$t('plugins.WorkshopService.bridgeCard.skip_material_gcode')" :title="$t('plugins.WorkshopService.bridgeCard.skip_material_gcode_tip')" dense hide-details class="mt-0" /></v-col>
							</v-row>
							<div v-if="help" class="pc-help"><b>{{ $t('plugins.WorkshopService.bridgeCard.port') }}:</b> {{ t('port') }}<br><b>{{ $t('plugins.WorkshopService.bridgeCard.a_single_connection_with_control_2') }}</b> {{ t('exclusive') }}<br><b>{{ $t('plugins.WorkshopService.bridgeCard.greeting_with_help') }}</b> {{ t('greeting') }}</div>
							<div class="text-caption grey--text mt-1">
								{{ $t('plugins.WorkshopService.bridgeCard.changing_the_port_does_not_cut') }}
								{{ $t('plugins.WorkshopService.bridgeCard.ports_below_1024_need') }} <code>instalar.sh</code>.
							</div>
							<div class="text-subtitle-2 mt-3 mb-1" :title="t('names')">{{ $t('plugins.WorkshopService.bridgeCard.names_by_ip') }}</div>
							<div v-if="help" class="pc-help mb-1">{{ t('names') }}</div>
							<div v-for="(n, i) in names" :key="i" class="d-flex align-center mb-1" style="gap:6px">
								<v-text-field v-model.trim="n.ip" label="IP" dense outlined hide-details style="max-width:170px" />
								<v-text-field v-model.trim="n.name" :label="$t('plugins.WorkshopService.bridgeCard.name_e_g_pc_workshop')" dense outlined hide-details style="max-width:240px" />
								<v-btn icon small :title="$t('plugins.WorkshopService.bridgeCard.delete_this_name')" @click="names.splice(i, 1)"><v-icon small>mdi-delete</v-icon></v-btn>
							</div>
							<v-btn x-small text color="primary" :title="t('names')" @click="names.push({ ip: '', name: '' })"><v-icon x-small left>mdi-plus</v-icon>{{ $t('plugins.WorkshopService.bridgeCard.add_name') }}</v-btn>
							<v-text-field v-model="queriesTxt" :label="$t('plugins.WorkshopService.bridgeCard.queries_always_allowed_comma_separated')" dense outlined hide-details class="mt-3" />
							<div class="text-caption grey--text mt-1">{{ $t('plugins.WorkshopService.bridgeCard.queries_go_through_even_if_someone') }}</div>
							<v-text-field v-model.number="config.debug_timeout_min" type="number" min="1" max="1440" :label="$t('plugins.WorkshopService.bridgeCard.minutes_until_debug_turns_itself_off')" :title="t('debug_timeout')" dense outlined hide-details class="mt-3" style="max-width:320px" />
							<v-switch v-model="config.debug_renew" dense hide-details :label="$t('plugins.WorkshopService.bridgeCard.debug_renew_label')" class="mt-1" />
							<div class="text-caption grey--text">{{ $t('plugins.WorkshopService.bridgeCard.debug_renew_help') }}</div>
							<div class="d-flex align-center mt-3" style="gap:8px">
								<span v-if="msg" class="text-caption" :class="msgError ? 'error--text' : 'success--text'">{{ msg }}</span>
								<v-spacer />
								<v-btn small color="primary" :title="$t('plugins.WorkshopService.bridgeCard.saves_port_mode_names_queries_and')" :loading="saving" @click="save()">{{ $t('plugins.WorkshopService.bridgeCard.save') }}</v-btn>
							</div>
						</div>
						<div v-else class="grey--text mt-3">{{ $t('plugins.WorkshopService.bridgeCard.reading_settings') }}</div>
					</v-tab-item>
				</v-tabs-items>

				<!-- DEPURACION: ultimas lineas en memoria del puente (no van al journal) -->
				<v-expansion-panels v-model="debugPanel" flat class="mt-3 pc-debug-panels">
					<v-expansion-panel>
						<v-expansion-panel-header class="pc-debug-head">
							<div class="d-flex align-center" style="gap:8px">
								<v-icon small>mdi-bug-outline</v-icon>{{ $t('plugins.WorkshopService.bridgeCard.debug') }}
								<v-chip x-small label dark :color="dbg && dbg.active ? 'warning' : 'grey'">{{ dbg && dbg.active ? $t('plugins.WorkshopService.bridgeCard.on_turns_off_in') + dur(dbg.remaining_s) : $t('plugins.WorkshopService.bridgeCard.off') }}</v-chip>
							</div>
						</v-expansion-panel-header>
						<v-expansion-panel-content>
							<div class="text-caption grey--text mb-2">{{ t('debug') }}</div>
							<div class="d-flex flex-wrap align-center" style="gap:6px">
								<v-btn small :color="dbg && dbg.active ? '' : 'primary'" :loading="actionInProgress === 'debug'" :title="t('debug_toggle')" @click="action({ action: 'debug', on: !(dbg && dbg.active) }, 'debug')">
									{{ dbg && dbg.active ? $t('plugins.WorkshopService.bridgeCard.turn_debug_off') : $t('plugins.WorkshopService.bridgeCard.turn_debug_on') }}
								</v-btn>
								<v-btn v-if="dbg && dbg.active" small outlined :loading="actionInProgress === 'debug_extend'" :title="$t('plugins.WorkshopService.bridgeCard.debug_extend_tip')" @click="action({ action: 'debug_extend' }, 'debug_extend')">
									<v-icon small left>mdi-timer-plus-outline</v-icon>{{ $t('plugins.WorkshopService.bridgeCard.debug_extend') }}
								</v-btn>
								<v-btn small outlined :title="t('debug_pause')" @click="debugPause = !debugPause">
									<v-icon small left>{{ debugPause ? 'mdi-play' : 'mdi-pause' }}</v-icon>{{ debugPause ? $t('plugins.WorkshopService.common.follow') : $t('plugins.WorkshopService.common.pause') }}
								</v-btn>
								<v-btn small outlined :title="t('debug_clear')" @click="cleanDebug()"><v-icon small left>mdi-broom</v-icon>{{ $t('plugins.WorkshopService.bridgeCard.clear') }}</v-btn>
								<v-btn small outlined :title="t('debug_copy')" @click="copyDebug()"><v-icon small left>{{ debugCopied ? 'mdi-check' : 'mdi-content-copy' }}</v-icon>{{ $t('plugins.WorkshopService.common.copy') }}</v-btn>
								<v-select v-model="debugClient" :items="debugItemsClient" :label="$t('plugins.WorkshopService.bridgeCard.debug_client')" dense outlined hide-details style="max-width:210px" class="mt-0" />
								<v-spacer />
								<span class="text-caption grey--text">{{ $t('plugins.WorkshopService.bridgeCard.n_lines', { n: debugLines.length }) }}{{ debugPause ? $t('plugins.WorkshopService.bridgeCard.paused') : '' }}</span>
							</div>
							<div class="pc-debug mt-2">
								<div v-for="l in debugLines" :key="l.id" class="pc-dl" :class="'pc-dl-' + l.k"><span class="grey--text">{{ l.t }}</span> <b>{{ l.c }}</b> {{ l.k }} {{ l.x }}</div>
								<div v-if="!debugLines.length" class="grey--text">{{ dbg && dbg.active ? $t('plugins.WorkshopService.bridgeCard.waiting_for_lines') : $t('plugins.WorkshopService.bridgeCard.no_lines_turn_debug_on_to') }}</div>
							</div>
						</v-expansion-panel-content>
					</v-expansion-panel>
				</v-expansion-panels>
			</template>
			<div v-else class="text-body-2 grey--text">{{ $t('plugins.WorkshopService.bridgeCard.reading_status') }}</div>
		</v-card-text>

		<v-snackbar v-model="snack.see" :color="snack.ok ? 'success' : 'error'" timeout="3500" bottom>{{ snack.text }}</v-snackbar>
	</v-card>
</template>

<script>
import i18n from '../../i18n'

'use strict'

import { copyText } from './copy.js'
import { apiText } from './workshop-api.js'

const STATE_FILE = '0:/sys/workshop/data/bridge-state.json';
const CONFIG = '0:/sys/workshop/config/bridge.json';
const ACCION = '0:/sys/workshop/data/bridge-action.json';
const VIEWER = '0:/sys/workshop/data/bridge-viewer.json';
const EVENTOS = {
	connected: a => i18n.t('plugins.WorkshopService.bridgeCard.ev_connected', a),
	disconnected: a => i18n.t('plugins.WorkshopService.bridgeCard.ev_disconnected', a) + (a.had_control ? i18n.t('plugins.WorkshopService.bridgeCard.had_control_the_bridge_is_free') : ''),
	listening: a => i18n.t('plugins.WorkshopService.bridgeCard.ev_listening', { port: a.port, exclusive: a.exclusive ? i18n.t('plugins.WorkshopService.bridgeCard.yes') : i18n.t('plugins.WorkshopService.bridgeCard.no'), password: a.password ? i18n.t('plugins.WorkshopService.bridgeCard.yes') : i18n.t('plugins.WorkshopService.bridgeCard.no') }),
	port_changed: a => i18n.t('plugins.WorkshopService.bridgeCard.ev_port_changed', a),
	control_taken: a => i18n.t('plugins.WorkshopService.bridgeCard.ev_control_taken', a),
	control_given: a => i18n.t('plugins.WorkshopService.bridgeCard.ev_control_given', a),
	control_released: a => i18n.t('plugins.WorkshopService.bridgeCard.ev_control_released', a),
	control_given_from_page: a => i18n.t('plugins.WorkshopService.bridgeCard.ev_control_given_from_page', a),
	control_released_from_page: a => i18n.t('plugins.WorkshopService.bridgeCard.ev_control_released_from_page', a),
	renamed: a => i18n.t('plugins.WorkshopService.bridgeCard.ev_renamed', a),
	renamed_from_page: a => i18n.t('plugins.WorkshopService.bridgeCard.ev_renamed_from_page', a),
	password_ok: a => i18n.t('plugins.WorkshopService.bridgeCard.ev_password_ok', a),
	password_wrong: a => i18n.t('plugins.WorkshopService.bridgeCard.ev_password_wrong', a),
	ip_blocked_by_password: a => i18n.t('plugins.WorkshopService.bridgeCard.ev_ip_blocked_by_password', a),
	password_set: () => i18n.t('plugins.WorkshopService.bridgeCard.bridge_password_set_untrusted_connections'),
	password_cleared: () => i18n.t('plugins.WorkshopService.bridgeCard.bridge_password_removed'),
	trusted: a => i18n.t('plugins.WorkshopService.bridgeCard.ev_trusted', a),
	untrusted: a => i18n.t('plugins.WorkshopService.bridgeCard.ev_untrusted', a),
	ip_blocked: a => i18n.t('plugins.WorkshopService.bridgeCard.ev_ip_blocked', a),
	ip_unblocked: a => i18n.t('plugins.WorkshopService.bridgeCard.ev_ip_unblocked', a),
	kicked: a => i18n.t('plugins.WorkshopService.bridgeCard.ev_kicked', a),
	order_rejected_password: a => i18n.t('plugins.WorkshopService.bridgeCard.ev_order_rejected_password', a),
	order_rejected_control: a => i18n.t('plugins.WorkshopService.bridgeCard.ev_order_rejected_control', a),
	duet_error: a => i18n.t('plugins.WorkshopService.bridgeCard.ev_duet_error', a) + (a.client ? i18n.t('plugins.WorkshopService.bridgeCard.ev_from_client', a) : '') + ': ' + a.error,
	connection_rejected: a => i18n.t('plugins.WorkshopService.bridgeCard.ev_connection_rejected', { ip: a.ip, reason: RECHAZOS[a.reason] || a.reason }),
	restarting: () => i18n.t('plugins.WorkshopService.bridgeCard.ev_restarting'),
	debug_on: a => i18n.t('plugins.WorkshopService.bridgeCard.ev_debug_on', a),
	debug_off: () => i18n.t('plugins.WorkshopService.bridgeCard.debug_off'),
	live_job_started: a => i18n.t('plugins.WorkshopService.bridgeCard.ev_live_job_started', a) + (a.name ? ` (${a.name})` : ''),
	live_job_ended: a => i18n.t('plugins.WorkshopService.bridgeCard.ev_live_job_ended', a),
	unexpected_error: a => i18n.t('plugins.WorkshopService.bridgeCard.ev_unexpected_error', a)
};
const RECHAZOS = {
	ip_blocked_page: i18n.t('plugins.WorkshopService.bridgeCard.ip_blocked_from_the_workshop_page'),
	ip_blocked_password: i18n.t('plugins.WorkshopService.bridgeCard.ip_blocked_for_wrong_passwords'),
	ip_not_allowed: i18n.t('plugins.WorkshopService.bridgeCard.ip_not_allowed_on_this_bridge'),
	too_many_connections: i18n.t('plugins.WorkshopService.bridgeCard.too_many_connections')
};
const results = {
	done: i18n.t('plugins.WorkshopService.bridgeCard.done'),
	password_set: i18n.t('plugins.WorkshopService.bridgeCard.password_set'),
	password_cleared: i18n.t('plugins.WorkshopService.bridgeCard.password_removed'),
	ip_blocked: i18n.t('plugins.WorkshopService.bridgeCard.blocked_f'),
	ip_unblocked: i18n.t('plugins.WorkshopService.bridgeCard.unblocked_f'),
	restarting: i18n.t('plugins.WorkshopService.bridgeCard.restarting'),
	debug_on: i18n.t('plugins.WorkshopService.bridgeCard.debug_on'),
	debug_off: i18n.t('plugins.WorkshopService.bridgeCard.debug_off_2')
};
const DEFAULT = { port: 23, exclusive: true, queries: ['M114', 'M115', 'M105', 'M119', 'M122', 'M408', 'M503', 'M27', 'M20', 'M36'], names: {}, extended_greeting: false, skip_material_macro: false, debug: false, debug_timeout_min: 30, debug_renew: true };
const GH = 60;
const READ_MS = 3000;
const READ_MAX_MS = 30000;
const commands = [
	{ cmd: 'BRIDGE HELP', desc: i18n.t('plugins.WorkshopService.bridgeCard.list_of_bridge_commands'), test: true },
	{ cmd: 'BRIDGE STATUS', desc: i18n.t('plugins.WorkshopService.bridgeCard.who_has_control_now'), test: true },
	{ cmd: 'BRIDGE LIST', desc: i18n.t('plugins.WorkshopService.bridgeCard.open_connections_name_ip_who_has'), test: true },
	{ cmd: 'BRIDGE NAME', desc: i18n.t('plugins.WorkshopService.bridgeCard.shows_the_name_of_this_connection'), test: true },
	{ cmd: 'BRIDGE NAME PC-shop', desc: i18n.t('plugins.WorkshopService.bridgeCard.names_the_connection_can_also_be'), test: false, because: i18n.t('plugins.WorkshopService.bridgeCard.the_name_sticks_to_the_connection') },
	{ cmd: 'BRIDGE USE', desc: i18n.t('plugins.WorkshopService.bridgeCard.keep_control_or_give_it'), test: false, because: i18n.t('plugins.WorkshopService.bridgeCard.a_test_connection_closes_right_away') },
	{ cmd: 'BRIDGE RELEASE', desc: i18n.t('plugins.WorkshopService.bridgeCard.release_control_so_someone_else_can'), test: false, because: i18n.t('plugins.WorkshopService.bridgeCard.a_test_connection_closes_right_away') },
	{ cmd: 'BRIDGE KEY <password>', desc: i18n.t('plugins.WorkshopService.bridgeCard.identify_to_send_commands_if_you'), test: false, because: i18n.t('plugins.WorkshopService.bridgeCard.sent_from_the_program_that_wants') },
	{ cmd: 'M115', desc: i18n.t('plugins.WorkshopService.bridgeCard.test_g_code_goes_through_the'), test: true }
];
const kinds = [
	{ id: 'connection', name: i18n.t('plugins.WorkshopService.bridgeCard.connections'), icon: 'mdi-lan-connect', color: 'info' },
	{ id: 'control', name: i18n.t('plugins.WorkshopService.bridgeCard.control'), icon: 'mdi-steering', color: 'success' },
	{ id: 'safety', name: i18n.t('plugins.WorkshopService.bridgeCard.security'), icon: 'mdi-shield-alert', color: 'warning' },
	{ id: 'error', name: i18n.t('plugins.WorkshopService.bridgeCard.errors_title'), icon: 'mdi-alert-circle', color: 'error' },
	{ id: 'info', name: i18n.t('plugins.WorkshopService.bridgeCard.others'), icon: 'mdi-information-outline', color: 'grey' }
];

function url(p) {
	return '/machine/file/' + encodeURIComponent(p);
}

async function readJson(p) {
	try {
		const r = await fetch(url(p), { cache: 'no-store' });
		return r.ok ? await r.json() : null;
	} catch (err) {
		return null;
	}
}

async function writeJson(p, data) {
	const r = await fetch(url(p), { method: 'PUT', body: JSON.stringify(data, null, 2), headers: { 'Content-Type': 'application/json' } });
	if (!r.ok) {
		throw new Error('HTTP ' + r.status);
	}
}

// Explanation of each button/option: it goes in the title (mouse) and, with the "?"
// button in the header, written below (the touch screen does not show title).
const help = {
	state: i18n.t('plugins.WorkshopService.bridgeCard.status_of_the_bridge_service_on'),
	version: i18n.t('plugins.WorkshopService.bridgeCard.bridge_version_and_how_long_it'),
	control: i18n.t('plugins.WorkshopService.bridgeCard.help_control'),
	release: i18n.t('plugins.WorkshopService.bridgeCard.releases_control_nobody_has_it_until'),
	give_control: i18n.t('plugins.WorkshopService.bridgeCard.help_give_control'),
	trust: i18n.t('plugins.WorkshopService.bridgeCard.this_ip_will_be_able_to'),
	remove_trust: i18n.t('plugins.WorkshopService.bridgeCard.help_remove_trust'),
	eject: i18n.t('plugins.WorkshopService.bridgeCard.cuts_this_connection_now_tap_twice'),
	block: i18n.t('plugins.WorkshopService.bridgeCard.cuts_all_connections_from_this_ip'),
	rename: i18n.t('plugins.WorkshopService.bridgeCard.changes_the_name_this_connection_is'),
	remember: i18n.t('plugins.WorkshopService.bridgeCard.saves_the_name_for_this_ip'),
	role: i18n.t('plugins.WorkshopService.bridgeCard.has_control_can_send_commands_listening'),
	connected: i18n.t('plugins.WorkshopService.bridgeCard.connections_open_now_maximum_allowed'),
	orders: i18n.t('plugins.WorkshopService.bridgeCard.commands_g_code_that_does_something'),
	rejected: i18n.t('plugins.WorkshopService.bridgeCard.rejected_commands_no_control_or_no'),
	response: i18n.t('plugins.WorkshopService.bridgeCard.help_response'),
	traffic: i18n.t('plugins.WorkshopService.bridgeCard.data_received_and_sent_by_the'),
	duet_errors: i18n.t('plugins.WorkshopService.bridgeCard.errors_talking_to_the_duet_and'),
	tab_connections: i18n.t('plugins.WorkshopService.bridgeCard.connections_who_is_connected_now_and'),
	tab_activity: i18n.t('plugins.WorkshopService.bridgeCard.activity_log_of_connections_rejections_and'),
	tab_commands: i18n.t('plugins.WorkshopService.bridgeCard.commands_the_bridge_commands_you_can'),
	tab_safety: i18n.t('plugins.WorkshopService.bridgeCard.security_and_key_who_can_connect'),
	tab_config: i18n.t('plugins.WorkshopService.bridgeCard.settings_port_a_single_connection_with'),
	test: i18n.t('plugins.WorkshopService.bridgeCard.opens_a_short_connection_from_the'),
	put_key: i18n.t('plugins.WorkshopService.bridgeCard.help_set_key'),
	remove_key: i18n.t('plugins.WorkshopService.bridgeCard.deletes_the_key_any_allowed_connection'),
	max_connections: i18n.t('plugins.WorkshopService.bridgeCard.help_max_connections'),
	wait_order: i18n.t('plugins.WorkshopService.bridgeCard.help_order_wait'),
	queries_in_job: i18n.t('plugins.WorkshopService.bridgeCard.help_queries_in_job'),
	attempts_key: i18n.t('plugins.WorkshopService.bridgeCard.how_many_wrong_keys_in_a'),
	block_min: i18n.t('plugins.WorkshopService.bridgeCard.how_many_minutes_an_ip_stays'),
	save_sec: i18n.t('plugins.WorkshopService.bridgeCard.saves_who_can_connect_and_the'),
	unlock: i18n.t('plugins.WorkshopService.bridgeCard.removes_the_block_on_this_ip'),
	port: i18n.t('plugins.WorkshopService.bridgeCard.telnet_port_the_bridge_listens_on'),
	exclusive: i18n.t('plugins.WorkshopService.bridgeCard.help_exclusive'),
	greeting: i18n.t('plugins.WorkshopService.bridgeCard.on_connect_after_connected_the_bridge'),
	names: i18n.t('plugins.WorkshopService.bridgeCard.fixed_names_for_known_ips_e'),
	debug: i18n.t('plugins.WorkshopService.bridgeCard.shows_the_last_lines_that_go'),
	debug_timeout: i18n.t('plugins.WorkshopService.bridgeCard.minutes_debug_stays_on_without_anyone'),
	debug_toggle: i18n.t('plugins.WorkshopService.bridgeCard.turns_the_bridge_debug_on_or'),
	debug_pause: i18n.t('plugins.WorkshopService.bridgeCard.freezes_what_you_see_the_bridge'),
	debug_clear: i18n.t('plugins.WorkshopService.bridgeCard.clears_what_is_on_screen'),
	debug_copy: i18n.t('plugins.WorkshopService.bridgeCard.copies_the_visible_lines_so_you'),
	live_job: i18n.t('plugins.WorkshopService.bridgeCard.if_a_program_announced_with_m9003'),
	last_order: i18n.t('plugins.WorkshopService.bridgeCard.the_last_line_that_is_not'),
	cache: i18n.t('plugins.WorkshopService.bridgeCard.queries_answered_with_a_reply_saved')
};

export default {
	data() {
		return {
			GH,
			KINDS: kinds,
			e: null,
			noInstalled: false,
			unit: null, // {installed, active, enabled, can_control} of the unit of this Pi (null = not read yet)
			unitBusy: false,
			unitMsg: '',
			lastSeq: null,
			received: null,
			now: Date.now(),
			timer: null,
			cyclesUnit: 0,
			tab: 0,
			help: false,
			filterEv: null,
			// conexiones
			editing: null,
			nameNew: '',
			rememberName: true,
			armed: null,
			armedTimer: null,
			actionInProgress: null,
			waiting: null,
			snack: { see: false, ok: true, text: '' },
			// comandos
			commands: commands,
			tests: {},
			fields: {},
			copied: null,
			// seguridad
			secForm: { modeIp: 'local', allowed: [], max_connections: 8, attempts_key: 5, block_min: 5, wait_order: 15, queries_in_job: true },
			secLoaded: false,
			keyNew: '',
			viewKey: false,
			savingSec: false,
			msgSec: null,
			msgSecError: false,
			// depuracion
			debugPanel: undefined,
			debugPause: false,
			debugClient: '', // '' = every client
			debugCopied: false,
			debugViews: [],
			debugSince: 0,
			lastHeartbeat: 0,
			// configuracion
			config: null,
			names: [],
			queriesTxt: '',
			saving: false,
			msg: null,
			msgError: false
		};
	},
	computed: {
		// lines for the Start / End G-code of the sending program: a real G-code (M118 prints a message) so the
		// same file also loads on the Duet; the bridge recognises the text and answers it itself
		gcodesProgram() {
			return [
				{ k: i18n.t('plugins.WorkshopService.bridgeCard.start_gcode'), v: 'M118 P0 S"BRIDGE JOB START Trabajo en vivo"' },
				{ k: i18n.t('plugins.WorkshopService.bridgeCard.end_gcode'), v: 'M118 P0 S"BRIDGE JOB END"' },
				{ k: i18n.t('plugins.WorkshopService.bridgeCard.cancel_gcode'), v: 'M118 P0 S"BRIDGE JOB CANCEL"' }
			];
		},
		// why the bridge cannot be restarted now ('' = it can): a live job, orders in the last 30 s, or a job on the machine
		bridgeInUse() {
			const e = this.e;
			if (!e) {
				return '';
			}
			if (e.activity && e.activity.live_job && e.activity.live_job.active) {
				return i18n.t('plugins.WorkshopService.bridgeCard.in_use_live_job');
			}
			if ((e.clients || []).some(c => c.last_order_age_s != null && c.last_order_age_s < 30)) {
				return i18n.t('plugins.WorkshopService.bridgeCard.in_use_recent_orders');
			}
			try {
				const st = this.$store.state.machine.model.state.status;
				if (['processing', 'paused', 'pausing', 'resuming', 'simulating', 'cancelling'].includes(st)) {
					return i18n.t('plugins.WorkshopService.bridgeCard.in_use_machine_job');
				}
			} catch (err) {
				// no object model yet
			}
			return '';
		},
		host() {
			return window.location.hostname;
		},
		sec() {
			return this.e && this.e.security;
		},
		dbg() {
			return this.e && this.e.debug;
		},
		debugOpen() {
			return this.debugPanel === 0;
		},
		// what is seen: the state lines (frozen on pause), without what was cleared
		debugLines() {
			return this.debugViews.filter(l => l.id > this.debugSince && (!this.debugClient || l.c === this.debugClient));
		},
		// the clients that appear in the lines (to filter by one of them)
		debugItemsClient() {
			const names = [...new Set(this.debugViews.map(l => l.c).filter(Boolean))].sort();
			if (this.debugClient && names.indexOf(this.debugClient) < 0) names.push(this.debugClient);
			return [{ text: i18n.t('plugins.WorkshopService.bridgeCard.all_clients'), value: '' }].concat(names.map(n => ({ text: n, value: n })));
		},
		stateChip() {
			if (this.noInstalled) {
				return { text: i18n.t('plugins.WorkshopService.bridgeCard.not_installed'), color: 'grey' };
			}
			if (!this.e) {
				return { text: '...', color: 'grey' };
			}
			if (this.e.error) {
				return { text: i18n.t('plugins.WorkshopService.bridgeCard.port_error'), color: 'error' };
			}
			if (!this.received || this.now - this.received > 10000) {
				return { text: i18n.t('plugins.WorkshopService.common.no_data_2'), color: 'warning' };
			}
			return { text: i18n.t('plugins.WorkshopService.bridgeCard.up_to_date'), color: 'success' };
		},
		bars() {
			const h = (this.e && this.e.history) || [];
			const max = Math.max(1, ...h.map(x => x[0] + x[1]));
			return h.map((x, i) => {
				const tot = x[0] + x[1];
				const height = tot ? Math.max(2, (tot / max) * (GH - 4)) : 0;
				const ho = tot ? height * x[0] / tot : 0;
				return {
					ho,
					hc: height - ho,
					r: x[2] > 0,
					title: i18n.t('plugins.WorkshopService.bridgeCard.bar_title', { m: 59 - i, o: x[0], q: x[1] }) + (x[2] ? i18n.t('plugins.WorkshopService.bridgeCard.bar_rejections', { n: x[2] }) : '') + (x[3] ? i18n.t('plugins.WorkshopService.bridgeCard.bar_connections', { n: x[3] }) : '')
				};
			});
		},
		summaryHour() {
			const h = (this.e && this.e.history) || [];
			const s = h.reduce((a, x) => [a[0] + x[0], a[1] + x[1], a[2] + x[2]], [0, 0, 0]);
			return i18n.t('plugins.WorkshopService.bridgeCard.hour_summary', { o: s[0], q: s[1], r: s[2] });
		},
		eventsFiltered() {
			const ev = (this.e && this.e.events) || [];
			return this.filterEv ? ev.filter(x => (x.type || 'info') === this.filterEv) : ev;
		},
		clientsNoTrusted() {
			if (!this.e || !this.sec) {
				return [];
			}
			const seen = new Set();
			return this.e.clients.filter(cl => {
				if (cl.trusted || seen.has(cl.ip)) {
					return false;
				}
				seen.add(cl.ip);
				return true;
			});
		}
	},
	watch: {
		sec(s) {
			// the safety form is filled once (do not overwrite what is being edited)
			if (s && !this.secLoaded) {
				this.secLoaded = true;
				this.loadSecForm();
			}
		}
	},
	// Bridge state: file on the SD that the bridge rewrites. It is read only
	// with the page in view (visible tab and active page: DWC keeps it
	// alive with keep-alive when going to another), every LEER_MS; if it is not there
	// (404) it is spaced out up to LEER_MAX_MS (2026-10-12: it was requested every 2 s
	// always, with 404 on the new path).
	mounted() {
		this.active = true;
		this.missing = 0;
		this.readUnit();
		this.read();
		this.schedule();
	},
	activated() {
		this.active = true;
		this.readUnit();
		this.read();
	},
	deactivated() {
		this.active = false;
	},
	beforeDestroy() {
		this.active = false;
		this.destroyed = true;
		clearTimeout(this.timer);
		clearTimeout(this.armedTimer);
	},
	methods: {
		schedule() {
			clearTimeout(this.timer);
			const ms = this.missing ? Math.min(READ_MAX_MS, READ_MS * Math.pow(2, this.missing)) : READ_MS;
			this.timer = setTimeout(() => {
				this.now = Date.now();
				if (this.active && !document.hidden && this.$el && this.$el.isConnected !== false && ++this.cyclesUnit % 4 === 0) {
					this.readUnit();
				}
				const p = (this.active && !document.hidden && this.$el && this.$el.isConnected !== false) ? this.read() : null;
				Promise.resolve(p).then(() => { if (!this.destroyed) this.schedule(); });
			}, ms);
		},
		async readUnit() {
			try {
				const r = JSON.parse(await apiText('bridge.service', {}));
				if (r && typeof r.installed === 'boolean') {
					this.unit = r;
				}
			} catch (err) {
				// the service does not know this operation (old version) or no answer: the card works as before
			}
		},
		async changeUnit(on) {
			this.unitBusy = true;
			this.unitMsg = '';
			try {
				const r = JSON.parse(await apiText('bridge.service.set', { on: !!on }));
				if (r && r.state) {
					this.unit = r.state;
				}
				if (r && !r.ok) {
					this.unitMsg = r.error === 'live_job' ? i18n.t('plugins.WorkshopService.bridgeCard.unit_live_job')
						: r.error === 'no_permission' ? i18n.t('plugins.WorkshopService.bridgeCard.unit_no_permission')
						: i18n.t('plugins.WorkshopService.bridgeCard.unit_failed', { x: r.error || '' });
				}
			} catch (err) {
				this.unitMsg = i18n.t('plugins.WorkshopService.bridgeCard.unit_failed', { x: err.message || '' });
			} finally {
				this.unitBusy = false;
				this.read();
			}
		},
		async read() {
			try {
				const r = await fetch(url(STATE_FILE), { cache: 'no-store' });
				if (r.status === 404) {
					this.noInstalled = true;
					this.missing = Math.min(this.missing + 1, 6);
					return;
				}
				this.missing = 0;
				if (!r.ok) {
					return;
				}
				const e = await r.json();
				this.noInstalled = false;
				if (e.seq !== this.lastSeq) {
					this.lastSeq = e.seq;
					this.received = Date.now();
				}
				this.e = e;
				this.takeDebug(e);
				this.heartbeat();
				this.checkAction();
			} catch (err) {
				// red / archivo a medio escribir: se reintenta en el proximo turno
			}
		},
		// ---- actions (file the bridge reads every second)
		async action(data, key) {
			const seq = Date.now() % 1000000000;
			this.actionInProgress = key;
			try {
				await writeJson(ACCION, Object.assign({ seq }, data));
				this.waiting = { seq, until: Date.now() + 8000 };
			} catch (err) {
				this.actionInProgress = null;
				this.notice(false, i18n.t('plugins.WorkshopService.bridgeCard.could_not_send_the_action_x', { x: err.message }));
			}
		},
		checkAction() {
			if (!this.waiting) {
				return;
			}
			const r = this.e && this.e.action;
			if (r && r.seq === this.waiting.seq) {
				this.waiting = null;
				this.actionInProgress = null;
				this.editing = null;
				this.notice(r.ok, r.ok ? (this.actionText(r) || i18n.t('plugins.WorkshopService.bridgeCard.done')) : i18n.t('plugins.WorkshopService.common.couldn_t_x', { x: this.actionText(r) }));
			} else if (Date.now() > this.waiting.until) {
				this.waiting = null;
				this.actionInProgress = null;
				this.notice(false, i18n.t('plugins.WorkshopService.bridgeCard.the_bridge_did_not_respond_is'));
			}
		},
		notice(ok, text) {
			this.snack = { see: true, ok, text: text };
		},
		beginRename(cl) {
			this.editing = cl.id;
			this.nameNew = cl.name;
			this.rememberName = true;
		},
		rename(cl) {
			if (!this.nameNew) {
				return;
			}
			this.action({ action: 'rename', client: cl.id, name: this.nameNew, remember: this.rememberName }, 'ren-' + cl.id);
		},
		eject(cl) {
			const k = 'exp-' + cl.id;
			if (this.armed !== k) {
				this.armed = k;
				clearTimeout(this.armedTimer);
				this.armedTimer = setTimeout(() => { this.armed = null; }, 4000);
				return;
			}
			this.armed = null;
			this.action({ action: 'kick', client: cl.id }, k);
		},
		// double tap: it cuts every connection (they come back by themselves when the bridge is up again)
		restartBridge() {
			if (this.bridgeInUse) {
				return;
			}
			if (this.armed !== 'restart') {
				this.armed = 'restart';
				clearTimeout(this.armedTimer);
				this.armedTimer = setTimeout(() => { this.armed = null; }, 4000);
				return;
			}
			this.armed = null;
			this.action({ action: 'restart' }, 'restart');
		},
		block(cl) {
			const k = 'blq-' + cl.ip;
			if (this.armed !== k) {
				this.armed = k;
				clearTimeout(this.armedTimer);
				this.armedTimer = setTimeout(() => { this.armed = null; }, 4000);
				return;
			}
			this.armed = null;
			this.action({ action: 'block', ip: cl.ip }, k);
		},
		putKey() {
			const key = this.keyNew;
			this.keyNew = '';
			this.action({ action: 'set_password', password: key }, 'key');
		},
		role(cl) {
			if (cl.control) {
				return { text: i18n.t('plugins.WorkshopService.bridgeCard.has_control'), color: 'green darken-1', icon: 'mdi-steering' };
			}
			if (cl.role === 'no_password') {
				return { text: i18n.t('plugins.WorkshopService.bridgeCard.no_key_query_only'), color: 'orange darken-2', icon: 'mdi-lock' };
			}
			return { text: this.e && this.e.exclusive ? i18n.t('plugins.WorkshopService.bridgeCard.listening') : i18n.t('plugins.WorkshopService.bridgeCard.can_send'), color: 'blue darken-1', icon: 'mdi-ear-hearing' };
		},
		kind(ev) {
			return kinds.find(t => t.id === (ev.type || 'info')) || kinds[kinds.length - 1];
		},
		ipOf(id) {
			return id ? id.split(':')[0] : '';
		},
		namePerIp(ip) {
			const cl = this.e && this.e.clients.find(x => x.ip === ip);
			return cl ? cl.name : ((this.config && this.config.names && this.config.names[ip]) || '');
		},
		// ---- seguridad
		async loadSecForm() {
			const c = (await readJson(CONFIG)) || {};
			const permitidas = c.allowed || [];
			this.secForm = {
				modeIp: permitidas.length ? 'list' : 'local',
				allowed: permitidas.slice(),
				max_connections: c.max_connections || 8,
				attempts_key: c.password_attempts || 5,
				block_min: Math.round((c.block_seconds || 300) / 60),
				wait_order: c.order_timeout_s || 15,
				queries_in_job: c.queries_in_job !== false
			};
		},
		async saveSafety() {
			const f = this.secForm;
			const permitidas = f.modeIp === 'list' ? (f.allowed || []).map(x => String(x).trim()).filter(Boolean) : [];
			if (f.modeIp === 'list' && !permitidas.length) {
				this.msgSec = i18n.t('plugins.WorkshopService.bridgeCard.add_at_least_one_ip_or');
				this.msgSecError = true;
				return;
			}
			const malas = permitidas.filter(x => !/^\d{1,3}(\.\d{1,3}){3}(\/\d{1,2})?$/.test(x));
			if (malas.length) {
				this.msgSec = i18n.t('plugins.WorkshopService.bridgeCard.not_understood_x_use', { x: malas.join(', ') });
				this.msgSecError = true;
				return;
			}
			const owner = this.e && this.e.clients.find(cl => cl.control);
			this.savingSec = true;
			try {
				// the file is reread: the key (hash) and the trusted ones are changed by the bridge
				const current = (await readJson(CONFIG)) || {};
				Object.assign(current, {
					allowed: permitidas,
					max_connections: Math.max(1, Math.min(50, Number(f.max_connections) || 8)),
					password_attempts: Math.max(1, Math.min(50, Number(f.attempts_key) || 5)),
					block_seconds: Math.max(1, Math.min(1440, Number(f.block_min) || 5)) * 60,
					order_timeout_s: Math.max(1, Math.min(300, Number(f.wait_order) || 15)),
					queries_in_job: !!f.queries_in_job
				});
				await writeJson(CONFIG, current);
				this.msgSec = i18n.t('plugins.WorkshopService.bridgeCard.saved_the_bridge_applies_it_within') + (owner && permitidas.length ? i18n.t('plugins.WorkshopService.bridgeCard.check_that_ip_stays_allowed', { ip: owner.ip, name: owner.name }) : '');
				this.msgSecError = false;
			} catch (err) {
				this.msgSec = i18n.t('plugins.WorkshopService.common.could_not_save_x', { x: err.message });
				this.msgSecError = true;
			} finally {
				this.savingSec = false;
			}
		},
		// ---- comandos
		async copy(text) {
			const ok = await copyText(text);
			this.copied = ok ? text : null;
			if (ok) {
				setTimeout(() => { if (this.copied === text) { this.copied = null; } }, 1500);
			}
		},
		field(c) {
			return this.fields[c.cmd] != null ? this.fields[c.cmd] : c.cmd;
		},
		async test(c) {
			const linea = String(this.field(c)).replace(/"/g, "'").trim();
			const cmd = c.cmd;
			const hour = new Date().toLocaleTimeString(this.$i18n.locale);
			this.$set(this.tests, cmd, { sending: true });
			try {
				const txt = await apiText('bridge.test', { line: linea });
				const r = JSON.parse(txt);
				this.$set(this.tests, cmd, r.error
					? { ok: false, text: r.error, hour: hour, sent: linea }
					: { ok: true, text: r.response || i18n.t('plugins.WorkshopService.common.no_response'), ms: r.ms, hour: hour, sent: linea });
			} catch (e) {
				this.$set(this.tests, cmd, { ok: false, text: i18n.t('plugins.WorkshopService.bridgeCard.could_not_test_x', { x: e.message || e }) + i18n.t('plugins.WorkshopService.bridgeCard.needs_updated_workshopservice'), hour: hour, sent: linea });
			}
		},
		// ---- depuracion
		takeDebug(e) {
			if (this.debugPause || !e.debug) {
				return;
			}
			this.debugViews = (e.debug.lines || []).slice(-300);
		},
		// The bridge turns debugging off by itself if nobody is looking: while the panel
		// is open bridge-viewer.json is written every 10 s (it counts its date).
		heartbeat() {
			if (!this.debugOpen || !this.dbg || !this.dbg.active || Date.now() - this.lastHeartbeat < 10000) {
				return;
			}
			this.lastHeartbeat = Date.now();
			writeJson(VIEWER, { viewer: 'page', at: new Date().toISOString() }).catch(() => {});
		},
		cleanDebug() {
			this.debugSince = Math.max(this.debugSince, (this.dbg && this.dbg.last_id) || 0);
		},
		async copyDebug() {
			const ok = await copyText(this.debugLines.map(l => `${l.t} ${l.c} ${l.k} ${l.x}`).join('\n'));
			this.debugCopied = ok;
			if (ok) {
				setTimeout(() => { this.debugCopied = false; }, 1500);
			}
		},
		// ---- Spanish texts for what the bridge sends (in English, with code)
		eventText(ev) {
			const f = EVENTOS[ev.code];
			return f ? f(ev.args || {}) : ev.text;
		},
		rejectText(r) {
			return RECHAZOS[r.code] || r.text;
		},
		actionText(r) {
			return results[r.code] || r.text;
		},
		// ---- formato
		dur(s) {
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
		num(n) {
			return n == null ? '--' : Number(n).toLocaleString();
		},
		bytes(b) {
			if (b == null) {
				return '--';
			}
			if (b < 1024) {
				return b + ' B';
			}
			if (b < 1048576) {
				return (b / 1024).toFixed(1) + ' KB';
			}
			return (b / 1048576).toFixed(1) + ' MB';
		},
		// ---- configuracion general
		t(k) {
			return help[k] || '';
		},
		goAKey() {
			this.tab = 3;
			this.help = true;
		},
		async openConfig() {
			this.msg = null;
			const c = (await readJson(CONFIG)) || {};
			this.config = Object.assign({}, DEFAULT, c);
			this.names = Object.entries(this.config.names || {}).map(([ip, nombre]) => ({ ip, name: nombre }));
			this.queriesTxt = (this.config.queries || []).join(', ');
		},
		async save() {
			const p = Number(this.config.port);
			if (!Number.isInteger(p) || p < 1 || p > 65535) {
				this.msg = i18n.t('plugins.WorkshopService.bridgeCard.invalid_port_1_to_65535');
				this.msgError = true;
				return;
			}
			this.saving = true;
			try {
				// the file is reread so as not to overwrite the security (key, trusted)
				const current = (await readJson(CONFIG)) || {};
				Object.assign(current, {
					port: p,
					exclusive: !!this.config.exclusive,
					extended_greeting: !!this.config.extended_greeting,
					skip_material_macro: !!this.config.skip_material_macro,
					debug_timeout_min: Math.max(1, Math.min(1440, Number(this.config.debug_timeout_min) || 30)),
					debug_renew: this.config.debug_renew !== false,
					names: Object.fromEntries(this.names.filter(n => n.ip && n.name).map(n => [n.ip, n.name])),
					queries: this.queriesTxt.split(/[\s,]+/).map(x => x.trim().toUpperCase()).filter(Boolean)
				});
				await writeJson(CONFIG, current);
				this.msg = i18n.t('plugins.WorkshopService.bridgeCard.saved_the_bridge_picks_it_up');
				this.msgError = false;
			} catch (err) {
				this.msg = i18n.t('plugins.WorkshopService.common.could_not_save_x', { x: err.message });
				this.msgError = true;
			} finally {
				this.saving = false;
			}
		}
	}
};
</script>

<style scoped>
.pc-head {
	flex-wrap: wrap;
	gap: 6px;
}
.pc-sub {
	font-weight: normal;
	line-height: 1.3;
}
.pc-top {
	display: grid;
	grid-template-columns: minmax(240px, 1fr) 3fr;
	gap: 12px;
}
@media (max-width: 900px) {
	.pc-top {
		grid-template-columns: 1fr;
	}
}
.pc-control {
	border: 1px solid var(--wf-line);
	border-radius: 8px;
	padding: 8px 12px;
}
.pc-control-on {
	border-color: var(--wf-ok);
}
.pc-control-name {
	font-size: 20px;
	font-weight: 500;
}
.pc-tiles {
	display: grid;
	grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
	gap: 8px;
}
.pc-tile {
	border: 1px solid var(--wf-line);
	border-radius: 8px;
	padding: 6px 10px;
}
.pc-notice {
	border-color: var(--wf-warn);
}
.pc-l {
	font-size: 11px;
	color: var(--tp-faint, #9e9e9e);
}
.pc-v {
	font-size: 22px;
	font-weight: 500;
	line-height: 1.2;
}
.pc-v small {
	font-size: 12px;
	color: var(--tp-faint, #9e9e9e);
}
.pc-v-small {
	font-size: 14px;
}
.pc-s {
	font-size: 11px;
	color: var(--tp-faint, #9e9e9e);
}
.pc-chart {
	border: 1px solid var(--wf-line);
	border-radius: 8px;
	padding: 6px 10px;
}
.pc-svg {
	width: 100%;
	height: 60px;
	display: block;
}
.pc-law {
	margin-right: 10px;
}
.pc-law i {
	display: inline-block;
	width: 9px;
	height: 9px;
	border-radius: 2px;
	margin-right: 4px;
	vertical-align: middle;
}
.pc-tabs-items {
	background: transparent !important;
}
.pc-empty {
	text-align: center;
	padding: 18px 0;
}
.pc-cli {
	border: 1px solid var(--wf-line);
	border-radius: 8px;
	padding: 8px 10px;
	margin-top: 8px;
}
.pc-role-control {
	border-color: var(--wf-ok);
}
.pc-debug {
	max-height: 320px;
	overflow-y: auto;
	font-family: monospace;
	font-size: 12px;
	background: rgba(0, 0, 0, 0.2);
	border-radius: 4px;
	padding: 6px 8px;
}
.pc-dl {
	white-space: pre-wrap;
	word-break: break-word;
}
.pc-dl-error {
	color: var(--wf-err);
}
.pc-dl-stale {
	color: var(--wf-warn);
}
.pc-role-no_password {
	border-color: var(--wf-warn);
}
.pc-cli-name {
	min-width: 180px;
}
.pc-cli-stats {
	display: flex;
	flex-wrap: wrap;
	gap: 14px;
	font-size: 12px;
	color: var(--tp-faint2, #bdbdbd);
	margin: 6px 0 0 40px;
}
.pc-last code {
	font-size: 11px;
}
.pc-events {
	max-height: 320px;
	overflow-y: auto;
	font-size: 12px;
}
.pc-ev {
	padding: 2px 0;
	border-bottom: 1px solid rgba(128, 128, 128, 0.1);
}
.pc-sec {
	border: 1px solid var(--wf-line);
	border-radius: 8px;
	padding: 8px 12px;
	margin-top: 10px;
}
.pc-sec-t {
	font-weight: 500;
	font-size: 14px;
	display: flex;
	align-items: center;
}
.pc-cmd {
	padding: 6px 0;
	border-bottom: 1px solid rgba(128, 128, 128, 0.15);
}
.pc-field {
	font-family: monospace;
	font-size: 13px;
	max-width: 320px;
}
.pc-cmd-code {
	cursor: pointer;
	font-size: 12px;
}
.pc-cmd-code:hover {
	outline: 1px dashed rgba(128, 128, 128, 0.6);
}
.pc-res {
	border: 1px solid var(--wf-ok);
	padding: 4px 8px;
	background: rgba(0, 0, 0, 0.2);
	border-radius: 8px;
}
.pc-res-err {
	border-color: var(--wf-err);
}
.pc-res pre {
	white-space: pre-wrap;
	word-break: break-word;
	font-size: 12px;
	margin: 0;
}
</style>
