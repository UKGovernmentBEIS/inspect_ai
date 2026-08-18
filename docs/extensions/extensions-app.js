/**
 * extensions-app.js
 * Card-grid listing for the /docs/extensions page.
 * Uses shared listing components; adds extension-specific card rendering
 * and simple category-only filtering.
 */
import {
  h, filterItems, getCategoryCounts,
  filterChip, emptyState,
  searchInput, mainHeaderLayout, cardGrid, groupedGrid,
  sidebarLayout, categoryFilterSection, renderListingPage,
  initKeyboardShortcut, initApp,
} from '../listing/listing.js';

const CATEGORIES = ['Sandboxes', 'Analysis', 'Frameworks', 'Tooling'];
const SEARCH_FIELDS = ['name', 'desc', 'author', 'categories'];

function primaryCategory(ext) {
  return (ext.categories && ext.categories[0]) || 'Tooling';
}

function extCard(ext) {
  const authorEl = ext.author_url
    ? h('a', {
        class: 'text-body-tertiary text-nowrap small text-decoration-none',
        href: ext.author_url, target: '_blank', rel: 'noopener',
        onclick: (e) => e.stopPropagation(),
      }, ext.author)
    : h('small', { class: 'text-body-tertiary text-nowrap' }, ext.author);

  return h('a', {
    class: 'listing-card-link d-block', href: ext.url,
    target: '_blank', rel: 'noopener',
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

// ── App state + rendering ──────────────────────────────────────────────────
let root;
let items = [];
let state = { category: 'All', searchQ: '' };

function render() {
  const results = filterItems(items, { ...state, searchFields: SEARCH_FIELDS });
  const counts  = getCategoryCounts(items);
  const isGrouped = state.category === 'All' && !state.searchQ.trim();

  const categoryChip = state.category !== 'All'
    ? filterChip(state.category, () => { state.category = 'All'; render(); })
    : null;

  renderListingPage({
    root,
    searchQ: state.searchQ,
    sidebarEl: sidebarLayout(
      categoryFilterSection({
        categories: CATEGORIES, counts, activeCategory: state.category,
        allLabel: 'All Extensions',
        onCategory: (key) => { state.category = key; render(); },
      }),
    ),
    headerEl: mainHeaderLayout({
      title: 'Extensions',
      chips: [categoryChip],
      count: results.length,
      countNoun: 'extensions',
      searchEl: searchInput({
        value: state.searchQ, placeholder: 'Search extensions\u2026',
        onInput: (v) => { state.searchQ = v; render(); },
      }),
    }),
    contentEl: results.length === 0
      ? emptyState('extensions')
      : isGrouped
        ? groupedGrid({ items: results, categories: CATEGORIES, primaryCategory, renderCard: extCard })
        : cardGrid(results, extCard),
  });
}

initKeyboardShortcut('#extensions-app');
initApp({
  rootId: 'extensions-app',
  onData: (el, data) => { root = el; items = data; render(); },
});
