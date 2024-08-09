import { html } from "htm/preact";
import { FontSize } from "../appearance/Fonts.mjs";
import { ApplicationIcons } from "../appearance/Icons.mjs";

import { Card, CardHeader, CardBody } from "../components/Card.mjs";
import { ANSIDisplay } from "../components/AnsiDisplay.mjs";

export const TaskErrorCard = ({ evalError }) => {
  return html`
    <${Card}>
      <${CardHeader} icon=${ApplicationIcons.error} label="Task Failed: ${evalError.message}"></${CardHeader}>
      <${CardBody} style=${{ fontSize: FontSize.smaller }}>
        <${ANSIDisplay} output=${evalError.traceback_ansi}/>
      </${CardBody}>
    </${Card}>
  `;
};
