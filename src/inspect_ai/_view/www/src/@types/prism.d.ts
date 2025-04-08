declare var Prism: {
  languages: any;
  highlight(contents: any, tokens: any, type: any): string;
  highlightElement(
    element: HTMLElement,
    async?: boolean,
    callback?: (element: HTMLElement) => void,
  );

  highlightAllUnder(
    element: HTMLElement,
    async?: boolean,
    callback?: (element: HTMLElement) => void,
  );
};
