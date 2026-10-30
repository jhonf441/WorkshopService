// Copy to the clipboard: navigator.clipboard only exists on https/localhost;
// DWC over http://<pi-name>.local needs the textarea trick. Inside a dialog (Vuetify keeps the focus)
// the textarea has to go INSIDE the dialog: an element of the dialog is passed in `contenedor`.
export function copyText(text, container) {
	try {
		if (navigator.clipboard && window.isSecureContext) {
			return navigator.clipboard.writeText(text).then(() => true, () => copyOld(text, container));
		}
	} catch (e) {
		// sigue abajo
	}
	return Promise.resolve(copyOld(text, container));
}

function copyOld(text, container) {
	const t = document.createElement('textarea');
	t.value = text;
	t.style.position = 'fixed';
	t.style.top = '0';
	t.style.left = '0';
	t.style.width = '1px';
	t.style.height = '1px';
	t.style.opacity = '0';
	const padre = (container && container.isConnected ? container : null) || document.body;
	const before = document.activeElement;
	padre.appendChild(t);
	t.focus();
	t.select();
	t.setSelectionRange(0, text.length);
	let ok = false;
	try {
		ok = document.execCommand('copy');
	} catch (e) {
		ok = false;
	}
	padre.removeChild(t);
	if (before && before.focus) {
		try {
			before.focus();
		} catch (e) {
			// not critical
		}
	}
	return ok;
}
