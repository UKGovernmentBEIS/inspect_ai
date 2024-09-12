/**
 * Opens a new window and prints the provided HTML content with optional custom CSS for printing.
 *
 * @param {string} html - The HTML content to be printed in the new window.
 * @param {string} css - Custom CSS that will be applied when the print media is active.
 *
 * @example
 * // Example usage:
 * printHtml('<h1>Hello World</h1>', 'h1 { color: red; }');
 */
export const printHtml = (html, css) => {
  // Open a new window
  const printWindow = window.open("", "", "height=600,width=800");

  // Write the element's content into the new window
  printWindow.document.write("<html><head><title>Print</title>");

  // Inject custom print CSS
  printWindow.document.write(`
          <link rel="stylesheet" crossorigin="" href="./assets/index.css">
          <style>
            @media print {
              ${css}
            }
          </style>
        `);

  printWindow.document.write("</head><body>");
  printWindow.document.write(html);
  printWindow.document.write("</body></html>");

  // Close the document to complete the writing process
  printWindow.document.close();

  // Wait for the window to load fully before triggering the print
  printWindow.onload = function () {
    printWindow.focus(); // Ensure the window is focused
    printWindow.print(); // Trigger the print
    printWindow.close(); // Close the window after printing
  };
};

/**
 * Generates an HTML string that displays the task title, model, and creation time in a styled grid layout.
 *
 * The task title, model, and creation time are retrieved from the elements with the IDs 'task-title',
 * 'task-model', and 'task-created', respectively. The generated HTML will display these elements in a
 * three-column grid with custom styling.
 *
 * @returns {string} - The generated HTML string containing the task information.
 *
 * @example
 * // Example usage:
 * const headingHtml = printHeadingHtml();
 * console.log(headingHtml);
 */
export const printHeadingHtml = () => {
  const task = document.getElementById("task-title").innerText;
  const model = document.getElementById("task-model").innerText;
  const time = document.getElementById("task-created").innerText;

  // Get the task name, date, model
  const headingHtml = `
<div style="display: grid; grid-template-columns: repeat(3, 1fr); column-gap: 0.5em; margin-bottom: 2em; justify-content: space-between; border-bottom: solid 1px silver;">
<div style="font-weight: 600">${task}</div>
<div style="text-align: center;">${model}</div>
<div style="text-align: right;">${time}</div>
</div>`;
  return headingHtml;
};
