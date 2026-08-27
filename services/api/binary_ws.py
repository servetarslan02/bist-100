"""
ALPHA BIST — Binary WebSocket v2.0 (Protobuf Native)

Gerçek Protobuf serialization ile WebSocket — JSON'dan 10x küçük, 10x hızlı.
gRPC ile aynı proto tanımlarını kullanır (proto/market.proto).

Desteklenen mesaj tipleri:
    - MarketTick (fiyat)
    - OHLCV (mum)
    - Signal (alım/satım sinyali)
    - PortfolioState (portföy durumu)
    - RiskMetrics (risk metrikleri)
    - MarketRegime (piyasa rejimi)
    - MarketEvent (olay)
    - Alert (alarm)
    - Heartbeat (kalp atışı)

Kullanım:
    ws = BinaryWebSocket()
    await ws.start(port=8765)

    # Client tarafı:
    const ws = new WebSocket('ws://localhost:8765');
    ws.binaryType = 'arraybuffer';
"""

import asyncio
import time
from typing import Any

import structlog

try:
    import websockets
    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False

# Protobuf imports — gRPC ile aynı generated kod
try:
    from ..grpc.generated import market_pb2
    HAS_PROTOBUF = True
except ImportError:
    HAS_PROTOBUF = False

import orjson

logger = structlog.get_logger()


