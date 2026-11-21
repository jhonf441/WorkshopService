<template>
	<!-- What the typed password has: a meter of 4 levels (the WORD says it, the colour only helps), the requirements with a check or a cross, and the
	     suggestion of a long phrase. Pure drawing: the page computes `level` (0 to 3) and `reqs` ([{ id, ok }]) with password-policy.js. Nothing here keeps the password. -->
	<div class="sv-pwm" :class="{ 'sv-pwm-idle': !typed }">
		<div class="sv-pwm-line">
			<span class="sv-pwm-bar" role="img" :aria-label="label" :data-level="level"><i v-for="n in 4" :key="n" :class="{ on: typed && n <= level + 1 }" /></span>
			<span class="sv-pwm-word" aria-live="polite">{{ typed ? label : $t('plugins.WorkshopService.servicePage.pw_meter_idle') }}</span>
		</div>
		<ul class="sv-pwm-reqs">
			<li v-for="r in reqs" :key="r.id" :class="r.ok ? 'sv-pwm-ok' : 'sv-pwm-no'">
				<span class="mdi" :class="r.ok ? 'mdi-check-circle-outline' : 'mdi-close-circle-outline'" aria-hidden="true" />
				<span class="sv-pwm-sr">{{ $t('plugins.WorkshopService.servicePage.' + (r.ok ? 'pw_met' : 'pw_not_met')) }}: </span>{{ $t('plugins.WorkshopService.servicePage.pw_req_' + r.id, { min: min, max: max }) }}
			</li>
		</ul>
		<div class="text-caption sv-prose">{{ $t('plugins.WorkshopService.servicePage.pw_suggest') }}</div>
	</div>
</template>

<script>
// Props: level (0 very weak ... 3 strong), typed (something was typed), reqs ([{ id, ok }]), min, max (the limits of the policy).
export default {
	name: 'PasswordMeter',
	props: {
		level: { type: Number, default: 0 },
		typed: { type: Boolean, default: false },
		reqs: { type: Array, default: () => [] },
		min: { type: Number, default: 10 },
		max: { type: Number, default: 60 }
	},
	computed: {
		label() { return this.$t('plugins.WorkshopService.servicePage.pw_level_' + this.level) }
	}
}
</script>

<style>
.sv-pwm { display: grid; gap: 8px; margin-top: 12px; max-width: 520px; }
.sv-pwm-line { display: flex; align-items: center; gap: 12px; }
.sv-pwm-bar { display: flex; gap: 4px; flex: 0 0 160px; }
.sv-pwm-bar i { flex: 1; height: 6px; border-radius: 3px; background: var(--wf-line-strong); }
.sv-pwm-bar[data-level='0'] i.on { background: var(--wf-c-error-text); }
.sv-pwm-bar[data-level='1'] i.on { background: var(--wf-c-warning-text); }
.sv-pwm-bar[data-level='2'] i.on { background: var(--wf-accent); }
.sv-pwm-bar[data-level='3'] i.on { background: var(--wf-c-success-text); }
.sv-pwm-word { font-weight: 600; font-size: var(--sv-f-2); }
.sv-pwm-reqs { display: grid; gap: 2px; margin: 0; padding: 0; list-style: none; font-size: var(--sv-f-2); }
.sv-pwm-reqs li { display: flex; align-items: center; gap: 8px; }
.sv-pwm-ok { color: var(--wf-c-success-text); }
.sv-pwm-no { color: var(--sv-text-2); }
.sv-pwm-sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
</style>
