// @ts-check
import { html } from "htm/preact";
import { ApplicationIcons } from "../../appearance/Icons.mjs";
import { FontSize, TextStyle } from "../../appearance/Fonts.mjs";

/**
 * Renders the StateEventView component.
 *
 * @param {Object} props - The properties passed to the component.
 * @param {string} props.id - The id of the event
 * @param {string | undefined} props.title - The name of the event
 * @param {string | undefined} props.icon - The icon of the event
 * @param {import("preact").ComponentChildren} props.children - The rendered event.
 * @returns {import("preact").JSX.Element} The component.
 */
export const EventPanel = ({ id, title, icon, children }) => {
  /**
   * @type {import("preact").ComponentChildren[] | undefined}
   */
  const arrChildren =
    children === undefined
      ? children
      : Array.isArray(children)
      ? children
      : [children];

  /**
   * Generates the id for the navigation pill.
   *
   * @param {number} index - The index of the pill.
   * @returns {string} The generated id.
   */
  const pillId = (index) => {
    return `${id}-nav-pill-${index}`;
  };

  const titleEl = title
    ? html`<div
        style=${{
          paddingLeft: "0.5em",
          display: "grid",
          gridTemplateColumns: "max-content max-content minmax(0, 1fr)",
          columnGap: "0.5em",
          fontSize: FontSize.small,
        }}
      >
        <i
          class=${icon || ApplicationIcons.metadata}
          style=${{ ...TextStyle.secondary }}
        />
        <div style=${{ ...TextStyle.label, ...TextStyle.secondary }}>
          ${title}
        </div>
        <div style=${{ justifySelf: "end" }}>
          ${arrChildren && arrChildren.length > 1
            ? html` <${EventNavs}
                navs=${arrChildren.map((child, index) => {
                  return {
                    id: `eventpanel-${id}-${index}`,
                    title:
                      index === 0
                        ? "summary"
                        : index + 1 === arrChildren.length
                        ? "raw"
                        : `item-${index + 1}`,
                    target: pillId(index),
                  };
                })}
              />`
            : ""}
        </div>
      </div>`
    : "";

  const card = html` <div
    class="card"
    style=${{
      padding: "0.5em",
      marginBottom: "-1px",
    }}
  >
    ${titleEl}
    <div
      class="card-body tab-content"
      style=${{ padding: 0, marginLeft: "2em" }}
    >
      ${arrChildren?.map((child, index) => {
        return html`<div
          id=${pillId(index)}
          class="tab-pane show ${index === 0 ? "active" : ""}"
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
 * @returns {import("preact").ComponentChildren} - The rendered navigation items as a list.
 */
const EventNavs = ({ navs }) => {
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