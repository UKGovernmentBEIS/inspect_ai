//@ts-check
import { html } from "htm/preact";
import { FontSize } from "../appearance/Fonts.mjs";

/**
 * Pagination component for rendering page navigation.
 *
 * @param {Object} props - The properties object.
 * @param {number} props.pageCount - Total number of pages.
 * @param {number} props.currentPage - The current active page (zero-based index).
 * @param {function} props.onCurrentPage - Callback function to handle page change.
 * @returns {import("preact").JSX.Element} The Pagination component.
 */
export const Pagination = ({ pageCount, currentPage, onCurrentPage }) => {
  return html`<nav aria-label="Page navigation example">
    <ul
      class="pagination"
      style=${{
        "--bs-pagination-padding-y": "0",
        marginBottom: "0",
        "--bs-pagination-font-size": FontSize.base,
      }}
    >
      <${PageText}
        PageButton
        text="Previous"
        onclick=${() => {
          if (currentPage > 0) {
            onCurrentPage(currentPage - 1);
          }
        }}
        enabled=${currentPage > 0}
      />
      <${PageItems}
        pageCount=${pageCount}
        currentPage=${currentPage}
        onCurrentPage=${onCurrentPage}
      />
      <${PageText}
        PageButton
        text="Next"
        onclick=${() => {
          if (currentPage < pageCount - 1) {
            onCurrentPage(currentPage + 1);
          }
        }}
        enabled=${currentPage < pageCount - 1}
      />
    </ul>
  </nav>`;
};

/**
 * PageButton component for rendering a single page navigation button.
 *
 * @param {Object} props - The properties object.
 * @param {string} props.text - The text to display on the button.
 * @param {function} props.onclick - The click event handler for the button.
 * @param {boolean} props.enabled - Indicates whether the button is enabled or disabled.
 * @returns {import("preact").JSX.Element} The Pagination component.
 */
const PageText = ({ text, onclick, enabled }) => {
  return html`<li class="page-item ${!enabled ? "disabled" : ""}">
    <a class="page-link" href="#" onclick=${onclick}>${text}</a>
  </li>`;
};

/**
 * PagePlaceholder component for rendering a single placeholder button.
 *
 * @returns {import("preact").JSX.Element} The Pagination component.
 */
const PagePlaceholder = () => {
  return html`<li class="page-item">
    <div class="page-link" style=${{ color: "var(--bs-body-color)" }}>…</div>
  </li>`;
};

/**
 * PageButton component for rendering a single page navigation button.
 *
 * @param {Object} props - The properties object.
 * @param {number} props.n - The page number
 * @param {number} props.currentPage - The currentPage
 * @param {(n: number) => void} props.onCurrentPage - Change the current page
 * @returns {import("preact").JSX.Element} The Pagination component.
 */
const PageNumber = ({ n, currentPage, onCurrentPage }) => {
  return html`<li class="page-item">
    <a
      class="page-link ${currentPage === n ? "active" : ""}"
      href="#"
      onclick=${() => {
        onCurrentPage(n);
      }}
      >${n + 1}</a
    >
  </li>`;
};

/**
 * PageButton component for rendering a single page navigation button.
 *
 * @param {Object} props - The properties object.
 * @param {number} props.pageCount - The number of pages
 * @param {number} props.currentPage - The currentPage
 * @param {(n: number) => void} props.onCurrentPage - Change the current page
 * @returns {import("preact").JSX.Element[]} The component items.
 */
const PageItems = ({ pageCount, currentPage, onCurrentPage }) => {
  const items = [];
  if (pageCount < 7) {
    for (let i = 0; i < pageCount; i++) {
      items.push(
        html`<${PageNumber}
          n=${i}
          currentPage=${currentPage}
          onCurrentPage=${onCurrentPage}
        />`,
      );
    }
  } else if (currentPage < 5) {
    for (let i = 0; i < 5; i++) {
      items.push(
        html`<${PageNumber}
          n=${i}
          currentPage=${currentPage}
          onCurrentPage=${onCurrentPage}
        />`,
      );
    }
    items.push(html`<${PagePlaceholder} />`);
    items.push(
      html`<${PageNumber}
        n=${pageCount - 1}
        currentPage=${currentPage}
        onCurrentPage=${onCurrentPage}
      />`,
    );
  } else if (currentPage > pageCount - 5) {
    items.push(
      html`<${PageNumber}
        n=${0}
        currentPage=${currentPage}
        onCurrentPage=${onCurrentPage}
      />`,
    );
    items.push(html`<${PagePlaceholder} />`);
    for (let i = pageCount - 5; i < pageCount; i++) {
      items.push(
        html`<${PageNumber}
          n=${i}
          currentPage=${currentPage}
          onCurrentPage=${onCurrentPage}
        />`,
      );
    }
  } else {
    items.push(
      html`<${PageNumber}
        n=${0}
        currentPage=${currentPage}
        onCurrentPage=${onCurrentPage}
      />`,
    );

    items.push(html`<${PagePlaceholder} />`);
    for (let i = currentPage; i < currentPage + 3; i++) {
      items.push(
        html`<${PageNumber}
          n=${i}
          currentPage=${currentPage}
          onCurrentPage=${onCurrentPage}
        />`,
      );
    }
    items.push(html`<${PagePlaceholder} />`);
    items.push(
      html`<${PageNumber}
        n=${pageCount - 1}
        currentPage=${currentPage}
        onCurrentPage=${onCurrentPage}
      />`,
    );
  }

  return items;
};
