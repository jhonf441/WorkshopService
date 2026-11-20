'use strict'

// The words of the bridge card as KEYS of the area bridgeCard (plugins.WorkshopService.bridgeCard.<key>) and the rules that choose them. No i18n
// import and nothing translated at load time: every function takes `t(key, params)` (the card passes its own translator), so the language is read
// when a text is drawn. bridge-text-mixin.js gives the card and its parts that translator.

export const AREA = 'plugins.WorkshopService.bridgeCard.'

// why a connection was refused (bridge code -> key); a code that is not here is shown as the bridge sent it
export const REJECT_KEYS = {
	ip_blocked_page: 'ip_blocked_from_the_workshop_page',
	ip_blocked_password: 'ip_blocked_for_wrong_passwords',
	ip_not_allowed: 'ip_not_allowed_on_this_bridge',
	too_many_connections: 'too_many_connections'
}

// the answer of the bridge to an action of the page (bridge code -> key)
export const RESULT_KEYS = {
	done: 'done',
	password_set: 'password_set',
	password_cleared: 'password_removed',
	ip_blocked: 'blocked_f',
	ip_unblocked: 'unblocked_f',
	restarting: 'restarting',
	debug_on: 'debug_on',
	debug_off: 'debug_off_2'
}

const simple = (key) => (a, t) => t(key, a)

// the events of the activity tab (bridge code -> function(args, t) -> text); a code that is not here is shown as the bridge sent it
export const EVENTS = {
	connected: simple('ev_connected'),
	disconnected: (a, t) => t('ev_disconnected', a) + (a.had_control ? t('had_control_the_bridge_is_free') : ''),
	listening: (a, t) => t('ev_listening', { port: a.port, exclusive: a.exclusive ? t('yes') : t('no'), password: a.password ? t('yes') : t('no') }),
	port_changed: simple('ev_port_changed'),
	control_taken: simple('ev_control_taken'),
	control_given: simple('ev_control_given'),
	control_released: simple('ev_control_released'),
	control_given_from_page: simple('ev_control_given_from_page'),
	control_released_from_page: simple('ev_control_released_from_page'),
	renamed: simple('ev_renamed'),
	renamed_from_page: simple('ev_renamed_from_page'),
	password_ok: simple('ev_password_ok'),
	password_wrong: simple('ev_password_wrong'),
	ip_blocked_by_password: simple('ev_ip_blocked_by_password'),
	password_set: (a, t) => t('bridge_password_set_untrusted_connections'),
	password_cleared: (a, t) => t('bridge_password_removed'),
	trusted: simple('ev_trusted'),
	untrusted: simple('ev_untrusted'),
	ip_blocked: (a, t) => t('ev_ip_blocked', a, Number(a.cut) || 0),
	ip_unblocked: simple('ev_ip_unblocked'),
	kicked: simple('ev_kicked'),
	order_rejected_password: simple('ev_order_rejected_password'),
	order_rejected_control: simple('ev_order_rejected_control'),
	duet_error: (a, t) => t('ev_duet_error', a) + (a.client ? t('ev_from_client', a) : '') + ': ' + a.error,
	connection_rejected: (a, t) => t('ev_connection_rejected', { ip: a.ip, reason: REJECT_KEYS[a.reason] ? t(REJECT_KEYS[a.reason]) : a.reason }),
	restarting: (a, t) => t('ev_restarting'),
	debug_on: simple('ev_debug_on'),
	debug_off: (a, t) => t('debug_off'),
	live_job_started: (a, t) => t('ev_live_job_started', a) + (a.name ? ` (${a.name})` : ''),
	live_job_ended: simple('ev_live_job_ended'),
	unexpected_error: simple('ev_unexpected_error')
}

export function eventText(ev, t) {
	const f = EVENTS[ev.code]
	return f ? f(ev.args || {}, t) : ev.text
}

export function rejectText(r, t) {
	return REJECT_KEYS[r.code] ? t(REJECT_KEYS[r.code]) : r.text
}

export function actionText(r, t) {
	return RESULT_KEYS[r.code] ? t(RESULT_KEYS[r.code]) : r.text
}

