'use strict'

// The pieces a page needs to guard a dangerous control, in ONE import: the double-tap button (ArmButton.vue), the chip group made of them (ArmChips.vue),
// the error card of a failed call (ErrorNotice.vue) and the pure rules (arm-levels.js).
export { default as ArmButton } from './ArmButton.vue'
export { default as ArmChips } from './ArmChips.vue'
export { default as ErrorNotice } from './ErrorNotice.vue'
export { ACTION_LEVELS, ARM_MS, needsArming, failureOf, resultText } from './arm-levels.js'
