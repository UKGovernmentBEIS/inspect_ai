/**
 * listing.js
 * Shared UI components and filter logic for card-grid listing pages.
 * Used by both /docs/extensions and /docs/evals SPAs.
 */

// ── DOM helpers ────────────────────────────────────────────────────────────
export function h(tag, attrs = {}, ...children) {
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

export function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

// ── Filter logic ──────────────────────────────────────────────────────────
/**
 * Generic item filter: text search across configurable fields + category match.
 * When searchQ is non-empty, category filter is bypassed.
 *
 * @param {Object[]} items
 * @param {Object} options
 * @param {string} [options.category='All']
 * @param {string} [options.searchQ='']
 * @param {string[]} [options.searchFields] - Field names to search (strings and string arrays)
 * @returns {Object[]}
 */
export function filterItems(items, { category = 'All', searchQ = '', searchFields = ['name', 'desc', 'categories'] } = {}) {
  let list = items;
  if (searchQ.trim()) {
    const lq = searchQ.toLowerCase();
    list = list.filter(e =>
      searchFields.some(field => {
        const val = e[field];
        if (Array.isArray(val)) return val.some(v => String(v).toLowerCase().includes(lq));
        return val != null && String(val).toLowerCase().includes(lq);
      })
    );
  } else if (category !== 'All') {
    list = list.filter(e => (e.categories || []).includes(category));
  }
  return list;
}

/**
 * Count items per category, with optional pre-filter.
 * Returns { All: N, CategoryA: N, CategoryB: N, ... }
 */
export function getCategoryCounts(items, preFilter) {
  const base = preFilter ? items.filter(preFilter) : items;
  const counts = { All: base.length };
  for (const e of base) {
    for (const cat of (e.categories || [])) {
      counts[cat] = (counts[cat] || 0) + 1;
    }
  }
  return counts;
}

// ── Shared components ─────────────────────────────────────────────────────
export function filterChip(label, onClear) {
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
    }, '\u00d7'),
  );
}

export function emptyState(noun) {
  return h('div', { class: 'text-center text-body-tertiary py-5' },
    h('h5', { class: 'mb-1' }, `No ${noun} match your filters`),
    h('p', { class: 'small mb-0' }, 'Try removing some filters or searching instead.'),
  );
}

export function sidebarFilterBtn({ active, label, count, onClick, indent }) {
  return h('button', {
    type: 'button',
    class: `list-group-item list-group-item-action d-flex justify-content-between align-items-center${active ? ' active' : ''}`,
    style: indent ? { paddingLeft: '1.1rem' } : undefined,
    onclick: onClick,
  },
    h('span', {}, label),
    h('span', { class: 'count small' }, String(count ?? 0)),
  );
}

export function searchInput({ value, placeholder, onInput }) {
  const input = h('input', {
    type: 'search',
    class: 'form-control form-control-sm',
    value,
    placeholder,
    oninput: (e) => onInput(e.target.value),
    style: { paddingLeft: '2rem' },
  });
  input.dataset.role = 'search-input';

  const icon = h('span', {
    style: {
      position: 'absolute', left: '.6rem', top: '50%',
      transform: 'translateY(-50%)', pointerEvents: 'none',
      color: 'var(--bs-secondary-color, #6c757d)',
    },
    html: '<svg width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>',
  });

  return h('div', { class: 'search-wrap position-relative' }, icon, input);
}

export function mainHeaderLayout({ title, chips, count, countNoun, searchEl }) {
  return h('div', { class: 'listing-main-header' },
    h('h1', {}, title),
    ...chips.filter(Boolean),
    h('span', { class: 'result-count' }, `${count} ${countNoun}`),
    searchEl,
  );
}

export function cardGrid(items, renderCard) {
  return h('div', { class: 'listing-grid' }, ...items.map(renderCard));
}

export function groupedGrid({ items, categories, primaryCategory, renderCard }) {
  const present = categories.filter(cat => items.some(e => primaryCategory(e) === cat));
  return h('div', {},
    ...present.map((cat, i) =>
      h('div', {},
        h('div', { class: `listing-cat-heading${i === 0 ? ' listing-cat-first' : ''}` }, cat),
        cardGrid(items.filter(e => primaryCategory(e) === cat), renderCard),
      ),
    ),
  );
}

// ── Sidebar helpers ───────────────────────────────────────────────────────
export function sidebarLayout(...sections) {
  return h('aside', { class: 'listing-sidebar border-end' },
    h('div', { class: 'listing-sidebar-inner px-3 py-3' }, ...sections.flat()),
  );
}

export function categoryFilterSection({ categories, counts, activeCategory, allLabel, onCategory, subCategories }) {
  return [
    h('h6', { class: 'text-uppercase text-body-tertiary small fw-semibold mb-2' }, 'Category'),
    h('div', { class: 'list-group list-group-flush' },
      sidebarFilterBtn({
        active: activeCategory === 'All', label: allLabel,
        count: counts.All || 0, onClick: () => onCategory('All'),
      }),
      ...categories
        .filter((c) => counts[c])
        .map((c) => sidebarFilterBtn({
          active: activeCategory === c, label: c,
          count: counts[c], onClick: () => onCategory(c),
          indent: subCategories ? !!subCategories[c] : false,
        })),
    ),
  ];
}

// ── Page rendering ────────────────────────────────────────────────────────
export function renderListingPage({ root, sidebarEl, headerEl, contentEl, searchQ }) {
  clear(root);
  const shell = h('div', { class: 'd-flex' },
    sidebarEl,
    h('main', { class: 'flex-grow-1 px-3 pt-3 pb-3 px-md-4' },
      headerEl,
      contentEl,
    ),
  );
  root.append(shell);

  if (searchQ) {
    const input = shell.querySelector('input[data-role="search-input"]');
    if (input && document.activeElement !== input) {
      input.focus();
      input.setSelectionRange(searchQ.length, searchQ.length);
    }
  }
}

// ── App bootstrap helpers ─────────────────────────────────────────────────
export function initKeyboardShortcut(rootSelector) {
  window.addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
      e.preventDefault();
      const input = document.querySelector(`${rootSelector} input[data-role="search-input"]`);
      if (input) { input.focus(); input.select(); }
    }
  });
}

export async function initApp({ rootId, onData }) {
  const root = document.getElementById(rootId);
  if (!root) return null;

  const src = root.dataset.src || `./${rootId.replace('-app', '')}.json`;
  const res = await fetch(src);
  if (!res.ok) {
    root.append(h('p', { class: 'text-danger p-3' }, `Failed to load ${src}: ${res.status}`));
    return null;
  }
  const data = await res.json();
  onData(root, data);
  return root;
}
