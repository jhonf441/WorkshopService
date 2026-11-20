'use strict'

// What a person does in Start-up (Setup), ONE action object each. All of them are administrator writes the service does not ask to confirm
// itself: the page asks (level 3 dialog). After each one the blocks that depend on it are read again.
//
//   applyChanges.run(payload)    startup.apply     the ticked changes of the plan (buildPayload of package-wizard.js); level 3 dialog
//   restoreFile.run(args)        startup.integrity.restore   { path, expected_sha, apply: true }: the factory copy of a file; level 3 dialog
//   packageExport.run({ categories })    package.export    answers { name, data (base64), manifest, skipped }; one touch (it only reads)
//   packageApply.run({ data, replace })  package.apply     the package of another machine, file by file; level 3 dialog
//
// startup.apply answers `{ applied: [...], failed: [...], run_id }`: a refusal as a whole (busy board, a safety file not confirmed) arrives as an
// error with the sentence of the service; per-file failures are in `data.failed` (the screen draws them next to their file).

import { createAction } from '../store/action.js'
import { readiness, startupFiles, startupPlan, startupRuns } from '../resources.js'

const again = () => [startupPlan.reload(), startupFiles.reload(), readiness.reload(), startupRuns.reload()]

export const applyChanges = createAction({ op: 'startup.apply', group: 'setup', arm: 'dialog', after: again })
export const restoreFile = createAction({ op: 'startup.integrity.restore', group: 'setup', arm: 'dialog', after: again })
export const packageExport = createAction({ op: 'package.export', group: 'setup' })
export const packageApply = createAction({ op: 'package.apply', group: 'setup', arm: 'dialog', after: () => [startupFiles.reload()] })
