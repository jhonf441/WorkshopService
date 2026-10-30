// <v-expand-transition> is not registered globally in DWC 3.7 (its core set only has the components DWC's own templates use).
// The pages use <ExpandTransition> from here: the Vuetify component when DWC exposes it to plugins, else Vue's plain Transition.
import { Transition } from 'vue'
import * as VuetifyComponents from 'vuetify/components'

export const ExpandTransition = VuetifyComponents.VExpandTransition || Transition
