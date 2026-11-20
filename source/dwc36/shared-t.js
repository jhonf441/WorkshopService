'use strict'

// Texts of the shared pieces (ServiceNotice, machine-free, DetailChart): plugins.<Id>.shared.<key>.
// build.py merges vue/_shared/i18n/*.json into the i18n of every Vue plugin and writes plugin-id.js.
import i18n from '../../i18n'
import { PLUGIN_ID } from './plugin-id.js'

export function ts(key, params) {
	return i18n.t('plugins.' + PLUGIN_ID + '.shared.' + key, params)
}

// a text with a singular and a plural form: `count` decides which one
export function tsc(key, count, params) {
	return i18n.tc('plugins.' + PLUGIN_ID + '.shared.' + key, count, params)
}
