import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, '..');
const outDir = path.join(rootDir, 'dist-web');

function copyRecursive(src, dest) {
  if (!fs.existsSync(src)) return;
  const stat = fs.statSync(src);
  if (stat.isDirectory()) {
    fs.mkdirSync(dest, { recursive: true });
    for (const entry of fs.readdirSync(src)) {
      copyRecursive(path.join(src, entry), path.join(dest, entry));
    }
  } else {
    fs.mkdirSync(path.dirname(dest), { recursive: true });
    fs.copyFileSync(src, dest);
  }
}

console.log('[1/2] Compiling TypeScript workspace packages...');
const tscResult = spawnSync('npm', ['run', 'build'], {
  cwd: rootDir,
  stdio: 'inherit',
  shell: process.platform === 'win32'
});
if (tscResult.status !== 0) {
  throw new Error('TypeScript build failed');
}

console.log('[2/2] Assembling unified public static bundle in ./dist-web ...');
fs.rmSync(outDir, { recursive: true, force: true });
fs.mkdirSync(outDir, { recursive: true });

// 1. Web portal static assets (/favicon.svg, /og-banner.svg, /site/*)
copyRecursive(path.join(rootDir, 'apps/web-portal/public'), outDir);

// 2. Demo store static assets (/assets/*, /css/store.css, /js/store.js) & UI showcase screenshots
copyRecursive(path.join(rootDir, 'apps/coin-wallet-store/public'), outDir);
copyRecursive(path.join(rootDir, 'docs/assets'), path.join(outDir, 'assets'));

// 3. Checkout portal static assets (/css/checkout.css, /icons/*)
copyRecursive(path.join(rootDir, 'apps/checkout-portal/public'), outDir);

// 4. Merchant admin self-hosted fonts & companion APK (/fonts/*, /youpi-sms-gateway.apk*)
copyRecursive(path.join(rootDir, 'apps/merchant-admin/public'), outDir);

// 5. OpenAPI YAML specification (/openapi.yaml)
copyRecursive(path.join(rootDir, 'openapi.yaml'), path.join(outDir, 'openapi.yaml'));

console.log('[✓] Static bundle ready in ./dist-web');
