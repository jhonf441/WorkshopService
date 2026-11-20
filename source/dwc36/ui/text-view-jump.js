'use strict'

// Where a jump of the file reader goes (pure: SvTextView.vue does the scrolling).
//
//   rowRange(rows, from, to)            [first, last] positions of the rows that hold the lines `from` to `to` (a line number is `n` of a row), or null when they are not drawn
//   scrollTopFor(top, height, box)      the scrollTop that leaves a block (its top and height inside the scrolled content) in the upper third of a box of `box` px, whole if it fits
//   wentKey(from, to)                   the text of the notice for the screen reader: { key, params }

export function rowRange(rows, from, to) {
	let first = -1
	let last = -1
	;(rows || []).forEach((r, i) => {
		if (r && typeof r.n === 'number' && r.n >= from && r.n <= to) {
			if (first < 0) first = i
			last = i
		}
	})
	return first < 0 ? null : [first, last]
}

export function scrollTopFor(top, height, box) {
	const b = Math.max(0, Number(box) || 0)
	const h = Math.max(0, Number(height) || 0)
	// a block taller than the box shows its first lines: it never goes above the third
	const room = h > b * 0.6 ? 0 : Math.max(0, b / 3 - h / 2)
	return Math.max(0, Math.round(top - Math.max(room, Math.min(b / 3, 24))))
}

export function wentKey(from, to) {
	return from === to ? { key: 'view_went_one', params: { n: from } } : { key: 'view_went_many', params: { from, to } }
}
