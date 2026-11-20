<template>
	<!-- Diagnostics > Load, at the foot: what THIS screen is (size, scale, browser, width class of the page), computed in the browser and ready to copy into a report, so
	     the data of the kiosk can be read without the developer tools. Read only: it asks nothing of the service. -->
	<section class="sv-card" aria-labelledby="sv-hs-title" data-card="screen">
		<div class="sv-card-head"><h2 id="sv-hs-title"><span class="mdi mdi-monitor-screenshot sv-ico" aria-hidden="true" />{{ t('health.screen_title') }}</h2></div>
		<div class="sv-row-ctl">
			<span class="sv-value" data-part="screen-line">{{ line }}</span>
			<sv-copy-button kind="screen" :label="t('health.screen_title')" :done="copied" @copy="copy" />
		</div>
	</section>
</template>

<script>
import { t } from '../../core/dwc.js'
import { timeNow } from '../../core/clock.js'
import { copyText } from '../../copy.js'
import SvCopyButton from '../../ui/SvCopyButton.vue'
import { screenOf } from './view.js'

export default {
	name: 'ScreenCard',
	components: { SvCopyButton },
	data() {
		return { info: screenOf({}), copiedAt: 0 }
	},
	computed: {
		// "Copied" for two seconds, counted with the clock of the page (no timer of its own)
		copied() {
			return this.copiedAt > 0 && timeNow() - this.copiedAt < 2000
		},
		line() {
			const i = this.info
			return t('health.screen_line', { w: i.width, h: i.height, ratio: i.ratio, browser: i.browser, dataW: i.dataW })
		}
	},
	mounted() {
		this.measure()
		window.addEventListener('resize', this.measure)
	},
	beforeDestroy() {
		window.removeEventListener('resize', this.measure)
	},
	methods: {
		t,
		measure() {
			const page = this.$el && this.$el.closest ? this.$el.closest('.sv-page') : null
			this.info = screenOf({ width: window.innerWidth, height: window.innerHeight, ratio: window.devicePixelRatio, ua: window.navigator.userAgent, dataW: page ? page.getAttribute('data-w') : '' })
		},
		async copy() {
			this.measure()
			await copyText(this.line, this.$el)
			this.copiedAt = timeNow()
		}
	}
}
</script>
