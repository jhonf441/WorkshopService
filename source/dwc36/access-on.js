'use strict'

// Is the access control (users and roles) ON for this machine? The answer is the one auth.whoami already gives every page (workshop-auth.js currentIdentity): `configured` is true only when the
// service has users and they are enabled; with no users, or with the users switched off, the machine is open (everybody is admin, `configured: false`) and no role is asked of anybody.
// Pure over the identity it is given, so a test can load it without the service. Display only: it never decides what a person may do (the service and workshopCan do).
import { currentIdentity } from './workshop-auth.js'

export function accessOnFor(identity) {
	return !!(identity && identity.configured === true)
}

export function accessOn() {
	return accessOnFor(currentIdentity())
}
