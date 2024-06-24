import { html } from "htm/preact";

// styles: { tabSet:{}, tabBody: {}}
export const TabSet = ({ id, type, classes, tools, styles, children }) => {
  if (!id) {
    throw new Error("Tabsets require an id to function properly");
  }

  // The tabs themselves
  const tabs = children;

  // Process the tab style
  const tabType = type || "tabs";
  const tabSetStyle = {
    alignItems: "space-between",
  };

  // Render the tabs
  return html`<ul
      ...${{ id }}
      class="nav nav-${tabType} ${classes ? classes : ""}"
      role="tablist"
      aria-orientation="horizontal"
      style=${{ ...tabSetStyle, ...styles.tabSet }}
    >
      <${Tabs} tabs=${tabs} type=${tabType} style=${styles.tabs} />
      <${TabTools} tools=${tools} />
    </ul>
    <${TabPanels} id=${id} tabs=${tabs} style=${styles.tabBody} />`;
};

// Defines a tab panel that appears within the tabset
export const TabPanel = ({
  id,
  index,
  selected,
  style,
  scrollable,
  children,
}) => {
  const tabContentsId = computeTabContentsId(id, index);

  return html`<div
    id="${tabContentsId}"
    class="tab-pane show ${selected ? "active" : ""}"
    style=${{
      flex: "1",
      overflowY: scrollable === undefined || scrollable ? "auto" : "hidden",
      ...style,
    }}
  >
    ${children}
  </div>`;
};

// Render the tabs / pills themselves
const Tabs = ({ tabs, type, style }) => {
  return tabs.map((tab, index) => {
    return html` <${Tab}
      type=${type || "tabs"}
      tab=${tab}
      index=${index}
      style=${style}
    />`;
  });
};

// An individual tab
const Tab = ({ type, tab, index, style }) => {
  // TODO: If there's no tab.props.id, this is just a string of "-1", "-2" per
  // index because there's no `id`, what should this really be?
  // eslint-disable-next-line no-undef
  const tabId = tab.props.id || computeTabId(id, index);
  const tabContentsId = computeTabContentsId(tab.props.id, index);
  const isActive = tab.props.selected;
  const tabStyle = {
    color: "var(--bs-body-color)",
    ...style,
    padding: "0.25rem 0.5rem",
  };
  const pillStyle = {
    ...style,
  };
  return html`
    <li class="nav-item" role="presentation">
      <button
        id="${tabId}"
        style=${type === "tabs" ? tabStyle : pillStyle}
        class="nav-link ${isActive ? "active" : ""}"
        data-bs-toggle="tab"
        data-bs-target="#${tabContentsId}"
        type="button"
        role="tab"
        aria-controls="${tabContentsId}"
        aria-selected="${isActive ? true : false}"
        ...${{
          onclick: (e) => {
            tab.props.onSelected(e);
            return false;
          },
        }}
      >
        ${tab.props.title}
      </button>
    </li>
  `;
};

// The tools shown for the tab
const TabTools = ({ tools }) => {
  return html`<div
    class="tab-tools"
    style=${{
      flexBasis: "auto",
      marginLeft: "auto",
      display: "flex",
      alignItems: "center",
      justifyContent: "end",
      flexWrap: "wrap",
      rowGap: "0.3rem",
    }}
  >
    ${tools}
  </div>`;
};

// Render the tab panels
const TabPanels = ({ id, tabs, style }) => {
  return html`<div class="tab-content" id="${id}-content" style=${{ ...style }}>
    ${tabs.map((tab, index) => {
      tab.props.index = index;
      return tab;
    })}
  </div>`;
};

const computeTabId = (id, index) => {
  return `${id}-${index}`;
};
const computeTabContentsId = (id, index) => {
  return `${id}-contents-${index}`;
};
