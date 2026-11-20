'use strict'

// Numbers as the language of DWC writes them. '' for a value that is not a number (the screen prints its own "no data").
//   number(1234.5, 'es', 1)  '1.234,5'      percent(42.3, 'es')  '42 %'      megabytes(55.25, 'en')  '55.3 MB'

export function number(value, locale, digits) {
	if (typeof value !== 'number' || !isFinite(value)) return ''
	const d = digits === undefined ? 0 : digits
	try {
		return new Intl.NumberFormat(locale || 'en', { minimumFractionDigits: 0, maximumFractionDigits: d }).format(value)
	} catch (e) {
		return value.toFixed(d)
	}
}

export function percent(value, locale) {
	const n = number(value, locale, 0)
	return n === '' ? '' : n + ' %'
}

export function megabytes(value, locale) {
	const n = number(value, locale, 1)
	return n === '' ? '' : n + ' MB'
}
