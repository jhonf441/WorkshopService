'use strict'

// What a person does in Connections, ONE action object each.
//
//   deleteCommands.run({ from, to })   history.delete   erases the commands received in a range of days; administrator; level 3 dialog of the page
//                                      (the service asks nothing). The list is read again afterwards by the screen.

import { createAction } from '../store/action.js'

export const deleteCommands = createAction({ op: 'history.delete', group: 'links', arm: 'dialog' })
