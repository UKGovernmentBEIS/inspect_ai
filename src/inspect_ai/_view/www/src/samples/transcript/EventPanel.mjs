// @ts-check
import { html } from "htm/preact";
import { useEffect, useMemo, useState } from "preact/hooks";
import { ApplicationIcons } from "../../appearance/Icons.mjs";
import { FontSize, TextStyle } from "../../appearance/Fonts.mjs";

/**
 * Renders the StateEventView component.
 *
 * @param {Object} props - The properties passed to the component.
 * @param {string} props.id - The id of the event
 * @param {string} props.classes - The classes for this element
 * @param {string | undefined} props.title - The name of the event
 * @param {string} props.subTitle - The subtitle for the event
 * @param {string | undefined} props.text - Secondary text for the event
 * @param {string | undefined} props.icon - The icon of the event
 * @param {number | undefined} props.titleColor - The title color of this item
 * @param {boolean | undefined} props.collapse - Default collapse behavior for card. If omitted, not collapsible.
 * @param {Object} props.style - The style properties passed to the component.
 * @param {Object} props.titleStyle - The style properties passed to the title component.
 * @param {import("preact").ComponentChildren} props.children - The rendered event.
 * @returns {import("preact").JSX.Element} The component.
 */
export const EventPanel = ({
  id,
  classes,
  title,
  subTitle,
  text,
  icon,
  titleColor,
  collapse,
  style,
  titleStyle,
  children,
}) => {
  const hasCollapse = collapse !== undefined;
  const [collapsed, setCollapsed] = useState(!!collapse);
  const [selectedNav, setSelectedNav] = useState("");

  const filteredArrChildren = useMemo(() => {
    const arrChildren = Array.isArray(children) ? children : [children];
    return arrChildren.filter((child) => !!child);
  }, [children]);

  useEffect(() => {
    setSelectedNav(pillId(0));
  }, [filteredArrChildren]);

  /**
   * Generates the id for the navigation pill.
   *
   * @param {number} index - The index of the pill.
   * @returns {string} The generated id.
   */
  const pillId = (index) => {
    return `${id}-nav-pill-${index}`;
  };

  const gridColumns = [];
  if (hasCollapse) {
    gridColumns.push("minmax(0, max-content)");
  }
  if (icon) {
    gridColumns.push("max-content");
  }
  gridColumns.push("minmax(0, max-content)");
  if (subTitle) {
    gridColumns.push("minmax(0, max-content)");
  }
  gridColumns.push("auto");
  gridColumns.push("minmax(0, max-content)");
  gridColumns.push("minmax(0, max-content)");

  const titleEl =
    title || icon || filteredArrChildren.length > 1
      ? html`<div
          title=${subTitle}
          style=${{
            display: "grid",
            gridTemplateColumns: gridColumns.join(" "),
            columnGap: "0.3em",
            fontSize: FontSize.small,
            cursor: hasCollapse ? "pointer" : undefined,
          }}
        >
          ${hasCollapse
            ? html`<i
                onclick=${() => {
                  setCollapsed(!collapsed);
                }}
                class=${collapsed
                  ? ApplicationIcons.chevron.right
                  : ApplicationIcons.chevron.down}
              />`
            : ""}
          ${icon
            ? html`<i
                class=${icon || ApplicationIcons.metadata}
                style=${{
                  ...TextStyle.secondary,
                  color: titleColor ? titleColor : "",
                  ...titleStyle,
                }}
                onclick=${() => {
                  setCollapsed(!collapsed);
                }}
              />`
            : ""}
          <div
            style=${{
              ...TextStyle.label,
              ...TextStyle.secondary,
              color: titleColor ? titleColor : "",
              ...titleStyle,
            }}
            onclick=${() => {
              setCollapsed(!collapsed);
            }}
          >
            ${title}
          </div>
          <div
            onclick=${() => {
              setCollapsed(!collapsed);
            }}
          ></div>
          <div
            style=${{
              justifySelf: "end",
              ...TextStyle.secondary,
              marginRight: "0.2em",
            }}
            onclick=${() => {
              setCollapsed(!collapsed);
            }}
          >
            ${collapsed ? text : ""}
          </div>
          <div
            style=${{
              justifySelf: "end",
              display: "flex",
              flexDirection: "columns",
            }}
          >
            ${(!hasCollapse || !collapsed) &&
            filteredArrChildren &&
            filteredArrChildren.length > 1
              ? html` <${EventNavs}
                  navs=${filteredArrChildren.map((child, index) => {
                    const defaultTitle = `Tab ${index}`;
                    const title =
                      child && typeof child === "object"
                        ? child["props"]?.name || defaultTitle
                        : defaultTitle;
                    return {
                      id: `eventpanel-${id}-${index}`,
                      title: title,
                      target: pillId(index),
                    };
                  })}
                  selectedNav=${selectedNav}
                  setSelectedNav=${setSelectedNav}
                />`
              : ""}
          </div>
        </div>`
      : "";

  const card = html` <div
    id=${id}
    style=${{
      padding: "0.625rem",
      marginBottom: "0.625rem",
      border: "solid 1px var(--bs-light-border-subtle)",
      borderRadius: "var(--bs-border-radius)",
      ...style,
    }}
    class=${classes || undefined}
  >
    ${titleEl}
    <div
      class="tab-content"
      style=${{
        padding: "0",
        display: !hasCollapse || !collapsed ? "inherit" : "none",
      }}
    >
      ${filteredArrChildren?.map((child, index) => {
        const id = pillId(index);
        return html`<div
          id=${id}
          class="tab-pane show ${id === selectedNav ? "active" : ""}"
        >
          ${child}
        </div>`;
      })}
    </div>
  </div>`;
  return card;
};

