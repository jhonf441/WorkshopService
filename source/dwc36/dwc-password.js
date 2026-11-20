'use strict'

// The state chip of the DWC password card, pure (no DOM, no store): the word is a catalog key, the colour and the icon never depend on the word alone.
//   passwordChip(has, t)   has: true | false | null (null = config.g could not be read); t(key) translates a key of the area `plugins.WorkshopService.`
// Returns { color, icon, text }.

export function passwordChip(has, t) {
	if (has === null || has === undefined) return { color: 'grey', icon: 'mdi-help-circle-outline', text: t('common.no_data_2') }
	if (has) return { color: 'success', icon: 'mdi-check-circle-outline', text: t('servicePage.set') }
	return { color: 'warning', icon: 'mdi-alert-outline', text: t('servicePage.no_password') }
}
