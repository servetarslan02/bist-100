"use client";

import { useEffect, useRef, useState, useCallback } from "react";

// =====================================================
// WebSocket Manager (Singleton)
// =====================================================

class WebSocketManager {
  private static instance: WebSocketManager;
  private ws: WebSocket | null = null;
  private subscribers: Map<string, Set<(data: any) => void>> = new Map();
  private reconnectTimer: NodeJS.Timeout | null = null;
  private _connected = false;

  static getInstance(): WebSocketManager {
    if (!WebSocketManager.instance) {
      WebSocketManager.instance = new WebSocketManager();
    }
    return WebSocketManager.instance;
  }

  get connected() {
    return this._connected;
  }

  connect() {
    if (this.ws?.readyState === WebSocket.OPEN) return;

    const wsUrl = `ws://${window.location.host}/ws/live`;
    this.ws = new WebSocket(wsUrl);

    this.ws.onopen = () => {
      this._connected = true;
      console.log("[WS] Connected");
    };

    this.ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        const channel = data.channel || data.type || "default";
        const subs = this.subscribers.get(channel);
        if (subs) {
          subs.forEach(cb => cb(data));
        }
        // Also notify wildcard subscribers
        const wildcardSubs = this.subscribers.get("*");
        if (wildcardSubs) {
          wildcardSubs.forEach(cb => cb(data));
        }
      } catch {}
    };

    this.ws.onclose = () => {
      this._connected = false;
      console.log("[WS] Disconnected, reconnecting...");
      this.reconnectTimer = setTimeout(() => this.connect(), 3000);
    };

    this.ws.onerror = () => {
      this._connected = false;
    };
  }

  disconnect() {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
    this._connected = false;
  }

  subscribe(channel: string, callback: (data: any) => void): () => void {
    if (!this.subscribers.has(channel)) {
      this.subscribers.set(channel, new Set());
    }
    this.subscribers.get(channel)!.add(callback);

    // Send subscribe message to server
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ action: "subscribe", channel }));
    }

    return () => {
      this.subscribers.get(channel)?.delete(callback);
      if (this.subscribers.get(channel)?.size === 0) {
        this.subscribers.delete(channel);
      }
    };
  }

  send(data: any) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data));
    }
  }
}

// =====================================================
// Hooks
// =====================================================

export function useWebSocket() {
  const [connected, setConnected] = useState(false);
  const managerRef = useRef<WebSocketManager>();

  useEffect(() => {
    const manager = WebSocketManager.getInstance();
    managerRef.current = manager;
    manager.connect();

    const interval = setInterval(() => {
      setConnected(manager.connected);
    }, 1000);

    return () => {
      clearInterval(interval);
    };
  }, []);

  return { connected, manager: managerRef.current };
}

export function useWSChannel<T = any>(channel: string) {
  const [data, setData] = useState<T | null>(null);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);

  useEffect(() => {
    const manager = WebSocketManager.getInstance();
    manager.connect();

    const unsub = manager.subscribe(channel, (msg) => {
      setData(msg);
      setLastUpdate(new Date());
    });

    return unsub;
  }, [channel]);

  return { data, lastUpdate };
}

export function useLivePrice(ticker: string) {
  const [price, setPrice] = useState<number | null>(null);
  const [change, setChange] = useState<number>(0);
  const [volume, setVolume] = useState<number>(0);

  useEffect(() => {
    const manager = WebSocketManager.getInstance();
    manager.connect();

    const unsub = manager.subscribe("market.tick", (data) => {
      if (data.ticker === ticker) {
        setPrice(data.price);
        setChange(data.change_pct || 0);
        setVolume(data.volume || 0);
      }
    });

    return unsub;
  }, [ticker]);

  return { price, change, volume };
}

export function useLiveSignals() {
  const [signals, setSignals] = useState<any[]>([]);

  useEffect(() => {
    const manager = WebSocketManager.getInstance();
    manager.connect();

    const unsub = manager.subscribe("signal.generated", (data) => {
      setSignals(prev => [data, ...prev].slice(0, 50));
    });

    return unsub;
  }, []);

  return signals;
}

export function useLiveAlerts() {
  const [alerts, setAlerts] = useState<any[]>([]);

  useEffect(() => {
    const manager = WebSocketManager.getInstance();
    manager.connect();

    const unsub = manager.subscribe("risk.alert", (data) => {
      setAlerts(prev => [data, ...prev].slice(0, 20));
    });

    return unsub;
  }, []);

  return alerts;
}
