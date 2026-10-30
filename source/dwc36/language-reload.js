'use strict'

// The components read their texts when the page loads (constants at module level), so they keep the language
// DWC had at that moment. When the language changes the page loads again once; the short delay lets DWC save the
// setting first. Every plugin imports this file; the flag makes only one of them act.
import i18n from '../../i18n'

const loaded = i18n.locale
const vm = i18n.vm || i18n._vm
if (vm && !window.__workshopLanguageReload) {
	window.__workshopLanguageReload = true
	vm.$watch(() => i18n.locale, locale => {
		if (locale !== loaded) setTimeout(() => location.reload(), 1500)
	})
}