class ProtobufMessage:
    """Protobuf tabanlı binary mesaj serialization.

    gRPC'deki ile aynı proto/market.proto tanımlarını kullanır.
    StreamMessage wrapper'ı ile tüm mesaj tiplerini tek bir
    binary frame içinde paketler.
    """

    # Mesaj tipi mapping (StreamMessage.MessageType enum)
    TYPE_MAP = {
        "tick": 0,      # TICK
        "ohlcv": 1,     # OHLCV
        "signal": 2,    # SIGNAL
        "portfolio": 3, # PORTFOLIO
        "risk": 4,      # RISK
        "regime": 5,    # REGIME
        "event": 6,     # EVENT
        "alert": 7,     # ALERT
        "heartbeat": 8, # HEARTBEAT
    }

    _sequence: int = 0

    @classmethod
    def _next_sequence(cls) -> int:
        cls._sequence += 1
        return cls._sequence

    @classmethod
    def encode_tick(cls, ticker: str, price: float, change: float,
                    change_pct: float, volume: int, bid: float = 0,
                    ask: float = 0, timestamp: int = 0) -> bytes:
        """MarketTick → Protobuf binary."""
        if not HAS_PROTOBUF:
            return cls._fallback_encode("tick", ticker=ticker, price=price,
                                        change=change, volume=volume, timestamp=timestamp)

        tick = market_pb2.MarketTick(
            ticker=ticker,
            price=price,
            change=change,
            change_pct=change_pct,
            volume=volume,
            bid=bid,
            ask=ask,
            timestamp=timestamp or int(time.time() * 1000),
        )
        msg = market_pb2.StreamMessage(
            type=market_pb2.StreamMessage.TICK,
            sequence=cls._next_sequence(),
            timestamp=int(time.time() * 1000),
            tick=tick,
        )
        return msg.SerializeToString()

    @classmethod
    def encode_ohlcv(cls, ticker: str, open_p: float, high: float,
                     low: float, close: float, volume: int,
                     timeframe: str = "1m", timestamp: int = 0) -> bytes:
        """OHLCV → Protobuf binary."""
        if not HAS_PROTOBUF:
            return cls._fallback_encode("ohlcv", ticker=ticker, open=open_p,
                                        high=high, low=low, close=close, volume=volume)

        ohlcv = market_pb2.OHLCV(
            ticker=ticker,
            timestamp=timestamp or int(time.time() * 1000),
            open=open_p,
            high=high,
            low=low,
            close=close,
            volume=volume,
            timeframe=timeframe,
        )
        msg = market_pb2.StreamMessage(
            type=market_pb2.StreamMessage.OHLCV,
            sequence=cls._next_sequence(),
            timestamp=int(time.time() * 1000),
            ohlcv=ohlcv,
        )
        return msg.SerializeToString()

    @classmethod
    def encode_signal(cls, ticker: str, direction: str, confidence: float,
                      target_price: float, stop_loss: float,
                      reason: str = "", timestamp: int = 0) -> bytes:
        """Signal → Protobuf binary."""
        if not HAS_PROTOBUF:
            return cls._fallback_encode("signal", ticker=ticker, direction=direction,
                                        confidence=confidence, timestamp=timestamp)

        direction_map = {"BUY": 0, "SELL": 1, "HOLD": 2}
        signal = market_pb2.Signal(
            ticker=ticker,
            direction=direction_map.get(direction, 2),
            confidence=confidence,
            target_price=target_price,
            stop_loss=stop_loss,
            reason=reason,
            timestamp=timestamp or int(time.time() * 1000),
        )
        msg = market_pb2.StreamMessage(
            type=market_pb2.StreamMessage.SIGNAL,
            sequence=cls._next_sequence(),
            timestamp=int(time.time() * 1000),
            signal=signal,
        )
        return msg.SerializeToString()

    @classmethod
    def encode_portfolio(cls, total_value: float, cash: float,
                         daily_pnl: float, daily_pnl_pct: float,
                         positions: list = None, timestamp: int = 0) -> bytes:
        """PortfolioState → Protobuf binary."""
        if not HAS_PROTOBUF:
            return cls._fallback_encode("portfolio", total_value=total_value, cash=cash)

        proto_positions = []
        for p in (positions or []):
            proto_positions.append(market_pb2.Position(
                ticker=p.get("ticker", ""),
                quantity=int(p.get("quantity", 0)),
                avg_price=float(p.get("avg_price", 0)),
                current_price=float(p.get("current_price", 0)),
                pnl=float(p.get("pnl", 0)),
                pnl_pct=float(p.get("pnl_pct", 0)),
                weight=float(p.get("weight", 0)),
            ))

        portfolio = market_pb2.PortfolioState(
            total_value=total_value,
            cash=cash,
            daily_pnl=daily_pnl,
            daily_pnl_pct=daily_pnl_pct,
            positions=proto_positions,
            timestamp=timestamp or int(time.time() * 1000),
        )
        msg = market_pb2.StreamMessage(
            type=market_pb2.StreamMessage.PORTFOLIO,
            sequence=cls._next_sequence(),
            timestamp=int(time.time() * 1000),
            portfolio=portfolio,
        )
        return msg.SerializeToString()

    @classmethod
    def encode_risk(cls, var_95: float, cvar_95: float, sharpe: float,
                    max_drawdown: float, volatility: float, beta: float,
                    timestamp: int = 0) -> bytes:
        """RiskMetrics → Protobuf binary."""
        if not HAS_PROTOBUF:
            return cls._fallback_encode("risk", var_95=var_95, sharpe=sharpe)

        risk = market_pb2.RiskMetrics(
            var_95=var_95,
            cvar_95=cvar_95,
            sharpe=sharpe,
            max_drawdown=max_drawdown,
            volatility=volatility,
            beta=beta,
            timestamp=timestamp or int(time.time() * 1000),
        )
        msg = market_pb2.StreamMessage(
            type=market_pb2.StreamMessage.RISK,
            sequence=cls._next_sequence(),
            timestamp=int(time.time() * 1000),
            risk=risk,
        )
        return msg.SerializeToString()

    @classmethod
    def encode_regime(cls, regime: str, confidence: float, vix: float = 0,
                      breadth: float = 0, timestamp: int = 0) -> bytes:
        """MarketRegime → Protobuf binary."""
        if not HAS_PROTOBUF:
            return cls._fallback_encode("regime", regime=regime, confidence=confidence)

        regime_map = {
            "BULL_TREND": 0, "BEAR_TREND": 1, "SIDEWAYS": 2,
            "HIGH_VOLATILITY": 3, "CRISIS": 4,
        }
        proto_regime = market_pb2.MarketRegime(
            regime=regime_map.get(regime, 2),
            confidence=confidence,
            vix=vix,
            breadth=breadth,
            timestamp=timestamp or int(time.time() * 1000),
        )
        msg = market_pb2.StreamMessage(
            type=market_pb2.StreamMessage.REGIME,
            sequence=cls._next_sequence(),
            timestamp=int(time.time() * 1000),
            regime=proto_regime,
        )
        return msg.SerializeToString()

    @classmethod
    def encode_event(cls, event_type: str, ticker: str, title: str,
                     summary: str = "", sentiment: float = 0,
                     impact_score: float = 0, timestamp: int = 0) -> bytes:
        """MarketEvent → Protobuf binary."""
        if not HAS_PROTOBUF:
            return cls._fallback_encode("event", ticker=ticker, title=title)

        type_map = {
            "KAP_ANNOUNCEMENT": 0, "NEWS": 1, "MACRO_DATA": 2,
            "EARNINGS": 3, "DIVIDEND": 4, "ANALYST_RATING": 5,
        }
        event = market_pb2.MarketEvent(
            type=type_map.get(event_type, 1),
            ticker=ticker,
            title=title,
            summary=summary,
            sentiment=sentiment,
            impact_score=impact_score,
            timestamp=timestamp or int(time.time() * 1000),
        )
        msg = market_pb2.StreamMessage(
            type=market_pb2.StreamMessage.EVENT,
            sequence=cls._next_sequence(),
            timestamp=int(time.time() * 1000),
            event=event,
        )
        return msg.SerializeToString()

    @classmethod
    def encode_alert(cls, alert_type: str, ticker: str, message: str,
                     severity: str = "INFO", value: float = 0,
                     threshold: float = 0, timestamp: int = 0) -> bytes:
        """Alert → Protobuf binary."""
        if not HAS_PROTOBUF:
            return cls._fallback_encode("alert", ticker=ticker, message=message)

        type_map = {"PRICE": 0, "VOLUME": 1, "ANOMALY": 2, "RISK": 3, "SIGNAL": 4}
        severity_map = {"INFO": 0, "WARNING": 1, "CRITICAL": 2}
        alert = market_pb2.Alert(
            type=type_map.get(alert_type, 0),
            ticker=ticker,
            message=message,
            severity=severity_map.get(severity, 0),
            value=value,
            threshold=threshold,
            timestamp=timestamp or int(time.time() * 1000),
        )
        msg = market_pb2.StreamMessage(
            type=market_pb2.StreamMessage.ALERT,
            sequence=cls._next_sequence(),
            timestamp=int(time.time() * 1000),
            alert=alert,
        )
        return msg.SerializeToString()

    @classmethod
    def encode_heartbeat(cls) -> bytes:
        """Heartbeat → Protobuf binary."""
        if not HAS_PROTOBUF:
            return cls._fallback_encode("heartbeat", timestamp=int(time.time() * 1000))

        msg = market_pb2.StreamMessage(
            type=market_pb2.StreamMessage.HEARTBEAT,
            sequence=cls._next_sequence(),
            timestamp=int(time.time() * 1000),
        )
        return msg.SerializeToString()

    @classmethod
    def decode(cls, data: bytes) -> dict[str, Any]:
        """Protobuf binary → Dict."""
        if not HAS_PROTOBUF:
            return cls._fallback_decode(data)

        try:
            msg = market_pb2.StreamMessage()
            msg.ParseFromString(data)

            result = {
                "type": cls._type_name(msg.type),
                "sequence": msg.sequence,
                "timestamp": msg.timestamp,
            }

            # Payload'a göre alt mesajı parse et
            payload_field = msg.WhichOneof("payload")
            if payload_field == "tick":
                result["data"] = {
                    "ticker": msg.tick.ticker,
                    "price": msg.tick.price,
                    "change": msg.tick.change,
                    "change_pct": msg.tick.change_pct,
                    "volume": msg.tick.volume,
                    "bid": msg.tick.bid,
                    "ask": msg.tick.ask,
                    "timestamp": msg.tick.timestamp,
                }
            elif payload_field == "ohlcv":
                result["data"] = {
                    "ticker": msg.ohlcv.ticker,
                    "open": msg.ohlcv.open,
                    "high": msg.ohlcv.high,
                    "low": msg.ohlcv.low,
                    "close": msg.ohlcv.close,
                    "volume": msg.ohlcv.volume,
                    "timeframe": msg.ohlcv.timeframe,
                    "timestamp": msg.ohlcv.timestamp,
                }
            elif payload_field == "signal":
                direction_map = {0: "BUY", 1: "SELL", 2: "HOLD"}
                result["data"] = {
                    "ticker": msg.signal.ticker,
                    "direction": direction_map.get(msg.signal.direction, "HOLD"),
                    "confidence": msg.signal.confidence,
                    "target_price": msg.signal.target_price,
                    "stop_loss": msg.signal.stop_loss,
                    "reason": msg.signal.reason,
                    "timestamp": msg.signal.timestamp,
                }
            elif payload_field == "portfolio":
                result["data"] = {
                    "total_value": msg.portfolio.total_value,
                    "cash": msg.portfolio.cash,
                    "daily_pnl": msg.portfolio.daily_pnl,
                    "daily_pnl_pct": msg.portfolio.daily_pnl_pct,
                    "positions": [
                        {
                            "ticker": p.ticker,
                            "quantity": p.quantity,
                            "avg_price": p.avg_price,
                            "current_price": p.current_price,
                            "pnl": p.pnl,
                            "pnl_pct": p.pnl_pct,
                            "weight": p.weight,
                        }
                        for p in msg.portfolio.positions
                    ],
                    "timestamp": msg.portfolio.timestamp,
                }
            elif payload_field == "risk":
                result["data"] = {
                    "var_95": msg.risk.var_95,
                    "cvar_95": msg.risk.cvar_95,
                    "sharpe": msg.risk.sharpe,
                    "max_drawdown": msg.risk.max_drawdown,
                    "volatility": msg.risk.volatility,
                    "beta": msg.risk.beta,
                    "timestamp": msg.risk.timestamp,
                }
            elif payload_field == "regime":
                regime_map = {0: "BULL_TREND", 1: "BEAR_TREND", 2: "SIDEWAYS",
                              3: "HIGH_VOLATILITY", 4: "CRISIS"}
                result["data"] = {
                    "regime": regime_map.get(msg.regime.regime, "SIDEWAYS"),
                    "confidence": msg.regime.confidence,
                    "vix": msg.regime.vix,
                    "breadth": msg.regime.breadth,
                    "timestamp": msg.regime.timestamp,
                }
            elif payload_field == "event":
                type_map = {0: "KAP_ANNOUNCEMENT", 1: "NEWS", 2: "MACRO_DATA",
                            3: "EARNINGS", 4: "DIVIDEND", 5: "ANALYST_RATING"}
                result["data"] = {
                    "type": type_map.get(msg.event.type, "NEWS"),
                    "ticker": msg.event.ticker,
                    "title": msg.event.title,
                    "summary": msg.event.summary,
                    "sentiment": msg.event.sentiment,
                    "impact_score": msg.event.impact_score,
                    "timestamp": msg.event.timestamp,
                }
            elif payload_field == "alert":
                type_map = {0: "PRICE", 1: "VOLUME", 2: "ANOMALY", 3: "RISK", 4: "SIGNAL"}
                severity_map = {0: "INFO", 1: "WARNING", 2: "CRITICAL"}
                result["data"] = {
                    "type": type_map.get(msg.alert.type, "PRICE"),
                    "ticker": msg.alert.ticker,
                    "message": msg.alert.message,
                    "severity": severity_map.get(msg.alert.severity, "INFO"),
                    "value": msg.alert.value,
                    "threshold": msg.alert.threshold,
                    "timestamp": msg.alert.timestamp,
                }
            else:
                result["data"] = {}

            return result

        except Exception as e:
            logger.warning("Protobuf decode failed, trying fallback", error=str(e))
            return cls._fallback_decode(data)

    @classmethod
    def _type_name(cls, type_int: int) -> str:
        """MessageType enum → string."""
        names = {0: "tick", 1: "ohlcv", 2: "signal", 3: "portfolio",
                 4: "risk", 5: "regime", 6: "event", 7: "alert", 8: "heartbeat"}
        return names.get(type_int, "unknown")

    @classmethod
    def _fallback_encode(cls, msg_type: str, **kwargs) -> bytes:
        """Protobuf yoksa orjson fallback."""
        data = {"type": msg_type, "ts": int(time.time() * 1000), **kwargs}
        return orjson.dumps(data)

    @classmethod
    def _fallback_decode(cls, data: bytes) -> dict[str, Any]:
        """Protobuf decode başarısızsa orjson fallback."""
        try:
            return orjson.loads(data)
        except Exception:
            return {"type": "unknown", "raw": data.hex()[:100]}


