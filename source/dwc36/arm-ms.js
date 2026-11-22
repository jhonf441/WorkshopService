'use strict'

// THE time a first tap of a double tap stays armed (DESIGN.md section 5, level 2: heating, moving, deleting). One value for the whole family:
// the plugins import it from here, the service page has a twin of this file (dwc36/arm-ms.js) and the hand-written JS plugins have the same number in
// src/_shared/00-arm.js. tests/arm-ms.test.js fails when any arm constant of the repo holds another value.
export const ARM_MS = 4000
