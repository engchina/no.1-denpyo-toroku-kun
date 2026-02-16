import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(scriptDir, '..');
const lintTarget = 'src/**/*.{ts,tsx}';
const forwardedArgs = process.argv.slice(2);

const eslintBin = path.join(projectRoot, 'node_modules', 'eslint', 'bin', 'eslint.js');
const tsParserDir = path.join(projectRoot, 'node_modules', '@typescript-eslint', 'parser');
const tsPluginDir = path.join(projectRoot, 'node_modules', '@typescript-eslint', 'eslint-plugin');
const tscBin = path.join(projectRoot, 'node_modules', 'typescript', 'bin', 'tsc');

const run = (command, args) => {
  const result = spawnSync(command, args, {
    cwd: projectRoot,
    stdio: 'inherit'
  });

  if (result.error) {
    console.error(`[lint] Failed to run ${command}: ${result.error.message}`);
    process.exit(1);
  }

  process.exit(result.status ?? 1);
};

if (existsSync(eslintBin) && existsSync(tsParserDir) && existsSync(tsPluginDir)) {
  run(process.execPath, [eslintBin, lintTarget, ...forwardedArgs]);
}

if (!existsSync(tscBin)) {
  console.error('[lint] Missing eslint deps and TypeScript compiler. Run npm install when network is available.');
  process.exit(1);
}

if (forwardedArgs.includes('--fix')) {
  console.warn('[lint] eslint dependencies are missing, `--fix` is skipped. Running type-check fallback.');
} else {
  console.warn('[lint] eslint dependencies are missing. Running type-check fallback.');
}

run(process.execPath, [tscBin, '--noEmit']);
