import { html } from "htm/preact";

export const EpochFilter = ({ epochs, epoch, setEpoch }) => {
  const options = ["all"];
  for (let i = 1; i <= epochs; i++) {
    options.push(i + "");
  }
  return html`
    <div style=${{ display: "flex", marginRight: "0.5rem" }}>
      <span
        class="epoch-filter-label"
        style=${{ alignSelf: "center", marginRight: "0.5em" }}
        >Epochs:</span
      >
      <select
        class="form-select form-select-sm"
        aria-label=".epoch-filter-label"
        style=${{ fontSize: "0.7rem" }}
        onChange=${(e) => {
          setEpoch(e.target.value);
        }}
      >
        ${options.map((option) => {
          return html`<option value="${option}" ${epoch === option ? "selected" : ""}>${option}</option>`;
        })}
      </select>
    </div>
  `;
};
