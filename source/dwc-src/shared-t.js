'use strict'

// Texts of the shared pieces (ServiceNotice, machine-free, DetailChart): plugins.<Id>.shared.<key>.
// build.py merges vue/_shared/i18n/*.json into the i18n of every Vue plugin and writes plugin-id.js.
import { i18n } from './dwc-host.js'
import { PLUGIN_ID } from './plugin-id.js'

export function ts(key, params) {
	return i18n.t('plugins.' + PLUGIN_ID + '.shared.' + key, params)
}
