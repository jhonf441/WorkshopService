// Official DWC plugin localization: plugins.WorkshopService.* (see src/i18n/index.ts of DuetWebControl).
// Import this file FIRST in index.js so the texts exist before any module that reads them at load time.
import { registerPluginLocalization } from '../../i18n'
import is from './i18n/es.json'
import en from './i18n/en.json'
import './language-reload.js' // the page loads again when the DWC language changes

registerPluginLocalization('WorkshopService', 'es', is)
registerPluginLocalization('WorkshopService', 'en', en)