// the explanation of each button or option: it goes in the title (mouse) and, with the "?" button of the header, written below
// (the touch screen does not show a title). short name -> key
export const HELP_KEYS = {
	state: 'status_of_the_bridge_service_on',
	version: 'bridge_version_and_how_long_it',
	contract_open: 'contract_open_title',
	control: 'help_control',
	release: 'releases_control_nobody_has_it_until',
	give_control: 'help_give_control',
	trust: 'this_ip_will_be_able_to',
	remove_trust: 'help_remove_trust',
	eject: 'cuts_this_connection_now_tap_twice',
	block: 'cuts_all_connections_from_this_ip',
	rename: 'changes_the_name_this_connection_is',
	remember: 'saves_the_name_for_this_ip',
	role: 'has_control_can_send_commands_listening',
	connected: 'connections_open_now_maximum_allowed',
	orders: 'commands_g_code_that_does_something',
	rejected: 'rejected_commands_no_control_or_no',
	response: 'help_response',
	traffic: 'data_received_and_sent_by_the',
	duet_errors: 'errors_talking_to_the_duet_and',
	tab_connections: 'connections_who_is_connected_now_and',
	tab_activity: 'activity_log_of_connections_rejections_and',
	tab_commands: 'commands_the_bridge_commands_you_can',
	tab_safety: 'security_and_key_who_can_connect',
	tab_config: 'settings_port_a_single_connection_with',
	test: 'opens_a_short_connection_from_the',
	put_key: 'help_set_key',
	remove_key: 'deletes_the_key_any_allowed_connection',
	max_connections: 'help_max_connections',
	wait_order: 'help_order_wait',
	queries_in_job: 'help_queries_in_job',
	attempts_key: 'how_many_wrong_keys_in_a',
	block_min: 'how_many_minutes_an_ip_stays',
	save_sec: 'saves_who_can_connect_and_the',
	unlock: 'removes_the_block_on_this_ip',
	port: 'telnet_port_the_bridge_listens_on',
	exclusive: 'help_exclusive',
	greeting: 'on_connect_after_connected_the_bridge',
	names: 'fixed_names_for_known_ips_e',
	debug: 'shows_the_last_lines_that_go',
	debug_timeout: 'minutes_debug_stays_on_without_anyone',
	debug_toggle: 'turns_the_bridge_debug_on_or',
	debug_pause: 'freezes_what_you_see_the_bridge',
	debug_clear: 'clears_what_is_on_screen',
	debug_copy: 'copies_the_visible_lines_so_you',
	live_job: 'if_a_program_announced_with_m9003',
	last_order: 'the_last_line_that_is_not',
	cache: 'queries_answered_with_a_reply_saved'
}

// the commands the bridge understands, for the tab Commands: desc and because are keys; test: the page may send it to try it
export const COMMANDS = [
	{ cmd: 'BRIDGE HELP', desc: 'list_of_bridge_commands', test: true },
	{ cmd: 'BRIDGE STATUS', desc: 'who_has_control_now', test: true },
	{ cmd: 'BRIDGE LIST', desc: 'open_connections_name_ip_who_has', test: true },
	{ cmd: 'BRIDGE NAME', desc: 'shows_the_name_of_this_connection', test: true },
	{ cmd: 'BRIDGE NAME PC-shop', desc: 'names_the_connection_can_also_be', test: false, because: 'the_name_sticks_to_the_connection' },
	{ cmd: 'BRIDGE USE', desc: 'keep_control_or_give_it', test: false, because: 'a_test_connection_closes_right_away' },
	{ cmd: 'BRIDGE RELEASE', desc: 'release_control_so_someone_else_can', test: false, because: 'a_test_connection_closes_right_away' },
	{ cmd: 'BRIDGE KEY <password>', desc: 'identify_to_send_commands_if_you', test: false, because: 'sent_from_the_program_that_wants' },
	{ cmd: 'M115', desc: 'test_g_code_goes_through_the', test: true }
]

// the kinds of event of the activity tab (the type the bridge sends, 'info' when it sends none)
export const KINDS = [
	{ id: 'connection', name: 'connections', icon: 'mdi-lan-connect', color: 'info' },
	{ id: 'control', name: 'control', icon: 'mdi-steering', color: 'success' },
	{ id: 'safety', name: 'security', icon: 'mdi-shield-alert', color: 'warning' },
	{ id: 'error', name: 'errors_title', icon: 'mdi-alert-circle', color: 'error' },
	{ id: 'info', name: 'others', icon: 'mdi-information-outline', color: 'grey' }
]

// what to paste in the sending program as its Start / End G-code: a real G-code (M118 prints a message) so the same file also loads on the Duet;
// the bridge recognises the text and answers it itself. k is a key
export const PROGRAM_GCODES = [
	{ k: 'start_gcode', v: 'M118 P0 S"BRIDGE JOB START Trabajo en vivo"' },
	{ k: 'end_gcode', v: 'M118 P0 S"BRIDGE JOB END"' },
	{ k: 'cancel_gcode', v: 'M118 P0 S"BRIDGE JOB CANCEL"' }
]

// the role of a client: which look and which key of its words. exclusive: the bridge is in the mode of a single connection with control
export function roleOf(cl, exclusive) {
	if (cl.control) return { key: 'has_control', color: 'green darken-1', icon: 'mdi-steering' }
	if (cl.role === 'no_password') return { key: 'no_key_query_only', color: 'orange darken-2', icon: 'mdi-lock' }
	return { key: exclusive ? 'listening' : 'can_send', color: 'blue darken-1', icon: 'mdi-ear-hearing' }
}
