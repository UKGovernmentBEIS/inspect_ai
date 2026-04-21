/**
 * extensions-app.js
 * Vanilla-JS renderer for the /docs/extensions SPA. Mounts into
 * #extensions-app, fetches extensions.json. Cards link directly to
 * external URLs (no internal detail pages).
 *
 * Layout mirrors /docs/evals with two small differences:
 *   1. Title + result-count + search on one row.
 *   2. When no filter/search is active, category headers break up the grid.
 */

// ── Categories (ordered) ───────────────────────────────────────────────────
const CATEGORIES = [
  'Sandboxes', 'Analysis', 'Frameworks', 'Tooling',
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

// ── Filter logic ───────────────────────────────────────────────────────────
function primaryCategory(ext) {
  return (ext.categories && ext.categories[0]) || 'Tooling';
}

function filterItems(items, { category, searchQ }) {
  let list = items;
  if (searchQ.trim()) {
    const lq = searchQ.toLowerCase();
    list = list.filter(e =>
      e.name.toLowerCase().includes(lq) ||
      (e.desc || '').toLowerCase().includes(lq) ||
      (e.author || '').toLowerCase().includes(lq) ||
      (e.categories || []).some(c => c.toLowerCase().includes(lq))
    );
  } else if (category !== 'All') {
    list = list.filter(e => (e.categories || []).includes(category));
  }
  return list;
}

function categoryCounts(items) {
  const counts = { All: items.length };
  for (const e of items) {
    for (const c of (e.categories || [])) counts[c] = (counts[c] || 0) + 1;
  }
  return counts;
}

// ── Components ──────────────────────────────────────────────────────────────
function extCard(ext) {
  const authorEl = ext.author_url
    ? h('a', {
        class: 'text-body-tertiary text-nowrap small text-decoration-none',
        href: ext.author_url,
        target: '_blank',
        rel: 'noopener',
        onclick: (e) => e.stopPropagation(),
      }, ext.author)
    : h('small', { class: 'text-body-tertiary text-nowrap' }, ext.author);

  return h('a', {
    class: 'ext-card-link d-block',
    href: ext.url,
    target: '_blank',
    rel: 'noopener',
  },
    h('div', { class: 'card h-100' },
      h('div', { class: 'card-body d-flex flex-column' },
        h('div', { class: 'd-flex justify-content-between align-items-start gap-2' },
          h('h6', { class: 'card-title mb-0 fw-normal text-body-emphasis' }, ext.name),
          authorEl,
        ),
        h('p', { class: 'card-text small text-body-secondary mt-2 mb-0 flex-grow-1' }, ext.desc),
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

function sidebar({ state, counts, onCategory }) {
  return h('aside', { class: 'extensions-sidebar border-end' },
    h('div', { class: 'extensions-sidebar-inner px-3 py-3' },
      h('h6', { class: 'text-uppercase text-body-tertiary small fw-semibold mb-2' }, 'Category'),
      h('div', { class: 'list-group list-group-flush' },
        sidebarFilterBtn({
          active: state.category === 'All', label: 'All Extensions',
          count: counts.All || 0, onClick: () => onCategory('All'),
        }),
        ...CATEGORIES
          .filter((c) => counts[c])
          .map((c) => sidebarFilterBtn({
            active: state.category === c, label: c,
            count: counts[c], onClick: () => onCategory(c),
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
        fontSize: '1.1em', lineHeight: 1, padding: 0, cursor: 'pointer',
      },
    }, '×'),
  );
}

function mainHeader({ state, count, onSearchInput, onClearCategory }) {
  const searchInput = h('input', {
    type: 'search',
    class: 'form-control form-control-sm',
    value: state.searchQ,
    placeholder: 'Search extensions…',
    oninput: (e) => onSearchInput(e.target.value),
    style: { paddingLeft: '2rem' },
  });
  searchInput.dataset.role = 'search-input';

  const searchIcon = h('span', {
    style: {
      position: 'absolute', left: '.6rem', top: '50%',
      transform: 'translateY(-50%)', pointerEvents: 'none',
      color: 'var(--bs-secondary-color, #6c757d)',
    },
    html: '<svg width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>',
  });

  const categoryChip = state.category !== 'All'
    ? filterChip(state.category, onClearCategory)
    : null;

  return h('div', { class: 'extensions-main-header' },
    h('h1', {}, 'Extensions'),
    categoryChip,
    h('span', { class: 'result-count' }, `${count} extensions`),
    h('div', { class: 'search-wrap position-relative' }, searchIcon, searchInput),
  );
}

function emptyState() {
  return h('div', { class: 'text-center text-body-tertiary py-5' },
    h('h5', { class: 'mb-1' }, 'No extensions match your filters'),
    h('p', { class: 'small mb-0' }, 'Try removing some filters or searching instead.'),
  );
}

function cardGrid(items) {
  return h('div', { class: 'extensions-grid' }, ...items.map(extCard));
}

function groupedGrid(items) {
  // Group items by their primary category, respecting CATEGORIES order.
  const present = CATEGORIES.filter(cat => items.some(e => primaryCategory(e) === cat));
  return h('div', {},
    ...present.map((cat, i) =>
      h('div', {},
        h('div', { class: `cat-group-heading${i === 0 ? ' cat-group-first' : ''}` }, cat),
        cardGrid(items.filter(e => primaryCategory(e) === cat)),
      ),
    ),
  );
}

// ── App state + rendering ──────────────────────────────────────────────────
let root;
let items = [];
let state = { category: 'All', searchQ: '' };

function render() {
  clear(root);

  const results = filterItems(items, state);
  const counts  = categoryCounts(items);
  const grouped = state.category === 'All' && !state.searchQ.trim();

  const shell = h('div', { class: 'd-flex' },
    sidebar({
      state, counts,
      onCategory: (key) => { state.category = key; render(); },
    }),
    h('main', { class: 'flex-grow-1 px-3 pt-3 pb-3 px-md-4' },
      mainHeader({
        state,
        count: results.length,
        onSearchInput:   (v) => { state.searchQ = v; render(); },
        onClearCategory: () => { state.category = 'All'; render(); },
      }),
      results.length === 0
        ? emptyState()
        : grouped
          ? groupedGrid(results)
          : cardGrid(results),
    ),
  );
  root.append(shell);

  const input = shell.querySelector('input[data-role="search-input"]');
  if (input && document.activeElement !== input && state.searchQ) {
    input.focus();
    input.setSelectionRange(state.searchQ.length, state.searchQ.length);
  }
}

async function init() {
  root = document.getElementById('extensions-app');
  if (!root) return;

  const src = root.dataset.src || './extensions.json';
  const res = await fetch(src);
  if (!res.ok) {
    root.append(h('p', { class: 'text-danger p-3' }, `Failed to load ${src}: ${res.status}`));
    return;
  }
  items = await res.json();

  window.addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
      e.preventDefault();
      const input = document.querySelector('#extensions-app input[data-role="search-input"]');
      if (input) { input.focus(); input.select(); }
    }
  });

  render();
}

init();