/**
 * Component to render navigation items.
 *
 * @param {Object} props - The component properties.
 * @param {Array<{id: string, title: string, target: string}>} props.navs - The array of navigation items.
 * @param {string} props.selectedNav - The id of the selected nav item.
 * @param {(target: string) => void} props.setSelectedNav - Select this nav target
 * @returns {import("preact").ComponentChildren} - The rendered navigation items as a list.
 */
const EventNavs = ({ navs, selectedNav, setSelectedNav }) => {
  return html`<ul
    class="nav nav-pills card-header-pills"
    style=${{ marginRight: "0" }}
    role="tablist"
    aria-orientation="horizontal"
  >
    ${navs.map((nav, index) => {
      return html`<${EventNav}
        active=${index === 0}
        id=${nav.id}
        target=${nav.target}
        title=${nav.title}
        selectedNav=${selectedNav}
        setSelectedNav=${setSelectedNav}
      />`;
    })}
  </ul>`;
};

/**
 * Component to render a single navigation item.
 *
 * @param {Object} props - The component properties.
 * @param {string} props.target - The target of the navigation item.
 * @param {string} props.title - The title of the navigation item.
 * @param {string} props.selectedNav - The id of the selected nav item.
 * @param {(target: string) => void} props.setSelectedNav - Select this nav target
 * @returns {import("preact").ComponentChildren} - The rendered navigation item.
 */
const EventNav = ({ target, title, selectedNav, setSelectedNav }) => {
  const active = target === selectedNav;
  return html`<li class="nav-item">
    <button
      type="button"
      role="tab"
      aria-controls=${target}
      aria-selected=${active}
      style=${{
        minWidth: "4rem",
        ...TextStyle.label,
        fontSize: FontSize.small,
        padding: "0.1rem  0.6rem",
        borderRadius: "var(--bs-border-radius)",
      }}
      class="nav-link ${active ? "active " : ""}"
      onclick=${() => {
        setSelectedNav(target);
      }}
    >
      ${title}
    </button>
  </li>`;
};
