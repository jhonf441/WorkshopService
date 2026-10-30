'use strict'

// Texts the WorkshopService publishes on its own (plugin data): {key, params} -> the text in the language of this DWC.
// The service never renders them: two viewers with different languages each see their own. The templates are a copy of
// the published keys of the service (area "svc" of vue/_shared/i18n, synced by tools/sync_service_texts.py; the numbers
// already come formatted). A plain string (data of an older service) is shown as it is.
// Same logic in src/_shared/06-service-text.js (JS plugins) and WorkshopService/dwc-src/service-text.js: keep them equal.
import i18n from '../../i18n'
import { PLUGIN_ID } from './plugin-id.js'

export function serviceText(v) {
	if (v === null || v === undefined) {
		return '';
	}
	if (typeof v !== 'object') {
		return String(v);
	}
	if (Array.isArray(v)) {
		return v.map(serviceText).join(', ');
	}
	const p = v.params || {};
	if (v.key === '_raw') {
		return String((String(i18n.locale || 'es').startsWith('es') ? p.es : p.en) || p.es || '');
	}
	if (v.key === '_join') {
		return (p.items || []).map(serviceText).join(p.sep === null || p.sep === undefined ? ', ' : p.sep);
	}
	if (!v.key) {
		return '';
	}
	const q = {};
	Object.keys(p).forEach(k => {
		q[k] = p[k] !== null && typeof p[k] === 'object' ? serviceText(p[k]) : p[k];
	});
	const path = 'plugins.' + PLUGIN_ID + '.svc.' + v.key;
	return i18n.te(path) || i18n.te(path, 'es') ? i18n.t(path, q) : v.key;
}

// A message as published: an object with exactly "key" and "params" (other objects with a "key" field are data).
export function isServiceMessage(v) {
	return !!v && typeof v === 'object' && !Array.isArray(v) && typeof v.key === 'string' && Object.keys(v).length === 2 && 'params' in v;
}

// The same structure with every message replaced by its text (for pages that read a whole published object).
export function serviceTexts(v) {
	if (isServiceMessage(v)) {
		return serviceText(v);
	}
	if (Array.isArray(v)) {
		return v.map(serviceTexts);
	}
	if (v && typeof v === 'object') {
		const out = {};
		Object.keys(v).forEach(k => {
			out[k] = serviceTexts(v[k]);
		});
		return out;
	}
	return v;
}

// A name the user can change whose factory value is one of the service keys `keys` (live job, light scenes, zones...):
// serviceDefaultKey gives the key whose Spanish or English text it still is (case and spaces aside; the first key for an
// empty name), or null for a name the person or the program gave.
export function serviceDefaultKey(value, keys) {
	const v = String(value === null || value === undefined ? '' : value).trim().toLowerCase();
	const list = [].concat(keys || []);
	if (!v) {
		return list.length ? list[0] : null;
	}
	const base = 'plugins.' + PLUGIN_ID + '.svc.';
	return list.find(k => v === String(i18n.t(base + k, 'es')).trim().toLowerCase() || v === String(i18n.t(base + k, 'en')).trim().toLowerCase()) || null;
}

// The name to show: a default one in the language of this DWC, any other as it is.
export function serviceDefaultName(value, keys) {
	const k = serviceDefaultKey(value, keys);
	return k ? String(i18n.t('plugins.' + PLUGIN_ID + '.svc.' + k)) : String(value === null || value === undefined ? '' : value).trim();
}
