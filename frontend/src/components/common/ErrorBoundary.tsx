import React from 'react';

/**
 * Last-resort boundary for the whole application.
 *
 * Without this, any exception thrown while rendering unmounts the entire React tree
 * and leaves `<div id="root">` empty. The user then sees nothing but the page
 * background - which reads as a dead, blank application with no explanation. This
 * component turns that silent failure into a visible, reportable error.
 */
interface ErrorBoundaryProps {
  children: React.ReactNode;
}

interface ErrorBoundaryState {
  error: Error | null;
}

export class ErrorBoundary extends React.Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo): void {
    console.error('LearnSense UI crashed while rendering:', error, info.componentStack);
  }

  render(): React.ReactNode {
    const { error } = this.state;
    if (!error) {
      return this.props.children;
    }

    return (
      <div className="min-h-screen flex items-center justify-center p-6" style={{ background: '#05070D' }}>
        <div
          className="max-w-2xl w-full rounded-2xl p-6 space-y-4"
          style={{ background: '#0E1422', border: '1px solid rgba(248,113,113,0.4)' }}
        >
          <div className="space-y-1">
            <h1 className="text-lg font-bold" style={{ color: '#F4F7FB' }}>
              The interface hit an unexpected error
            </h1>
            <p className="text-xs" style={{ color: '#8D99AA' }}>
              This is a bug in the app, not in your data. Your uploaded material and learner
              progress are stored on the server and were not affected.
            </p>
          </div>

          <pre
            className="text-[11px] p-3 rounded-lg overflow-x-auto whitespace-pre-wrap"
            style={{ background: '#05070D', color: '#FCA5A5', border: '1px solid rgba(255,255,255,0.07)' }}
          >
            {error.name}: {error.message}
          </pre>

          <button
            type="button"
            onClick={() => window.location.reload()}
            className="px-4 py-2 rounded-lg text-xs font-bold"
            style={{ background: '#22D3EE', color: '#05070D' }}
          >
            Reload LearnSense
          </button>
        </div>
      </div>
    );
  }
}
