import { Component, type ErrorInfo, type ReactNode } from "react";

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

export default class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { hasError: false, error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error("ErrorBoundary caught an error:", error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex flex-col items-center justify-center gap-3 rounded-md border border-border-weak bg-surface-raised p-8 text-center">
          <div className="text-status-faultText font-semibold">Something went wrong.</div>
          <div className="text-sm text-text-secondary">
            {this.state.error?.message || "An unexpected error occurred while rendering this page."}
          </div>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="mt-2 rounded-md bg-surface-base border border-border-weak px-4 py-2 text-sm text-text-primary hover:text-text-maxContrast"
          >
            Reload
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
