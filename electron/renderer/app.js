'use strict';

/**
 * EasyFig renderer.
 *
 * Owns the interface state, mirrors it into the controls, and asks the Python
 * engine for a figure whenever something changes.  All engine access goes
 * through `window.easyfig` (see preload.js); this file never touches Node.
 */

const api = window.easyfig;

const STORAGE_KEY = 'easyfig.state.v1';
const RENDER_DEBOUNCE_MS = 140;
const MAX_STATS_ROWS = 400;
const MAX_PERSIST_BYTES = 2 * 1024 * 1024;

/* ── Preset bundles (mirrors the desktop app's two visual presets) ──────── */

const PRESET_BUNDLES = {
  default: {
    line_width: 2.0, marker_size: 10, label_font_size: 10, legend_font_size: 14,
    legend_marker_size: 10, tick_label_size: 14, axis_label_font_size: 12,
    title_font_size: 16, tick_length: 4.0, tick_width: 1.5,
    show_minor_ticks: false, tick_label_bold: false, point_alpha: 0.7,
    errorbar_capsize: 7, errorbar_linewidth: 2.0, bar_edge_width: 1.0,
    show_data_labels: true, show_legend: true, legend_loc: 'auto',
    legend_ncol: 1, line_style: 'solid', bar_style: 'solid',
  },
  sci: {
    line_width: 1.4, marker_size: 7, label_font_size: 8, legend_font_size: 8,
    legend_marker_size: 7, tick_label_size: 9, axis_label_font_size: 10,
    title_font_size: 11, tick_length: 5.0, tick_width: 1.0,
    show_minor_ticks: true, tick_label_bold: false, point_alpha: 0.45,
    errorbar_capsize: 3, errorbar_linewidth: 1.2, bar_edge_width: 1.0,
    show_data_labels: false, show_legend: true, legend_loc: 'best',
    legend_ncol: 1, line_style: 'solid', bar_style: 'white',
  },
};

const DEMO_DATASETS = [
  { name: '示例 A', sizes: [1, 2, 3, 4, 5],
    data: [[10.1, 10.4], [20.2, 20.6], [30.1, 30.4], [40.6, 40.2], [50.3, 50.9]],
    color: '#4E74B3' },
  { name: '示例 B', sizes: [1, 2, 3, 4, 5],
    data: [[9.8, 10.0], [19.6, 19.9], [31.0, 30.7], [39.2, 39.6], [51.4, 51.0]],
    color: '#FB9780' },
];

/* ── State ──────────────────────────────────────────────────────────────── */

const state = {
  schema: { defaultSettings: {}, palettes: [], baseColors: [] },
  settings: {},
  datasets: [],
  selected: -1,
  fit: { method: 'none', degree: 2, showRaw: true, showFit: true, addJitter: false },
  statistics: [],
  preview: null,
  zoom: 'fit',
  theme: 'system',
  activePalette: 0,
  busy: false,
  renderedOnce: false,
  info: null,
  /* 'single' draws one chart; 'compose' tiles several panels into one figure. */
  mode: 'single',
  compose: { panels: [] },
  composeLayout: null,
};

let renderTimer = null;
let renderToken = 0;

/* ── Small DOM helpers ──────────────────────────────────────────────────── */

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

