import { html } from "htm/preact";
import { Component } from "preact";

import { ErrorPanel } from "./ErrorPanel.mjs";

export class AppErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(error) {
    // Update state so the next render will show the fallback UI.
    return { hasError: true , error: error};
  }

  componentDidCatch(error, errorInfo) {
    // You can also log the error to an error reporting service
    logErrorToMyService(error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      console.log({e: this.state.error});
      // You can render any custom fallback UI
      return html`<${ErrorPanel}
        title="An unexpected error occurred."
        error="${this.state.error}"
      />`;
    }

    return this.props.children;
  }
}
