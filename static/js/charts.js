// Declarative, daisyUI-themed ApexCharts.
//
// Markup contract (no JS in templates):
//
//   <div class="chart-panel">
//     <script type="application/json" data-chart-config>
//       { "type": "area", "series": [...], "options": { ... } }
//     </script>
//     <div data-chart></div>
//   </div>
//
// `[data-chart]` is the render target; its sibling `[data-chart-config]` holds the
// series + any ApexCharts option overrides. We merge those over a theme baseline read
// from the daisyUI CSS variables on <html>, and re-read + re-render every chart when
// the admin switches the theme (the console mutates <html data-theme>).

const root = document.documentElement;

// Resolve a CSS color expression to a serialized `rgb(...)` string. daisyUI 5 emits
// colors in oklch; painting them onto a probe and reading back `color` yields rgb in
// every browser, which sidesteps any oklch-in-SVG rendering quirk.
function resolveColor(expr) {
  const probe = document.createElement('span');
  probe.style.color = expr;
  probe.style.display = 'none';
  document.body.appendChild(probe);
  const rgb = getComputedStyle(probe).color;
  probe.remove();
  return rgb;
}

function cssVar(name) {
  return getComputedStyle(root).getPropertyValue(name).trim();
}

// A CSS var painted through resolveColor, so callers get rgb regardless of source space.
function themeColor(name) {
  return resolveColor(`var(${name})`);
}

function remToPx(value) {
  const n = Number.parseFloat(value);
  if (Number.isNaN(n)) return 0;
  return value.includes('rem') ? n * 16 : n;
}

function luminance(rgb) {
  const parts = rgb.match(/\d+(\.\d+)?/g);
  if (!parts) return 1;
  const [r, g, b] = parts.map(Number);
  return (0.299 * r + 0.587 * g + 0.114 * b) / 255;
}

function readTheme() {
  const base100 = themeColor('--color-base-100');
  return {
    palette: [
      themeColor('--color-primary'),
      themeColor('--color-secondary'),
      themeColor('--color-accent'),
      themeColor('--color-info'),
      themeColor('--color-success'),
      themeColor('--color-warning'),
      themeColor('--color-error'),
    ],
    baseContent: themeColor('--color-base-content'),
    base100,
    gridBorder: themeColor('--color-base-300'),
    isDark: luminance(base100) < 0.5,
    barRadius: remToPx(cssVar('--radius-field')) || 4,
    fontFamily: cssVar('--font-sans') || 'Inter, ui-sans-serif, system-ui, sans-serif',
  };
}

// pie/donut/polarArea/radialBar draw a separator stroke between slices; ApexCharts
// defaults it to white, which clashes on dark themes. Match the card background instead.
const RADIAL_TYPES = new Set(['pie', 'donut', 'polarArea', 'radialBar']);

// Baseline options harmonised with daisyUI. Caller overrides (config.options) win via
// deepMerge, but color/typography defaults come from the live theme.
function daisyDefaults(theme, type) {
  const mode = theme.isDark ? 'dark' : 'light';
  return {
    chart: {
      type,
      fontFamily: theme.fontFamily,
      background: 'transparent',
      foreColor: theme.baseContent,
      toolbar: { show: false },
      zoom: { enabled: false },
    },
    theme: { mode },
    colors: theme.palette,
    grid: { borderColor: theme.gridBorder, strokeDashArray: 4 },
    dataLabels: { enabled: false },
    // A bar takes no stroke: a non-zero width paints every zero-height stacked
    // segment as a thin line in the series colour — e.g. an always-present but
    // empty "issue" series would cap each logs-activity bar in phantom red.
    // (curve:'smooth' only means something for line/area anyway.)
    stroke: RADIAL_TYPES.has(type)
      ? { width: 2, colors: [theme.base100] }
      : type === 'bar'
        ? { width: 0 }
        : { width: 2, curve: 'smooth' },
    plotOptions: { bar: { borderRadius: theme.barRadius, borderRadiusApplication: 'end' } },
    tooltip: { theme: mode },
    legend: { labels: { colors: theme.baseContent } },
    noData: { text: 'No data', style: { color: theme.baseContent } },
  };
}

// daisyUI color names a config may reference by token, e.g. "colors": ["primary", "error"].
// Resolved against the live theme so overrides recolor on theme switch like defaults do.
const TOKENS = new Set([
  'primary',
  'secondary',
  'accent',
  'neutral',
  'info',
  'success',
  'warning',
  'error',
  'base-content',
]);

function resolveTokens(colors) {
  return colors.map((c) => (TOKENS.has(c) ? themeColor(`--color-${c}`) : c));
}

function isObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function deepMerge(base, override) {
  const out = { ...base };
  for (const key of Object.keys(override)) {
    out[key] =
      isObject(base[key]) && isObject(override[key])
        ? deepMerge(base[key], override[key])
        : override[key];
  }
  return out;
}

// Every live chart, so a theme switch can re-apply the baseline to all of them.
const charts = [];

function optionsFor(config, theme) {
  const merged = deepMerge(daisyDefaults(theme, config.type || 'line'), config.options || {});
  if (Array.isArray(merged.colors)) merged.colors = resolveTokens(merged.colors);
  merged.series = config.series;
  return merged;
}

function initChart(target) {
  if (target.dataset.chartReady) return;
  const script = target.parentElement?.querySelector('[data-chart-config]');
  if (!script) return;
  let config;
  try {
    config = JSON.parse(script.textContent);
  } catch {
    return;
  }
  const theme = readTheme();
  const chart = new ApexCharts(target, optionsFor(config, theme));
  chart.render();
  target.dataset.chartReady = '1';
  charts.push({ chart, config });
}

// Charts can live in a hidden tab (display:none → zero size), where ApexCharts would
// render empty. A ResizeObserver fires as soon as a target has a real size — on first
// layout for visible charts, or when a hidden tab is switched on — so each renders at
// its true width regardless of scroll position.
const sizing = new ResizeObserver((entries) => {
  for (const entry of entries) {
    const target = entry.target;
    if (target.dataset.chartReady || target.clientWidth === 0) continue;
    sizing.unobserve(target);
    initChart(target);
  }
});

function initAll(scope) {
  const rootEl = scope?.querySelectorAll ? scope : document;
  for (const target of rootEl.querySelectorAll('[data-chart]')) {
    if (!target.dataset.chartReady) sizing.observe(target);
  }
}

function retheme() {
  const theme = readTheme();
  for (const { chart, config } of charts) {
    chart.updateOptions(optionsFor(config, theme), false, false);
  }
}

// The console theme selector mutates <html data-theme>; recolor every chart in place.
new MutationObserver(retheme).observe(root, {
  attributes: true,
  attributeFilter: ['data-theme'],
});

// Charts can arrive with an HTMX swap; init only the freshly inserted subtree.
document.body.addEventListener('htmx:load', (e) => initAll(e.detail.elt));

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => initAll());
} else {
  initAll();
}
