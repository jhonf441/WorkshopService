'use strict'

// What a person does with the database and its backups (Data and backups), ONE action object each. The service answers `{ ok, ... }`
// (shape okflag: a refusal is thrown) and the status is read again afterwards, so the screen shows what the service holds now.
// One write at a time (group `db`: a backup blocks the other changes of the service while it runs).
//
//   dbBackup.run()                       db.backup        a backup now; synchronous, may take a while; answers { file, mb }
//   dbSettings.run({ auto, daily, weekly, extra_copy, summarize })   db.settings   saved by block, never on change
//   dbKeep.run({ file, keep })           db.keep          keep a backup from the automatic cleaning / let it go; reversible, one touch
//   dbFolder.run({ path })               db.folder        move the backups to another place; level 3 dialog of the page ("N will be copied")
//   dbDeletePrevious.run()               db.delete_previous   delete the copies left in the former folder; level 3 dialog of the page

import { createAction } from '../store/action.js'
import { dbStatus, dbPlaces } from '../resources.js'

const again = () => [dbStatus.reload()]

export const dbBackup = createAction({ op: 'db.backup', group: 'db', after: again })
export const dbSettings = createAction({ op: 'db.settings', group: 'db', after: again })
export const dbKeep = createAction({ op: 'db.keep', group: 'db', after: again })
export const dbFolder = createAction({ op: 'db.folder', group: 'db', arm: 'dialog', after: () => { dbPlaces.clear(); return again() } })
export const dbDeletePrevious = createAction({ op: 'db.delete_previous', group: 'db', arm: 'dialog', after: again })
