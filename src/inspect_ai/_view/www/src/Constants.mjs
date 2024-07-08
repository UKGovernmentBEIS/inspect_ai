// Provides centralized repository of bootstrap icons
// used throughout the workspace
export const icons = {
  arrows: {
    right: "bi bi-arrow-right",
    down: "bi bi-arrow-down",
  },
  "collapse-all": "bi bi-arrows-collapse",
  "collapse-up": "bi bi-chevron-up",
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
  inspect: "bi bi-gear",
  json: "bi bi-filetype-json",
  logging: {
    notset: "bi bi-card-text",
    debug: "bi bi-bug",
    info: "bi bi-info-square",
    warning: "bi bi-exclamation-triangle",
    error: "bi bi-x-circle",
    critical: "bi bi-fire",
  },
  menu: "bi bi-list",
  model: "bi bi-cpu",
  "toggle-right": "bi bi-chevron-right",
  more: "bi bi-zoom-in",
  next: "bi bi-chevron-right",
  previous: "bi bi-chevron-left",
  role: {
    user: "bi bi-person",
    system: "bi bi-cpu",
    assistant: "bi bi-robot",
    tool: "bi bi-tools",
  },
  sample: "bi bi-speedometer",
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
  usage: "bi bi-stopwatch",
};

export const colors = {
  logging: {
    debug: "var(--bs-secondary)",
    info: "var(--bs-blue)",
    warning: "var(--bs-warning)",
    error: "var(--bs-danger)",
    critical: "var(--bs-danger)",
  },
};

export const sharedStyles = {
  moreButton: {
    maxHeight: "1.8em",
    fontSize: "0.8rem",
    padding: "0 0.2em 0 0.2em",
    color: "var(--bs-secondary)",
  },
  threeLineClamp: {
    display: "-webkit-box",
    "-webkit-line-clamp": "3",
    "-webkit-box-orient": "vertical",
    overflow: "hidden",
  },
  lineClamp: (len) => {
    return {
      display: "-webkit-box",
      "-webkit-line-clamp": `${len}`,
      "-webkit-box-orient": "vertical",
      overflow: "hidden",
    };
  },
  wrapText: () => {
    return {
      whiteSpace: "nowrap",
      textOverflow: "ellipsis",
      overflow: "hidden",
    };
  },
  scoreFills: {
    green: {
      backgroundColor: "var(--bs-success)",
      borderColor: "var(--bs-success)",
      color: "var(--bs-body-bg)",
    },
    red: {
      backgroundColor: "var(--bs-danger)",
      borderColor: "var(--bs-danger)",
      color: "var(--bs-body-bg)",
    },
    orange: {
      backgroundColor: "var(--bs-orange)",
      borderColor: "var(--bs-orange)",
      color: "var(--bs-body-bg)",
    },
  },
};