function el(tag, props = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === 'class') node.className = value;
    else if (key === 'text') node.textContent = value;
    else if (key === 'html') node.innerHTML = value;
    else if (key === 'dataset') Object.assign(node.dataset, value);
    else if (key.startsWith('on') && typeof value === 'function') {
      node.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (key === 'style' && typeof value === 'object') {
      for (const [prop, val] of Object.entries(value)) node.style.setProperty(prop, val);
    } else if (value === true) node.setAttribute(key, '');
    else node.setAttribute(key, value);
  }
  for (const child of [].concat(children)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

const clear = (node) => { while (node.firstChild) node.removeChild(node.firstChild); return node; };

function debounceRender(delay = RENDER_DEBOUNCE_MS) {
  clearTimeout(renderTimer);
  renderTimer = setTimeout(() => renderPreview(), delay);
}

/* ── Overlays ───────────────────────────────────────────────────────────── */

const overlayLayer = $('#overlayLayer');

function closeOverlay() {
  overlayLayer.hidden = true;
  clear(overlayLayer);
  $$('.well.is-open').forEach((well) => well.classList.remove('is-open'));
}

function openOverlay(contentNode, { backdrop = true, onClose = null } = {}) {
  clear(overlayLayer);
  overlayLayer.hidden = false;
  if (backdrop) {
    overlayLayer.append(el('div', {
      class: 'overlay-backdrop',
      onclick: () => { closeOverlay(); onClose?.(); },
    }));
  }
  overlayLayer.append(contentNode);
  return contentNode;
}

/**
 * Present a modal sheet.  `fields` is a list of {kind, ...} descriptors; the
 * caller receives a getter for the current values when Confirm is pressed.
 */
function showSheet({ title, subtitle, body, confirmLabel = '确定', cancelLabel = '取消',
                     onConfirm, destructive = false }) {
  const sheet = el('div', { class: 'sheet', role: 'dialog', 'aria-modal': 'true' }, [
    el('div', { class: 'sheet__header' }, [
      el('h2', { class: 'sheet__title', text: title }),
      subtitle ? el('p', { class: 'sheet__subtitle', text: subtitle }) : null,
    ]),
    el('div', { class: 'sheet__body' }, [body]),
    el('div', { class: 'sheet__footer' }, [
      el('button', {
        type: 'button', class: 'button', text: cancelLabel,
        onclick: () => closeOverlay(),
      }),
      el('button', {
        type: 'button',
        class: `button ${destructive ? '' : 'button--primary'}`.trim(),
        text: confirmLabel,
        onclick: async () => {
          try {
            const keep = await onConfirm?.();
            if (keep !== false) closeOverlay();
          } catch (error) {
            toast(error.message, 'error');
          }
        },
      }),
    ]),
  ]);
  openOverlay(sheet);
  const focusable = sheet.querySelector('input, select, button');
  focusable?.focus();
  return sheet;
}

function toast(message, kind = 'info', timeout = 3200) {
  const layer = $('#toastLayer');
  const node = el('div', { class: `toast ${kind === 'error' ? 'toast--error' : ''}`.trim() }, [
    message,
  ]);
  layer.append(node);
  setTimeout(() => {
    node.classList.add('is-leaving');
    setTimeout(() => node.remove(), 220);
  }, timeout);
}

function setStatus(message, dotState = null) {
  $('#statusMessage').textContent = message;
  if (dotState) $('#engineDot').dataset.state = dotState;
}

/* ── Settings <-> controls ──────────────────────────────────────────────── */

function controlKind(node) {
  if (node.classList.contains('switch')) return 'switch';
  if (node.classList.contains('segmented')) return 'segment';
  if (node.classList.contains('slider')) return 'slider';
  if (node.classList.contains('stepper')) return 'number';
  if (node.tagName === 'SELECT') return 'select';
  return 'text';
}

function writeControl(node, value) {
  const kind = controlKind(node);
  switch (kind) {
    case 'switch':
      node.setAttribute('aria-checked', value ? 'true' : 'false');
      break;
    case 'segment': {
      const target = String(value);
      $$('button', node).forEach((button) => {
        button.setAttribute('aria-checked', button.dataset.value === target ? 'true' : 'false');
        button.setAttribute('role', 'radio');
      });
      break;
    }
    case 'slider': {
      node.value = String(value);
      const output = node.parentElement?.querySelector('.slider__value');
      if (output) output.textContent = formatNumber(value, Number(node.step) || 1);
      break;
    }
    case 'number':
      node.value = value === null || value === undefined ? '' : String(value);
      break;
    default:
      node.value = value ?? '';
  }
}

function formatNumber(value, step) {
  const number = Number(value);
  if (!Number.isFinite(number)) return '—';
  if (Number.isInteger(step) && Number.isInteger(number)) return String(number);
  const decimals = Math.min(2, Math.max(0, String(step).split('.')[1]?.length ?? 0));
  return number.toFixed(decimals);
}

function readControl(node) {
  const kind = controlKind(node);
  switch (kind) {
    case 'switch':
      return node.getAttribute('aria-checked') === 'true';
    case 'segment':
      return $('button[aria-checked="true"]', node)?.dataset.value ?? null;
    case 'slider':
    case 'number': {
      const number = Number(node.value);
      return Number.isFinite(number) ? number : 0;
    }
    default:
      return node.value;
  }
}

function bindSettings() {
  $$('[data-setting]').forEach((node) => {
    const key = node.dataset.setting;
    const commit = (value) => {
      if (value === null || value === undefined) return;
      if (state.settings[key] === value) return;
      state.settings[key] = value;
      if (key === 'visual_preset') applyPresetBundle(value, { fromUser: true });
      if (key === 'chart_type') applyChartTypeSeriesDefaults(value);
      updateVisibility();
      persist();
      debounceRender();
    };

    const kind = controlKind(node);
    if (kind === 'switch') {
      node.addEventListener('click', () => {
        const next = node.getAttribute('aria-checked') !== 'true';
        node.setAttribute('aria-checked', next ? 'true' : 'false');
        commit(next);
      });
    } else if (kind === 'segment') {
      $$('button', node).forEach((button) => {
        button.addEventListener('click', () => {
          $$('button', node).forEach((b) => b.setAttribute('aria-checked', 'false'));
          button.setAttribute('aria-checked', 'true');
          commit(button.dataset.value);
        });
      });
    } else if (kind === 'slider') {
      node.addEventListener('input', () => {
        const output = node.parentElement?.querySelector('.slider__value');
        if (output) output.textContent = formatNumber(node.value, Number(node.step) || 1);
        commit(Number(node.value));
      });
    } else if (kind === 'number') {
      node.addEventListener('change', () => commit(Number(node.value)));
    } else {
      node.addEventListener('change', () => commit(node.value));
    }
  });
}

function syncControls() {
  $$('[data-setting]').forEach((node) => {
    const value = state.settings[node.dataset.setting];
    if (value !== undefined) writeControl(node, value);
  });
  $$('[data-color-setting]').forEach((well) => {
    const color = state.settings[well.dataset.colorSetting];
    well.style.setProperty('--swatch', color || '#888888');
    well.title = `${well.dataset.colorSetting}: ${color}`;
  });
  // The fit controls are not chart settings; they live on state.fit.
  const methodSelect = $('#fitMethod');
  if (methodSelect && methodSelect.value !== state.fit.method) methodSelect.value = state.fit.method;
  $('#fitDegree').value = String(state.fit.degree);
  setSwitch($('#fitShowRaw'), state.fit.showRaw);
  setSwitch($('#fitShowFit'), state.fit.showFit);
  setSwitch($('#fitJitter'), state.fit.addJitter);
}

function setSwitch(node, value) {
  if (node) node.setAttribute('aria-checked', value ? 'true' : 'false');
}

/* ── Conditional visibility ─────────────────────────────────────────────── */

function updateVisibility() {
  const chartType = state.settings.chart_type || 'line';
  const isPie = chartType === 'pie';

  $$('[data-when]').forEach((node) => {
    const allowed = node.dataset.when.split(/\s+/);
    node.classList.toggle('is-hidden', !allowed.includes(chartType));
  });

  $$('[data-when-section]').forEach((node) => {
    const spec = node.dataset.whenSection;
    let visible;
    if (spec.startsWith('!')) visible = chartType !== spec.slice(1);
    else visible = spec.split(/\s+/).includes(chartType);
    node.classList.toggle('is-hidden', !visible);
  });

  $$('[data-when-setting]').forEach((node) => {
    node.classList.toggle('is-hidden', !state.settings[node.dataset.whenSetting]);
  });

  $$('[data-when-fit]').forEach((node) => {
    node.classList.toggle('is-hidden', !node.dataset.whenFit.split(/\s+/).includes(state.fit.method));
  });

  // Single-chart-only controls and composition-only controls swap places.
  $$('[data-mode]').forEach((node) => {
    node.classList.toggle('is-hidden', node.dataset.mode !== state.mode);
  });
  updateComposeVisibility();

  // Pie charts ignore axes, legend and error-bar styling entirely.
  if (isPie) {
    $$('[data-when-setting]').forEach((node) => node.classList.add('is-hidden'));
  }
}

/** Show or hide compose rows that depend on a compose value.
 *
 * `data-when-compose="key"` follows truthiness, `"!key"` inverts it and
 * `"key=value"` compares as a string - so the grid fields only appear once the
 * layout is actually manual.
 */
function updateComposeVisibility() {
  $$('[data-when-compose]').forEach((node) => {
    const spec = node.dataset.whenCompose;
    let visible;
    if (spec.includes('=')) {
      const [key, expected] = spec.split('=');
      visible = String(state.compose[key] ?? '') === expected;
    } else {
      const positive = !spec.startsWith('!');
      const key = positive ? spec : spec.slice(1);
      visible = positive ? Boolean(state.compose[key]) : !state.compose[key];
    }
    node.classList.toggle('is-hidden', !visible);
  });
}

/* ── Presets ────────────────────────────────────────────────────────────── */

function applyPresetBundle(preset, { fromUser = false } = {}) {
  const bundle = PRESET_BUNDLES[preset] || PRESET_BUNDLES.default;
  Object.assign(state.settings, bundle);
  state.settings.visual_preset = preset;
  syncControls();
  if (fromUser) setStatus(`已套用${preset === 'sci' ? ' SCI ' : '默认'}预设`);
}

/**
 * A chart type implies two series toggles (scatter means points and no line).
 * The rule comes from the engine so all three front ends agree.
 */
function applyChartTypeSeriesDefaults(chartType) {
  const defaults = state.schema.chartTypeSeriesDefaults?.[chartType];
  if (!defaults) return;
  Object.assign(state.settings, defaults);
  syncControls();
}

/* ── Sidebar ────────────────────────────────────────────────────────────── */

function renderDatasetList() {
  const list = clear($('#datasetList'));
  $('#datasetCount').textContent = String(state.datasets.length);

  if (!state.datasets.length) {
    list.append(el('li', { class: 'source-list__empty', text: '还没有数据集' }));
    return;
  }

  state.datasets.forEach((dataset, index) => {
    const points = (dataset.sizes || []).length;
    const item = el('li', {
      class: `source-item ${index === state.selected ? 'is-selected' : ''}`.trim(),
      role: 'option',
      'aria-selected': index === state.selected ? 'true' : 'false',
      onclick: () => {
        state.selected = index;
        renderDatasetList();
      },
      ondblclick: () => openDatasetEditor(index),
    }, [
      el('span', { class: 'source-item__swatch', style: { '--swatch': dataset.color || '#888' } }),
      el('span', { class: 'source-item__name', text: dataset.name }),
      el('span', { class: 'source-item__meta', text: `${points} 点` }),
    ]);
    list.append(item);
  });
}

function renderPaletteStack() {
  const stack = clear($('#paletteStack'));
  const palettes = state.schema.palettes || [];
  $('#paletteCount').textContent = String(palettes.length);

  palettes.forEach((palette, index) => {
    const strip = el('span', { class: 'palette-card__strip' },
      palette.colors.map((color) => el('span', { style: { '--swatch': color } })));
    const card = el('button', {
      type: 'button',
      class: `palette-card ${index === state.activePalette ? 'is-active' : ''}`.trim(),
      title: `${palette.journal} · ${palette.kind}${palette.note ? `\n${palette.note}` : ''}`,
      onclick: () => {
        state.activePalette = index;
        renderPaletteStack();
        applyPaletteToAll(index);
      },
    }, [
      el('span', { class: 'palette-card__label', text: `P${palette.issue} ${palette.journal.split('/')[0].trim()} · ${palette.count} 色` }),
      strip,
    ]);
    stack.append(card);
  });
}

function paletteColorsFor(count, paletteIndex = state.activePalette) {
  const palette = state.schema.palettes?.[paletteIndex];
  if (!palette || !palette.colors.length) return [];
  const colors = palette.colors;
  if (count <= 0) return [];
  if (count >= colors.length) {
    return Array.from({ length: count }, (_, index) => colors[index % colors.length]);
  }
  const step = colors.length / count;
  return Array.from({ length: count }, (_, index) => colors[Math.floor(index * step)]);
}

function applyPaletteToAll(paletteIndex = state.activePalette) {
  if (!state.datasets.length) {
    toast('还没有数据集可以套用配色');
    return;
  }
  const colors = paletteColorsFor(state.datasets.length, paletteIndex);
  state.datasets.forEach((dataset, index) => { dataset.color = colors[index]; });
  const palette = state.schema.palettes?.[paletteIndex];
  renderDatasetList();
  persist();
  debounceRender(0);
  if (palette) toast(`已套用 P${palette.issue} ${palette.journal.split('/')[0].trim()} 配色`);
}

/* ── Colour popover ─────────────────────────────────────────────────────── */

function openColorPopover(anchor, options = {}) {
  const { settingKey = null, title = '颜色', onPick = null } = options;
  const current = options.initial
    || (settingKey ? state.settings[settingKey] : null)
    || '#888888';
  let chosen = current;

  const preview = el('span', {
    class: 'source-item__swatch',
    style: { '--swatch': chosen, width: '18px', height: '18px' },
  });

  const commit = (color) => {
    chosen = color;
    preview.style.setProperty('--swatch', color);
    if (settingKey) {
      state.settings[settingKey] = color;
      syncControls();
      persist();
      debounceRender();
    }
    onPick?.(color);
  };

  const presetGrid = el('div', { class: 'swatch-grid' },
    (state.schema.baseColors || []).map((entry) => el('button', {
      type: 'button',
      class: 'swatch',
      title: `${entry.name} ${entry.hex}`,
      style: { '--swatch': entry.hex },
      onclick: () => { commit(entry.hex); markSelected(presetGrid, entry.hex); },
    })));

  const paletteSelect = el('select', {
    class: 'popup popover__palette-select',
    onchange: (event) => {
      state.activePalette = Number(event.target.value);
      buildPaletteSection();
    },
  }, (state.schema.palettes || []).map((palette, index) => el('option', {
    value: String(index),
    text: `P${palette.issue} · ${palette.journal} · ${palette.count} 色`,
  })));
  paletteSelect.value = String(state.activePalette);

  const paletteGrid = el('div', { class: 'swatch-grid' });
  const paletteMeta = el('p', { class: 'popover__meta' });

  function buildPaletteSection() {
    const palette = state.schema.palettes?.[state.activePalette];
    clear(paletteGrid);
    if (!palette) return;
    palette.colors.forEach((color, index) => {
      paletteGrid.append(el('button', {
        type: 'button',
        class: 'swatch',
        title: `P${palette.issue} ${palette.journal} ${index + 1} · ${color}`,
        style: { '--swatch': color, '--swatch-text': readableTextColor(color) },
        onclick: () => { commit(color); markSelected(paletteGrid, color); },
      }, [el('span', { class: 'swatch__index', text: String(index + 1) })]));
    });
    paletteMeta.textContent = [
      `第${palette.issue}期`, palette.journal, palette.kind, palette.note,
    ].filter(Boolean).join(' · ');
  }

  function markSelected(grid, color) {
    const target = String(color || '').toLowerCase();
    $$('.swatch', grid).forEach((node) => {
      const value = (node.style.getPropertyValue('--swatch') || '').trim().toLowerCase();
      node.classList.toggle('is-selected', value === target);
    });
  }

  const hexInput = el('input', {
    type: 'text', class: 'textfield', value: current, spellcheck: 'false',
  });
  const applyHex = () => {
    api.request('normalize_color', { color: hexInput.value.trim(), fallback: null })
      .then((result) => {
        if (!result.color) { toast('请输入颜色值，例如 #4E74B3 或 red', 'error'); return; }
        commit(result.color);
        markSelected(paletteGrid, result.color);
      })
      .catch((error) => toast(error.message, 'error'));
  };
  hexInput.addEventListener('keydown', (event) => { if (event.key === 'Enter') applyHex(); });

  const popover = el('div', { class: 'popover', role: 'dialog', 'aria-label': '选择颜色' }, [
    el('div', { class: 'popover__row' }, [
      el('span', { class: 'popover__title', style: { margin: '0' }, text: title }),
      el('span', { class: 'spacer' }),
      preview,
    ]),
    el('div', { class: 'popover__section' }, [
      el('p', { class: 'popover__title', text: '常用' }),
      presetGrid,
    ]),
    el('div', { class: 'popover__section' }, [
      el('p', { class: 'popover__title', text: '科研配色' }),
      paletteSelect,
      paletteGrid,
      paletteMeta,
    ]),
    el('div', { class: 'popover__section' }, [
      el('p', { class: 'popover__title', text: '自定义' }),
      el('div', { class: 'popover__row' }, [
        hexInput,
        el('button', { type: 'button', class: 'button', text: '应用', onclick: applyHex }),
      ]),
    ]),
  ]);

  buildPaletteSection();
  markSelected(presetGrid, current);
  markSelected(paletteGrid, current);
  $$('.well').forEach((node) => node.classList.remove('is-open'));
  anchor.classList.add('is-open');

  const rect = anchor.getBoundingClientRect();
  popover.style.top = `${Math.min(rect.bottom + 8, Math.max(12, window.innerHeight - 430))}px`;
  popover.style.left = `${Math.max(12, Math.min(rect.right - 316, window.innerWidth - 332))}px`;
  openOverlay(popover);
  hexInput.focus();
  hexInput.select();
}

function readableTextColor(hex) {
  const value = String(hex).replace('#', '');
  if (value.length !== 6) return '#000000';
  const r = parseInt(value.slice(0, 2), 16) / 255;
  const g = parseInt(value.slice(2, 4), 16) / 255;
  const b = parseInt(value.slice(4, 6), 16) / 255;
  const lin = (c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  const luminance = 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
  return luminance > 0.45 ? '#000000' : '#ffffff';
}

function bindColors() {
  $$('[data-color-setting]').forEach((well) => {
    well.addEventListener('click', (event) => {
      event.stopPropagation();
      openColorPopover(well, { settingKey: well.dataset.colorSetting });
    });
  });
}

/**
 * Only settings the engine knows about are ever sent over the bridge; anything
 * else (interface-only keys) would be rejected as an unknown setting.
 */
function bridgeSettings() {
  const known = new Set(
    state.schema.settingKeys || Object.keys(state.schema.defaultSettings || {}),
  );
  const result = {};
  for (const [key, value] of Object.entries(state.settings)) {
    if (known.has(key)) result[key] = value;
  }
  return result;
}

/* ── Preview ────────────────────────────────────────────────────────────── */

async function renderPreview({ force = false } = {}) {
  if (!state.settings.chart_type) return;

  if (!state.datasets.length) {
    state.preview = null;
    state.statistics = [];
    state.composeLayout = null;
    $('#canvasFrame').classList.add('is-hidden');
    $('#canvasEmpty').classList.add('is-visible');
    $('#previewMeta').textContent = '—';
    $('#statusSize').textContent = '—';
    renderStatistics();
    renderLayoutDiagram(null);
    if (!state.renderedOnce) { state.renderedOnce = true; api.signalRendered(); }
    return;
  }

  const token = ++renderToken;
  state.busy = true;
  $('#engineDot').dataset.state = 'busy';
  $('#canvasFrame').classList.add('is-loading');

  const composing = state.mode === 'compose';
  const request = {
    datasets: state.datasets,
    settings: bridgeSettings(),
    fit: state.fit,
    dpi: 132,
  };
  if (composing) {
    request.panels = composePanelsPayload();
    request.compose = composeOverrides();
  }

  try {
    const result = await api.request(composing ? 'compose' : 'render', request);
    if (token !== renderToken && !force) return;

    state.preview = result;
    state.statistics = result.statistics || [];
    $('#previewImage').src = `data:image/png;base64,${result.png}`;
    applyZoom();
    $('#canvasFrame').classList.remove('is-hidden');
    $('#canvasEmpty').classList.remove('is-visible');
    const layoutNote = composing
      ? ` · ${result.rows}×${result.cols} 格 / ${result.panelCount} 面板` : '';
    $('#previewMeta').textContent = `${result.pixelWidth} × ${result.pixelHeight} px · ${result.dpi} dpi${layoutNote}`;
    $('#statusSize').textContent = `${result.pixelWidth} × ${result.pixelHeight} px`;
    if (composing) {
      state.composeLayout = result;
      renderLayoutDiagram(result);
    }
    renderStatistics();
    setStatus('就绪', 'ready');
    if (!state.renderedOnce) {
      state.renderedOnce = true;
      api.signalRendered();
    }
  } catch (error) {
    if (token !== renderToken) return;
    $('#engineDot').dataset.state = 'error';
    setStatus(error.message.split('\n')[0], 'error');
    toast(error.message.split('\n')[0], 'error', 6000);
  } finally {
    if (token === renderToken) {
      state.busy = false;
      $('#canvasFrame').classList.remove('is-loading');
    }
  }
}

function applyZoom() {
  const frame = $('#canvasFrame');
  const preview = state.preview;
  const fit = state.zoom === 'fit';
  frame.classList.toggle('is-fit', fit);
  if (!preview) return;
  if (!fit) {
    frame.style.setProperty('width', `${preview.pixelWidth}px`);
    frame.style.setProperty('height', `${preview.pixelHeight}px`);
  } else {
    frame.style.removeProperty('width');
    frame.style.removeProperty('height');
  }
}

function renderStatistics() {
  const tbody = $('#statsTable').querySelector('tbody');
  clear(tbody);
  $('#statsCount').textContent = String(state.statistics.length);

  let rows = 0;
  let truncated = false;
  outer:
  for (const dataset of state.statistics) {
    const sizes = dataset.sizes || [];
    for (let index = 0; index < sizes.length; index += 1) {
      if (rows >= MAX_STATS_ROWS) { truncated = true; break outer; }
      tbody.append(el('tr', {}, [
        el('td', { text: index === 0 ? dataset.name : '' }),
        el('td', { text: formatCell(sizes[index]) }),
        el('td', { text: formatCell(dataset.mean?.[index]) }),
        el('td', { text: formatCell(dataset.std?.[index]) }),
        el('td', { text: formatCell(dataset.max?.[index]) }),
        el('td', { text: formatCell(dataset.min?.[index]) }),
      ]));
      rows += 1;
    }
  }

  if (!rows) {
    tbody.append(el('tr', {}, [el('td', { colspan: '6', text: '暂无数据' })]));
  } else if (truncated) {
    tbody.append(el('tr', {}, [el('td', { colspan: '6', text: `仅显示前 ${MAX_STATS_ROWS} 行` })]));
  }
}

function formatCell(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return '—';
  return number.toFixed(4);
}

/* ── Dataset editing ────────────────────────────────────────────────────── */

function parseNumbers(text) {
  return String(text)
    .split(/[\s,;]+/)
    .map((part) => part.trim())
    .filter(Boolean)
    .map(Number)
    .filter((value) => Number.isFinite(value));
}

function openDatasetEditor(index) {
  const editing = Number.isInteger(index) && index >= 0 && index < state.datasets.length;
  const dataset = editing
    ? state.datasets[index]
    : {
      name: `数据集 ${state.datasets.length + 1}`,
      sizes: [1, 2, 3],
      data: [[1], [2], [3]],
      color: paletteColorsFor(state.datasets.length + 1)[state.datasets.length] || '#1f77b4',
    };

  const nameInput = el('input', { type: 'text', class: 'textfield', value: dataset.name });
  const sizesInput = el('textarea', {
    class: 'textfield', rows: '2',
  });
  sizesInput.value = (dataset.sizes || []).join(' ');
  sizesInput.style.setProperty('height', '52px');
  sizesInput.style.setProperty('resize', 'vertical');

  const dataInput = el('textarea', { class: 'textfield' });
  dataInput.value = (dataset.data || []).map((group) => group.join(' ')).join('\n');
  dataInput.style.setProperty('height', '150px');
  dataInput.style.setProperty('resize', 'vertical');
  dataInput.style.setProperty('font-family', 'var(--font-mono)');

  const colorWell = el('button', {
    type: 'button', class: 'well',
    style: { '--swatch': dataset.color || '#1f77b4' },
    onclick: (event) => {
      event.stopPropagation();
      openColorPopover(colorWell, {
        initial: colorWell.dataset.value,
        title: '数据集颜色',
        onPick: (color) => {
          colorWell.dataset.value = color;
          colorWell.style.setProperty('--swatch', color);
        },
      });
    },
  });
  colorWell.dataset.value = dataset.color || '#1f77b4';

  const body = el('div', {}, [
    el('div', { class: 'field-grid' }, [
      el('div', { class: 'field field--full' }, [
        el('label', { class: 'field__label', text: '名称' }), nameInput,
      ]),
      el('div', { class: 'field' }, [
        el('label', { class: 'field__label', text: '颜色' }), colorWell,
      ]),
      el('div', { class: 'field field--full' }, [
        el('label', { class: 'field__label', text: 'X 值（空格或逗号分隔）' }), sizesInput,
      ]),
      el('div', { class: 'field field--full' }, [
        el('label', { class: 'field__label', text: 'Y 值（每行对应一个 X，可写多次测量）' }), dataInput,
      ]),
    ]),
  ]);

  showSheet({
    title: editing ? '编辑数据集' : '添加数据集',
    subtitle: '每行是一组重复测量，组数与 X 值个数相同。',
    confirmLabel: editing ? '保存' : '添加',
    body,
    onConfirm: () => {
      const name = nameInput.value.trim();
      if (!name) { toast('请输入名称', 'error'); return false; }
      const sizes = parseNumbers(sizesInput.value);
      if (!sizes.length) { toast('请输入 X 值', 'error'); return false; }
      const groups = dataInput.value
        .split('\n')
        .map((line) => parseNumbers(line))
        .filter((group) => group.length);
      if (!groups.length) { toast('请输入 Y 值', 'error'); return false; }
      if (groups.length !== sizes.length) {
        toast(`X 值有 ${sizes.length} 个，但 Y 有 ${groups.length} 行`, 'error');
        return false;
      }
      const entry = {
        name: uniqueName(name, editing ? index : -1),
        sizes,
        data: groups,
        color: colorWell.dataset.value,
      };
      if (editing) state.datasets[index] = entry;
      else state.datasets.push(entry);
      state.selected = editing ? index : state.datasets.length - 1;
      renderDatasetList();
      persist();
      debounceRender(0);
      return true;
    },
  });
}

function uniqueName(name, skipIndex) {
  const taken = new Set(state.datasets.map((d, i) => (i === skipIndex ? null : d.name)));
  if (!taken.has(name)) return name;
  let counter = 2;
  while (taken.has(`${name}_${counter}`)) counter += 1;
  return `${name}_${counter}`;
}

function removeSelectedDataset() {
  if (state.selected < 0 || state.selected >= state.datasets.length) {
    toast('请先选择一个数据集');
    return;
  }
  const [removed] = state.datasets.splice(state.selected, 1);
  state.selected = Math.min(state.selected, state.datasets.length - 1);
  renderDatasetList();
  persist();
  debounceRender(0);
  toast(`已移除「${removed.name}」`);
}

function clearDatasets() {
  if (!state.datasets.length) return;
  state.datasets = [];
  state.selected = -1;
  renderDatasetList();
  persist();
  debounceRender(0);
}

/* ── Import ─────────────────────────────────────────────────────────────── */

async function importTable() {
  const path = await api.openTable();
  if (!path) return;

  let info;
  try {
    info = await api.request('inspect_table', { path });
  } catch (error) {
    toast(error.message, 'error');
    return;
  }

  const orientationSelect = el('select', { class: 'popup' }, [
    el('option', { value: 'vertical', text: '纵向：每列一个数据集' }),
    el('option', { value: 'horizontal', text: '横向：每行一个数据集' }),
  ]);

  const timeSelect = el('select', { class: 'popup' }, [
    el('option', { value: '', text: '（不使用）' }),
    ...info.columns.map((column) => el('option', { value: column.name, text: column.name })),
  ]);

  const unitSelect = el('select', { class: 'popup' }, [
    el('option', { value: 's', text: '秒 (s)' }),
    el('option', { value: 'ms', text: '毫秒 (ms)' }),
  ]);

  const list = el('div', { class: 'checkbox-list' },
    info.columns.map((column) => {
      const box = el('input', { type: 'checkbox', class: 'checkbox' });
      box.checked = true;
      box.dataset.column = column.name;
      return el('label', { class: 'check-row' }, [
        box,
        el('span', { class: 'check-row__name', text: column.name }),
        el('span', {
          class: 'check-row__meta',
          text: `${column.nonEmpty} 个值${column.numeric ? '' : ' · 非数值'}`,
        }),
      ]);
    }));

  const previewTable = el('table', { class: 'preview-table' }, [
    el('thead', {}, [el('tr', {}, info.columns.map((column) => el('th', { text: column.name })))]),
    el('tbody', {}, (info.preview || []).map((row) => el('tr', {},
      row.map((cell) => el('td', { text: cell === null ? '' : String(cell) }))))),
  ]);

  const body = el('div', {}, [
    el('div', { class: 'field-grid' }, [
      el('div', { class: 'field' }, [
        el('label', { class: 'field__label', text: '方向' }), orientationSelect,
      ]),
      el('div', { class: 'field' }, [
        el('label', { class: 'field__label', text: '时间列（作为 X）' }), timeSelect,
      ]),
      el('div', { class: 'field' }, [
        el('label', { class: 'field__label', text: '时间单位' }), unitSelect,
      ]),
    ]),
    el('p', { class: 'field__label', text: `选择要导入的列 · 共 ${info.rows} 行` }),
    list,
    el('p', { class: 'field__label', text: '前几行预览', style: { 'margin-top': '10px' } }),
    el('div', { class: 'preview-scroll' }, [previewTable]),
  ]);

  showSheet({
    title: '导入表格',
    subtitle: path.split(/[\\/]/).pop(),
    confirmLabel: '导入',
    body,
    onConfirm: async () => {
      const checked = $$('input[type="checkbox"]', list)
        .filter((box) => box.checked)
        .map((box) => box.dataset.column);
      if (!checked.length) { toast('请至少选择一列', 'error'); return false; }

      const result = await api.request('import_table', {
        path,
        orientation: orientationSelect.value,
        timeColumn: timeSelect.value || null,
        timeUnit: unitSelect.value,
        columns: checked,
      });
      const imported = result.datasets || [];
      for (const dataset of imported) {
        dataset.name = uniqueName(dataset.name, -1);
        state.datasets.push(dataset);
      }
      state.selected = state.datasets.length - 1;
      if (orientationSelect.value === 'vertical' && timeSelect.value) {
        state.settings.xaxis_mode = 'numeric';
        // The bridge converts milliseconds to seconds, so the axis unit is s.
        state.settings.x_unit = 's';
        state.settings.chart_type = state.settings.chart_type === 'pie'
          ? 'line' : state.settings.chart_type;
        state.settings.show_connecting_line = true;
      }
      syncControls();
      updateVisibility();
      renderDatasetList();
      persist();
      debounceRender(0);
      toast(`已导入 ${imported.length} 个数据集`);
      return true;
    },
  });
}

async function importMultiline() {
  const paths = await api.openMultiline();
  if (!paths) return;

  const orientationSelect = el('select', { class: 'popup' }, [
    el('option', { value: 'vertical', text: '纵向：表头是 X，每列是重复测量' }),
    el('option', { value: 'horizontal', text: '横向：首列是 X，每行是重复测量' }),
  ]);
  const mergeBox = el('input', { type: 'checkbox', class: 'checkbox' });

  const body = el('div', {}, [
    el('div', { class: 'field-grid' }, [
      el('div', { class: 'field' }, [
        el('label', { class: 'field__label', text: '方向' }), orientationSelect,
      ]),
      el('div', { class: 'field' }, [
        el('label', { class: 'field__label', text: '合并相同 X' }), mergeBox,
      ]),
    ]),
    el('p', { class: 'field__label', text: `${paths.length} 个文件` }),
    el('div', { class: 'checkbox-list' },
      paths.map((path) => el('div', { class: 'check-row' }, [
        el('span', { class: 'check-row__name', text: path.split(/[\\/]/).pop() }),
      ]))),
  ]);

  showSheet({
    title: '导入多线图',
    subtitle: '每个文件成为一条曲线；合并后相同 X 的测量会汇总到一组。',
    confirmLabel: '导入',
    body,
    onConfirm: async () => {
      const result = await api.request('import_multiline', {
        paths,
        orientation: orientationSelect.value,
        merge: mergeBox.checked,
      });
      for (const dataset of result.datasets || []) {
        dataset.name = uniqueName(dataset.name, -1);
        state.datasets.push(dataset);
      }
      state.selected = state.datasets.length - 1;
      state.settings.xaxis_mode = 'numeric';
      state.settings.chart_type = 'line';
      state.settings.show_connecting_line = true;
      state.settings.show_mean = true;
      syncControls();
      updateVisibility();
      renderDatasetList();
      persist();
      debounceRender(0);
      toast(`已导入 ${(result.datasets || []).length} 个数据集`);
      return true;
    },
  });
}

/* ── Export ─────────────────────────────────────────────────────────────── */

async function exportFigure() {
  if (!state.datasets.length) {
    toast('还没有数据可以导出', 'error');
    return;
  }
  const safeName = String(state.settings.title || 'easyfig')
    .replace(/[\\/:*?"<>|\u0000-\u001f]+/g, '_')
    .slice(0, 80) || 'easyfig';
  const target = await api.saveFigure({ defaultPath: `${safeName}.png` });
  if (!target) return;

  setStatus('正在导出…', 'busy');
  try {
    const composing = state.mode === 'compose';
    const request = {
      path: target,
      datasets: state.datasets,
      settings: bridgeSettings(),
      fit: state.fit,
    };
    if (composing) {
      request.panels = composePanelsPayload();
      request.compose = composeOverrides();
    }
    const result = await api.request(composing ? 'export_compose' : 'export', request);
    setStatus('就绪', 'ready');
    const size = result.bytes ? `${(result.bytes / 1024).toFixed(0)} KB` : '';
    toast(`已导出 ${result.path.split(/[\\/]/).pop()} · ${result.pixelWidth}×${result.pixelHeight} px ${size}`);
  } catch (error) {
    setStatus(error.message.split('\n')[0], 'error');
    toast(error.message, 'error', 6000);
  }
}

/* ── Composition (拼图) ─────────────────────────────────────────────────── */

const COMPOSE_CHART_TYPES = [
  { value: '', label: '跟随全局' },
  { value: 'line', label: '折线' },
  { value: 'scatter', label: '散点' },
  { value: 'line_scatter', label: '折线+散点' },
  { value: 'errorbar', label: '误差条' },
  { value: 'bar', label: '柱状' },
  { value: 'pie', label: '饼图' },
];

function composeSchema() {
  return state.schema.compose || {};
}

function composeDefaults() {
  return structuredClone(composeSchema().composeDefaults || {});
}

function findLayoutPreset(key) {
  return (composeSchema().layoutPresets || []).find((entry) => entry.key === key) || null;
}

/**
 * Keep the panel grouping in step with the datasets that exist: dropped
 * datasets leave their panels, unseen datasets get a panel of their own.
 */
function syncComposePanels() {
  const names = state.datasets.map((dataset) => dataset.name);
  const known = new Set(names);
  const seen = new Set();
  const panels = [];

  for (const panel of state.compose.panels || []) {
    const members = (panel.datasets || []).filter((name) => known.has(name) && !seen.has(name));
    if (!members.length) continue;
    members.forEach((name) => seen.add(name));
    panels.push({ ...panel, datasets: members });
  }
  for (const name of names) {
    if (seen.has(name)) continue;
    seen.add(name);
    panels.push({ datasets: [name] });
  }
  state.compose.panels = panels;
  return panels;
}

/** The a/b/c marker for a panel, following the current style. */
function panelLabelText(index) {
  const style = state.compose.label_style || 'abc';
  let name = '';
  let value = index;
  do {
    name = String.fromCharCode(97 + (value % 26)) + name;
    value = Math.floor(value / 26) - 1;
  } while (value >= 0);
  if (style === 'paren') return `(${name})`;
  if (style === 'ABC') return name.toUpperCase();
  if (style === 'dot') return `${name}.`;
  return name;
}

/** The span a panel shows: the preset's when one is selected, else its own. */
function panelSpan(panel, index) {
  const preset = findLayoutPreset(state.compose.layout_preset);
  const spans = preset?.spans || [];
  if (index < spans.length) return spans[index];
  return [Number(panel.rowspan) || 1, Number(panel.colspan) || 1];
}

function composePanelsPayload() {
  return syncComposePanels().map((panel) => {
    const entry = { datasets: [...panel.datasets] };
    const settings = {};
    if (panel.chartType) settings.chart_type = panel.chartType;
    if (panel.xlabel) settings.xlabel = panel.xlabel;
    if (panel.ylabel) settings.ylabel = panel.ylabel;
    if (Object.keys(settings).length) entry.settings = settings;
    if (panel.title) entry.title = panel.title;
    if (Number(panel.rowspan) > 1) entry.rowspan = Number(panel.rowspan);
    if (Number(panel.colspan) > 1) entry.colspan = Number(panel.colspan);
    return entry;
  });
}

function composeOverrides() {
  const keys = new Set(composeSchema().composeSettingKeys || []);
  const overrides = {};
  for (const [key, value] of Object.entries(state.compose)) {
    if (key === 'panels') continue;
    if (keys.has(key)) overrides[key] = value;
  }
  return overrides;
}

function commitComposeChange() {
  persist();
  debounceRender();
}

/** Fold the selected preset's spans into the panels, then drop the preset. */
function materializeLayoutPreset() {
  const preset = findLayoutPreset(state.compose.layout_preset);
  if (!preset) {
    state.compose.layout_preset = '';
    return;
  }
  const spans = preset.spans || [];
  syncComposePanels().forEach((panel, index) => {
    if (index >= spans.length) return;
    panel.rowspan = spans[index][0];
    panel.colspan = spans[index][1];
  });
  state.compose.layout_preset = '';
}

function applyLayoutPreset(key) {
  state.compose.layout_preset = key;
  const preset = findLayoutPreset(key);
  if (!preset || key === 'auto') {
    state.compose.layout_mode = 'auto';
  } else {
    state.compose.layout_mode = 'manual';
    state.compose.grid_rows = preset.rows;
    state.compose.grid_cols = preset.cols;
    state.compose.row_heights = preset.layout?.row_heights || [];
    state.compose.col_widths = preset.layout?.col_widths || [];
  }
  syncComposeControls();
  renderComposePanels();
  commitComposeChange();
}

function parseRatios(text) {
  return String(text || '')
    .split(/[\s,]+/)
    .map((part) => Number(part))
    .filter((value) => Number.isFinite(value) && value > 0);
}

function setInputValue(selector, value) {
  const node = $(selector);
  if (node) node.value = value;
}

function renderLayoutDiagram(result) {
  const node = $('#layoutDiagram');
  if (!node) return;
  if (!result?.diagram) {
    node.textContent = '当前排版（出图后更新）';
    return;
  }
  const header = `${result.rows} 行 × ${result.cols} 列 · ${result.panelCount} 个面板`;
  node.textContent = `${result.diagram}\n\n${header}`;
}

function renderComposePanels() {
  const container = $('#panelCards');
  if (!container) return;
  clear(container);

  const panels = syncComposePanels();
  $('#panelCount').textContent = String(panels.length);
  if (!panels.length) {
    container.append(el('p', { class: 'row__hint', text: '先导入数据，再分配面板。' }));
    return;
  }

  panels.forEach((panel, index) => {
    const names = panel.datasets.join(' / ');
    const card = el('div', { class: 'panel-card' });

    card.append(el('div', { class: 'panel-card__head' }, [
      el('span', { class: 'panel-card__marker', text: panelLabelText(index) }),
      el('span', { class: 'panel-card__names', text: names, title: names }),
      el('button', {
        type: 'button', class: 'button button--tiny', text: '系列',
        onclick: () => openPanelSeriesSheet(index),
      }),
    ]));

    const typeSelect = el('select', { class: 'popup' });
    COMPOSE_CHART_TYPES.forEach((option) => {
      typeSelect.append(el('option', { value: option.value, text: option.label }));
    });
    typeSelect.value = panel.chartType || '';
    typeSelect.addEventListener('change', () => {
      panel.chartType = typeSelect.value;
      commitComposeChange();
    });

    const titleInput = el('input', {
      type: 'text', class: 'textfield', value: panel.title || '',
      placeholder: names, 'aria-label': `面板 ${panelLabelText(index)} 标题`,
    });
    titleInput.addEventListener('change', () => {
      panel.title = titleInput.value.trim();
      commitComposeChange();
    });

    const xInput = el('input', {
      type: 'text', class: 'textfield', value: panel.xlabel || '',
      placeholder: state.settings.xlabel || 'X 轴（全局）',
      'aria-label': `面板 ${panelLabelText(index)} X 轴标签`,
    });
    xInput.addEventListener('change', () => {
      panel.xlabel = xInput.value.trim();
      commitComposeChange();
    });

    const yInput = el('input', {
      type: 'text', class: 'textfield', value: panel.ylabel || '',
      placeholder: state.settings.ylabel || 'Y 轴（全局）',
      'aria-label': `面板 ${panelLabelText(index)} Y 轴标签`,
    });
    yInput.addEventListener('change', () => {
      panel.ylabel = yInput.value.trim();
      commitComposeChange();
    });

    const [rowspan, colspan] = panelSpan(panel, index);
    const spanInput = (value, label, key) => {
      const node = el('input', {
        type: 'number', class: 'stepper', min: '1', max: '6', step: '1',
        value: String(value), 'aria-label': label,
      });
      node.addEventListener('change', () => {
        const next = Math.max(1, Math.min(6, Number(node.value) || 1));
        node.value = String(next);
        // A manual span has to survive the preset, so materialise it first.
        if (state.compose.layout_preset) materializeLayoutPreset();
        panel[key] = next;
        syncComposeControls();
        renderComposePanels();
        commitComposeChange();
      });
      return node;
    };

    card.append(el('div', { class: 'panel-card__body' }, [
      el('div', { class: 'panel-card__field' }, [
        el('span', { class: 'panel-card__label', text: '类型' }), typeSelect,
      ]),
      el('div', { class: 'panel-card__field' }, [
        el('span', { class: 'panel-card__label', text: '标题' }), titleInput,
      ]),
      el('div', { class: 'panel-card__field' }, [
        el('span', { class: 'panel-card__label', text: 'X 轴' }), xInput,
      ]),
      el('div', { class: 'panel-card__field' }, [
        el('span', { class: 'panel-card__label', text: 'Y 轴' }), yInput,
      ]),
      el('div', { class: 'panel-card__field panel-card__field--span' }, [
        el('span', { class: 'panel-card__label', text: '跨行' }),
        spanInput(rowspan, `面板 ${panelLabelText(index)} 跨行`, 'rowspan'),
        el('span', { class: 'panel-card__label', text: '跨列' }),
        spanInput(colspan, `面板 ${panelLabelText(index)} 跨列`, 'colspan'),
      ]),
    ]));

    container.append(card);
  });
}

function openPanelSeriesSheet(index) {
  const panel = syncComposePanels()[index];
  if (!panel) return;

  const rows = state.datasets.map((dataset) => {
    const input = el('input', { type: 'checkbox', class: 'checkbox' });
    input.checked = panel.datasets.includes(dataset.name);
    input.value = dataset.name;
    return { name: dataset.name, input };
  });
  const body = el('div', { class: 'check-list' },
    rows.map((row) => el('label', { class: 'check-row' }, [
      row.input, el('span', { class: 'check-row__name', text: row.name }),
    ])));

  showSheet({
    title: `面板 ${panelLabelText(index)} 的系列`,
    subtitle: '勾选要放进这一格的数据集；被勾走的数据会自动从其它格子移出。',
    body,
    onConfirm: () => {
      const picked = rows.filter((row) => row.input.checked).map((row) => row.name);
      if (!picked.length) {
        toast('每个面板至少要有一个数据集', 'error');
        return false;
      }
      for (const other of state.compose.panels) {
        if (other === panel) continue;
        other.datasets = (other.datasets || []).filter((name) => !picked.includes(name));
      }
      panel.datasets = picked;
      renderComposePanels();
      commitComposeChange();
      return true;
    },
  });
}

function populateComposeControls() {
  const schema = composeSchema();

  const preset = $('#composePreset');
  if (preset) {
    clear(preset);
    (schema.layoutPresets || []).forEach((entry) => {
      preset.append(el('option', { value: entry.key, text: `${entry.key} · ${entry.label}` }));
    });
    preset.value = state.compose.layout_preset || 'auto';
  }

  const font = $('#composeFontFamily');
  if (font) {
    clear(font);
    (schema.fontFamilies || []).forEach((entry) => {
      const label = entry.installed ? entry.label : `${entry.label}（未安装）`;
      font.append(el('option', { value: entry.value, text: label }));
    });
    font.value = state.compose.font_family || '';
  }
}

function syncComposeControls() {
  $$('[data-compose]').forEach((node) => {
    const value = state.compose[node.dataset.compose];
    if (value !== undefined) writeControl(node, value);
  });
  for (const [selector, key] of [
    ['#composeRows', 'grid_rows'], ['#composeCols', 'grid_cols'],
    ['#composeGapX', 'gap_x'], ['#composeGapY', 'gap_y'],
  ]) {
    const node = $(selector);
    if (node) writeControl(node, state.compose[key]);
  }
  setInputValue('#composeRowHeights', (state.compose.row_heights || []).join(', '));
  setInputValue('#composeColWidths', (state.compose.col_widths || []).join(', '));
  const preset = $('#composePreset');
  if (preset) preset.value = state.compose.layout_preset || 'auto';
  const font = $('#composeFontFamily');
  if (font) font.value = state.compose.font_family || '';
  updateComposeVisibility();
}

function bindComposeControls() {
  $$('[data-compose]').forEach((node) => {
    const key = node.dataset.compose;
    const commit = (value) => {
      if (value === null || value === undefined) return;
      if (state.compose[key] === value) return;
      state.compose[key] = value;
      if (key === 'label_style' || key === 'label_position') renderComposePanels();
      updateComposeVisibility();
      commitComposeChange();
    };

    const kind = controlKind(node);
    if (kind === 'switch') {
      node.addEventListener('click', () => {
        const next = node.getAttribute('aria-checked') !== 'true';
        node.setAttribute('aria-checked', next ? 'true' : 'false');
        commit(next);
      });
    } else if (kind === 'segment') {
      $$('button', node).forEach((button) => {
        button.addEventListener('click', () => {
          $$('button', node).forEach((b) => b.setAttribute('aria-checked', 'false'));
          button.setAttribute('aria-checked', 'true');
          commit(button.dataset.value);
        });
      });
    } else if (kind === 'slider') {
      node.addEventListener('input', () => {
        const output = node.parentElement?.querySelector('.slider__value');
        if (output) output.textContent = formatNumber(node.value, Number(node.step) || 1);
        commit(Number(node.value));
      });
    } else if (kind === 'number') {
      node.addEventListener('change', () => commit(Number(node.value)));
    } else {
      node.addEventListener('change', () => commit(node.value));
    }
  });

  $('#composePreset')?.addEventListener('change', (event) => applyLayoutPreset(event.target.value));

  for (const [selector, key] of [['#composeRows', 'grid_rows'], ['#composeCols', 'grid_cols']]) {
    $(selector)?.addEventListener('change', (event) => {
      const value = Math.max(1, Math.min(12, Number(event.target.value) || 1));
      event.target.value = String(value);
      if (state.compose.layout_preset) materializeLayoutPreset();
      state.compose[key] = value;
      state.compose.layout_mode = 'manual';
      syncComposeControls();
      commitComposeChange();
    });
  }

  for (const [selector, key] of [['#composeRowHeights', 'row_heights'],
    ['#composeColWidths', 'col_widths']]) {
    $(selector)?.addEventListener('change', (event) => {
      if (state.compose.layout_preset) materializeLayoutPreset();
      state.compose[key] = parseRatios(event.target.value);
      commitComposeChange();
    });
  }

  $('#autoPanelsButton')?.addEventListener('click', () => {
    state.compose.panels = state.datasets.map((dataset) => ({ datasets: [dataset.name] }));
    renderComposePanels();
    commitComposeChange();
    toast('已按数据集自动分格');
  });

  $('#modeSegment')?.addEventListener('click', (event) => {
    const button = event.target.closest('button[data-mode]');
    if (button) setMode(button.dataset.mode);
  });
}

/**
 * Put the groups that belong to the current mode first: composing is driven by
 * the layout/panel/typography groups, while single charts need the chart groups
 * at the top.  The footer always stays last.
 */
function arrangeInspector() {
  const scroll = $('.inspector__scroll');
  if (!scroll) return;
  const footer = $('.inspector__footer', scroll);
  const sections = $$(':scope > section.group', scroll);
  const composing = sections.filter((node) => node.dataset.mode === 'compose');
  const single = sections.filter((node) => node.dataset.mode !== 'compose');
  const order = state.mode === 'compose'
    ? [...composing, ...single]
    : [...single, ...composing];
  for (const node of order) {
    if (footer) scroll.insertBefore(node, footer);
    else scroll.append(node);
  }
  scroll.scrollTop = 0;
}

function setMode(mode, { render = true } = {}) {
  state.mode = mode === 'compose' ? 'compose' : 'single';
  const segment = $('#modeSegment');
  if (segment) {
    $$('button', segment).forEach((node) => {
      node.setAttribute('aria-checked', node.dataset.mode === state.mode ? 'true' : 'false');
    });
  }
  const composing = state.mode === 'compose';
  const exportButton = $('#exportButton');
  if (exportButton) exportButton.textContent = composing ? '导出拼图' : '导出图表';
  const stageTitle = $('#stageTitle');
  if (stageTitle) stageTitle.textContent = composing ? '拼图预览' : '预览';

  updateVisibility();
  arrangeInspector();
  if (composing) renderComposePanels();
  else renderLayoutDiagram(null);
  persist();
  if (render) debounceRender(0);
}

/* ── Persistence ────────────────────────────────────────────────────────── */

function persist() {
  try {
    const payload = {
      settings: state.settings,
      fit: state.fit,
      zoom: state.zoom,
      theme: state.theme,
      activePalette: state.activePalette,
      datasets: state.datasets,
      mode: state.mode,
      compose: state.compose,
    };
    const text = JSON.stringify(payload);
    if (text.length > MAX_PERSIST_BYTES) {
      // Too large for localStorage: keep the settings, drop the data.
      delete payload.datasets;
      localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
      return;
    }
    localStorage.setItem(STORAGE_KEY, text);
  } catch {
    /* storage full or unavailable - not fatal */
  }
}

function restore() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

/* ── Theme ──────────────────────────────────────────────────────────────── */

const THEME_CYCLE = ['system', 'light', 'dark'];

async function cycleTheme() {
  const index = THEME_CYCLE.indexOf(state.theme);
  const next = THEME_CYCLE[(index + 1) % THEME_CYCLE.length];
  await setTheme(next);
  const label = next === 'system' ? '跟随系统' : next === 'light' ? '浅色' : '深色';
  toast(`外观：${label}`);
}

async function setTheme(theme) {
  state.theme = theme;
  const result = await api.setTheme(theme);
  document.documentElement.dataset.appearance = result.dark ? 'dark' : 'light';
  persist();
}

/* ── Bootstrap ──────────────────────────────────────────────────────────── */

/**
 * The engine spells "no unit" as an empty string, but the unit lists use
 * "(none)" for display.  Without this mapping the <select> would be given a
 * value that matches no option and would render blank.
 */
function unitOptions(units = []) {
  return units.map((unit) => ({
    value: unit === '(none)' ? '' : unit,
    label: unit === '(none)' ? '无单位' : unit,
  }));
}

function populateSchemaControls() {
  const schema = state.schema;

  const fill = (selector, entries) => {
    const node = $(selector);
    if (!node) return;
    clear(node);
    entries.forEach((entry) => node.append(el('option', {
      value: entry.value ?? entry, text: entry.label ?? entry,
    })));
  };

  fill('#ctlXUnit', unitOptions(schema.xUnits));
  fill('#ctlYUnit', unitOptions(schema.yUnits));
  fill('[data-setting="bar_style"]', schema.barStyles || []);
  fill('[data-setting="legend_loc"]', schema.legendLocations || []);

  const fitSelect = $('#fitMethod');
  clear(fitSelect);
  (schema.fitMethods || []).forEach((entry) => {
    fitSelect.append(el('option', { value: entry.value, text: entry.label }));
  });
}

function bindStaticControls() {
  $('#exportButton').addEventListener('click', exportFigure);
  $('#refreshButton').addEventListener('click', () => renderPreview({ force: true }));
  $('#themeButton').addEventListener('click', cycleTheme);

  $('#addDatasetButton').addEventListener('click', () => openDatasetEditor(-1));
  $('#editDatasetButton').addEventListener('click', () => {
    if (state.selected < 0) toast('请先选择一个数据集');
    else openDatasetEditor(state.selected);
  });
  $('#removeDatasetButton').addEventListener('click', removeSelectedDataset);
  $('#clearDatasetsButton').addEventListener('click', clearDatasets);
  $('#importTableButton').addEventListener('click', importTable);
  $('#importMultilineButton').addEventListener('click', importMultiline);
  $('#applyPaletteButton').addEventListener('click', () => applyPaletteToAll());

  $('#resetSettingsButton').addEventListener('click', () => {
    state.settings = { ...state.schema.defaultSettings };
    state.settings.visual_preset = 'default';
    syncControls();
    updateVisibility();
    persist();
    debounceRender(0);
    toast('已恢复默认设置');
  });

  $$('.group__header').forEach((header) => {
    header.addEventListener('click', () => {
      const group = header.parentElement;
      group.dataset.open = group.dataset.open === 'true' ? 'false' : 'true';
    });
  });

  const statsPanel = $('#statsPanel');
  statsPanel.classList.add('is-open');
  const toggleStats = () => {
    const open = statsPanel.classList.toggle('is-open');
    $('#statsToggle').setAttribute('aria-expanded', open ? 'true' : 'false');
  };
  $('#statsToggle').addEventListener('click', toggleStats);
  $('#statsToggle').addEventListener('keydown', (event) => {
    if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); toggleStats(); }
  });

  $('#zoomSegment').addEventListener('click', (event) => {
    const button = event.target.closest('button[data-zoom]');
    if (!button) return;
    state.zoom = button.dataset.zoom;
    $$('button', $('#zoomSegment')).forEach((node) => {
      node.setAttribute('aria-checked', node === button ? 'true' : 'false');
    });
    applyZoom();
    persist();
  });
  $$('button', $('#zoomSegment')).forEach((node) => {
    node.setAttribute('aria-checked', node.dataset.zoom === state.zoom ? 'true' : 'false');
  });

  // Fit controls
  $('#fitMethod').addEventListener('change', (event) => {
    state.fit.method = event.target.value;
    updateVisibility();
    persist();
    debounceRender();
  });
  $('#fitDegree').addEventListener('change', (event) => {
    state.fit.degree = Math.max(1, Math.min(10, Number(event.target.value) || 2));
    event.target.value = String(state.fit.degree);
    persist();
    debounceRender();
  });
  const fitSwitch = (selector, key) => {
    const node = $(selector);
    node.addEventListener('click', () => {
      const next = node.getAttribute('aria-checked') !== 'true';
      setSwitch(node, next);
      state.fit[key] = next;
      persist();
      debounceRender();
    });
  };
  fitSwitch('#fitShowRaw', 'showRaw');
  fitSwitch('#fitShowFit', 'showFit');
  fitSwitch('#fitJitter', 'addJitter');

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeOverlay();
    const meta = event.metaKey || event.ctrlKey;
    if (meta && event.key.toLowerCase() === 's') { event.preventDefault(); exportFigure(); }
    if (meta && event.key.toLowerCase() === 'o') {
      event.preventDefault();
      if (event.shiftKey) importMultiline(); else importTable();
    }
  });

  window.addEventListener('resize', () => { if (state.zoom === 'fit') applyZoom(); });
}

