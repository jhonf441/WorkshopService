'use strict'

// The rows of a help, in their fixed order and without the empty ones: what it is, what it is for, what you lose without it, how to use it.
// Pure over the translator `t` (the shared catalog keys help_tip_*), so tests/help-unified.test.js loads it in node. Used by HelpFold.vue and HelpGuide.vue.
//   helpRows({ what, why, ifMissing, how }, t)  ->  [{ k, label, text }]

// a help of at most this many characters is "short": it is drawn in line (<help-line>); a longer one is folded (<help-fold>)
export const HELP_LINE_MAX = 200

export function helpRows(spec, t) {
	return [
		{ k: 'what', label: t('help_tip_what'), text: spec.what },
		{ k: 'why', label: t('help_tip_why'), text: spec.why },
		{ k: 'miss', label: t('help_tip_missing'), text: spec.ifMissing },
		{ k: 'how', label: t('help_tip_how'), text: spec.how }
	].filter(r => r.text)
}
