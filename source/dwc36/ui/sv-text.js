'use strict'

// The words of the kit. A piece of ui/ never reads the catalogs of a page: whoever mounts the kit PROVIDES a translator
// (provide: { svText: (key, params) => string }) and every piece injects it with this mixin. Without a provider the key itself
// is shown, so a missing provider is seen at once.
//
// Keys the kit asks for (the page maps them to its catalogs, area `kit`): see KIT_KEYS; a test checks that the page has them all.

export const KIT_KEYS = Object.freeze([
	'toggle_on', 'toggle_off', 'sending', 'sending_note', 'verifying', 'verifying_note', 'done', 'refused', 'unverified', 'retry', 'checking_permission',
	'cancel', 'understand_risk', 'sign_in', 'no_session', 'needs_role', 'read_failed', 'busy', 'loading',
	'refreshing', 'updated_at', 'refresh', 'stale', 'close', 'session_closed', 'help_title', 'help_what', 'help_why', 'help_missing', 'help_how',
	'view_went_one', 'view_went_many', 'view_loading', 'view_slow', 'view_tools', 'view_search', 'view_prev', 'view_next', 'view_hits', 'view_no_hits', 'view_wrap', 'view_wrap_help', 'view_copy', 'view_download', 'view_more', 'copy', 'copied',
	'unsaved_mark', 'unsaved_title', 'unsaved_text', 'unsaved_keep', 'unsaved_save', 'unsaved_discard', 'unsaved_failed'
])

export const svTextMixin = {
	inject: { svText: { default: () => key => key } },
	methods: {
		kt(key, params) {
			return this.svText(key, params)
		}
	}
}

// the focusable elements inside a box, in order (sheets and dialogs keep the Tab key inside)
export function focusables(root) {
	if (!root || !root.querySelectorAll) return []
	const all = root.querySelectorAll('a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])')
	return Array.prototype.filter.call(all, el => !el.hidden)
}
