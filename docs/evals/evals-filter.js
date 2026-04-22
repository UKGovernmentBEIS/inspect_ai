/**
 * evals-filter.js
 * ─────────────────────────────────────────────────────────────────────────────
 * Evals-specific filtering, sorting, persistence, and command helpers.
 * Generic filter/count logic lives in ../listing/listing.js.
 * ─────────────────────────────────────────────────────────────────────────────
 */

import { filterItems, getCategoryCounts as _getCategoryCounts } from '../listing/listing.js';

// ─── Sort modes ───────────────────────────────────────────────────────────────
export const SORT = {
  ALPHA:    'alpha',
  SAMPLES:  'samples',
  FEATURED: 'featured',
};

// ─── Core filter function ─────────────────────────────────────────────────────
/**
 * Filter and sort eval records. When searchQ is non-empty, category and source
 * filters are bypassed.
 */
export function filterEvals(evals, options = {}) {
  const {
    category = 'All',
    source   = 'All',
    searchQ  = '',
    sort     = SORT.ALPHA,
  } = options;

  let list = evals;

  if (searchQ.trim()) {
    list = filterItems(list, { searchQ, searchFields: ['name', 'desc', 'categories', 'tags'] });
  } else {
    if (source !== 'All') list = list.filter(e => e.source === source);
    list = filterItems(list, { category, searchFields: ['name', 'desc', 'categories', 'tags'] });
  }

  return sortEvals(list, sort);
}

// ─── Sort ─────────────────────────────────────────────────────────────────────
export function sortEvals(evals, sort = SORT.ALPHA) {
  const list = [...evals];
  if (sort === SORT.ALPHA) {
    list.sort((a, b) => {
      const amc = (a.model_cards || []).length;
      const bmc = (b.model_cards || []).length;
      if (bmc !== amc) return bmc - amc;
      return a.name.localeCompare(b.name);
    });
  }
  if (sort === SORT.SAMPLES)  list.sort((a, b) => (b.samples || 0) - (a.samples || 0));
  if (sort === SORT.FEATURED) list.sort((a, b) => ((b.featured ? 1 : 0) - (a.featured ? 1 : 0)) || a.name.localeCompare(b.name));
  return list;
}

// ─── Category counts ──────────────────────────────────────────────────────────
/**
 * Count evals per category, optionally restricted to a source package.
 */
export function getCategoryCounts(evals, sourceFilter = 'All') {
  const preFilter = sourceFilter !== 'All' ? (e) => e.source === sourceFilter : undefined;
  return _getCategoryCounts(evals, preFilter);
}

// ─── Source counts ────────────────────────────────────────────────────────────
export function getSourceCounts(evals) {
  const counts = { All: evals.length, evals: 0, harbor: 0 };
  for (const e of evals) {
    counts[e.source] = (counts[e.source] || 0) + 1;
  }
  return counts;
}

// ─── Related evals ────────────────────────────────────────────────────────────
export function getRelated(evals, current, limit = 4) {
  return evals
    .filter(e => e.id !== current.id && (e.categories || []).some(c => (current.categories || []).includes(c)))
    .slice(0, limit);
}

// ─── Active filters summary ───────────────────────────────────────────────────
export function getActiveFilters({ category, source, searchQ }) {
  const active = [];
  if (category && category !== 'All') active.push(category);
  if (source   && source   !== 'All') active.push(source === 'evals' ? 'inspect_evals' : 'inspect_harbor');
  if (searchQ  && searchQ.trim())     active.push(`"${searchQ.trim()}"`);
  return active;
}

// ─── localStorage persistence ─────────────────────────────────────────────────
const STORAGE_KEY = 'inspectEvals_state';

export function loadPersistedState() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return defaultState();
    const saved = JSON.parse(raw);
    delete saved.kind;
    delete saved.density;
    delete saved.accent;
    return { ...defaultState(), ...saved };
  } catch (_) {
    return defaultState();
  }
}

export function savePersistedState(state) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      category: state.category,
      source:   state.source,
      sort:     state.sort,
    }));
  } catch (_) { /* quota exceeded or private browsing */ }
}

function defaultState() {
  return { category: 'All', source: 'All', searchQ: '', sort: SORT.ALPHA };
}

// ─── Install command helpers ──────────────────────────────────────────────────
export function getInstallCmd(eval_) {
  return eval_.source === 'harbor' ? 'pip install inspect-harbor' : 'pip install inspect-evals';
}

export function getRunCmd(eval_, model = 'openai/gpt-5') {
  return `inspect eval ${eval_.code} --model ${model}`;
}

export function getPythonSnippet(eval_, model = 'openai/gpt-5') {
  const pkg  = eval_.source === 'harbor' ? 'inspect_harbor' : 'inspect_evals';
  const task = eval_.id.replace(/^h_/, '');
  return [
    `from inspect_ai import eval`,
    `from ${pkg} import ${task}`,
    ``,
    `eval(${task}(), model="${model}")`,
  ].join('\n');
}

export function getSourceUrl(eval_) {
  if (eval_.source === 'harbor') {
    return 'https://github.com/laude-institute/harbor';
  }
  return `https://github.com/UKGovernmentBEIS/inspect_evals/tree/main/src/${eval_.code}`;
}

// ─── Reactive state container ────────────────────────────────────────────────
export function createState({ evals, onChange, initialState = {} }) {
  let state = { ...loadPersistedState(), ...initialState };

  function derive() {
    const results        = filterEvals(evals, state);
    const categoryCounts = getCategoryCounts(evals, state.source);
    const sourceCounts   = getSourceCounts(evals);
    const activeFilters  = getActiveFilters(state);
    return { results, categoryCounts, sourceCounts, filters: { ...state }, activeFilters };
  }

  function notify() {
    savePersistedState(state);
    onChange(derive());
  }

  return {
    get:         ()  => derive(),
    setCategory: (v) => { state = { ...state, category: v }; notify(); },
    setSource:   (v) => { state = { ...state, source:   v }; notify(); },
    setSearch:   (v) => { state = { ...state, searchQ:  v }; notify(); },
    setSort:     (v) => { state = { ...state, sort:     v }; notify(); },
    clearAll:    ()  => { state = { ...state, category: 'All', source: 'All', searchQ: '' }; notify(); },
  };
}

// ─── UMD/global export ───────────────────────────────────────────────────────
if (typeof window !== 'undefined') {
  window.EvalsFilter = {
    SORT, filterEvals, sortEvals, getCategoryCounts, getSourceCounts,
    getRelated, getActiveFilters, loadPersistedState, savePersistedState,
    getInstallCmd, getRunCmd, getPythonSnippet, getSourceUrl, createState,
  };
}
