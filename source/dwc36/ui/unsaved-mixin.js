'use strict'

// For every editor with Save / Cancel (see unsaved-guard.js). The component gives ONE method and may give three more:
//
//   unsavedPair()        [what is being edited, what is saved]: two values with the same shape; they are compared by content (a deep copy), so touching something and putting it back is no change
//   saveBeforeLeaving()  (optional) the Save of the editor, for "Save and leave": Promise<bool> (true = saved), or 'later' when it opens its own review dialog and then calls resumeLeave() / dropLeave()
//   discardUnsaved()     (optional) puts the draft back as saved
//   unsavedLabel()       (optional) what the dialog names ("profile Lights")
//
// It gives the component:  hasUnsaved (the mark "Unsaved changes" and the highlighted Save button read it)  and  leaveWith(go): the way out of the editor itself
// (Back, Cancel, closing its dialog, Escape): go() runs at once when nothing changed, else the dialog asks first.
import { confirmLeave, registerGuard, sameContent } from './unsaved-guard.js'

export const unsavedMixin = {
	computed: {
		hasUnsaved() {
			const p = this.unsavedPair()
			return !sameContent(p[0], p[1])
		}
	},
	created() {
		this.unsavedOff = registerGuard({
			dirty: () => this.hasUnsaved,
			save: () => (typeof this.saveBeforeLeaving === 'function' ? Promise.resolve(this.saveBeforeLeaving()) : Promise.resolve(false)),
			discard: () => (typeof this.discardUnsaved === 'function' ? this.discardUnsaved() : undefined),
			label: () => (typeof this.unsavedLabel === 'function' ? this.unsavedLabel() : '')
		})
	},
	beforeDestroy() {
		if (this.unsavedOff) this.unsavedOff()
	},
	methods: {
		unsavedPair() {
			return [null, null]
		},
		leaveWith(go) {
			return confirmLeave(go)
		}
	}
}
