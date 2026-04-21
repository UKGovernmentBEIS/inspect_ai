/**
 * evals-app.js
 * Card-grid listing for the /docs/evals page.
 * Uses shared listing components; adds eval-specific features:
 *   - Hash-based routing with detail pages
 *   - Source/package filter dimension
 *   - localStorage persistence
 *   - Detail page with code blocks and usage snippets
 */
import {
  h, clear, filterChip, emptyState, sidebarFilterBtn,
  searchInput, mainHeaderLayout, cardGrid, groupedGrid,
  sidebarLayout, categoryFilterSection, renderListingPage,
  initKeyboardShortcut, initApp,
} from '../listing/listing.js';

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
  'Coding', 'Assistants', 'Reasoning', 'Knowledge',
  'Cybersecurity', 'Safeguards',
  'Science', 'Mathematics', 'Biology', 'Chemistry', 'Physics',
  'Professional', 'Finance', 'Medicine', 'Law',
  'Behavior', 'Multimodal', 'Scheming',
];

const SUB_CATEGORIES = {
  Biology: 'Science', Chemistry: 'Science', Physics: 'Science', Mathematics: 'Science',
  Finance: 'Professional', Medicine: 'Professional', Law: 'Professional',
};

// ── Hash routing ───────────────────────────────────────────────────────────
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

// ── Components ─────────────────────────────────────────────────────────────
function evalCard(eval_) {
  const pkgLabel = eval_.source === 'harbor' ? 'inspect_harbor' : 'inspect_evals';
  const contrib = (eval_.contributors && eval_.contributors[0]) || '';
  const samples = eval_.samples != null
    ? `${Number(eval_.samples).toLocaleString()} samples`
    : '';

  return h('a', {
    class: 'listing-card-link d-block',
    href: buildHash({ route: 'detail', id: eval_.id }),
    onclick: (e) => { e.preventDefault(); navigate({ route: 'detail', id: eval_.id }); },
  },
    h('div', { class: 'card h-100' },
      h('div', { class: 'card-body d-flex flex-column' },
        h('div', { class: 'd-flex justify-content-between align-items-start gap-2' },
          h('h6', { class: 'card-title mb-0 fw-normal text-body-emphasis' }, eval_.name),
          h('small', { class: 'text-body-tertiary text-nowrap' }, pkgLabel),
        ),
        h('p', { class: 'card-text small text-body-secondary mt-2 mb-0 flex-grow-1' }, eval_.desc),
        h('div', { class: 'd-flex justify-content-between align-items-center small text-body-tertiary mt-2' },
          contrib ? h('span', {}, `@${contrib}`) : h('span'),
          samples ? h('span', { class: 'font-monospace', style: { fontSize: '.75em' } }, samples) : null,
        ),
      ),
    ),
  );
}

function packageFilterSection({ state, sourceCounts, onPackage }) {
  return [
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
  ];
}

// ── Detail page ───────────────────────────────────────────────────────────
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

  const pillStyle = { color: 'inherit', background: 'transparent', borderRadius: '.25rem', padding: '.4em .8em' };

  const sourcePill = h('a', {
    class: 'badge border text-decoration-none fw-normal',
    href: '#/',
    onclick: (e) => { e.preventDefault(); navigate({ route: 'index', filters: { source: eval_.source } }); },
    style: pillStyle,
  }, eval_.source === 'harbor' ? 'inspect_harbor' : 'inspect_evals');

  const categoryPills = (eval_.categories || []).map((cat) =>
    h('a', {
      class: 'badge border text-decoration-none fw-normal',
      href: buildHash({ route: 'index', filters: { category: cat } }),
      onclick: (e) => { e.preventDefault(); navigate({ route: 'index', filters: { category: cat } }); },
      style: pillStyle,
    }, cat),
  );

  const hero = h('div', { class: 'border-bottom pb-4' },
    h('h1', { class: 'fw-semibold mb-2' }, eval_.name),
    h('div', { class: 'd-flex align-items-center gap-2 flex-wrap mb-3' },
      sourcePill, ...categoryPills,
    ),
    h('div', { class: 'd-flex flex-wrap gap-4' },
      contribLine ? heroMeta('Contributed by', contribLine) : null,
      heroMeta('Source', h('a', { href: eval_.url || sourceUrl, target: '_blank', rel: 'noopener' },
        `${eval_.code.split('/').pop()} \u2197`)),
      eval_.paper ? heroMeta('Paper', h('a', { href: eval_.paper, target: '_blank', rel: 'noopener' },
        (eval_.paper.includes('arxiv.org') ? 'arXiv' : 'Link') + ' \u2197')) : null,
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
        }, 'View all options in the Inspect docs \u2197'),
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

