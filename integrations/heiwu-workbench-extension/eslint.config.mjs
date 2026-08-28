import antfu from '@antfu/eslint-config';

export default antfu({
	stylistic: {
		indent: 'tab',
		quotes: 'single',
		semi: true,
	},
	typescript: true,
	ignores: ['build/dist/', 'dist/', 'node_modules/', '.eslintcache'],
}, {
	files: ['tests/**/*.mjs'],
	rules: {
		'test/no-import-node-test': 'off',
	},
});
