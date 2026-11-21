<template>
	<!-- The service page: its shell. One low header (what it is, how the service is, who I am), ONE band for what changes how everything
	     is read, the sections, the tabs of the open section and its screen. The place lives in the address (?s=&t=&a=).
	     Every section is a folder of sections/: the shell tells it whether it is in view and which tab is open. -->
	<div class="sv-page workshop-theme" :data-w="width" :data-xl="px >= 1500 ? '1' : null" :data-cols="cols" :style="{ '--wf-badge': badge }">
		<header class="sv-head">
			<span class="sv-badge"><span class="mdi mdi-flash sv-ico" aria-hidden="true" /></span>
			<h1>{{ title }}</h1>
			<div class="sv-head-right">
				<a class="sv-chip" :data-level="status.level" :href="hrefOf({ s: 'home' })" :aria-label="t('shell.status_label', { text: status.text })" @click="follow($event, { s: 'home' })">
					<span class="mdi sv-ico sv-ico-s" :class="status.icon" aria-hidden="true" />{{ status.text }}
				</a>
				<button type="button" class="sv-chip sv-chip-line" :data-level="who.level" :aria-label="who.label" aria-haspopup="dialog" @click="onWho">
					<span class="mdi mdi-account-circle-outline sv-ico sv-ico-s" aria-hidden="true" />{{ who.text }}
				</button>
			</div>
		</header>
		<sv-band :level="band.level" :icon="band.icon" :title="band.title" :text="band.text" :alert="band.alert" />
		<div class="sv-layout">
			<sv-section-nav :entries="entries" :current="entry" :label="t('shell.nav_label')" :pick-label="t('shell.pick_section')" :count-label="countLabel" :fold-label="t('shell.nav_fold')" :open-label="t('shell.nav_open')" :pin-label="t('shell.nav_pin')" :unpin-label="t('shell.nav_unpin')" @go="goEntry" />
			<div class="sv-body">
				<sv-tabs :tabs="tabs" :value="at.t" :label="t('shell.tabs_label')" panel="sv-panel" @input="goTab" />
				<div id="sv-panel" :role="tabs.length > 1 ? 'tabpanel' : null" :aria-labelledby="tabs.length > 1 ? 'sv-panel-tab-' + at.t : null">
					<sv-zone v-if="cover" status="locked" :lock="cover" />
					<home-section v-show="at.s === 'home'" :active="page.active && at.s === 'home'" />
					<machine-section v-if="seenMachine && !cover" v-show="at.s === 'machine'" :active="page.active && at.s === 'machine'" :tab="at.t" />
					<data-section v-if="seenData && !cover" v-show="at.s === 'data'" :active="page.active && at.s === 'data'" :tab="at.t" />
					<setup-section v-if="seenSetup && !cover" v-show="at.s === 'setup'" :active="page.active && at.s === 'setup'" :tab="at.t" />
					<links-section v-if="seenLinks && !cover" v-show="at.s === 'links'" :active="page.active && at.s === 'links'" :tab="at.t" />
					<access-host v-if="seenAccess && adminOk && !cover" v-show="at.s === 'access'" :active="page.active && at.s === 'access'" :tab="at.t" />
					<security-host v-if="seenSecurity && adminOk && !cover" v-show="at.s === 'security'" :active="page.active && at.s === 'security'" :tab="at.t" />
					<health-section v-if="seenHealth && !cover" v-show="at.s === 'health'" :active="page.active && at.s === 'health'" :tab="at.t" :anchor="at.a" />
				</div>
			</div>
		</div>
		<session-section :open="page.section === 'session'" @close="closeSession" />
		<sv-unsaved-dialog />
	</div>
</template>

