<template>
	<!-- Access > Keys: create, change and revoke the keys of the external services (ApiKeys) and, under them, what each one reaches and its last use
	     (AccessKeys, read only). `operations` is the API description, for the operation pickers of the key dialog. -->
	<div class="access-keys-tab">
		<api-keys :operations="operations" />
		<access-keys :focus="focus" />
	</div>
</template>

<script>
'use strict'

import ApiKeys from './ApiKeys.vue'
import AccessKeys from './AccessKeys.vue'

export default {
	name: 'AccessKeysTab',
	components: { ApiKeys, AccessKeys },
	props: { focus: { type: Object, default: null }, operations: { type: Array, default: () => [] } }
}
</script>
