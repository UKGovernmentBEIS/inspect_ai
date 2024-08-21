// @ts-check
import { html } from "htm/preact";
import { useState } from "preact/hooks";
import { ApplicationIcons } from "../../appearance/Icons.mjs";
import { FontSize, TextStyle } from "../../appearance/Fonts.mjs";

/**
 * Renders the StateEventView component.
 *
 * @param {Object} props - The properties passed to the component.
 * @param {string} props.id - The id of the event
 * @param {string | undefined} props.title - The name of the event
 * @param {string | undefined} props.text - Secondary text for the event
 * @param {string | undefined} props.icon - The icon of the event
 * @param {number | undefined} props.depth - The depth of this item
 * @param {boolean | undefined} props.collapse - Default collapse behavior for card. If omitted, not collapsible.
 * @param {Object} props.style - The style properties passed to the component.
 * @param {import("preact").ComponentChildren} props.children - The rendered event.
 * @returns {import("preact").JSX.Element} The component.
 */
export const EventPanel = ({
  id,
  title,
  text,
  icon,
  depth = 0,
  collapse,
  style,
  children,
}) => {
  /**
   * @type {import("preact").ComponentChildren[] | undefined}
   */
  const arrChildren = Array.isArray(children) ? children : [children];
  const filteredArrChilden = arrChildren.filter((child) => !!child);

  const hasCollapse = collapse !== undefined;
  const [collapsed, setCollapsed] = useState(!!collapse);

  /**
   * Generates the id for the navigation pill.
   *
   * @param {number} index - The index of the pill.
   * @returns {string} The generated id.
   */
  const pillId = (index) => {
    return `${id}-nav-pill-${index}`;
  };

  const titleEl =
    title || icon || filteredArrChilden.length > 1
      ? html`<div
          style=${{
            paddingLeft: "0.5em",
            display: "grid",
            gridTemplateColumns:
              "max-content minmax(0, max-content) auto minmax(0, max-content) minmax(0, max-content)",
            columnGap: "0.5em",
            fontSize: FontSize.small,
            cursor: hasCollapse ? "pointer" : undefined,
          }}
        >
          ${icon
            ? html`<i
                class=${icon || ApplicationIcons.metadata}
                style=${{ ...TextStyle.secondary }}
                onclick=${() => {
                  setCollapsed(!collapsed);
                }}
              />`
            : html`<div></div>`}
          <div
            style=${{ ...TextStyle.label, ...TextStyle.secondary }}
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
            style=${{ justifySelf: "end", ...TextStyle.secondary }}
            onclick=${() => {
              setCollapsed(!collapsed);
            }}
          >
            ${text}
          </div>
          <div
            style=${{
              justifySelf: "end",
              display: "flex",
              flexDirection: "columns",
            }}
          >
            ${(!hasCollapse || !collapsed) &&
            filteredArrChilden &&
            filteredArrChilden.length > 1
              ? html` <${EventNavs}
                  navs=${filteredArrChilden.map((child, index) => {
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
                />`
              : ""}
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
          </div>
        </div>`
      : "";

  const left_padding = 0.5 + depth * 1.5;
  const card = html` <div
    id=${id}
    class="card"
    style=${{
      padding: `0.5em 0.5em 0.5em ${left_padding}em`,
      marginBottom: "-1px",
      ...style,
    }}
  >
    ${titleEl}
    ${!hasCollapse || !collapsed
      ? html` <div
          class="card-body tab-content"
          style=${{ padding: 0, marginLeft: "0.5em" }}
        >
          ${filteredArrChilden?.map((child, index) => {
            return html`<div
              id=${pillId(index)}
              class="tab-pane show ${index === 0 ? "active" : ""}"
            >
              ${child}
            </div>`;
          })}
        </div>`
      : ""}
  </div>`;
  return card;
};

/**
 * Component to render navigation items.
 *
 * @param {Object} props - The component properties.
 * @param {Array<{id: string, title: string, target: string}>} props.navs - The array of navigation items.
 * @returns {import("preact").ComponentChildren} - The rendered navigation items as a list.
 */
const EventNavs = ({ navs }) => {
  return html`<ul
    class="nav nav-pills card-header-pills"
    style=${{
      marginRight: "0",
      alignItems: "flex-start",
      justifyContent: "flex-end",
    }}
    role="tablist"
    aria-orientation="horizontal"
  >
    ${navs.map((nav, index) => {
      return html`<${EventNav}
        active=${index === 0}
        id=${nav.id}
        target=${nav.target}
        title=${nav.title}
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
 * @param {boolean} props.active - Is the navigation item active.
 * @returns {import("preact").ComponentChildren} - The rendered navigation item.
 */
const EventNav = ({ target, title, active }) => {
  return html`<li class="nav-item">
    <button
      data-bs-toggle="pill"
      data-bs-target="#${target}"
      type="button"
      role="tab"
      aria-controls=${target}
      aria-selected=${active}
      style=${{
        minWidth: "4rem",
        ...TextStyle.label,
        fontSize: FontSize.small,
        padding: "0.1rem  0.6rem",
        borderRadius: "3px",
      }}
      class="nav-link ${active ? "active " : ""}"
    >
      ${title}
    </button>
  </li>`;
};
