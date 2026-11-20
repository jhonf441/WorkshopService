'use strict'

// What the key screens share: how an entry of a key (a capability, an operation or a pattern) is named and described, and how typed patterns are
// normalised. ApiKeys (the list) and ApiKeyForm (the fields of the dialog) both use it; they need `catalog` (roles.list capabilities) and `operations`
// (api.describe) as data or props. The prefix and the titles come from key-names.js.

import { capOf, capTitle, classKey, isCap } from './key-names.js'

function list(txt) {
	return String(txt || '').split(/[\s,]+/).map(x => x.trim().toLowerCase()).filter(Boolean)
}

// the lists of the dialog are arrays (chips): the typed patterns are normalised like the text before
export function normPatterns(v) {
	return Array.isArray(v) ? [...new Set(v.map(x => String(x).trim().toLowerCase()).filter(Boolean))] : list(v)
}

export const keyNamesMixin = {
	methods: {
		nameClass(c) { return this.$t('plugins.WorkshopService.' + classKey(c)) },
		isCap,
		capOf(e) { return capOf(this.catalog, e) },
		capTitle(e) { return capTitle(this.catalog, e) },
		// only a capability that is delegable and not of the administration class can be allowed to a key (the service checks it again)
		capGrantable(id) { const c = this.catalog.find(x => x.id === id); return !!c && c.delegable && c.class !== 'admin' },
		// what an entry is: a capability (its title and the operations it groups), an operation (its description) or a pattern
		descriptionOp(p) {
			if (this.isCap(p)) {
				const c = this.capOf(p)
				return c ? this.$t('plugins.WorkshopService.keys.cap_chip') + ': ' + c.title + ' (' + c.ops.join(', ') + ')' : p
			}
			const o = this.operations.find(x => x.op === p)
			return o ? (o.desc || p) : this.$t('plugins.WorkshopService.keys.cap_pattern_hint')
		}
	}
}
