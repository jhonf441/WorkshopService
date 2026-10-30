<template>
	<div class="svc-spark">
		<div class="d-flex align-center text-caption grey--text" style="gap:8px">
			<span class="svc-spark-t">{{ title }}</span>
			<v-spacer />
			<span v-if="values.length > 1">{{ min }}&ndash;{{ max }} {{ unit }}</span>
			<b v-if="values.length" :style="{ color: color }">{{ last }} {{ unit }}</b>
		</div>
		<svg v-if="values.length > 1" :viewBox="'0 0 ' + width + ' ' + height" preserveAspectRatio="none" class="svc-spark-svg" :style="{ height: height + 'px' }">
			<polyline :points="area" :fill="color" fill-opacity="0.12" stroke="none" />
			<polyline :points="line" fill="none" :stroke="color" stroke-width="1.6" vector-effect="non-scaling-stroke" stroke-linejoin="round" />
		</svg>
		<div v-else class="text-caption grey--text svc-spark-empty" :style="{ height: height + 'px' }">{{ $t('plugins.WorkshopService.procDocs.ui_no_hist') }}</div>
	</div>
</template>

<script>
'use strict'

// Tiny line chart (no library) for the history of one metric: the title, the range and the last value.
export default {
	name: 'Spark',
	props: {
		values: { type: Array, default: () => [] },
		title: { type: String, default: '' },
		unit: { type: String, default: '' },
		color: { type: String, default: '#42A5F5' },
		height: { type: Number, default: 34 },
		decimals: { type: Number, default: 1 },
		minZero: { type: Boolean, default: true }
	},
	data() {
		return { width: 200 }
	},
	computed: {
		min() {
			return this.fmt(Math.min.apply(null, this.values))
		},
		max() {
			return this.fmt(Math.max.apply(null, this.values))
		},
		last() {
			return this.fmt(this.values[this.values.length - 1])
		},
		limits() {
			const it = this.minZero ? 0 : Math.min.apply(null, this.values)
			let hi = Math.max.apply(null, this.values)
			if (hi - it < 1e-9) hi = it + 1
			return { lo: it, hi }
		},
		points() {
			const n = this.values.length
			const { lo: it, hi } = this.limits
			return this.values.map((v, i) => {
				const x = n > 1 ? (i / (n - 1)) * this.width : 0
				const y = this.height - 2 - ((v - it) / (hi - it)) * (this.height - 4)
				return x.toFixed(1) + ',' + y.toFixed(1)
			})
		},
		line() {
			return this.points.join(' ')
		},
		area() {
			return '0,' + this.height + ' ' + this.points.join(' ') + ' ' + this.width + ',' + this.height
		}
	},
	methods: {
		fmt(v) {
			return Number(v).toFixed(this.decimals).replace(/\.0+$/, '')
		}
	}
};
</script>

<style scoped>
.svc-spark-svg {
	display: block;
	width: 100%;
	margin-top: 2px;
	border-radius: 4px;
	background: rgba(128, 128, 128, 0.08);
}
.svc-spark-empty {
	display: flex;
	align-items: center;
	margin-top: 2px;
}
.svc-spark-t {
	white-space: nowrap;
	overflow: hidden;
	text-overflow: ellipsis;
	min-width: 0;
}
</style>
