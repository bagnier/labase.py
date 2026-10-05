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
// `[data-chart]` is the target; its sibling `[data-chart-config]` holds the series and option
// overrides, merged over a baseline from the theme's CSS variables, re-read on a theme switch.

const root = document.documentElement;

// A CSS colour as `rgb(...)`, read back off a probe: daisyUI's oklch may render oddly in SVG.
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

// Slice separators default to white, wrong on dark themes: use the card background.
const RADIAL_TYPES = new Set(['pie', 'donut', 'polarArea', 'radialBar']);

// The theme baseline; config.options win.
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
    // No stroke on bars: it draws empty stacked segments as coloured lines.
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

// Theme colour names a config may use ("primary"), resolved live.
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

const charts = [];

// `drilldown: { url, target }`: zooming reloads `target` for the brushed [from, to] (epoch ms);
// reset reloads it whole.
function wireDrilldown(options, drill) {
  options.chart.toolbar = {
    show: true,
    tools: {
      download: false,
      selection: false,
      zoom: true,
      zoomin: false,
      zoomout: false,
      pan: false,
      reset: true,
    },
  };
  options.chart.zoom = { enabled: true, type: 'x', autoScaleYaxis: true };
  const reload = (params) => {
    const query = params ? `?${new URLSearchParams(params)}` : '';
    window.htmx?.ajax('GET', `${drill.url}${query}`, { target: drill.target, swap: 'innerHTML' });
  };
  options.chart.events = {
    ...(options.chart.events || {}),
    zoomed: (_ctx, { xaxis }) => {
      if (xaxis?.min != null && xaxis?.max != null) {
        reload({ from: Math.round(xaxis.min), to: Math.round(xaxis.max) });
      } else {
        reload(null); // toolbar reset — back to the full window
      }
    },
  };
}

function optionsFor(config, theme) {
  const merged = deepMerge(daisyDefaults(theme, config.type || 'line'), config.options || {});
  if (Array.isArray(merged.colors)) merged.colors = resolveTokens(merged.colors);
  if (config.drilldown) wireDrilldown(merged, config.drilldown);
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

// A chart in a hidden tab has no size and would render empty: render on its first real size.
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

new MutationObserver(retheme).observe(root, {
  attributes: true,
  attributeFilter: ['data-theme'],
});

// Charts arriving in an HTMX swap.
document.body.addEventListener('htmx:load', (e) => initAll(e.detail.elt));

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => initAll());
} else {
  initAll();
}
