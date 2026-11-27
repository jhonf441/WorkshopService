'use strict'

// For every editor with Save / Cancel (see unsaved-guard.js). The component gives ONE method and may give three more:
//
//   unsavedPair()        [what is being edited, what is saved]: two values with the same shape; they are compared by content (a deep copy), so touching something and putting it back is no change
//   saveBeforeLeaving()  (optional) the Save of the editor, for "Save and leave": Promise<bool> (true = saved), or 'later' when it opens its own review dialog and then calls resumeLeave() / dropLeave()
//   discardUnsaved()     (optional) puts the draft back as saved
//   unsavedLabel()       (optional) what the dialog names ("profile Lights")
//
// It also remembers WHERE the editor got dirty (unsavedWhere, the place of the page) for the dialog.
// It gives the component:  hasUnsaved (the mark "Unsaved changes" and the highlighted Save button read it)  and  leaveWith(go): the way out of the editor itself
// (Back, Cancel, closing its dialog, Escape): go() runs at once when nothing changed, else the dialog asks first.
import { confirmLeave, currentSpot, registerGuard, sameContent } from './unsaved-guard.js'

export const unsavedMixin = {
	data() {
		return { unsavedWhere: null }
	},
	computed: {
		hasUnsaved() {
			const p = this.unsavedPair()
			return !sameContent(p[0], p[1])
		}
	},
	watch: {
		// where the person was when the draft got different from the saved one: the dialog names it and "Keep editing" goes back there
		hasUnsaved(now) {
			if (now) this.unsavedWhere = currentSpot() || this.unsavedWhere
		}
	},
	created() {
		this.unsavedWhere = currentSpot()
		this.unsavedOff = registerGuard({
			dirty: () => this.hasUnsaved,
			where: () => this.unsavedWhere,
			// shows the editor after "Keep editing": scrolled into view and ringed for two seconds (inline: no stylesheet, no motion)
			focus: () => {
				const el = this.$el
				if (!el || !el.style || typeof el.scrollIntoView !== 'function') return
				el.scrollIntoView({ block: 'center' })
				const before = el.style.boxShadow
				el.style.boxShadow = 'inset 0 0 0 2px var(--wf-focus)'
				setTimeout(() => { el.style.boxShadow = before }, 2000)
			},
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
