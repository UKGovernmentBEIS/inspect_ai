// forward keydown events so shortcuts can work in vscode, see:
// https://github.com/microsoft/vscode/issues/65452#issuecomment-586485815
if (window.parent.postMessage) {
  window.document.addEventListener("keydown", (e) => {
    const event = {
      type: "keydown",
      data: {
        altKey: e.altKey,
        code: e.code,
        ctrlKey: e.ctrlKey,
        isComposing: e.isComposing,
        key: e.key,
        location: e.location,
        metaKey: e.metaKey,
        repeat: e.repeat,
        shiftKey: e.shiftKey,
      },
    };
    window.parent.postMessage(event, "*");
  });
}

// listen for execCommand messages
window.addEventListener(
  "message",
  function (event) {
    if (event.data.type === "devhost-exec-command") {
      window.document.execCommand(event.data.data);
    } else if (event.data.type === "theme-colors-override") {
      mapTheme(event.data.data);
      document.documentElement.removeAttribute("data-bs-theme");
    }
  },
  true
);

const mapTheme = (colors) => {
  Object.keys(kColorMap).forEach((key) => {
    kColorMap[key].forEach((target) => {
      this.window.document.documentElement.style.setProperty(
        target,
        colors[key],
        "important"
      );
    });
  });

  const styleSelectors = Object.keys(kColorStyles);
  if (styleSelectors.length > 0) {
    const styles = styleSelectors.map((styleSelector) => {
      const lines = [`${styleSelector} {`];
      Object.keys(kColorStyles[styleSelector]).forEach((vscodeColor) => {
        kColorStyles[styleSelector][vscodeColor].forEach((val) => {
          lines.push(`  ${val}: ${colors[vscodeColor]};`);
        });
      });
      lines.push(`}`);
      lines.push(``);
      return lines.join("\n");
    });

    const styleEl = document.createElement("style");
    styleEl.appendChild(document.createTextNode(styles.join("\n")));
    this.window.document.head.appendChild(styleEl);
  }
};

const kColorMap = {
  "--vscode-editor-background": [
    "--bs-body-bg",
    "--bs-card-bg",
    "--bs-table-bg",
  ],
  "--vscode-editor-selectionHighlightBackground": ["--bs-light-bg-subtle"],
  "--vscode-editor-foreground": [
    "--bs-body-color",
    "--bs-table-color",
    "--bs-accordion-btn-color",
    "--bs-emphasis-color",
    "--bs-navbar-brand-color",
    "--bs-navbar-brand-hover-color",
  ],
  "--vscode-editorInfo-foreground": ["--bs-code-color"],
  "--vscode-peekViewTitle-background": ["--bs-light", "--bs-btn-bg"],
  "--vscode-banner-iconForeground": [
    "--bs-primary",
    "--bs-nav-pills-link-active-bg",
  ],
  "--vscode-breadcrumb-foreground": ["--bs-secondary"],
  "--vscode-list-inactiveSelectionBackground": ["--bs-secondary-bg"]
};


const kColorStyles = {
  ".btn-tools": {
    "--vscode-peekViewTitle-background": [
      "--bs-btn-hover-bg",
      "--bs-btn-bg",
      "--bs-btn-border-color",
      "--bs-btn-hover-border-color",
    ],
    "--vscode-peekViewTitleDescription-foreground": [
      "--bs-btn-color",
      "--bs-btn-hover-color",
    ],
  },
  ".navbar-brand": {
    "--vscode-sideBarSectionHeader-foreground": [
      "--bs-navbar-brand-color",
      "--bs-navbar-brand-hover-color",
    ],
  },
  ".navbar-text": {
    "--vscode-sideBarSectionHeader-foreground": [
      "--bs-navbar-color",
    ],
  },
  body: {
    "--vscode-editorGroup-border": [
      "--bs-border-color",
      "--bs-card-border-color",
    ],
  },
  ".accordion-item": {
    "--vscode-list-inactiveSelectionBackground": [
      "--bs-accordion-active-bg"
    ],  
  },
  ".card-header": {
    "--vscode-editorGroup-border": [
      "--bs-border-color",
      "--bs-card-border-color",
    ],
  },
  ".card": {
    "--vscode-editorGroup-border": [
      "--bs-border-color",
      "--bs-card-border-color",
    ],
  },
  ".nav-pills": {
    "--vscode-list-inactiveSelectionBackground": [
      "--bs-nav-pills-link-active-bg",
    ],
    "--vscode-editor-selectionForeground": ["--bs-nav-pills-link-active-color"],
  },
  ".nav-link": {
    "--vscode-editor-selectionForeground": [
      "--bs-nav-link-color",
      "--bs-link-hover-color",
    ],
  },
  ".nav-link:hover": {
    "--vscode-editor-selectionForeground": [
      "--bs-nav-link-color",
      "--bs-nav-link-hover-color",
      "--bs-nav-tabs-link-hover-border-color"
    ],
  },
  ".ansi-display": {
    "--vscode-terminal-ansiBlack": ["--ansiBlack"],
    "--vscode-terminal-ansiRed": ["--ansiRed"],
    "--vscode-terminal-ansiGreen": ["--ansiGreen"],
    "--vscode-terminal-ansiYellow": ["--ansiYellow"],
    "--vscode-terminal-ansiBlue": ["--ansiBlue"],
    "--vscode-terminal-ansiMagenta": ["--ansiMagenta"],
    "--vscode-terminal-ansiCyan": ["--ansiCyan"],
    "--vscode-terminal-ansiWhite": ["--ansiWhite"],
    "--vscode-terminal-ansiBrightBlack": ["--ansiBrightBlack"],
    "--vscode-terminal-ansiBrightRed": ["--ansiBrightRed"],
    "--vscode-terminal-ansiBrightGreen": ["--ansiBrightGreen"],
    "--vscode-terminal-ansiBrightYellow": ["--ansiBrightYellow"],
    "--vscode-terminal-ansiBrightBlue": ["--ansiBrightBlue"],
    "--vscode-terminal-ansiBrightMagenta": ["--ansiBrightMagenta"],
    "--vscode-terminal-ansiBrightCyan": ["--ansiBrightCyan"],
    "--vscode-terminal-ansiBrightWhite": ["--ansiBrightWhite"],
  },
  ".sidebar .list-group": {
    "--vscode-list-hoverBackground": ["--bs-tertiary-bg"],
    "--vscode-foreground": ["--bs-secondary-color"],
    "--vscode-sideBarSectionHeader-background": [
      "--bs-list-group-active-bg",
      "--bs-list-group-active-border-color",
      "--bs-list-group-action-active-bg",
    ],
    "--vscode-sideBarSectionHeader-foreground": [
      "--bs-list-group-active-color",
    ],
  },
};