<script>
import { t, tc } from '../core/dwc.js'
import { pageState, widthOf } from '../core/page-state.js'
import { every, wake } from '../core/clock.js'
import { session, can, want, signIn, startSession, onSessionChange, recheckSession } from '../core/store/session.js'
import { setServiceDown } from '../core/store/resource.js'
import { serviceRunning, noteChanges } from '../core/live/published.js'
import { startHeartbeat } from '../core/live/heartbeat.js'
import { ADMIN_ENTRY, ADMIN_OP, entryOf, navEntries, sectionOf, tabsOf } from './places.js'
import { go, hrefOf, PATH, readPlace } from './url-sync.js'
import { placeOnActivation } from './scroll-home.js'
import { pluginBadge } from '../plugin-colors.js'
import { PLUGIN_ID } from '../plugin-id.js'
import HomeSection from '../sections/home/index.vue'
import { homeModel } from '../sections/home/model.js'
import SessionSection from '../sections/session/index.vue'
import HealthSection from '../sections/health/index.vue'
import MachineSection from '../sections/machine/index.vue'
import DataSection from '../sections/data/index.vue'
import SetupSection from '../sections/setup/index.vue'
import LinksSection from '../sections/links/index.vue'
import AccessHost from '../sections/access/index.vue'
import SecurityHost from '../sections/security/index.vue'
import SvBand from '../ui/SvBand.vue'
import SvSectionNav from '../ui/SvSectionNav.vue'
import SvTabs from '../ui/SvTabs.vue'
import SvZone from '../ui/SvZone.vue'
import SvUnsavedDialog from '../ui/SvUnsavedDialog.vue'
import { routeGuard } from '../ui/unsaved-guard.js'
import '../styles/tokens.css'
import '../styles/kit.css'
import '../styles/page.css'

const STATUS_ICONS = { ok: 'mdi-check-circle-outline', warn: 'mdi-alert-outline', error: 'mdi-close-circle-outline' }
const SIGNED_OUT = ['signed-out', 'signing-in', 'expired', 'pin-locked']

