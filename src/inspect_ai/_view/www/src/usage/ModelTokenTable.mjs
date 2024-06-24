import { html } from "htm/preact";

export const ModelTokenTable = ({ model_usage }) => {
  return html`
  <${TokenTable}>
    <${TokenHeader}/>
    <tbody>
    ${Object.keys(model_usage).map((key) => {
      const vals = Object.values(model_usage[key]);
      return html`<${TokenRow} model=${key} values=${vals} />`;
    })}
    </tbody>
  </${TokenTable}>
  `;
};

const TokenTable = ({ children }) => {
  return html`<table
    class="table table-sm"
    style=${{ width: "100%", fontSize: "0.8rem", marginTop: "0.7rem" }}
  >
    ${children}
  </table>`;
};

const thStyle = {
  padding: 0,
  fontSize: "0.7rem",
  fontWeight: 400,
  textTransform: "uppercase",
};

const TokenHeader = () => {
  return html`<thead>
    <tr>
      <td></td>
      <td
        colspan="3"
        align="center"
        class="card-subheading"
        style=${{ paddingBottom: "0.7rem" }}
      >
        Tokens
      </td>
    </tr>
    <tr>
      <th style=${thStyle}>Model</th>
      <th style=${thStyle}>Input</th>
      <th style=${thStyle}>Output</th>
      <th style=${thStyle}>Total</th>
    </tr>
  </thead>`;
};

const TokenRow = ({ model, values }) => {
  return html`<tr>
    <td>${model}</td>
    ${values.map((val) => {
      return html`<td>${val.toLocaleString()}</td>`;
    })}
  </tr>`;
};