const kForcedValues = {
  "body" : {
    "--bs-border-radius": "0"
  }
}

// listen for execCommand messages
window.addEventListener(
  "message",
  function (event) {
    if (event.data.type === "devhost-exec-command") {
      window.document.execCommand(event.data.data);
    } else if (event.data.type === "theme-colors-override") {

      const colors = event.data.data;
      Object.keys(kColorMap).forEach((key) => {
        kColorMap[key].forEach((target) => {
          this.window.document.documentElement.style.setProperty(
            target,
            colors[key],
            "important"
          );
        });
      });

      const styleSelectors = Object.keys(kColorStyles);
      if (styleSelectors.length > 0) {
        const styles = styleSelectors.map((styleSelector) => {
          const lines = [`${styleSelector} {`];
          Object.keys(kColorStyles[styleSelector]).forEach((vscodeColor) => {
            kColorStyles[styleSelector][vscodeColor].forEach((val) => {
              lines.push(`  ${val}: ${colors[vscodeColor]};`);
            });
          });
          lines.push(`}`);
          lines.push(``);
          return lines.join("\n");
        });

        const styleEl = document.createElement("style");
        styleEl.appendChild(document.createTextNode(styles.join("\n")));
        this.window.document.head.appendChild(styleEl);
      }

      // There are just statically set custom values
      const forcedSelectors = Object.keys(kForcedValues);
      if (forcedSelectors.length > 0) {
        const forcedStyles = forcedSelectors.map((sel) => {
          const lines = [`${sel} {`];
          Object.keys(kForcedValues[sel]).forEach((key) => {
            lines.push(`  ${key}: ${kForcedValues[sel][key]};`);
          })
          lines.push(`}`);
          lines.push(``);
          return lines.join("\n");
        });
    
        const styleEl = document.createElement("style");
        styleEl.appendChild(document.createTextNode(forcedStyles.join("\n")));
        this.window.document.head.appendChild(styleEl);
      }  


      // Set accordion button styles
      const accordionColor = colors["--vscode-breadcrumb-foreground"];
      const styleEl = document.createElement("style");

      styleEl.appendChild(this.document.createTextNode(`
      .accordion{
      --bs-accordion-btn-icon: url("data:image/svg+xml,%3csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16' fill='${accordionColor}'%3e%3cpath fill-rule='evenodd' d='M1.646 4.646a.5.5 0 0 1 .708 0L8 10.293l5.646-5.647a.5.5 0 0 1 .708.708l-6 6a.5.5 0 0 1-.708 0l-6-6a.5.5 0 0 1 0-.708z'/%3e%3c/svg%3e");      
      --bs-accordion-btn-active-icon: url("data:image/svg+xml,%3csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16' fill='${accordionColor}'%3e%3cpath fill-rule='evenodd' d='M1.646 4.646a.5.5 0 0 1 .708 0L8 10.293l5.646-5.647a.5.5 0 0 1 .708.708l-6 6a.5.5 0 0 1-.708 0l-6-6a.5.5 0 0 1 0-.708z'/%3e%3c/svg%3e");
      }
      `));
      this.window.document.head.appendChild(styleEl);


    }
      },
  true
);

