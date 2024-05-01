import { html } from "htm/preact";

export const TabSet = ({ id, classes, style, type, tools, children }) => {
  if (!id) {
    throw new Error("Tabsets require an id to function properly");
  }

  const computeTabId = (index) => {
    return `${id}-${index}`;
  };
  const computeTabContentsId = (index) => {
    return `${id}-contents-${index}`;
  };

  const tabs = children.map((child) => {
    return child.props;
  });

  const tabType = type || "tabs";
  const tabSetStyle = {
    alignItems: "space-between",
    marginBottom: tabType === "tabs" ? undefined : "0.5rem",
  };
  return html` <ul
      ...${{ id, style }}
      class="nav nav-${tabType} ${classes ? classes : ""}"
      role="tablist"
      aria-orientation="horizontal"
      style=${{ ...tabSetStyle, ...style }}
    >
      ${tabs.map((tab, index) => {
        const tabId = tab.id || computeTabId(index);
        const tabContentsId = computeTabContentsId(index);
        const isActive = tab.selected;
        const tabStyle = {
          color: "var(--bs-body-color)",
          ...tab.style,
          padding: "0.25rem 0.5rem"
        };
        const pillStyle = {
          ...tab.style,
        };
        return html`
          <li class="nav-item" role="presentation">
            <button
              id="${tabId}"
              style=${tabType === "tabs" ? tabStyle : pillStyle}
              class="nav-link ${isActive ? "active" : ""}"
              data-bs-toggle="tab"
              data-bs-target="#${tabContentsId}"
              type="button"
              role="tab"
              aria-controls="${tabContentsId}"
              aria-selected="${isActive ? true : false}"
              ...${{ onclick: (e) => {tab.onSelected(e); return false }}}
            >
              ${tab.title}
            </button>
          </li>
        `;
      })}
      <div
        class="tab-tools"
        style=${{
          flexBasis: "auto",
          marginLeft: "auto",
          display: "flex",
          alignItems: "center",
          justifyContent: "end",
          flexWrap: "wrap",
          rowGap: "0.3rem"
        }}
      >
        ${tools}
      </div>
    </ul>
    <div class="tab-content" id="${id}-content">
      ${tabs.map((tab, index) => {
        const isActive = tab.selected;
        const tabContentsId = computeTabContentsId(index);
        return html`<div
          id="${tabContentsId}"
          class="tab-pane show ${isActive ? "active" : ""}"
          style=${{ flex: "1 1 auto", minHeight: "10em" }}
        >
          ${tab.children}
        </div>`;
      })}
    </div>`;
};

export const Tab = ({ id, title, onSelected, selected, style, children }) => {
  return { id, title, onSelected, selected, style, children };
};
