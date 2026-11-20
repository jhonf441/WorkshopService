'use strict'

// "Show me this object in Access": Security (the review, the report) asks the Access section to open a tab and, when it names one, a profile, a
// person or a key. The two sections do not know each other: the request lives here, and the address (the tab) is moved by whoever asks.
//
//   accessGo               { tab, name, id, n }  the last request; n grows with every request so asking twice for the same object shows it twice
//   askAccess(request)     { tab, name?, id? }   records the request (nextGo of access-go.js)

import Vue from 'vue'
import { nextGo } from '../../access-go.js'

export const accessGo = Vue.observable({ tab: '', name: '', id: '', n: 0 })

export function askAccess(request) {
	Object.assign(accessGo, nextGo(accessGo, request))
}