class BinaryWebSocket:
    """Binary WebSocket sunucusu — Protobuf native.

    Tüm mesajlar Protobuf StreamMessage olarak kodlanır.
    Client'lar binaryType='arraybuffer' ile bağlanır.
    """

    def __init__(self):
        self._clients: set = set()
        self._running = False
        self._msg_handler: callable | None = None

    def on_message(self, handler: callable):
        """Mesaj handler'ı kaydet."""
        self._msg_handler = handler

    async def handler(self, websocket, path=None):
        """WebSocket bağlantı handler'ı."""
        self._clients.add(websocket)
        client_id = id(websocket)
        logger.info("Binary WebSocket client connected",
                     client_id=client_id,
                     protocol="protobuf" if HAS_PROTOBUF else "orjson-fallback")

        try:
            # Hoşgeldin mesajı
            welcome = ProtobufMessage.encode_heartbeat()
            await websocket.send(welcome)

            async for message in websocket:
                if isinstance(message, bytes):
                    decoded = ProtobufMessage.decode(message)
                    msg_type = decoded.get("type", "unknown")

                    if msg_type == "heartbeat":
                        # Heartbeat'e heartbeat ile cevap ver
                        await websocket.send(ProtobufMessage.encode_heartbeat())
                    elif self._msg_handler:
                        await self._msg_handler(decoded)
                    else:
                        logger.debug("Binary WS message received", type=msg_type)
                else:
                    # JSON fallback (eski istemciler)
                    try:
                        data = orjson.loads(message)
                        logger.debug("JSON fallback message", type=data.get("type"))
                    except Exception:
                        logger.warning("Caught Exception in handler", exc_info=True)
        except Exception as e:
            logger.debug("WebSocket client disconnected",
                         client_id=client_id, error=str(e))
        finally:
            self._clients.discard(websocket)

    async def broadcast_tick(self, ticker: str, price: float, change: float,
                             change_pct: float, volume: int, bid: float = 0,
                             ask: float = 0):
        """Tüm istemcilere fiyat yayınla (Protobuf binary)."""
        message = ProtobufMessage.encode_tick(
            ticker=ticker, price=price, change=change,
            change_pct=change_pct, volume=volume, bid=bid, ask=ask,
        )
        await self._broadcast_binary(message)

    async def broadcast_ohlcv(self, ticker: str, open_p: float, high: float,
                              low: float, close: float, volume: int,
                              timeframe: str = "1m"):
        """Tüm istemcilere OHLCV yayınla (Protobuf binary)."""
        message = ProtobufMessage.encode_ohlcv(
            ticker=ticker, open_p=open_p, high=high, low=low,
            close=close, volume=volume, timeframe=timeframe,
        )
        await self._broadcast_binary(message)

    async def broadcast_signal(self, ticker: str, direction: str,
                               confidence: float, target_price: float,
                               stop_loss: float, reason: str = ""):
        """Tüm istemcilere sinyal yayınla (Protobuf binary)."""
        message = ProtobufMessage.encode_signal(
            ticker=ticker, direction=direction, confidence=confidence,
            target_price=target_price, stop_loss=stop_loss, reason=reason,
        )
        await self._broadcast_binary(message)

    async def broadcast_portfolio(self, total_value: float, cash: float,
                                  daily_pnl: float, daily_pnl_pct: float,
                                  positions: list = None):
        """Tüm istemcilere portföy durumu yayınla (Protobuf binary)."""
        message = ProtobufMessage.encode_portfolio(
            total_value=total_value, cash=cash, daily_pnl=daily_pnl,
            daily_pnl_pct=daily_pnl_pct, positions=positions,
        )
        await self._broadcast_binary(message)

    async def broadcast_risk(self, var_95: float, cvar_95: float, sharpe: float,
                             max_drawdown: float, volatility: float, beta: float):
        """Tüm istemcilere risk metrikleri yayınla (Protobuf binary)."""
        message = ProtobufMessage.encode_risk(
            var_95=var_95, cvar_95=cvar_95, sharpe=sharpe,
            max_drawdown=max_drawdown, volatility=volatility, beta=beta,
        )
        await self._broadcast_binary(message)

    async def broadcast_regime(self, regime: str, confidence: float,
                               vix: float = 0, breadth: float = 0):
        """Tüm istemcilere piyasa rejimi yayınla (Protobuf binary)."""
        message = ProtobufMessage.encode_regime(
            regime=regime, confidence=confidence, vix=vix, breadth=breadth,
        )
        await self._broadcast_binary(message)

    async def broadcast_event(self, event_type: str, ticker: str, title: str,
                              summary: str = "", sentiment: float = 0,
                              impact_score: float = 0):
        """Tüm istemcilere olay yayınla (Protobuf binary)."""
        message = ProtobufMessage.encode_event(
            event_type=event_type, ticker=ticker, title=title,
            summary=summary, sentiment=sentiment, impact_score=impact_score,
        )
        await self._broadcast_binary(message)

    async def broadcast_alert(self, alert_type: str, ticker: str, message_text: str,
                              severity: str = "INFO", value: float = 0,
                              threshold: float = 0):
        """Tüm istemcilere alarm yayınla (Protobuf binary)."""
        message = ProtobufMessage.encode_alert(
            alert_type=alert_type, ticker=ticker, message=message_text,
            severity=severity, value=value, threshold=threshold,
        )
        await self._broadcast_binary(message)

    async def broadcast_json(self, data: dict[str, Any]):
        """JSON fallback — eski istemciler için."""
        message = orjson.dumps(data, default=str)
        await self._broadcast_binary(message)

    async def _broadcast_binary(self, message: bytes):
        """Binary mesajı tüm istemcilere gönder."""
        if not self._clients:
            return

        disconnected = set()
        for client in self._clients:
            try:
                await client.send(message)
            except Exception:
                disconnected.add(client)

        self._clients -= disconnected

    async def start(self, host: str = "0.0.0.0", port: int = 8765):
        """Binary WebSocket sunucusunu başlat."""
        if not HAS_WEBSOCKETS:
            logger.warning("websockets not installed, Binary WS disabled")
            return

        self._running = True
        logger.info("Binary WebSocket server starting",
                     host=host, port=port,
                     protocol="protobuf" if HAS_PROTOBUF else "orjson-fallback")

        async with websockets.serve(self.handler, host, port):
            while self._running:
                await asyncio.sleep(1)

    async def stop(self):
        """Sunucuyu durdur."""
        self._running = False
        for client in list(self._clients):
            try:
                await client.close()
            except Exception:
                logger.warning("Caught Exception in stop", exc_info=True)
        self._clients.clear()

    def get_stats(self) -> dict[str, Any]:
        """İstatistikler."""
        return {
            "clients": len(self._clients),
            "running": self._running,
            "protocol": "protobuf" if HAS_PROTOBUF else "orjson-fallback",
            "sequence": ProtobufMessage._sequence,
        }
