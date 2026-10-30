'use strict'

// The components read their texts when the page loads (constants at module level), so they keep the language
// DWC had at that moment. When the language changes the page loads again once; the short delay lets DWC save the
// setting first. Every plugin imports this file; the flag makes only one of them act.
import { i18n, onLocaleChange } from './dwc-host.js'

const loaded = i18n.locale
if (!window.__workshopLanguageReload) {
	window.__workshopLanguageReload = true
	onLocaleChange(locale => {
		if (locale !== loaded) setTimeout(() => location.reload(), 1500)
	})
}
