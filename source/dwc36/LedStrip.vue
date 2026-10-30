<!-- 	The status zone as seen on the physical strip: ONE line, one dot per LED.
	It is the only way to draw it on the Vue pages (Lights, Services), and an
	exact copy of _shared/25-led-state.js (sidebar, jog), so all
	screens look the same. If you change the color or the size, change it in
	both. WorkshopService/dwc-src/LedStrip.vue is a copy of this file.
	segs = [[hex, level 0..1, count], ...] (plugins.WorkshopService.data
	statusLightSecs / statusLightModes, computed by the Pi). -->
<template>
	<span ref="led_strip" class="led-strip" :style="style" :title="title" />
</template>

<script>
import i18n from '../../i18n'

const shutdown = 'rgba(40,40,40,0.9)';

// an LED with little brightness still looks on (as on the strip)
export function ledColor(s) {
	if (!(s[1] > 0)) {
		return shutdown;
	}
	const h = String(s[0]).replace('#', '');
	const a = 0.6 + 0.4 * Math.sqrt(Math.min(1, s[1]));
	return `rgba(${parseInt(h.substr(0, 2), 16)},${parseInt(h.substr(2, 2), 16)},${parseInt(h.substr(4, 2), 16)},${a})`;
}

// Scalable strip (2026-10-10): a single element; each LED takes 1/N of the width
// (10 or 1000 LEDs, never overflows). Separators on top while they fit
// (>= 4 px per LED); with less room, a continuous bar with the real proportion.
// Copy of tiraEstilo in _shared/25-led-state.js.
export function stripStyle(secs, width) {
	const total = secs.reduce((t, s) => t + s[2], 0);
	if (!total) {
		return { backgroundImage: 'none' };
	}
	let pos = 0;
	const parts = [];
	secs.forEach(s => {
		const c = ledColor(s);
		parts.push(`${c} ${(pos / total * 100).toFixed(2)}%`, `${c} ${((pos + s[2]) / total * 100).toFixed(2)}%`);
		pos += s[2];
	});
	const layers = [];
	if ((width || 200) / total >= 4) {
		const g = (width || 200) / total >= 9 ? 2 : 1;
		const step = `calc(100% / ${total})`;
		layers.push(`repeating-linear-gradient(90deg, transparent 0, transparent calc(${step} - ${g}px), rgba(0,0,0,0.85) calc(${step} - ${g}px), rgba(0,0,0,0.85) ${step})`);
	}
	layers.push(`linear-gradient(90deg,${parts.join(',')})`);
	const lit = secs.find(s => s[1] > 0);
	return { backgroundImage: layers.join(','), boxShadow: lit ? '0 0 5px ' + ledColor(lit) : 'none' };
}

export default {
	props: {
		secs: { type: Array, default: () => [] }
	},
	data() {
		return { width: 0 };
	},
	computed: {
		clean() {
			return (this.secs || []).filter(s => s[2] > 0);
		},
		style() {
			return stripStyle(this.clean, this.width);
		},
		title() {
			const total = this.clean.reduce((t, s) => t + s[2], 0);
			const on = this.clean.reduce((t, s) => t + (s[1] > 0 ? s[2] : 0), 0);
			return i18n.t('plugins.WorkshopService.ledStrip.n_leds_m_on', { n: total, m: on });
		}
	},
	mounted() {
		this.width = this.$refs.led_strip.clientWidth;
		if (typeof ResizeObserver === 'function') {
			this.ro = new ResizeObserver(() => { this.width = this.$refs.led_strip ? this.$refs.led_strip.clientWidth : 0; });
			this.ro.observe(this.$refs.led_strip);
		}
	},
	beforeDestroy() {
		if (this.ro) {
			this.ro.disconnect();
		}
	}
};
</script>

<style scoped>
.led-strip {
	display: block;
	width: 100%;
	min-width: 0;
	height: 8px;
	border-radius: 4px;
	background-repeat: no-repeat;
}
</style>
