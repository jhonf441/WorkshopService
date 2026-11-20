'use strict'

// What the service says about the class of a file of the SD (startup.files, dsf/sd_files.py), for the Configuration package (PackageFileRow.vue).
// No Vue and no imports, so a test can feed it every case. The grouping, the filter, the counts and the state words are in package-view.js.
//
// A file:    { path, kind, status, state, used_by: [], safety, created_before?, breaks_if_missing? }

export const STATUSES = ['ok', 'edited', 'missing', 'not_yet', 'attention']
export const KINDS = ['workshop-owned', 'template', 'native-managed', 'generated', 'expected-external']

// Files the wizard will NOT recreate by itself (a template that was created once and deleted): the page says so on the row.
export function wontRecreate(file) {
	return file.kind === 'template' && file.status === 'missing' && !!file.created_before
}

// The key of the class text in the catalog (sd_files.kind_<kind>); an unknown one falls to null.
export function kindKey(file) {
	return KINDS.indexOf(file.kind) === -1 ? null : 'kind_' + file.kind
}
