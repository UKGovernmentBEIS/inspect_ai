import { html } from "htm/preact";
import { useState } from "preact/hooks";
import { FontSize, TextStyle } from "../appearance/Fonts.mjs";

export const NavPills = ({ children }) => {
  const [activeItem, setActiveItem] = useState(children[0].props["title"]);

  const NavPill = ({ title, activeItem, setActiveItem }) => {
    const active = activeItem === title;
    return html` <li class="nav-item">
      <button
        type="button"
        role="tab"
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
          setActiveItem(title);
        }}
      >
        ${title}
      </button>
    </li>`;
  };

  const navPills = children.map((nav, idx) => {
    const title =
      typeof nav === "object"
        ? nav["props"]?.title || `Tab ${idx}`
        : `Tab ${idx}`;
    return html`<${NavPill}
      title=${title}
      activeItem=${activeItem}
      setActiveItem=${setActiveItem}
    />`;
  });

  const navBodies = children.map((child) => {
    return html` <div
      style=${{
        display: child["props"]?.title === activeItem ? "block" : "none",
      }}
    >
      ${child}
    </div>`;
  });

  return html`<ul
      class="nav nav-pills card-header-pills"
      style=${{ marginRight: "0" }}
      role="tablist"
      aria-orientation="horizontal"
    >
      ${navPills}
    </ul>
    ${navBodies}`;
};
