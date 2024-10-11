// @ts-check
/**
 * Arrow Icons
 * @typedef {Object} ArrowIcons
 * @property {string} right
 * @property {string} down
 * @property {string} up
 */

/**
 * Arrow Icons
 * @typedef {Object} ChangeIcons
 * @property {string} add
 * @property {string} remove
 * @property {string} replace
 */

/**
 * Logging Icons
 * @typedef {Object} LoggingIcons
 * @property {string} notset
 * @property {string} debug
 * @property {string} http
 * @property {string} info
 * @property {string} warning
 * @property {string} error
 * @property {string} critical
 */

/**
 * Role Icons
 * @typedef {Object} RoleIcons
 * @property {string} user
 * @property {string} system
 * @property {string} assistant
 * @property {string} tool
 * @property {string} unknown
 */

/**
 * Solver Icons
 * @typedef {Object} SolverIcons
 * @property {string} default
 * @property {string} generate
 * @property {string} chain_of_thought
 * @property {string} self_critique
 * @property {string} system_message
 * @property {string} use_tools
 */

/**
 * Solver Icons
 * @typedef {Object} CollapseIcons
 * @property {string} up
 * @property {string} all
 */

/**
 * Chevron Icons
 * @typedef {Object} ChevronIcons
 * @property {string} down
 * @property {string} right
 */

/**
 * Caret Icons
 * @typedef {Object} CaretIcons
 * @property {string} right
 * @property {string} down
 */

/**
 * Approval Icons
 * @typedef {Object} ApprovalIcons
 * @property {string} approve
 * @property {string} reject
 * @property {string} terminate
 * @property {string} escalate
 * @property {string} modify
 */

/**
 * Provides a centralized repository of Bootstrap icons
 * used throughout the workspace.
 * @typedef {Object} Icons
 * @property {string} approve
 * @property {ApprovalIcons} approvals
 * @property {ArrowIcons} arrows
 * @property {CaretIcons} caret
 * @property {ChangeIcons} changes
 * @property {ChevronIcons} chevron
 * @property {CollapseIcons} collapse
 * @property {string} close
 * @property {string} config
 * @property {string} confirm
 * @property {string} copy
 * @property {(epoch: string) => string} epoch
 * @property {string} error
 * @property {string} expand-all
 * @property {string} expand-down
 * @property {string} fork
 * @property {string} info
 * @property {string} input
 * @property {string} inspect
 * @property {string} json
 * @property {LoggingIcons} logging
 * @property {string} menu
 * @property {string} messages
 * @property {string} metadata
 * @property {string} multiple-choice
 * @property {string} model
 * @property {string} toggle-right
 * @property {string} more
 * @property {string} next
 * @property {string} previous
 * @property {string} refresh
 * @property {RoleIcons} role
 * @property {string} running
 * @property {string} sample
 * @property {string} samples
 * @property {string} scorer
 * @property {string} search
 * @property {SolverIcons} solvers
 * @property {string} step
 * @property {string} subtask
 * @property {string} transcript
 * @property {string} usage
 */

/** @type {Icons} */
export const ApplicationIcons = {
  approve: "bi bi-shield",
  approvals: {
    approve: "bi bi-shield-check",
    reject: "bi bi-shield-x",
    terminate: "bi bi-shield-exclamation",
    escalate: "bi bi-box-arrow-up",
    modify: "bi bi-pencil-square",
  },
  arrows: {
    right: "bi bi-arrow-right",
    down: "bi bi-arrow-down",
    up: "bi bi-arrow-up",
  },
  caret: {
    right: "bi bi-caret-right",
    down: "bi bi-caret-down",
  },
  changes: {
    add: "bi bi-plus",
    remove: "bi bi-dash",
    replace: "bi bi-plus-slash-minus",
  },
  chevron: {
    right: "bi bi-chevron-right",
    down: "bi bi-chevron-down",
  },
  collapse: {
    all: "bi bi-arrows-collapse",
    up: "bi bi-chevron-up",
  },
  close: "bi bi-x",
  config: "bi bi-gear",
  confirm: "bi bi-check",
  copy: "bi bi-copy",
  epoch: (epoch) => {
    return `bi bi-${epoch}-circle`;
  },
  error: "bi bi-exclamation-circle",
  "expand-all": "bi bi-arrows-expand",
  "expand-down": "bi bi-chevron-down",
  fork: "bi bi-signpost-split",
  info: "bi bi-info-circle",
  input: "bi bi-terminal",
  inspect: "bi bi-gear",
  json: "bi bi-filetype-json",
  logging: {
    notset: "bi bi-card-text",
    debug: "bi bi-bug",
    http: "bi bi-download",
    info: "bi bi-info-square",
    warning: "bi bi-exclamation-triangle",
    error: "bi bi-x-circle",
    critical: "bi bi-fire",
  },
  menu: "bi bi-list",
  messages: "bi bi-chat-right-text",
  metadata: "bi bi-table",
  model: "bi bi-grid-3x3-gap",
  "toggle-right": "bi bi-chevron-right",
  more: "bi bi-zoom-in",
  "multiple-choice": "bi bi-card-list",
  next: "bi bi-chevron-right",
  previous: "bi bi-chevron-left",
  refresh: "bi bi-arrow-clockwise",
  role: {
    user: "bi bi-person",
    system: "bi bi-cpu",
    assistant: "bi bi-robot",
    tool: "bi bi-tools",
    unknown: "bi bi-patch-question",
  },
  running: "bi bi-stars",
  sample: "bi bi-database",
  samples: "bi bi-file-spreadsheet",
  scorer: "bi bi-calculator",
  search: "bi bi-search",
  solvers: {
    default: "bi bi-arrow-return-right",
    generate: "bi bi-share",
    chain_of_thought: "bi bi-link",
    self_critique: "bi bi-arrow-left-right",
    system_message: "bi bi-cpu",
    use_tools: "bi bi-tools",
  },
  step: "bi bi-fast-forward-btn",
  subtask: "bi bi-subtract",
  transcript: "bi bi-list-columns-reverse",
  usage: "bi bi-stopwatch",
};
