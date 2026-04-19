/**
 * evals-app.js
 * Vanilla-JS renderer for the /docs/evals SPA. Mounts into #evals-app,
 * fetches evals.json, uses evals-filter.js for filter/sort/count logic,
 * and implements hash-path routing (#/, #/?category=…, #/eval/<id>) with
 * history.pushState. Markup is Bootstrap 5 (card, list-group, badge,
 * form-control, grid) — the host site ships Bootstrap CSS + JS.
 */

import {
  filterEvals,
  getCategoryCounts,
  getSourceCounts,
  loadPersistedState,
  savePersistedState,
  getInstallCmd,
  getRunCmd,
  getPythonSnippet,
  getSourceUrl,
} from './evals-filter.js';

// ── Categories (ordered) ───────────────────────────────────────────────────
const CATEGORIES = [
  'Coding', 'Assistants', 'Cybersecurity', 'Safeguards', 'Mathematics',
  'Reasoning', 'Knowledge', 'Multimodal', 'Scheming', 'Bias', 'Behavior',
  'Personality', 'Writing', 'Other',
];

// ── DOM helpers ────────────────────────────────────────────────────────────
function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === 'html') el.innerHTML = v;
    else el.setAttribute(k, v);
  }
  for (const c of children.flat()) {
    if (c == null || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

const clear = (node) => { while (node.firstChild) node.removeChild(node.firstChild); };

function copyToClipboard(text, button) {
  navigator.clipboard?.writeText(text);
  if (!button) return;
  const orig = button.textContent;
  button.textContent = 'Copied';
  button.disabled = true;
  setTimeout(() => { button.textContent = orig; button.disabled = false; }, 1400);
}

// ── Hash routing ────────────────────────────────────────────────────────────
function parseHash(hash) {
  const raw = (hash || '').replace(/^#/, '');
  if (!raw || raw === '/') return { route: 'index', filters: {} };
  if (raw.startsWith('/eval/')) return { route: 'detail', id: decodeURIComponent(raw.slice(6)) };
  if (raw.startsWith('/?')) {
    const params = new URLSearchParams(raw.slice(2));
    return {
      route: 'index',
      filters: {
        category: params.get('category') || 'All',
        source:   params.get('source')   || 'All',
        searchQ:  params.get('q')        || '',
      },
    };
  }
  return { route: 'index', filters: {} };
}

function buildHash(route) {
  if (route.route === 'detail') return `#/eval/${encodeURIComponent(route.id)}`;
  const f = route.filters || {};
  const params = new URLSearchParams();
  if (f.category && f.category !== 'All') params.set('category', f.category);
  if (f.source   && f.source   !== 'All') params.set('source',   f.source);
  if (f.searchQ  && f.searchQ.trim())     params.set('q',        f.searchQ.trim());
  const qs = params.toString();
  return qs ? `#/?${qs}` : '#/';
}

function pushRoute(route, replace = false) {
  const newHash = buildHash(route);
  if (newHash === location.hash || (newHash === '#/' && !location.hash)) return;
  history[replace ? 'replaceState' : 'pushState'](null, '', newHash);
}

// ── Components ──────────────────────────────────────────────────────────────
function pill(source) {
  const cls = source === 'harbor' ? 'evals-pill-harbor' : 'evals-pill-evals';
  return h('span', { class: `badge rounded-pill fw-medium ${cls}` },
    source === 'harbor' ? 'inspect_harbor' : 'inspect_evals');
}

function evalCard(eval_) {
  const pkgLabel = eval_.source === 'harbor' ? 'inspect_harbor' : 'inspect_evals';
  const contrib = (eval_.contributors && eval_.contributors[0]) || '';
  const samples = eval_.samples != null
    ? `${Number(eval_.samples).toLocaleString()} samples`
    : '';

  return h('a', {
    class: 'eval-card-link d-block',
    href: buildHash({ route: 'detail', id: eval_.id }),
    onclick: (e) => { e.preventDefault(); navigate({ route: 'detail', id: eval_.id }); },
  },
    h('div', { class: 'card h-100' },
      h('div', { class: 'card-body d-flex flex-column gap-2' },
        h('div', { class: 'd-flex justify-content-between align-items-start gap-2' },
          h('h6', { class: 'card-title mb-0 fw-normal text-body-emphasis' }, eval_.name),
          h('small', { class: 'text-body-tertiary text-nowrap' }, pkgLabel),
        ),
        h('p', { class: 'card-text small text-body-secondary mb-0 flex-grow-1' }, eval_.desc),
        h('div', { class: 'd-flex justify-content-between align-items-center small text-body-tertiary mt-1' },
          contrib ? h('span', {}, `@${contrib}`) : h('span'),
          samples ? h('span', { class: 'font-monospace' }, samples) : null,
        ),
      ),
    ),
  );
}

function sidebarFilterBtn({ active, label, count, onClick }) {
  return h('button', {
    type: 'button',
    class: `list-group-item list-group-item-action d-flex justify-content-between align-items-center${active ? ' active' : ''}`,
    onclick: onClick,
  },
    h('span', {}, label),
    h('span', { class: 'count small' }, String(count ?? 0)),
  );
}

function sidebar({ state, categoryCounts, sourceCounts, onPackage, onCategory }) {
  return h('aside', { class: 'evals-sidebar border-end' },
    h('div', { class: 'evals-sidebar-inner px-3 py-3' },

      h('h6', { class: 'text-uppercase text-body-tertiary small fw-semibold mb-2' }, 'Package'),
      h('div', { class: 'list-group list-group-flush mb-4' },
        sidebarFilterBtn({
          active: state.source === 'All', label: 'All Packages',
          count: sourceCounts.All, onClick: () => onPackage('All'),
        }),
        sidebarFilterBtn({
          active: state.source === 'evals', label: 'inspect_evals',
          count: sourceCounts.evals, onClick: () => onPackage('evals'),
        }),
        sidebarFilterBtn({
          active: state.source === 'harbor', label: 'inspect_harbor',
          count: sourceCounts.harbor, onClick: () => onPackage('harbor'),
        }),
      ),

      h('h6', { class: 'text-uppercase text-body-tertiary small fw-semibold mb-2' }, 'Category'),
      h('div', { class: 'list-group list-group-flush' },
        sidebarFilterBtn({
          active: state.category === 'All', label: 'All Evals',
          count: categoryCounts.All || 0, onClick: () => onCategory('All'),
        }),
        ...CATEGORIES
          .filter((c) => categoryCounts[c])
          .map((c) => sidebarFilterBtn({
            active: state.category === c, label: c,
            count: categoryCounts[c], onClick: () => onCategory(c),
          })),
      ),
    ),
  );
}

function filterChip(label, onClear) {
  return h('span', {
    class: 'badge rounded-pill bg-primary-subtle text-primary-emphasis border border-primary-subtle d-inline-flex align-items-center fw-normal',
    style: { gap: '.3rem' },
  },
    h('span', {}, label),
    h('button', {
      type: 'button',
      'aria-label': `Remove ${label} filter`,
      onclick: onClear,
      style: {
        background: 'transparent', border: 0, color: 'inherit',
        fontSize: '1.1em', lineHeight: 1, padding: 0,
        cursor: 'pointer',
      },
    }, '×'),
  );
}

function mainHeader({ state, count, onSearchInput, onClearSearch, onClearSource, onClearCategory }) {
  const searchInput = h('input', {
    type: 'search',
    class: 'form-control form-control-sm',
    value: state.searchQ,
    placeholder: 'Search evals…',
    oninput: (e) => onSearchInput(e.target.value),
    style: { maxWidth: '240px' },
  });
  searchInput.dataset.role = 'search-input';

  const sourceChip = state.source !== 'All'
    ? filterChip(
        state.source === 'evals' ? 'inspect_evals' : 'inspect_harbor',
        onClearSource,
      )
    : null;

  const categoryChip = state.category !== 'All'
    ? filterChip(state.category, onClearCategory)
    : null;

  return h('div', { class: 'd-flex align-items-center gap-2 flex-wrap mb-3 evals-main-header' },
    sourceChip,
    categoryChip,
    h('span', { class: 'text-body-tertiary small' }, `${count} evals`),
    h('div', { class: 'ms-auto' }, searchInput),
  );
}

function emptyState() {
  return h('div', { class: 'text-center text-body-tertiary py-5' },
    h('h5', { class: 'mb-1' }, 'No evals match your filters'),
    h('p', { class: 'small mb-0' }, 'Try removing some filters or searching instead.'),
  );
}

// ── Detail page ────────────────────────────────────────────────────────────
function codeBlock(text, lang = '') {
  const langClass = lang ? ` ${lang}` : '';
  return h('div', { class: 'sourceCode' },
    h('pre', { class: `sourceCode${langClass}` },
      h('code', { class: lang ? `sourceCode ${lang}` : '' }, text.trimEnd()),
    ),
  );
}

function heroMeta(label, value) {
  if (!value) return null;
  return h('div', {},
    h('div', { class: 'text-uppercase text-body-tertiary small fw-semibold', style: { letterSpacing: '.06em' } }, label),
    h('div', { class: 'small' }, value),
  );
}

function detailPage(eval_) {
  const contributors = eval_.contributors || [];
  const contribLine = contributors.length
    ? contributors.map((c) => `@${c}`).join(', ')
    : null;
  const runCmd     = getRunCmd(eval_);
  const installCmd = getInstallCmd(eval_);
  const sourceUrl  = getSourceUrl(eval_);
  const pyText     = getPythonSnippet(eval_);

  const optionsText = [
    `inspect eval ${eval_.code} --model anthropic/claude-opus-4-6`,
    `inspect eval ${eval_.code} --model google/gemini-3.1-pro-preview`,
    `inspect eval ${eval_.code} --limit 10`,
    `inspect eval ${eval_.code} --temperature 0.5`,
    `inspect eval ${eval_.code} --reasoning-effort medium`,
  ].join('\n');

  const sourcePill = h('a', {
    class: 'badge border text-decoration-none fw-normal',
    href: '#/',
    onclick: (e) => { e.preventDefault(); navigate({ route: 'index', filters: { source: eval_.source } }); },
    style: { color: 'inherit', background: 'transparent', borderRadius: '.25rem', padding: '.4em .8em' },
  }, eval_.source === 'harbor' ? 'inspect_harbor' : 'inspect_evals');

  const categoryPill = h('a', {
    class: 'badge border text-decoration-none fw-normal',
    href: buildHash({ route: 'index', filters: { category: eval_.category } }),
    onclick: (e) => { e.preventDefault(); navigate({ route: 'index', filters: { category: eval_.category } }); },
    style: { color: 'inherit', background: 'transparent', borderRadius: '.25rem', padding: '.4em .8em' },
  }, eval_.category);

  const hero = h('div', { class: 'border-bottom pb-4' },
    h('h1', { class: 'fw-semibold mb-2' }, eval_.name),
    h('div', { class: 'd-flex align-items-center gap-2 flex-wrap mb-3' },
      sourcePill, categoryPill,
    ),
    h('div', { class: 'd-flex flex-wrap gap-4' },
      contribLine ? heroMeta('Contributed by', contribLine) : null,
      heroMeta('Source', h('a', { href: eval_.url || sourceUrl, target: '_blank', rel: 'noopener' },
        `${eval_.code.split('/').pop()} ↗`)),
      eval_.paper ? heroMeta('Paper', h('a', { href: eval_.paper, target: '_blank', rel: 'noopener' }, 'arXiv ↗')) : null,
      eval_.samples != null ? heroMeta('Samples', Number(eval_.samples).toLocaleString()) : null,
    ),
  );

  return h('div', { class: 'container pb-3', style: { maxWidth: '800px' } },
    hero,
    h('div', { class: 'py-4' },
      h('section', {},
        h('p', {},
          eval_.desc,
          ' For complete details, see ',
          h('a', { href: eval_.url || sourceUrl, target: '_blank', rel: 'noopener' },
            eval_.source === 'harbor' ? `Harbor Registry: ${eval_.name}` : `Inspect Evals: ${eval_.name}`),
          '.',
        ),
      ),
      h('section', { class: 'mt-2' },
        h('h2', {}, 'Usage'),
        h('p', {}, 'Install the package:'),
        codeBlock(installCmd, 'bash'),
        h('p', { class: 'mt-3' }, 'Run the eval from the CLI:'),
        codeBlock(runCmd, 'bash'),
        h('p', { class: 'mt-3' }, 'Or use the Python API:'),
        codeBlock(pyText, 'python'),
      ),
      h('section', {},
        h('h2', {}, 'Options'),
        h('p', {},
          'Run against different models or control evaluation behaviour with standard options:'),
        codeBlock(optionsText, 'bash'),
        h('a', {
          href: 'https://inspect.aisi.org.uk/options.html',
          target: '_blank', rel: 'noopener',
          class: 'mt-2 d-inline-block',
        }, 'View all options in the Inspect docs ↗'),
      ),
    ),
  );
}

// ── App state + rendering ──────────────────────────────────────────────────
let root;
let evals = [];
let state = { category: 'All', source: 'All', searchQ: '' };
let view = { route: 'index' };

function navigate(next, { replace = false } = {}) {
  view = next.route === 'detail'
    ? { route: 'detail', id: next.id }
    : { route: 'index' };

  if (next.filters) {
    const filters = next.filters;
    state = {
      category: filters.category ?? 'All',
      source:   filters.source   ?? 'All',
      searchQ:  filters.searchQ  ?? '',
    };
  }

  pushRoute(
    view.route === 'detail'
      ? { route: 'detail', id: view.id }
      : { route: 'index', filters: state },
    replace,
  );
  savePersistedState({ category: state.category, source: state.source });
  render();
}

function applyHash() {
  const parsed = parseHash(location.hash);
  if (parsed.route === 'detail') {
    view = { route: 'detail', id: parsed.id };
  } else {
    view = { route: 'index' };
    if (location.hash && location.hash !== '#/') {
      state = {
        category: parsed.filters.category || 'All',
        source:   parsed.filters.source   || 'All',
        searchQ:  parsed.filters.searchQ  || '',
      };
    }
  }
  render();
}

function focusSearch() {
  const input = document.querySelector('#evals-app input[data-role="search-input"]');
  if (input) { input.focus(); input.select(); }
}

function render() {
  clear(root);
  if (view.route === 'detail') {
    const ev = evals.find((e) => e.id === view.id);
    if (!ev) {
      root.append(
        h('div', { class: 'container py-5', style: { maxWidth: '720px' } },
          h('h1', { class: 'h4' }, 'Eval not found'),
          h('p', {}, `No eval with id “${view.id}” in this listing.`),
          h('a', {
            href: '#/',
            onclick: (e) => { e.preventDefault(); navigate({ route: 'index', filters: {} }); },
          }, '← All Evals'),
        ),
      );
      return;
    }
    window.scrollTo(0, 0);
    root.append(detailPage(ev));
    return;
  }

  const results        = filterEvals(evals, state);
  const categoryCounts = getCategoryCounts(evals, state.source);
  const sourceCounts   = getSourceCounts(evals);

  const shell = h('div', { class: 'd-flex' },
    sidebar({
      state, categoryCounts, sourceCounts,
      onPackage:  (key) => navigate({ route: 'index', filters: { ...state, source:   key } }),
      onCategory: (key) => navigate({ route: 'index', filters: { ...state, category: key } }),
    }),
    h('main', { class: 'flex-grow-1 px-3 pb-3 px-md-4' },
      h('h1', { class: 'fw-semibold mt-0 mb-2' }, 'Evals'),
      mainHeader({
        state,
        count: results.length,
        onSearchInput: (v) => {
          state.searchQ = v;
          pushRoute({ route: 'index', filters: state }, /*replace*/ true);
          render();
        },
        onClearSearch: () => navigate({ route: 'index', filters: { ...state, searchQ: '' } }),
        onClearSource: () => navigate({ route: 'index', filters: { ...state, source: 'All' } }),
        onClearCategory: () => navigate({ route: 'index', filters: { ...state, category: 'All' } }),
      }),
      results.length === 0
        ? emptyState()
        : h('div', { class: 'evals-grid' },
            ...results.map((ev) => evalCard(ev))),
    ),
  );
  root.append(shell);

  // Preserve search input focus + caret across re-renders
  const input = shell.querySelector('input[data-role="search-input"]');
  if (input && document.activeElement !== input && state.searchQ) {
    input.focus();
    input.setSelectionRange(state.searchQ.length, state.searchQ.length);
  }
}

async function init() {
  root = document.getElementById('evals-app');
  if (!root) return;

  const src = root.dataset.src || './evals.json';
  const res = await fetch(src);
  if (!res.ok) {
    root.append(h('p', { class: 'text-danger p-3' }, `Failed to load ${src}: ${res.status}`));
    return;
  }
  evals = await res.json();

  const parsed = parseHash(location.hash);
  const persisted = loadPersistedState();
  if (parsed.route === 'detail' || (location.hash && location.hash !== '#/')) {
    state = {
      category: parsed.filters?.category || 'All',
      source:   parsed.filters?.source   || 'All',
      searchQ:  parsed.filters?.searchQ  || '',
    };
    view = parsed.route === 'detail' ? { route: 'detail', id: parsed.id } : { route: 'index' };
  } else {
    state = { category: persisted.category, source: persisted.source, searchQ: '' };
    pushRoute({ route: 'index', filters: state }, /*replace*/ true);
  }

  window.addEventListener('popstate', applyHash);
  window.addEventListener('hashchange', applyHash);
  window.addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
      e.preventDefault();
      focusSearch();
    }
  });

  render();
}

init();
