import process from 'node:process';
import esbuild from 'esbuild';

import common from './esbuild.common';

(async () => {
	const localGateway = process.argv.includes('--local');
	const context = await esbuild.context({
		...common,
		define: {
			...common.define,
			__WORKBENCH_LOCAL_GATEWAY__: JSON.stringify(localGateway),
		},
		outdir: localGateway ? './dist-local/' : common.outdir,
	});
	if (process.argv.includes('--watch')) {
		await context.watch();
	}
	else {
		await context.rebuild();
		await context.dispose();
	}
})();
