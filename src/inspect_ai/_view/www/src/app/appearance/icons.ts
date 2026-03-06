const loggingIcons: Record<string, string> = {
  notset: "bi bi-card-text",
  debug: "bi bi-bug",
  http: "bi bi-download",
  info: "bi bi-info-square",
  warning: "bi bi-exclamation-triangle",
  error: "bi bi-x-circle",
  critical: "bi bi-fire",
};

export const iconForMimeType = (mimeType: string): string => {
  if (mimeType === "application/pdf") {
    return "bi bi-file-pdf";
  } else if (mimeType.startsWith("image/")) {
    return "bi bi-file-image";
  } else {
    return "bi bi-file-earmark";
  }
};

export const ApplicationIcons = {
  agent: "bi bi-grid", // bi bi-x-diamond
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
  cancelled: "bi bi-x-circle",
  caret: {
    right: "bi bi-caret-right",
    down: "bi bi-caret-down",
  },
  changes: {
    add: "bi bi-plus",
    remove: "bi bi-dash",
    replace: "bi bi-plus-slash-minus",
  },
  checkbox: {
    checked: "bi bi-check-circle",
    unchecked: "bi bi-circle",
  },
  chevron: {
    right: "bi bi-chevron-right",
    down: "bi bi-chevron-down",
  },
  "clear-text": "bi bi-x-circle-fill",
  close: "bi bi-x",
  collapse: {
    all: "bi bi-arrows-collapse",
    up: "bi bi-chevron-up",
  },
  config: "bi bi-gear",
  confirm: "bi bi-check",
  copy: "bi bi-copy",
  display: "bi bi-card-text",
  downloadLog: "bi bi-download",
  epoch: (epoch: string) => {
    return `bi bi-${epoch}-circle`;
  },
  edit: "bi bi-pencil-square",
  error: "bi bi-exclamation-circle-fill",
  eval: "bi bi-info-circle-fill",
  "eval-set": "bi bi-list-task",
  expand: {
    all: "bi bi-arrows-expand",
    down: "bi bi-chevron-down",
  },
  file: "bi bi-file-code",
  filter: "bi bi-funnel",
  folder: "bi bi-folder",
  fork: "bi bi-signpost-split",
  flow: "ii inspect-flow",
  home: "bi bi-house",
  info: "bi bi-info-circle",
  input: "bi bi-terminal",
  inspect: "ii inspect-icon-16",
  inspectFile: "ii inspect-icon-file",
  json: "bi bi-filetype-json",
  limits: {
    messages: "bi bi-chat-right-text",
    custom: "bi bi-exclamation-triangle",
    operator: "bi bi-person-workspace",
    tokens: "bi bi-list",
    time: "bi bi-clock",
    execution: "bi bi-stopwatch",
    cost: "bi bi-currency-dollar",
  },
  link: "bi bi-link-45deg",
  loading: "bi bi-arrow-clockwise",
  logging: loggingIcons,
  menu: "bi bi-list",
  messages: "bi bi-chat-right-text",
  metadata: "bi bi-table",
  metrics: "bi bi-clipboard-data",
  model: "bi bi-grid-3x3-gap",
  "toggle-right": "bi bi-chevron-right",
  more: "bi bi-zoom-in",
  "multiple-choice": "bi bi-card-list",
  navbar: {
    home: "ii inspect-icon-home",
    back: "ii inspect-icon-back",
    forward: "ii inspect-icon-forward",
    inspectLogo: "ii inspect-icon-16",
    tasks: "ii inspect-icon-tasks",
  },

  next: "bi bi-chevron-right",
  noSamples: "bi bi-ban",
  options: "bi bi-gear",
  pendingTask: "bi bi-clock",
  play: "bi bi-play-fill",
  previous: "bi bi-chevron-left",
  refresh: "bi bi-arrow-clockwise",
  retry: "bi bi-arrow-repeat",
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
  sandbox: "bi bi-box-seam",
  scorer: "bi bi-calculator",
  search: "bi bi-search",
  sidebar: "bi bi-list",
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
  success: "bi bi-check-circle-fill",
  toggle: {
    // combination of toggle-on and toggle2-off looked best for our default button font size
    on: "bi bi-toggle-on",
    off: "bi bi-toggle2-off",
  },
  transcript: "bi bi-list-columns-reverse",
  tree: {
    open: "bi bi-caret-down-fill",
    closed: "bi bi-caret-right-fill",
  },
  turns: "bi bi-chat-left-text", // bi bi-repeat
  usage: "bi bi-stopwatch",
};