function render() {
  if (view.route === 'detail') {
    clear(root);
    const ev = evals.find((e) => e.id === view.id);
    if (!ev) {
      root.append(
        h('div', { class: 'container py-5', style: { maxWidth: '720px' } },
          h('h1', { class: 'h4' }, 'Eval not found'),
          h('p', {}, `No eval with id "${view.id}" in this listing.`),
          h('a', {
            href: '#/',
            onclick: (e) => { e.preventDefault(); navigate({ route: 'index', filters: {} }); },
          }, '\u2190 All Evals'),
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

  const isFiltered = state.category !== 'All' || state.source !== 'All' || state.searchQ.trim();
  const primaryCategory = (e) => (e.categories || [])[0];

  const sourceChip = state.source !== 'All'
    ? filterChip(
        state.source === 'evals' ? 'inspect_evals' : 'inspect_harbor',
        () => navigate({ route: 'index', filters: { ...state, source: 'All' } }),
      )
    : null;
  const categoryChip = state.category !== 'All'
    ? filterChip(state.category, () => navigate({ route: 'index', filters: { ...state, category: 'All' } }))
    : null;

  renderListingPage({
    root,
    searchQ: state.searchQ,
    sidebarEl: sidebarLayout(
      packageFilterSection({
        state, sourceCounts,
        onPackage: (key) => navigate({ route: 'index', filters: { ...state, source: key } }),
      }),
      categoryFilterSection({
        categories: CATEGORIES, counts: categoryCounts,
        activeCategory: state.category, allLabel: 'All Evals',
        onCategory: (key) => navigate({ route: 'index', filters: { ...state, category: key } }),
        subCategories: SUB_CATEGORIES,
      }),
    ),
    headerEl: mainHeaderLayout({
      title: 'Evals',
      chips: [sourceChip, categoryChip],
      count: results.length,
      countNoun: 'evals',
      searchEl: searchInput({
        value: state.searchQ, placeholder: 'Search evals\u2026',
        onInput: (v) => {
          state.searchQ = v;
          pushRoute({ route: 'index', filters: state }, true);
          render();
        },
      }),
    }),
    contentEl: results.length === 0
      ? emptyState('evals')
      : isFiltered
        ? cardGrid(results, evalCard)
        : h('div', {},
            // Model card evals at top (no heading), then category groups below
            (() => {
              const mcEvals = results
                .filter(e => (e.model_cards || []).length > 0)
                .sort((a, b) => (b.model_cards || []).length - (a.model_cards || []).length);
              return mcEvals.length > 0
                ? h('div', { style: { marginBottom: '1.5rem' } }, cardGrid(mcEvals, evalCard))
                : null;
            })(),
            groupedGrid({ items: results, categories: CATEGORIES, primaryCategory, renderCard: evalCard }),
          ),
  });
}

initKeyboardShortcut('#evals-app');
initApp({
  rootId: 'evals-app',
  onData: (el, data) => {
    root = el;
    evals = data;

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
      pushRoute({ route: 'index', filters: state }, true);
    }

    window.addEventListener('popstate', applyHash);
    window.addEventListener('hashchange', applyHash);

    render();
  },
});
