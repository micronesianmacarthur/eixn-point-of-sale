/**
 * Checks that the compiled stylesheet and the vendored assets actually cover
 * what the templates ask for. Wired into `npm run build`, because every one of
 * these failure modes is silent: the page still renders 200, it just arrives
 * unstyled, or with blank icons, or with a 404 that nobody notices until a shop
 * reports the till "looks broken".
 *
 * What it caught while this branch was being written:
 *   - vendoring css/solid.min.css alone, which contains no glyph rules at all
 *   - 29 modal backdrops using v3's bg-opacity-50, which v4 dropped
 *   - a stylesheet referencing a font that was never vendored
 */
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const templatesDir = join(root, 'backend', 'templates');
const staticDir = join(root, 'backend', 'static');
const appCss = join(staticDir, 'css', 'app.css');

const FA_STYLESHEETS = [
  'fontawesome/fontawesome.min.css',
  'fontawesome/solid.min.css',
];

const failures = [];
const fail = (message) => failures.push(message);

function htmlFiles(dir = templatesDir) {
  const found = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) found.push(...htmlFiles(path));
    else if (entry.name.endsWith('.html')) found.push(path);
  }
  return found;
}

const sources = htmlFiles().map((path) => ({ path, text: readFileSync(path, 'utf8') }));
const allTemplates = sources.map((source) => source.text).join('\n');

// ── 1. No remote assets ─────────────────────────────────────────────────────
const remoteTags = allTemplates.match(/(?:src|href)="(?:https?:)?\/\/[^"]+"/g) ?? [];
const remoteHosts = remoteTags
  .filter((tag) => !/w3\.org|schemas\./.test(tag))
  .map((tag) => tag.match(/\/\/([^/"]+)/)[1]);
if (remoteHosts.length) {
  fail(`templates still load remote assets from: ${[...new Set(remoteHosts)].join(', ')}`);
}

// ── 2. Every icon the templates use has a glyph rule ────────────────────────
// The glyph definitions live in css/fontawesome.min.css; css/solid.min.css is
// only the @font-face. Vendoring one without the other renders blank icons.
const faCss = FA_STYLESHEETS.map((rel) => readFileSync(join(staticDir, 'vendor', rel), 'utf8')).join('\n');
const glyphs = new Set([...faCss.matchAll(/\.(fa-[a-z0-9-]+):before/g)].map((m) => m[1]));
const iconsUsed = new Set([...allTemplates.matchAll(/\bfas\s+fa-([a-z0-9-]+)/g)].map((m) => `fa-${m[1]}`));
const iconsMissing = [...iconsUsed].filter((icon) => !glyphs.has(icon)).sort();
if (iconsMissing.length) {
  fail(
    `${iconsMissing.length} icon(s) used in templates have no glyph rule in the vendored ` +
      `Font Awesome CSS: ${iconsMissing.join(', ')}`,
  );
}

// ── 3. Every asset a vendored stylesheet points at was vendored too ─────────
const stylesheets = [
  { rel: 'css/app.css', css: readFileSync(appCss, 'utf8') },
  ...FA_STYLESHEETS.map((rel) => ({
    rel: `vendor/${rel}`,
    css: readFileSync(join(staticDir, 'vendor', rel), 'utf8'),
  })),
];
for (const { rel, css } of stylesheets) {
  for (const [, url] of css.matchAll(/url\(([^)"']+)\)/g)) {
    if (url.startsWith('data:')) continue;
    if (!existsSync(resolve(dirname(join(staticDir, rel)), url))) {
      fail(`${rel} references ${url}, which does not exist under backend/static`);
    }
  }
}

// ── 4. Every utility the templates use survived the v3 → v4 switch ──────────
// Tailwind only emits what it finds, and v4 dropped or renamed enough utilities
// that a rename in a template silently yields no CSS at all.
const appCssText = readFileSync(appCss, 'utf8');
const looksLikeUtility = /^(?:[a-z-]+:)*[a-z-]+-(?:\d|\[)/;
const asSelector = (token) => `.${token.replace(/([:/.%[\](),])/g, '\\$1')}`;
// A dictionary key such as 'border-red-500 ring-2 ring-red-200': in an Alpine
// object binding, plus the quotes from the surrounding JS. Only the edges come
// off: colons inside a token are variant prefixes (hover:bg-blue-600).
const clean = (token) => token.replace(/^[\"']+/g, '').replace(/[\"':]+$/g, '');
const candidates = new Set();
// Only class-bearing attributes. Harvesting every quoted string would pick up
// charset="utf-8" and similar, which are not utilities and not in the CSS.
const CLASS_ATTR = /(?:^|\s)(?::class|x-bind:class|class)="([^"]*)"/g;
const CLASSLIST_CALL = /classList\.(?:add|remove|toggle)\((['"])(.*?)\1/g;
for (const { text } of sources) {
  const withoutTags = text.replace(/\{%.*?%\}|\{\{.*?\}\}/gs, ' ');
  for (const [, attr] of withoutTags.matchAll(CLASS_ATTR)) {
    for (const token of attr.split(/\s+/)) candidates.add(clean(token));
  }
  for (const match of withoutTags.matchAll(CLASSLIST_CALL)) {
    for (const token of match[2].split(/\s+/)) candidates.add(clean(token));
  }
}
const missingUtilities = [...candidates].filter(
  (token) => looksLikeUtility.test(token) && !appCssText.includes(asSelector(token)),
);
if (missingUtilities.length) {
  fail(
    `${missingUtilities.length} utility class(es) used in templates are absent from ` +
      `static/css/app.css: ${missingUtilities.join(', ')}`,
  );
}

// ── Report ─────────────────────────────────────────────────────────────────
if (failures.length) {
  console.error('verify-static: FAILED');
  for (const message of failures) console.error(`  - ${message}`);
  process.exit(1);
}
console.log(
  `verify-static: OK — ${sources.length} templates, ${iconsUsed.size} icons, ` +
    `${candidates.size} class tokens, ${stylesheets.length} stylesheets, no remote assets ` +
    `(${relative(root, staticDir)} = ${relative(root, appCss)})`,
);