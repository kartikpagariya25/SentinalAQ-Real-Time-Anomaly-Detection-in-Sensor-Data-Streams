import React from "react";

export default class ErrorBoundary extends React.Component {
  state = { err: null };

  static getDerivedStateFromError(err) {
    return { err };
  }

  componentDidCatch() {
    // transient data-shape glitch — recover on the next poll instead of a blank screen
    this.timer = setTimeout(() => this.setState({ err: null }), 1200);
  }

  componentWillUnmount() {
    clearTimeout(this.timer);
  }

  render() {
    if (this.state.err) {
      return (
        <div className="flex h-40 flex-col items-center justify-center gap-2 text-sm text-muted">
          <span className="live-dot h-2 w-2 rounded-full bg-amber-500" />
          reconnecting…
        </div>
      );
    }
    return this.props.children;
  }
}
