'use strict'

// What the screens that change a person or a group share before they open the confirmation dialog: ask the service for the dry run of the change
// (access-precheck.js) and, when it would be refused, show its sentence on the card instead of opening the dialog.
//
//   mixins: [askMixin]       this.refused (the sentence, '' = none)   await this.passes(change) -> true when the dialog may open

import { accessApi } from './access-api.js'
import { precheck } from './access-precheck.js'

export const askMixin = {
	data() {
		return { refused: '', checking: false }
	},
	methods: {
		async passes(change) {
			this.refused = ''
			this.checking = true
			try {
				this.refused = await precheck(accessApi, change)
			} finally {
				this.checking = false
			}
			return !this.refused
		}
	}
}
