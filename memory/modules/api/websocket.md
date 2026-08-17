# api/websocket

**Dosya:** `services/api/websocket.py`
**Satır:** 242

## Açıklama

ALPHA BIST — WebSocket Real-time Server v1.0

Gerçek zamanlı güncelleme:
- /ws/market — anlık fiyatlar
- /ws/opportunities — yeni fırsatlar
- /ws/portfolio — P&L güncelleme
- /ws/risk — risk alertleri
- /ws/system — servis durumu

Kullanım:
  ws_server = WebSocketServer()
  await ws_server.start(port=8765)

## Sınıflar (2)

- `WebSocketConnection`
- `WebSocketServer`

## Fonksiyonlar (3)

- `__init__()`
- `__init__()`
- `get_stats()`

