"use client";

/**
 * ErrorBoundary — React Error Boundary
 * =====================================
 * Tüm sayfalar için global hata yakalama.
 * TradingView/Bloomberg standardı: hata olursa graceful fallback göster.
 */

import React, { Component, type ReactNode } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
  name?: string;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error(`[ErrorBoundary${this.props.name ? `:${this.props.name}` : ""}]`, error, errorInfo);
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;

      return (
        <div className="flex flex-col items-center justify-center gap-3 p-8 rounded-xl bg-zinc-900/60 border border-zinc-800 min-h-[200px]">
          <AlertTriangle size={24} className="text-amber-400" />
          <div className="text-center">
            <p className="text-sm font-semibold text-zinc-200">Bir şeyler yanlış gitti</p>
            <p className="text-[11px] text-zinc-500 mt-1 max-w-[300px]">
              {this.state.error?.message || "Beklenmeyen bir hata oluştu."}
            </p>
          </div>
          <button
            onClick={this.handleReset}
            className="flex items-center gap-1.5 px-3 py-1.5 text-[11px] font-semibold rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-300 transition-colors"
          >
            <RefreshCw size={11} />
            Tekrar Dene
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}
