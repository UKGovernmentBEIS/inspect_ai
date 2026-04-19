/**
 * evals-filter.js
 * ─────────────────────────────────────────────────────────────────────────────
 * Pure-JS filtering, search, and count logic for the Inspect Evals index.
 * No dependencies. No DOM manipulation. No build step required.
 *
 * Designed to be consumed by any host (Quarto, plain HTML, or a JS framework).
 * The host is responsible for rendering; this library handles all data logic.
 *
 * Usage
 * ─────
 * // 1. Import (ESM)
 * import { filterEvals, getCategoryCounts, getSourceCounts, createState, SORT } from './evals-filter.js';
 *
 * // OR load as a plain script tag — everything is exposed on window.EvalsFilter
 * <script src="evals-filter.js"></script>
 * const { filterEvals, getCategoryCounts, createState } = window.EvalsFilter;
 *
 * // 2. Provide your eval records (from inspect_evals + inspect_harbor registries)
 * const evals = [ ...your eval objects... ];
 *
 * // 3. Create reactive state
 * const state = createState({ evals, onChange: render });
 *
 * // 4. Update state — onChange fires automatically
 * state.setCategory('Coding');
 * state.setSource('harbor');
 * state.setSearch('swe');
 * state.clearAll();
 *
 * // 5. Read derived data
 * const { results, categoryCounts, sourceCounts, activeFilters } = state.get();
 * ─────────────────────────────────────────────────────────────────────────────
 */

// ─── Types (JSDoc) ────────────────────────────────────────────────────────────
/**
 * @typedef {Object} EvalRecord
 * @property {string}   id           - Unique slug, e.g. 'swe_bench' or 'h_swebench_verified_1_0'
 * @property {string}   name         - Display name, e.g. 'SWE-bench Verified'
 * @property {'evals'|'harbor'} source - Package the eval belongs to
 * @property {string}   category     - Primary category, e.g. 'Coding', 'Safeguards'
 * @property {string[]} tags         - Additional tags, e.g. ['Agent','Security']
 * @property {'agent'|'qa'|'generation'|'multimodal'} kind
 * @property {string[]} modalities   - e.g. ['agent','sandbox','vision']
 * @property {string}   desc         - One-sentence description
 * @property {string|null} paper     - arXiv or paper URL, or null
 * @property {string}   code         - Task path, e.g. 'inspect_evals/swe_bench'
 * @property {string}   contributor  - GitHub username
 * @property {number}   [samples]    - Dataset size
 * @property {boolean}  [featured]   - Whether to surface first in 'featured' sort
 */

/**
 * @typedef {Object} FilterState
 * @property {string} category    - Selected category, 'All' = no filter
 * @property {string} source      - 'All' | 'evals' | 'harbor'
 * @property {string} searchQ     - Free-text search query
 */

/**
 * @typedef {Object} DerivedState
 * @property {EvalRecord[]} results        - Filtered + sorted eval list
 * @property {Record<string,number>} categoryCounts - Count per category (respects source filter)
 * @property {Record<string,number>} sourceCounts   - Count per source package
 * @property {FilterState}  filters        - Current filter values
 * @property {string[]}     activeFilters  - Human-readable list of active filters
 */

// ─── Sort modes ───────────────────────────────────────────────────────────────
export const SORT = {
  ALPHA:    'alpha',
  SAMPLES:  'samples',
  FEATURED: 'featured',
};

// ─── Core filter function ─────────────────────────────────────────────────────
/**
 * Filter and sort an array of eval records.
 *
 * When `searchQ` is non-empty, category and source filters are bypassed so
 * users always find what they're looking for regardless of active sidebar state.
 *
 * @param {EvalRecord[]} evals
 * @param {FilterState & { sort?: string }} options
 * @returns {EvalRecord[]}
 */
export function filterEvals(evals, options = {}) {
  const {
    category = 'All',
    source   = 'All',
    searchQ  = '',
    sort     = SORT.ALPHA,
  } = options;

  let list = evals;

  // Search overrides category/source filters
  if (searchQ.trim()) {
    const lq = searchQ.toLowerCase();
    list = list.filter(e =>
      e.name.toLowerCase().includes(lq) ||
      e.desc.toLowerCase().includes(lq) ||
      (e.categories || []).some(c => c.toLowerCase().includes(lq)) ||
      e.tags.some(t => t.toLowerCase().includes(lq))
    );
  } else {
    if (category !== 'All') list = list.filter(e => (e.categories || []).includes(category));
    if (source   !== 'All') list = list.filter(e => e.source   === source);
  }

  return sortEvals(list, sort);
}

// ─── Sort ─────────────────────────────────────────────────────────────────────
/**
 * Sort an array of eval records in place (returns a new array).
 * @param {EvalRecord[]} evals
 * @param {string} sort - One of SORT.ALPHA | SORT.SAMPLES | SORT.FEATURED
 * @returns {EvalRecord[]}
 */
export function sortEvals(evals, sort = SORT.ALPHA) {
  const list = [...evals];
  if (sort === SORT.ALPHA)    list.sort((a, b) => a.name.localeCompare(b.name));
  if (sort === SORT.SAMPLES)  list.sort((a, b) => (b.samples || 0) - (a.samples || 0));
  if (sort === SORT.FEATURED) list.sort((a, b) => ((b.featured ? 1 : 0) - (a.featured ? 1 : 0)) || a.name.localeCompare(b.name));
  return list;
}

