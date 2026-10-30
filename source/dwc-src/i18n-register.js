// Official DWC plugin localization: plugins.WorkshopService.* (DWC 3.7: registerPluginMessages, see PLUGINS.md).
// Import this file FIRST in index.js so the texts exist before any module that reads them at load time.
import { registerPluginMessages } from 'DuetWebControl'
import es from './i18n/es.json'
import en from './i18n/en.json'

registerPluginMessages('WorkshopService', { es, en })