export default {
	name: 'ServicePage',
	components: { AccessHost, SecurityHost, HomeSection, HealthSection, MachineSection, DataSection, SetupSection, LinksSection, SessionSection, SvBand, SvSectionNav, SvTabs, SvZone, SvUnsavedDialog },
	// the words of the kit come from the catalogs of this page (area `kit`); a role id is said by its name
	provide() {
		return {
			svText: (key, params) => t('kit.' + key, params && params.role ? Object.assign({}, params, { role: this.roleName(params.role) }) : params),
			// how a screen moves the person: it never touches the address itself
			svNav: { go: place => go(place), href: place => hrefOf(place) },
			svSignIn: () => signIn()
		}
	},
	data() {
		return { page: pageState, session, px: 0, seenHealth: false, seenMachine: false, seenData: false, seenSetup: false, seenLinks: false, seenAccess: false, seenSecurity: false, under: { s: 'home', t: '', a: '' } }
	},
	computed: {
		title() {
			return t('plugins.WorkshopService.page.system_service')
		},
		badge() {
			return pluginBadge(PLUGIN_ID)
		},
		width() {
			return widthOf(this.px)
		},
		// two columns of cards: always when wide, and in the medium width only from 900 px
		cols() {
			return this.width === 'l' || (this.width === 'm' && this.px >= 900) ? '2' : null
		},
		running() {
			return serviceRunning()
		},
		// the place the page draws: My session is a sheet OVER the place that was open (the home, when the address opens the sheet directly)
		at() {
			const p = this.page
			return p.section === 'session' ? this.under : { s: p.section, t: p.tab, a: p.anchor }
		},
		mayAdmin() {
			return can(ADMIN_OP).state === 'ok'
		},
		// what the home says: its verdict is the ONE status chip, its rows are the counts of the navigation
		home() {
			return homeModel()
		},
		status() {
			const v = this.home.verdict
			return { level: v.level, icon: v.level ? STATUS_ICONS[v.level] || STATUS_ICONS.warn : 'mdi-help-circle-outline', text: tc('home.' + v.key, v.n) }
		},
		who() {
			const s = this.session
			if (s.state === 'resolving') return { level: null, text: t('shell.session_resolving'), label: t('shell.session_resolving') }
			// nobody can sign in while the file of people is damaged: the chip says so instead of offering it
			if (s.damaged) return { level: 'error', text: t('shell.session_damaged'), label: t('shell.session_label_damaged') }
			// the service did not say who the person is: the chip says so and asks again when touched
			if (s.unknown) return { level: 'warn', text: t('shell.session_unknown'), label: t('shell.session_label_unknown') }
			if (SIGNED_OUT.indexOf(s.state) >= 0) return { level: 'info', text: t('shell.session_sign_in'), label: t('shell.session_label_out') }
			if (!s.configured || s.usersOff || !s.name) return { level: null, text: t('shell.session_open'), label: t('shell.session_open') }
			const params = { name: s.name, role: this.roleName(s.roleName || s.role) }
			return { level: null, text: t('shell.session_who', params), label: t('shell.session_label', params) }
		},
		// ONE band, by priority: stopped > damaged > open mode or roles off > reconnecting
		band() {
			const s = this.session
			const make = (level, icon, key, alert, text) => ({ level, icon, alert, title: t('shell.band_' + key + '_title'), text: text || t('shell.band_' + key + '_text') })
			if (!this.running) return make('error', 'mdi-lan-disconnect', 'stopped', true)
			if (s.damaged) return make('error', 'mdi-file-alert-outline', 'damaged', true)
			const open = s.networkOpen ? ' ' + t('shell.band_network_open') : ''
			if (s.state === 'active' && s.usersOff) return make('warn', 'mdi-shield-off-outline', 'roles_off', false, t('shell.band_roles_off_text') + open)
			if (s.state === 'active' && !s.configured) return make('warn', 'mdi-shield-off-outline', 'open', false)
			if (this.page.retry) return make('warn', 'mdi-lan-pending', 'retry', false, t('shell.band_retry_text', this.page.retry))
			return { level: 'warn', icon: '', title: '', text: '', alert: false }
		},
		entries() {
			const out = SIGNED_OUT.indexOf(this.session.state) >= 0
			return navEntries(this.mayAdmin).map(e => {
				// what the current session cannot open carries a padlock on its icon (the person of the session, or the role); it stays a link to its cover
				const lock = out && e.id !== 'home' ? 'session' : e.locked ? 'role' : ''
				return {
					id: e.id, icon: e.icon, lock, href: hrefOf({ s: e.to }), name: t('shell.nav_' + e.id),
					lockLabel: lock === 'session' ? t('shell.nav_needs_session') : lock === 'role' ? t('shell.nav_needs_role', { role: this.roleName('admin') }) : '',
					count: e.id === ADMIN_ENTRY ? 0 : this.home.badges[e.id] || 0
				}
			})
		},
		entry() {
			return entryOf(this.at.s, this.mayAdmin)
		},
		tabs() {
			const s = this.at.s
			if (this.cover) return []
			return tabsOf(s).map(id => ({ id, name: t('shell.tab_' + s + '_' + id), href: hrefOf({ s, t: id }) }))
		},
		// a section only who administers can open: ONE cover with the cause, the role it needs and the way out
		// the screens of Administration are built only when the session and the role say yes: while it is being checked, or behind the cover, nothing asks
		adminOk() {
			return !this.session.damaged && can(ADMIN_OP).state === 'ok'
		},
		cover() {
			const s = sectionOf(this.at.s)
			if (!s || this.at.s === 'home') return null
			// nobody signed in: ONE cover for the whole place (no button: the chip of the header is the one way in) and the sections are not even built
			if (SIGNED_OUT.indexOf(this.session.state) >= 0 && !this.session.damaged) return { state: 'session', text: t('shell.cover_out_text', { what: t('shell.nav_' + this.entry) }), help: t('shell.cover_out_help'), fixed: true }
			if (!s.admin) return null
			if (this.session.damaged) return { state: 'role', title: t('shell.band_damaged_title'), text: t('shell.cover_damaged_text'), fixed: true }
			const c = can(ADMIN_OP)
			if (c.state === 'session') return { state: 'session', text: t('shell.cover_admin_out'), neededRole: 'admin' }
			if (c.state === 'role') return { state: 'role', text: t('shell.cover_admin_role', { role: this.roleName(this.session.roleName || this.session.role) }), neededRole: 'admin' }
			return null
		}
	},
	// an editor with unsaved changes: a change of section or tab, the Back button and DWC's own menu ask first (unsaved-guard.js); leaving by reload is the browser's message
	beforeRouteUpdate(to, from, next) {
		routeGuard(to, from, next)
	},
	beforeRouteLeave(to, from, next) {
		routeGuard(to, from, next)
	},
	watch: {
		'$route.query'() {
			if (this.$route && this.$route.path === PATH) readPlace()
		},
		running: { immediate: true, handler(now) { setServiceDown(!now) } }
	},
	created() {
		this.offs = [startSession(), onSessionChange(() => want([ADMIN_OP]))]
		want([ADMIN_OP])
		readPlace()
		this.$watch(() => [this.page.section, this.page.tab, this.page.anchor].join('|'), () => {
			if (this.page.section !== 'session') this.under = { s: this.page.section, t: this.page.tab, a: this.page.anchor }
			if (this.page.section === 'health') this.seenHealth = true
			if (this.page.section === 'machine') this.seenMachine = true
			if (this.page.section === 'data') this.seenData = true
			if (this.page.section === 'setup') this.seenSetup = true
			if (this.page.section === 'links') this.seenLinks = true
			if (this.page.section === 'access') this.seenAccess = true
			if (this.page.section === 'security') this.seenSecurity = true      // a screen is built the first time it is opened
		}, { immediate: true })
	},
	mounted() {
		this.measure()
		if (typeof window !== 'undefined') {
			this.onResize = () => this.measure()
			this.onVisible = () => { pageState.visible = !document.hidden; wake() }
			window.addEventListener('resize', this.onResize, { passive: true })
			document.addEventListener('visibilitychange', this.onVisible)
			if (typeof window.ResizeObserver === 'function' && this.$el && this.$el.parentElement) {
				this.observer = new window.ResizeObserver(() => this.measure())
				this.observer.observe(this.$el.parentElement)
			}
		}
		this.offs.push(every(1, now => noteChanges(now)), startHeartbeat(() => { const s = sectionOf(pageState.section); return !!(s && s.live) }))
		this.setActive(true)
	},
	// DWC keeps the page alive when the person goes to another one: it rests then (no clock, no heartbeat, no reads)
	activated() {
		this.setActive(true)
		if (this.$route && this.$route.path === PATH) readPlace()
		this.measure()
		this.place()
	},
	deactivated() {
		this.setActive(false)
	},
	beforeDestroy() {
		this.setActive(false)
		;(this.offs || []).forEach(off => { if (typeof off === 'function') off() })
		if (typeof window !== 'undefined') {
			window.removeEventListener('resize', this.onResize)
			document.removeEventListener('visibilitychange', this.onVisible)
		}
		if (this.observer) this.observer.disconnect()
	},
	methods: {
		t,
		hrefOf,
		signIn,
		setActive(on) {
			pageState.active = !!on
			if (!on && this.stopPlacing) this.stopPlacing()
			wake()
		},
		// the room the page really has: its own container, never the window (DWC's panels and the control bar take theirs)
		measure() {
			const el = this.$el
			this.px = (el && (el.clientWidth || (el.parentElement && el.parentElement.clientWidth))) || 0
		},
		// only here (the page was just opened): bring the header into view on a low screen. Never on a change of section, tab or data
		place() {
			const app = this.$vuetify && this.$vuetify.application
			if (this.stopPlacing) this.stopPlacing()
			this.stopPlacing = placeOnActivation(this.$el, { barTop: (app && app.top) || 0, anchor: pageState.anchor })
		},
		roleName(role) {
			return ['viewer', 'operator', 'technician', 'admin'].indexOf(role) >= 0 ? t('api.role_' + role) : String(role || '')
		},
		countLabel(n) {
			return tc('shell.count_label', n)
		},
		goEntry(id) {
			const e = navEntries(this.mayAdmin).find(x => x.id === id)
			if (e) go({ s: e.to })
		},
		goTab(id) {
			go({ s: this.at.s, t: id })
		},
		// a real link that stays in the page on a plain click
		follow(e, place) {
			if (e && (e.ctrlKey || e.metaKey || e.shiftKey || e.altKey || e.button > 0)) return
			if (e && typeof e.preventDefault === 'function') e.preventDefault()
			go(place)
		},
		// the chip opens My session; signed out it is the way in (the sheet would only repeat the button)
		onWho() {
			if (this.session.unknown) return recheckSession()
			if (!this.session.damaged && SIGNED_OUT.indexOf(this.session.state) >= 0) return signIn()
			go({ s: 'session' })
		},
		closeSession() {
			if (this.page.section === 'session') go(this.under, { replace: true })
		}
	}
}
</script>