// ─── Category counts ──────────────────────────────────────────────────────────
/**
 * Count evals per category, optionally restricted to a source package.
 * Returns an object like: { All: 204, Coding: 73, Safeguards: 38, ... }
 *
 * @param {EvalRecord[]} evals
 * @param {string} [sourceFilter='All'] - Restrict counts to this source
 * @returns {Record<string, number>}
 */
export function getCategoryCounts(evals, sourceFilter = 'All') {
  const base = sourceFilter === 'All' ? evals : evals.filter(e => e.source === sourceFilter);
  const counts = { All: base.length };
  for (const e of base) {
    for (const cat of (e.categories || [])) {
      counts[cat] = (counts[cat] || 0) + 1;
    }
  }
  return counts;
}

// ─── Source counts ────────────────────────────────────────────────────────────
/**
 * Count evals per source package.
 * Returns: { All: 204, evals: 126, harbor: 78 }
 *
 * @param {EvalRecord[]} evals
 * @returns {Record<string, number>}
 */
export function getSourceCounts(evals) {
  const counts = { All: evals.length, evals: 0, harbor: 0 };
  for (const e of evals) {
    counts[e.source] = (counts[e.source] || 0) + 1;
  }
  return counts;
}

// ─── Related evals ────────────────────────────────────────────────────────────
/**
 * Find related evals in the same category, excluding the current eval.
 *
 * @param {EvalRecord[]} evals
 * @param {EvalRecord} current
 * @param {number} [limit=4]
 * @returns {EvalRecord[]}
 */
export function getRelated(evals, current, limit = 4) {
  return evals
    .filter(e => e.id !== current.id && (e.categories || []).some(c => (current.categories || []).includes(c)))
    .slice(0, limit);
}

// ─── Active filters summary ───────────────────────────────────────────────────
/**
 * Returns a human-readable list of active filters, e.g. ['Coding', 'inspect_harbor'].
 *
 * @param {FilterState} filters
 * @returns {string[]}
 */
export function getActiveFilters({ category, source, searchQ }) {
  const active = [];
  if (category && category !== 'All') active.push(category);
  if (source   && source   !== 'All') active.push(source === 'evals' ? 'inspect_evals' : 'inspect_harbor');
  if (searchQ  && searchQ.trim())     active.push(`"${searchQ.trim()}"`);
  return active;
}

// ─── localStorage persistence ─────────────────────────────────────────────────
const STORAGE_KEY = 'inspectEvals_state';

/**
 * Load persisted filter state from localStorage. Safe — returns defaults on error.
 * @returns {FilterState & { sort: string }}
 */
export function loadPersistedState() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return defaultState();
    const saved = JSON.parse(raw);
    // Strip stale keys from old versions
    delete saved.kind;
    delete saved.density;
    delete saved.accent;
    return { ...defaultState(), ...saved };
  } catch (_) {
    return defaultState();
  }
}

/**
 * Persist current filter state to localStorage.
 * @param {FilterState & { sort: string }} state
 */
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
/**
 * Return the pip install command for an eval.
 * @param {EvalRecord} eval_
 * @returns {string}
 */
export function getInstallCmd(eval_) {
  return eval_.source === 'harbor' ? 'pip install inspect-harbor' : 'pip install inspect-evals';
}

/**
 * Return the CLI run command for an eval.
 * @param {EvalRecord} eval_
 * @param {string} [model='openai/gpt-5']
 * @returns {string}
 */
export function getRunCmd(eval_, model = 'openai/gpt-5') {
  return `inspect eval ${eval_.code} --model ${model}`;
}

/**
 * Return the Python API snippet for an eval.
 * @param {EvalRecord} eval_
 * @param {string} [model='openai/gpt-5']
 * @returns {string}
 */
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

/**
 * Return GitHub source URL for an eval.
 * @param {EvalRecord} eval_
 * @returns {string}
 */
export function getSourceUrl(eval_) {
  if (eval_.source === 'harbor') {
    return 'https://github.com/laude-institute/harbor';
  }
  return `https://github.com/UKGovernmentBEIS/inspect_evals/tree/main/src/${eval_.code}`;
}

// ─── Reactive state container (optional convenience wrapper) ──────────────────
/**
 * Create a simple reactive state container. Calls `onChange` whenever state changes.
 * This is a lightweight alternative to React/stores for vanilla JS hosts.
 *
 * @param {{ evals: EvalRecord[], onChange: (derived: DerivedState) => void, initialState?: Partial<FilterState> }} options
 * @returns {{ get: () => DerivedState, setCategory, setSource, setSearch, setSort, clearAll }}
 */
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

// ─── UMD/global export (for plain <script src> usage without ESM) ─────────────
if (typeof window !== 'undefined') {
  window.EvalsFilter = {
    SORT,
    filterEvals,
    sortEvals,
    getCategoryCounts,
    getSourceCounts,
    getRelated,
    getActiveFilters,
    loadPersistedState,
    savePersistedState,
    getInstallCmd,
    getRunCmd,
    getPythonSnippet,
    getSourceUrl,
    createState,
  };
}
