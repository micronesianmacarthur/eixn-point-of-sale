/**
 * Copies the third-party browser assets out of node_modules into
 * backend/static/vendor/ so that a deployed POS needs nothing but Python and
 * Django: no CDN, no node, no network. Re-run via `npm run vendor` after
 * bumping a version in package.json.
 */
import { cpSync, mkdirSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const modules = join(root, 'node_modules');
const vendor = join(root, 'backend', 'static', 'vendor');

// Only the solid family is used in the templates (fas), so the regular and
// brands webfonts are left out — they are ~300 kB for icons nobody renders.
const COPIES = [
  ['htmx.org/dist/htmx.min.js', 'htmx/htmx.min.js'],
  ['alpinejs/dist/cdn.min.js', 'alpine/alpine.min.js'],
  // Pinned to 2.8.0 because the dashboard chart is written against the 2.x API;
  // 3.x/4.x renamed most of it.
  ['chart.js/dist/Chart.min.js', 'chartjs/Chart.min.js'],
  [
    // The glyph definitions (.fa-cash-register:before { content: "\f7fa" } …,
    // ~1950 of them) live here, NOT in solid.min.css. Vendoring only
    // solid.min.css gives you the @font-face and a font-weight rule but no
    // icon shapes at all — every <i class="fas fa-…"> renders blank.
    '@fortawesome/fontawesome-free/css/fontawesome.min.css',
    'fontawesome/fontawesome.min.css',
  ],
  [
    // …whereas solid.min.css is only the @font-face for the free solid family
    // plus .fas { font-weight: 900 }. Both files are required.
    '@fortawesome/fontawesome-free/css/solid.min.css',
    'fontawesome/solid.min.css',
  ],
  // solid.min.css asks for ../webfonts/fa-solid-900.woff2, so the font has to
  // land one level up from the stylesheet.
  [
    '@fortawesome/fontawesome-free/webfonts/fa-solid-900.woff2',
    'webfonts/fa-solid-900.woff2',
  ],
  [
    '@fontsource-variable/inter/files/inter-latin-wght-normal.woff2',
    'fonts/inter-latin-wght-normal.woff2',
  ],
];

rmSync(vendor, { recursive: true, force: true });

for (const [from, to] of COPIES) {
  const source = join(modules, from);
  const target = join(vendor, to);
  mkdirSync(dirname(target), { recursive: true });
  cpSync(source, target);
  const kb = Math.round(statSync(target).size / 1024);
  console.log(`${to.padEnd(40)} ${kb} kB`);
}

// Font Awesome lists a .ttf next to the .woff2 in every @font-face src. We only
// ship the woff2 (~153 kB vs ~600 kB), so drop the truetype alternate instead of
// leaving a stylesheet that 404s on a resource no modern browser will request.
const solidCss = join(vendor, 'fontawesome', 'solid.min.css');
const original = readFileSync(solidCss, 'utf8');
const pruned = original.replace(/,url\([^)]*\)\s*format\("truetype"\)/g, '');
if (pruned === original) {
  throw new Error(
    'vendor-static: no format("truetype") fallback found in solid.min.css — ' +
      'Font Awesome may have changed its @font-face src list.',
  );
}
writeFileSync(solidCss, pruned);
console.log(`${'fontawesome/solid.min.css'.padEnd(40)} truetype fallback pruned`);