import { html } from "htm/preact";
import { ApplicationIcons } from "../appearance/icons";

import { ANSIDisplay } from "../components/AnsiDisplay";
import { Card, CardBody, CardHeader } from "../components/Card";

export const TaskErrorCard = ({ evalError }) => {
  return html`
    <${Card}>
      <${CardHeader} icon=${ApplicationIcons.error} label="Task Failed: ${evalError.message}"></${CardHeader}>
      <${CardBody}>
        <${ANSIDisplay} output=${evalError.traceback_ansi} style=${{ fontSize: "clamp(0.2rem, calc(0.2em + .93vw), 0.9rem)" }}/>
      </${CardBody}>
    </${Card}>
  `;
};
