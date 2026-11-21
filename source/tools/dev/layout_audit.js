// tools/dev/layout_audit.js -- the layout, spacing and contrast audit of the service page in the browser.
//
// It is ONE expression: it evaluates to a function `audit(options)` that returns { counts, findings }. Run it in the page of the simulator (tools/dev/run_sim.py --build <name>):
//
//     page.evaluate(`(${fs.readFileSync('tools/dev/layout_audit.js', 'utf8')})()`)          // Playwright
//     (the Playwright MCP: browser_evaluate with the text of this file wrapped the same way)
//
// Visit every place of the page (section by section, tab by tab, the viewer open, rows unfolded, at 320 / 390 / 768 / 1100 / 1280 / 1920 px, scrolled and not) and run it each time.
// What it finds (every finding says the kind, a selector and the numbers):
//   overlap     two visible children of a toolbar / row / action bar whose boxes intersect (more than 4 px2)
//   actions     the buttons of a .sv-card-actions that do not share the left and right edge when stacked, or the height when side by side (0.5 px)
//   body        an unfolded .sv-row-body that does not start at the left edge of its row or that intersects the head of the row
//   edge        text closer than 12 px to the visible border of its container (a card, a row with a border, a details)
//   cut         text that does not fit its box (scrollWidth > clientWidth) with no ellipsis and no scroll
//   touch       a button whose box is closer than 6 px to the separator / edge of its row
//   gap         two adjacent buttons closer than 6 px
//   contrast    text whose real contrast with its effective background is below 4.5 (3 for text of 18.66 px or bold 14 px or more)
//   busy        a button that waits (aria-busy) whose text is hidden or empty
//   buttons     buttons of one block with another letter, another height on the same line, or another left edge when stacked
//   escape      an element that goes beyond the box of its card / row / note (more than 1.5 px)
//   hscroll     a block that scrolls sideways without being a table declared with its own scroll, or the page itself
//   label       a line of text less than 8 px from the button beside it on the same line
//   rim         a box with a background or a border (card, fold, note, diff, row body, actions) with less than 8 px of padding on any side
//   formgap     sibling fields of ONE form row on the same line more than 48 px apart (the fields of a form go together, SvFormRow)
//   titlegap    the title of a block (h3 / .sv-tblock-title) closer than 8 px to the bar or the table that follows it (SvTableBlock gives 12)
//   formbase    the action button of a form row that does not sit on the base of the input of its row (more than 4 px of difference)
(function () {
	return function audit(options) {
		const opts = Object.assign({ contrast: true, edge: true }, options || {})
		const findings = []
		const counts = {}
		const add = (kind, el, info) => {
			counts[kind] = (counts[kind] || 0) + 1
			if (findings.length < 400) findings.push(Object.assign({ kind, at: sel(el) }, info))
		}
		const sel = el => {
			if (!el || !el.tagName) return ''
			let s = el.tagName.toLowerCase()
			if (el.id) s += '#' + el.id
			const c = (typeof el.className === 'string' ? el.className : '').trim().split(/\s+/).filter(Boolean).slice(0, 3)
			if (c.length) s += '.' + c.join('.')
			const a = el.getAttribute && (el.getAttribute('data-card') || el.getAttribute('data-part') || el.getAttribute('data-act'))
			if (a) s += '[' + a + ']'
			return s
		}
		const shown = el => {
			// what a closed <details> holds is not on the screen (the browser still gives it a box)
			for (let d = el.closest('details:not([open])'); d; d = d.parentElement && d.parentElement.closest('details:not([open])')) if (d !== el && !(el.closest('summary') && el.closest('summary').parentElement === d)) return false
			const r = el.getBoundingClientRect()
			if (r.width < 1 || r.height < 1) return false
			// what sits inside a 1 px box (the header of a table that becomes cards, visible to a screen reader only) is not on the screen
			for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) { const b = p.getBoundingClientRect(); if (b.width <= 1.5 && b.height <= 1.5) return false }
			const cs = getComputedStyle(el)
			return cs.visibility !== 'hidden' && cs.display !== 'none'
		}
		const box = el => el.getBoundingClientRect()
		const inter = (a, b) => Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left)) * Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top))

		// 1. overlap among the children of toolbars, rows and bars
		const holders = document.querySelectorAll('.sv-tv-bar, .sv-tv-find, .sv-tv-acts, .sv-tv-head, .sv-row, .sv-row-ctl, .sv-card-actions, .sv-tools, .roles-tools, .sv-card-head, .sv-seg, .sv-fgrid')
		holders.forEach(h => {
			const kids = Array.from(h.children).filter(shown)
			for (let i = 0; i < kids.length; i++) for (let j = i + 1; j < kids.length; j++) {
				const a = inter(box(kids[i]), box(kids[j]))
				if (a > 4) add('overlap', h, { a: sel(kids[i]), b: sel(kids[j]), px2: Math.round(a) })
			}
		})

		// 2. the action bars of cards
		document.querySelectorAll('.sv-card-actions').forEach(bar => {
			const bs = Array.from(bar.querySelectorAll(':scope > .v-btn, :scope > .sv-btn')).filter(shown)
			for (let i = 1; i < bs.length; i++) {
				const p = box(bs[i - 1]), q = box(bs[i])
				const stacked = q.top >= p.bottom - 1
				if (stacked && (Math.abs(p.left - q.left) > 0.5 || Math.abs(p.right - q.right) > 0.5)) add('actions', bar, { why: 'stacked buttons do not share the edges', left: [p.left, q.left], right: [p.right, q.right] })
				if (!stacked && Math.abs(p.height - q.height) > 0.5) add('actions', bar, { why: 'side by side with another height', h: [p.height, q.height] })
			}
		})

		// 3. what a row unfolds
		document.querySelectorAll('.sv-row-body').forEach(b => {
			if (!shown(b)) return
			const row = b.closest('.sv-row') || b.parentElement
			const r = box(row), x = box(b)
			if (x.left - r.left > 2) add('body', b, { why: 'does not start at the left edge of the row', offset: Math.round(x.left - r.left) })
			;[row.querySelector(':scope > .sv-row-main'), row.querySelector(':scope > .sv-row-ctl')].filter(Boolean).forEach(h => {
				if (shown(h) && inter(box(h), x) > 4) add('body', b, { why: 'intersects the head of the row', with: sel(h) })
			})
		})

		// 4/5/6. text: edges, cut and contrast
		const walker = document.createTreeWalker(document.querySelector('.sv-page') || document.body, NodeFilter.SHOW_TEXT)
		const seen = new Set()
		const parse = c => { const m = c.match(/rgba?\(([^)]+)\)/); if (!m) return null; const p = m[1].split(/[ ,/]+/).map(parseFloat); return [p[0], p[1], p[2], p.length > 3 && !isNaN(p[3]) ? p[3] : 1] }
		const over = (f, b) => [0, 1, 2].map(i => f[i] * f[3] + b[i] * (1 - f[3])).concat([1])
		const lum = c => { const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4) }; return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]) }
		const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05) }
		const effectiveBg = el => {
			const layers = []
			for (let e = el; e; e = e.parentElement) {
				const c = parse(getComputedStyle(e).backgroundColor)
				if (c && c[3] > 0) { layers.push(c); if (c[3] >= 1) break }
			}
			let base = [255, 255, 255, 1]
			if (!layers.length || layers[layers.length - 1][3] < 1) base = parse(getComputedStyle(document.body).backgroundColor) || [30, 30, 30, 1]
			if (base[3] < 1) base = over(base, [30, 30, 30, 1])
			return layers.reverse().reduce((b, l) => over(l, b), base)
		}
		const bordered = el => {
			for (let e = el.parentElement; e && e !== document.body; e = e.parentElement) {
				const cs = getComputedStyle(e)
				const has = ['Left', 'Right'].some(s => parseFloat(cs['border' + s + 'Width']) > 0 && cs['border' + s + 'Style'] !== 'none' && parse(cs['border' + s + 'Color'])[3] > 0)
				if (has && e.getBoundingClientRect().width > 60) return e
			}
			return null
		}
		let n
		while ((n = walker.nextNode())) {
			const el = n.parentElement
			if (!el || seen.has(el) || !n.nodeValue.trim() || !shown(el)) continue
			seen.add(el)
			const cs = getComputedStyle(el)
			if (el.closest('script,style,.sv-vh,[aria-hidden="true"]') && !opts.hidden) continue
			const range = document.createRange(); range.selectNodeContents(n)
			const tr = range.getBoundingClientRect()
			if (opts.edge) {
				const c = bordered(el)
				// the place of a text inside a block that scrolls sideways is anywhere: its edge says nothing
				let scrolls = false
				for (let p = el; c && p && p !== c.parentElement; p = p.parentElement) { const ox = getComputedStyle(p).overflowX; if (ox === 'auto' || ox === 'scroll') scrolls = true }
				if (c && !scrolls) {
					const cr = box(c)
					if (tr.right > cr.right + 1 || tr.left < cr.left - 1) { /* it is scrolled out of its box: not at its edge */ } else
					if (tr.left - cr.left < 12 && tr.left - cr.left >= -1 && tr.width > 0) add('edge', el, { gap: Math.round(tr.left - cr.left), container: sel(c), text: n.nodeValue.trim().slice(0, 30) })
					else if (cr.right - tr.right < 12 && cr.right - tr.right >= -1 && tr.width > 0 && cs.textAlign !== 'left' && !el.closest('.v-btn, .sv-btn, .v-chip')) add('edge', el, { gap: Math.round(cr.right - tr.right), side: 'right', container: sel(c), text: n.nodeValue.trim().slice(0, 30) })
				}
			}
			if (el.scrollWidth > el.clientWidth + 1 && cs.overflowX === 'visible' && cs.display !== 'inline') {
				const inScroller = el.closest('.sv-tv, .sv-diff, .roles-scroll, .sv-table-wrap, pre, [style*="overflow"]')
				if (!inScroller) add('cut', el, { scroll: el.scrollWidth, client: el.clientWidth, text: n.nodeValue.trim().slice(0, 30) })
			}
			if (opts.contrast && !el.closest('[disabled], .v-btn--disabled, [aria-disabled="true"]')) {
				const fg = parse(cs.color)
				if (fg) {
					const bg = effectiveBg(el)
					const f = over(fg, bg)
					const size = parseFloat(cs.fontSize), bold = parseInt(cs.fontWeight, 10) >= 700
					const need = size >= 24 * 0.7778 * 1 || (bold && size >= 14) ? 3 : 4.5
					const r = ratio(f, bg)
					if (r < need) add('contrast', el, { ratio: Math.round(r * 100) / 100, need, color: cs.color, bg: 'rgb(' + bg.slice(0, 3).map(Math.round).join(',') + ')', text: n.nodeValue.trim().slice(0, 30) })
				}
			}
		}

		// 7. buttons against the separators of their row, and neighbours glued together
		document.querySelectorAll('li.sv-row, .access-row, .access-version-row').forEach(row => {
			if (!shown(row)) return
			const rr = box(row)
			row.querySelectorAll('.sv-btn, .v-btn').forEach(b => {
				if (!shown(b)) return
				const x = box(b)
				if (x.top - rr.top < 6 || rr.bottom - x.bottom < 6) add('touch', b, { top: Math.round(x.top - rr.top), bottom: Math.round(rr.bottom - x.bottom), row: sel(row) })
			})
		})
		document.querySelectorAll('.sv-page .sv-btn, .sv-page .v-btn').forEach(b => {
			const nx = b.nextElementSibling
			if (!nx || !(nx.matches('.sv-btn, .v-btn')) || !shown(b) || !shown(nx)) return
			const p = box(b), q = box(nx)
			const sameLine = Math.abs(p.top - q.top) < p.height / 2
			if (sameLine && q.left - p.right < 6 && q.left - p.right > -1) add('gap', b, { gap: Math.round(q.left - p.right), next: sel(nx) })
		})

		// 9. the buttons of ONE block look like each other: the same letter and height, and, when they are stacked, the same left edge
		const btnSel = '.sv-btn, .v-btn:not(.v-btn--icon):not(.v-btn--fab), label.sv-file'
		document.querySelectorAll('.sv-row, .sv-card, .access-edit-block, .sv-panel, .sv-card-actions').forEach(block => {
			const bs = Array.from(block.querySelectorAll(btnSel)).filter(b => shown(b) && !b.closest('.sv-seg, .sv-select, .sv-how-terms, .roles-index, .sv-tv-acts, summary') && !b.classList.contains('sv-text'))
			for (let i = 1; i < bs.length; i++) {
				const p = bs[i - 1], q = bs[i]
				const sameRow = p.closest('.sv-row') && p.closest('.sv-row') === q.closest('.sv-row')
				if (p.parentElement !== q.parentElement && !sameRow) continue
				const cp = getComputedStyle(p), cq = getComputedStyle(q)
				const rp = box(p), rq = box(q)
				if (cp.fontSize !== cq.fontSize) add('buttons', block, { why: 'another letter', a: sel(p) + ' ' + cp.fontSize, b: sel(q) + ' ' + cq.fontSize })
				else if (Math.abs(rp.height - rq.height) > 0.5 && Math.abs(rp.top - rq.top) < 4) add('buttons', block, { why: 'another height on the same line', a: sel(p) + ' ' + rp.height, b: sel(q) + ' ' + rq.height })
				else if (rq.top >= rp.bottom - 1 && Math.abs(rp.left - rq.left) > 1) add('buttons', block, { why: 'stacked with another left edge', a: sel(p) + ' ' + Math.round(rp.left), b: sel(q) + ' ' + Math.round(rq.left) })
			}
		})

		// 10. nothing leaves its card: a visible child whose box goes beyond the box of the container with a border or a background (the numbers of a flow, an icon, a chip)
		document.querySelectorAll('.sv-card, .sv-how-node, .access-edit-block, .access-edit-row, .sv-panel, .sv-note, .sv-row').forEach(c => {
			if (!shown(c)) return
			const cr = box(c)
			c.querySelectorAll('*').forEach(e => {
				if (!shown(e) || e.matches('input[type=checkbox], input[type=radio]') || e.closest('.v-menu__content, .sv-select-list, .sv-sheet, .sv-veil') || getComputedStyle(e).position === 'fixed') return
				const r = box(e)
				const over = Math.max(cr.left - r.left, r.right - cr.right, cr.top - r.top, r.bottom - cr.bottom)
				if (over > 1.5 && r.width > 2 && r.height > 2 && !e.closest('.roles-scroll, .sv-tv, .sv-diff, pre')) add('escape', e, { over: Math.round(over), container: sel(c) })
			})
		})

		// 11. no block scrolls sideways unless it is a table declared with its own scroll (the roles matrix, the table of who can do what, the reader of a file), and the page itself never does
		const declared = '.v-data-table__wrapper, .roles-scroll, .can-table-wrap, .sv-table-wrap, .access-table-wrap, .sv-tv, .sv-seg, .roles-index, .sv-select-list, .v-menu__content, .sv-sheet-body'
		document.querySelectorAll('.sv-page *').forEach(e => {
			if (!shown(e) || e.closest(declared)) return
			const cs = getComputedStyle(e)
			if ((cs.overflowX === 'auto' || cs.overflowX === 'scroll') && e.scrollWidth > e.clientWidth + 1) add('hscroll', e, { scroll: e.scrollWidth, client: e.clientWidth })
		})
		if (document.documentElement.scrollWidth > window.innerWidth + 1) add('hscroll', document.documentElement, { scroll: document.documentElement.scrollWidth, client: window.innerWidth, why: 'the page scrolls sideways' })

		// 12. a text label (a line of text that is not a button) closer than 8 px to the button next to it on the same line, as "You edited it, go to lines:" glued to its first chip
		document.querySelectorAll('.sv-page *, .sv-sheet *').forEach(l => {
			if (l.matches('.sv-btn, .v-btn, button, input, label, select') || !shown(l) || !(l.textContent || '').trim()) return
			;[l.previousElementSibling, l.nextElementSibling].forEach(b => {
				if (!b || !b.matches('.sv-btn, .v-btn, button') || !shown(b)) return
				const p = box(l), q = box(b)
				if (Math.abs(p.top - q.top) > Math.max(p.height, q.height) / 2 + 6 && !(p.top < q.bottom && q.top < p.bottom)) return
				const gap = b === l.nextElementSibling ? q.left - p.right : p.left - q.right
				if (gap < 8 && gap > -1) add('label', l, { gap: Math.round(gap), button: sel(b), text: l.textContent.trim().slice(0, 30) })
			})
		})

		// 13. the rim: a box with a background or a border (a card, a fold, a note, a diff, the actions of a row) whose content is closer than 8 px to its edge on any side
		document.querySelectorAll('.sv-diff, .sv-note, .sv-card, .sv-fold-body, .sv-row-body, .sv-card-actions, .sv-panel').forEach(c => {
			if (!shown(c) || !c.children.length && !(c.textContent || '').trim()) return
			const cs = getComputedStyle(c)
			const framed = (parse(cs.backgroundColor) || [0, 0, 0, 0])[3] > 0 || ['Top', 'Right', 'Bottom', 'Left'].some(x => parseFloat(cs['border' + x + 'Width']) > 0 && cs['border' + x + 'Style'] !== 'none')
			if (!framed) return
			const pad = ['Top', 'Right', 'Bottom', 'Left'].map(x => parseFloat(cs['padding' + x]) || 0)
			if (Math.min.apply(null, pad) < 8) add('rim', c, { padding: pad.map(Math.round).join(' '), why: 'content closer than 8 px to the edge of its box' })
		})

		// 14. forms: the fields of a row stay together (siblings on one line, at most 48 px apart) and the action sits on the base of the inputs (4 px)
		const inputOf = f => f.querySelector('.sv-field, .v-input__slot, input:not([type=checkbox]):not([type=radio]), select, textarea') || f
		const isField = f => !f.matches('button, .v-btn, .sv-btn') && !!f.querySelector('input:not([type=checkbox]):not([type=radio]):not([type=hidden]), select, textarea') && shown(f)
		const isAct = f => (f.matches('button, .v-btn, .sv-btn') ? f : f.querySelector(':scope > button, :scope > .v-btn, :scope > .sv-btn')) && !f.querySelector('input, select, textarea') && shown(f)
		document.querySelectorAll('.sv-page *').forEach(h => {
			if (h.closest('.sv-tv, .v-data-table, table, .sv-sheet-body .sv-select-list')) return
			const kids = Array.from(h.children)
			const fields = kids.filter(isField)
			if (!fields.length) return
			const sameLine = (a, b) => Math.abs(box(a).top - box(b).top) < Math.max(24, Math.min(box(a).height, box(b).height) / 2)
			for (let i = 0; i < fields.length; i++) for (let j = i + 1; j < fields.length; j++) {
				const a = box(fields[i]), b = box(fields[j])
				if (!sameLine(fields[i], fields[j])) continue
				const gap = b.left >= a.right ? b.left - a.right : a.left - b.right
				if (gap > 48) add('formgap', h, { a: sel(fields[i]), b: sel(fields[j]), gap: Math.round(gap) })
			}
			kids.filter(isAct).forEach(act => {
				const btn = act.matches('button, .v-btn, .sv-btn') ? act : act.querySelector('button, .v-btn, .sv-btn')
				const near = fields.filter(f => sameLine(f, act))
				if (!near.length) return
				const diff = Math.abs(box(btn).bottom - box(inputOf(near[near.length - 1])).bottom)
				if (diff > 4) add('formbase', h, { button: sel(btn), field: sel(near[near.length - 1]), diff: Math.round(diff) })
			})
		})

		// 15. the title of a block is never glued to what follows it (the bar of its table, the table): at least 8 px
		document.querySelectorAll('.sv-page h3, .sv-page h4, .sv-page .sv-tblock-title').forEach(h => {
			if (!shown(h)) return
			let n = h.nextElementSibling
			while (n && !shown(n)) n = n.nextElementSibling
			if (!n) return
			const gap = box(n).top - box(h).bottom
			if (gap < 8 && gap > -1) add('titlegap', h, { next: sel(n), gap: Math.round(gap) })
		})

		// 8. a button that waits keeps its text
		document.querySelectorAll('[aria-busy="true"].sv-btn, [aria-busy="true"].v-btn').forEach(b => {
			const cs = getComputedStyle(b)
			const text = (b.innerText || '').trim()
			if (!text) add('busy', b, { why: 'no text' })
			b.querySelectorAll('*').forEach(c => { if (getComputedStyle(c).visibility === 'hidden' && (c.innerText || '').trim()) add('busy', b, { why: 'text hidden', child: sel(c) }) })
			void cs
		})

		return { counts, findings, url: location.href, width: window.innerWidth, scrolled: window.scrollY }
	}
})()