function bindMenu() {
  api.onMenu((command, payload) => {
    switch (command) {
      case 'import-table': importTable(); break;
      case 'import-multiline': importMultiline(); break;
      case 'export': exportFigure(); break;
      case 'refresh': renderPreview({ force: true }); break;
      case 'focus-inspector': $('#inspector').scrollIntoView({ block: 'start' }); break;
      case 'theme': setTheme(payload || 'system'); break;
      case 'about-cli':
        toast('命令行版：easyfig plot --table data.csv -o out.png');
        break;
      default: break;
    }
  });
}

function showEngineError(message) {
  const sidebar = $('#sidebar');
  const existing = $('.engine-error', sidebar);
  if (existing) existing.remove();
  sidebar.prepend(el('div', { class: 'engine-error' }, [
    el('strong', { text: '无法启动绘图引擎' }),
    el('div', { text: message }),
    el('code', { text: `请设置 EASYFIG_PYTHON 指向 Python，或在项目根目录执行：\n  python -m pip install -e .` }),
  ]));
  setStatus('绘图引擎不可用', 'error');
}

async function init() {
  try {
    state.info = await api.info();
  } catch {
    state.info = null;
  }

  const platform = state.info?.platform || 'unknown';
  document.body.classList.add(`platform-${platform}`);

  if (state.info?.python && !state.info.python.found) {
    showEngineError('未找到 Python 解释器。');
  }

  const saved = restore();
  if (saved?.theme) state.theme = saved.theme;
  else state.theme = state.info?.theme || 'system';
  await setTheme(state.theme);

  try {
    state.schema = await api.request('hello');
  } catch (error) {
    showEngineError(error.message);
    document.body.classList.remove('booting');
    return;
  }

  state.settings = { ...state.schema.defaultSettings };
  if (saved?.settings) {
    for (const [key, value] of Object.entries(saved.settings)) {
      if (key in state.settings && !key.startsWith('__')) state.settings[key] = value;
    }
  }
  if (saved?.fit) state.fit = { ...state.fit, ...saved.fit };
  if (saved?.zoom) state.zoom = saved.zoom;
  if (typeof saved?.activePalette === 'number') state.activePalette = saved.activePalette;

  state.compose = { ...composeDefaults(), panels: [] };
  if (saved?.compose) {
    for (const [key, value] of Object.entries(saved.compose)) {
      if (key === 'panels') continue;
      if (key in state.compose) state.compose[key] = value;
    }
    if (Array.isArray(saved.compose.panels)) state.compose.panels = saved.compose.panels;
  }
  state.mode = saved?.mode === 'compose' ? 'compose' : 'single';
  // `--mode=compose` on the command line (see main.js) wins over the saved mode.
  const requestedMode = new URLSearchParams(window.location.search).get('mode');
  if (requestedMode === 'compose' || requestedMode === 'single') state.mode = requestedMode;

  state.datasets = Array.isArray(saved?.datasets) && saved.datasets.length
    ? saved.datasets
    : structuredClone(DEMO_DATASETS);
  state.selected = state.datasets.length ? 0 : -1;

  populateSchemaControls();
  populateComposeControls();
  bindSettings();
  bindColors();
  bindStaticControls();
  bindComposeControls();
  bindMenu();

  $('#documentSubtitle').textContent = state.datasets.length
    ? `${state.datasets.length} 个数据集`
    : '未命名图表';

  syncControls();
  syncComposeControls();
  updateVisibility();
  renderDatasetList();
  renderPaletteStack();
  renderComposePanels();
  setMode(state.mode, { render: false });
  document.body.classList.remove('booting');

  api.onEngineReady(() => setStatus('就绪', 'ready'));
  api.onEngineError((payload) => showEngineError(payload.message));

  setStatus('正在绘制…', 'busy');
  renderPreview();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
