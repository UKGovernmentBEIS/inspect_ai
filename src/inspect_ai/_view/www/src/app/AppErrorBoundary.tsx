import { Component, ErrorInfo, ReactNode } from "react";
import { ErrorPanel } from "../components/ErrorPanel";

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error?: Error;
}

export class AppErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(error: Error): State {
    // Update state so the next render will show the fallback UI.
    return { hasError: true, error: error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    // You can also log the error to an error reporting service
    console.log({ error, errorInfo });
  }

  render(): ReactNode {
    if (this.state.hasError) {
      console.error({ e: this.state.error });
      if (this.state.error) {
        return (
          <ErrorPanel
            title="An unexpected error occurred."
            error={this.state.error}
          />
        );
      } else {
        return (
          <div>An unknown error with no additional information occured.</div>
        );
      }
    }
    return this.props.children;
  }
}
