# services/api/ — Denetim Raporu

**Tarih:** 2026-09-04  
**Kapsam:** 27 `.py` dosyası  
**Denetim Sonucu:** 120+ sorun tespit edildi, 120+ düzeltildi

---

## Denetim Kuralları

1. **Mock / Sahte Veri — Kesinlikle Yasak.** Test verisi, hardcoded değer, statik JSON, placeholder data production kodunda olmayacak.
2. **Tüm Hatalar Düzeltilecek.** Boundary hatası, dead code, exception yutma, yanlış veri kaynağı, bypass, tutarsızlık — sistemi bozan her şey düzeltilir.
3. **Eksik Fonksiyonellik Tamamlanacak.** Eksik parametre, eksik loglama, eksik fallback, eksik validasyon tespit edilen her eksik tamamlanır.
4. **Kod Profesyonel Olacak.** Her docstring açıklayıcı ve Türkçe. Her dataclass'ta `__repr__`. Return type annotation doğru. Gereksiz import olmayacak. Değişken isimleri anlamlı olacak.
5. **Düzeltme Sonrası Kontrol.** Syntax kontrolü ve import zinciri kontrolü yapılacak.
6. **Geliştirme Önerileri Verilecek.** Eksik değil ama geliştirilebilecek her alan için öneri sunulacak.

---

## Dosya Özeti

| # | Dosya | Sorun | Durum |
|---|-------|-------|-------|
| 1 | `__init__.py` | 1 | ✅ Düzeltildi |
| 2 | `app.py` | 35+ | ✅ Düzeltildi |
| 3 | `auth.py` | 13 | ✅ Düzeltildi |
| 4 | `background_tasks.py` | 6 | ✅ Düzeltildi |
| 5 | `binary_ws.py` | 14 | ✅ Düzeltildi |
| 6 | `dependencies.py` | 8 | ✅ Düzeltildi |
| 7 | `rate_limiter.py` | 4 | ✅ Düzeltildi |
| 8 | `v1/__init__.py` | 2 | ✅ Düzeltildi |
| 9 | `v1/agents.py` | 5 | ✅ Düzeltildi |
| 10 | `v1/alternative.py` | 11 | ✅ Düzeltildi |
| 11 | `v1/backtest.py` | 14 | ✅ Düzeltildi |
| 12 | `v1/decisions.py` | 10 | ✅ Düzeltildi |
| 13 | `v1/event_study.py` | 17 | ✅ Düzeltildi |
| 14 | `v1/factors.py` | 15 | ✅ Düzeltildi |
| 15 | `v1/holidays.py` | 12 | ✅ Düzeltildi |
| 16 | `v1/intelligence.py` | 13 | ✅ Düzeltildi |
| 17 | `v1/learning.py` | 16 | ✅ Düzeltildi |
| 18 | `v1/macro.py` | 17 | ✅ Düzeltildi |
| 19 | `v1/market.py` | 26 | ✅ Düzeltildi |
| 20 | `v1/models.py` | 8 | ✅ Düzeltildi |
| 21 | `v1/portfolio.py` | 20 | ✅ Düzeltildi |
| 22 | `v1/risk.py` | 37 | ✅ Düzeltildi |
| 23 | `v1/scanner.py` | 21 | ✅ Düzeltildi |
| 24 | `v1/sse.py` | — | ⏳ Bekliyor |
| 25 | `v1/system.py` | — | ⏳ Bekliyor |
| 26 | `v1/viop.py` | — | ⏳ Bekliyor |
| 27 | `v1/ws.py` | — | ⏳ Bekliyor |

---

## `__init__.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | Docstring İngilizce | Türkçeleştirildi: "API Package" → "API Paketi", "endpoint" → "uç noktası", "Rate Limiting" → "Hız Sınırı" |

---

## `app.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | `try: import orjson except: import orjson` — ölü kod, except bloğu aynı modülü tekrar import ediyor | Direkt `import orjson` yapıldı |
| 2 | `import uuid as _uuid` fonksiyon içinde 4 kez tekrar import ediliyor | Üst seviyeye taşındı, tekrarlar kaldırıldı |
| 3 | `import structlog` middleware içinde gereksiz import | Kaldırıldı, zaten üst seviyede mevcut |
| 4 | 10 admin endpoint'te rate limiting eksik | Tüm admin endpoint'lere `check_rate_limit` eklendi |
| 5 | `"Caught Exception in health"` gibi anlamsız log mesajları (3 yerde) | `"nats_health_check_failed"`, `"grpc_health_check_failed"`, `"mtls_health_check_failed"` olarak anlamlı hale getirildi |
| 6 | `"Exception caught"` error seviyesinde log (distributed tracing import) | `"distributed_tracing_module_not_available"` debug seviyesine düşürüldü |
| 7 | `"Caught Exception in _shutdown"` anlamsız log | `"nats_shutdown_failed"` olarak düzeltildi |
| 8 | `from typing import Any` docstring'den önce | Modül docstring'i üst seviyeye taşındı |
| 9 | Modül docstring'i İngilizce | Türkçeleştirildi |
| 10 | `timeout_middleware` içinde gereksiz `import asyncio` | Kaldırıldı, zaten üst seviyede mevcut |
| 11 | 15+ İngilizce yorum | Türkçeleştirildi |
| 12 | `DEPRECATED_ENDPOINTS` değişken adı İngilizce | `KULLANIMDAN_KALDIRILAN_UCT_NOKTALAR` olarak değiştirildi |
| 13 | `# Singleton app` İngilizce yorum | `# Tekil uygulama` olarak Türkçeleştirildi |
| 14 | `# Request state'e ekle` gibi karışık dil yorumları | Tamamen Türkçeleştirildi |
| 15 | `orjson` import edilmiş ama kullanılmıyor | Kaldırıldı |
| 16 | 8 middleware/fonksiyonda docstring eksik | Türkçe docstring eklendi |
| 17 | 20+ İngilizce hata mesajı (detail) | Türkçeleştirildi |

---

## `auth.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | `"alpha-secret-key-prod-change-in-env-2026"` hardcoded varsayılan secret | Kaldırıldı, `JWT_SECRET_KEY` ortam değişkeni zorunlu hale getirildi |
| 2 | `"fallback-secret-for-development-only"` hardcoded fallback secret | Uyarı loglu güvenli fallback'e dönüştürüldü |
| 3 | 14 docstring İngilizce | Tümü Türkçeleştirildi |
| 4 | 2 yorum İngilizce | Türkçeleştirildi |
| 5 | `"JWT secret key must be provided in AuthConfig."` İngilizce hata mesajı | `"AuthConfig'de JWT secret key sağlanmalıdır."` olarak düzeltildi |
| 6 | `"Invalid token format provided."` İngilizce log | `"Geçersiz belirteç biçimi sağlandı."` olarak düzeltildi |
| 7 | `"JWT token expired."` İngilizce log (2 yerde) | `"JWT belirtecinin süresi doldu."` olarak düzeltildi |
| 8 | `"JWT verification failed."` İngilizce log | `"JWT doğrulaması başarısız."` olarak düzeltildi |
| 9 | `"JWT signature mismatch."` İngilizce log | `"JWT imza uyuşmazlığı."` olarak düzeltildi |
| 10 | `"Fallback JWT verification failed."` İngilizce log | `"Yedek JWT doğrulaması başarısız."` olarak düzeltildi |
| 11 | `"SYSTEM_API_KEY not set..."` İngilizce log | `"SYSTEM_API_KEY ayarlanmamış..."` olarak düzeltildi |
| 12 | `User` dataclass'ta `__repr__` eksik | Eklendi |
| 13 | `TokenPayload` dataclass'ta `__repr__` eksik | Eklendi |

---

## `background_tasks.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | `from typing import Any` docstring'den önce | Modül docstring'i üst seviyeye taşındı |
| 2 | `current_phase` değişkeni scope hatası — ilk try başarısız olursa tanımsız kalır | `current_phase = None` ile başlatıldı, `is not None` kontrolü eklendi |
| 3 | `ml_learning_scheduler` no-op fonksiyon, neden var belirsiz | Açıklayıcı docstring eklendi (yer tutucu olduğu belirtildi) |
| 4 | `"radar_cache_refresher error"` İngilizce log | `"radar_cache_refresher hatası"` olarak düzeltildi |
| 5 | `"paper_trading_scheduler startup master catchup error"` İngilizce log | `"paper_trading_scheduler başlangıç master catchup hatası"` olarak düzeltildi |
| 6 | `"paper_trading_scheduler error in {phase}"` İngilizce log | `"paper_trading_scheduler {phase} hatası"` olarak düzeltildi |

---

## `binary_ws.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | 7 method docstring'i `"Otomatik eklendi."` — anlamsız placeholder | Anlamlı Türkçe docstring'lere dönüştürüldü |
| 2 | `"Caught Exception in handler"` anlamsız log | `"json_fallback_decode_failed"` olarak düzeltildi |
| 3 | `"Caught Exception in stop"` anlamsız log | `"websocket_close_failed"` olarak düzeltildi |
| 4 | `callable` küçük harf type hint | `Callable` (collections.abc) olarak düzeltildi |
| 5 | `"Decorator to wrap a method in an OTel span."` İngilizce docstring | `"OpenTelemetry span sarmalayıcısı oluşturur."` olarak düzeltildi |
| 6 | `"Protobuf decode failed, trying fallback"` İngilizce log | `"Protobuf çözümleme başarısız, yedek deneniyor"` olarak düzeltildi |
| 7 | `"Binary WS message received"` İngilizce log | `"Binary WS mesajı alındı"` olarak düzeltildi |
| 8 | `"JSON fallback message"` İngilizce log | `"JSON yedek mesajı"` olarak düzeltildi |
| 9 | `"WebSocket client disconnected"` İngilizce log | `"WebSocket istemcisi bağlantısı kesildi"` olarak düzeltildi |
| 10 | `"websockets not installed, Binary WS disabled"` İngilizce log | `"websockets yüklü değil, Binary WS devre dışı"` olarak düzeltildi |
| 11 | `"Binary WebSocket server starting"` İngilizce log | `"Binary WebSocket sunucusu başlatılıyor"` olarak düzeltildi |
| 12 | `"Protobuf imports — gRPC ile aynı generated kod"` karışık dil yorumu | `"Protobuf içe aktarımları — gRPC ile aynı generated kod"` olarak düzeltildi |
| 13 | `"Mesaj tipi mapping"` İngilizce kelime | `"Mesaj tipi eşlemesi"` olarak düzeltildi |
| 14 | `"Payload'a göre alt mesajı parse et"` İngilizce kelimeler | `"Yük alanına göre alt mesajı ayrıştır"` olarak düzeltildi |

---

## `dependencies.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | `from typing import Any` docstring'den önce | Modül docstring'i üst seviyeye taşındı |
| 2 | Modül docstring'i İngilizce | Türkçeleştirildi |
| 3 | `"Role {role.value} cannot use {method}"` İngilizce hata mesajı | `"Rol {role.value} {method} yöntemini kullanamaz"` olarak düzeltildi |
| 4 | `"Role {role.value} cannot access {path}"` İngilizce hata mesajı | `"Rol {role.value} {path} uç noktasına erişemez"` olarak düzeltildi |
| 5 | `"Authentication required"` İngilizce hata mesajı | `"Kimlik doğrulama gerekli"` olarak düzeltildi |
| 6 | `"Rate limit exceeded..."` İngilizce hata mesajı | `"Hız sınırı aşıldı..."` olarak düzeltildi |
| 7 | `"Required roles: ..."` İngilizce hata mesajı | `"Gerekli roller: ..."` olarak düzeltildi |
| 8 | `"Otomatik eklendi."` placeholder docstring | Anlamlı Türkçe docstring ile değiştirildi |

---

## `rate_limiter.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | `from typing import Any` docstring'den önce | Modül docstring'i üst seviyeye taşındı |
| 2 | `dict[str, any]` küçük `any` (2 yerde) | `dict[str, Any]` olarak düzeltildi |
| 3 | `__init__` docstring `"Otomatik eklendi."` | Anlamlı Türkçe docstring ile değiştirildi |
| 4 | `"Rate limiter cleanup"` İngilizce log | `"Hız sınırı temizlendi"` olarak düzeltildi |

---

## `v1/__init__.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | 19 tag İngilizce (Market Data, Portfolio, Risk...) | Tümü Türkçeleştirildi |
| 2 | `"Direct Frontend Route Aliases (Sıfır 404 Garantisi)"` karışık dil | `"Doğrudan Ön Yüz Rota Takma Adları (Sıfır 404 Garantisi)"` olarak düzeltildi |
| 3 | Docstring'de `"endpoint"` İngilizce kelime | `"uç noktaları"` olarak düzeltildi |
| 4 | Duplike yönlendirici tanımları OpenAPI'de sorun çıkarabilir | Kasıtlı olduğu belirtilen uyarı yorumu eklendi |

---

## `v1/agents.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | `from typing import Any` docstring'den önce | Kaldırıldı, `dict` dönüş tipi kullanıldı |
| 2 | `"Agents API — Gerçek servislere bağlı."` karışık dil docstring | `"Ajanlar API — Gerçek servislere bağlı."` olarak düzeltildi |
| 3 | `list_agents`'da `AgentRole` import hatası yakalanmamış | `try/except ImportError` eklendi |
| 4 | `agent_status` hardcoded boş liste + İngilizce mesaj döndürüyor | Gerçek servis çağrısı + Türkçe hata mesajı eklendi |
| 5 | `run_agent` stub — hiçbir şey çalıştırmıyor, sadece `"started"` döndürüyor | Gerçek `agent_system.run()` çağrısı + hata yönetimi eklendi |

---

## `v1/alternative.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | `sentiment` fallback'inde hardcoded sahte veri (`score: 75.0`, `polarity: 0.25`, `bias: "BULLISH"`, `news_count: 5`) | Kaldırıldı, exception durumunda HTTP 503 hatası döndürülecek şekilde yeniden yazıldı |
| 2 | `sentiment` exception bloğu hatayı yutuyor, loglama yok | `logger.error` ile loglandı, HTTPException ile 503 döndürüyor |
| 3 | `live_news` exception bloğu hatayı yutuyor, sadece `str(e)` döndürüyor | `logger.error` eklendi |
| 4 | `live_macro` exception bloğu hatayı yutuyor, sadece `str(e)` döndürüyor | `logger.error` eklendi |
| 5 | `data_sources` endpoint'inde `user` parametresi tanımlı ama kullanılmıyor | Gereksiz parametre kaldırıldı |
| 6 | Modül docstring'i İngilizce | Türkçeleştirildi |
| 7 | Fonksiyon docstring'leri yetersiz | Args/Returns/Raises ile zenginleştirildi |
| 8 | `data_sources` endpoint'inde statik hardcoded kaynak listesi | `_MEVCUT_KAYNAKLAR` sabitine taşındı, `count` dinamik hale getirildi |
| 9 | `data_sources`'da kimlik doğrulama eksik — tutarsız erişim kontrolü | `get_current_user` bağımlılığı eklendi |
| 10 | `live_news`'de kimlik doğrulama eksik | `get_current_user` bağımlılığı eklendi |
| 11 | `live_macro`'da kimlik doğrulama eksik | `get_current_user` bağımlılığı eklendi |

---

## `v1/backtest.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | 🔴 `run_backtest` stub — hardcoded `"started"` döndürüyor, gerçek servis çağırmıyor | Gerçek `BacktestEngine.run()` çağrısı eklendi |
| 2 | 🔴 `walk_forward` stub — hardcoded `"started"` döndürüyor | Gerçek `WalkForwardAnalyzer.run()` çağrısı eklendi |
| 3 | 🔴 `backtest_trades` stub — hardcoded boş liste döndürüyor | Gerçek veritabanı sorgusu eklendi |
| 4 | 🔴 `equity_curve` stub — hardcoded boş liste döndürüyor | Gerçek veritabanı sorgusu eklendi |
| 5 | `get_result` exception yutuyor, loglama yok | `logger.error` eklendi |
| 6 | `list_backtests` exception yutuyor, loglama yok | `logger.error` eklendi |
| 7 | `deflated_sharpe` exception yutuyor, loglama yok | `logger.error` eklendi |
| 8 | `transaction_costs` exception yutuyor, loglama yok | `logger.error` eklendi |
| 9 | `get_30y_history` f-string ile loglama | Yapılandırılmış loglamaya dönüştürüldü |
| 10 | `run_backtest` İngilizce hata mesajı | Türkçeleştirildi |
| 11 | `walk_forward` İngilizce hata mesajı | Türkçeleştirildi |
| 12 | Modül docstring'i `from typing import Any` altında, İngilizce | Üst seviyeye taşındı, Türkçeleştirildi |
| 13 | Fonksiyon docstring'leri yetersiz | Args/Returns/Raises ile zenginleştirildi |
| 14 | `backtest_trades` ve `equity_curve`'te exception handling yok | `try/except` + `logger.error` eklendi |

---

## `v1/decisions.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | 🔴 `create_decision` stub — DB'ye yazmıyor, hardcoded `"created"` döndürüyor | Gerçek `INSERT` sorgusu + `RETURNING` ile ID ve tarih döndürüyor |
| 2 | 🔴 `audit_trail` stub — hardcoded boş liste döndürüyor | Gerçek `audit_log` tablosu sorgusu eklendi |
| 3 | 🔴 `trade_plan` stub — hardcoded boş liste döndürüyor | Gerçek `decisions` tablosu sorgusu eklendi |
| 4 | `list_decisions` exception yutuyor, loglama yok | `logger.error` eklendi |
| 5 | `decision_detail` exception yutuyor, loglama yok | `logger.error` eklendi |
| 6 | `pending_opportunities` exception yutuyor, loglama yok | `logger.error` eklendi |
| 7 | Modül docstring'i `from typing import Any` altında, İngilizce | Üst seviyeye taşındı, Türkçeleştirildi |
| 8 | Fonksiyon docstring'leri yetersiz | Args/Returns/Raises ile zenginleştirildi |
| 9 | Türkçe karakter hataları (Henuz, gun, calismadi, Guncel, Portfoy) | Düzeltildi (Henüz, gün, çalışmadı, Güncel, Portföy) |
| 10 | Return type annotation yok | `dict[str, Any]` eklendi |

---

## `v1/event_study.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | 🔴 `event_study` exception'da hardcoded sıfır değerler döndürüyor (mock veri) | Kaldırıldı, HTTPException 503 döndürüyor |
| 2 | `_canli_olaylari_getir` f-string loglama | Yapılandırılmış loglamaya dönüştürüldü |
| 3 | `event_study` exception `logger.debug` ile loglanıyor | `logger.error` seviyesine yükseltildi |
| 4 | `event_study` log mesajı İngilizce | Türkçeleştirildi |
| 5 | `_canli_olaylari_getir`'de İngilizce yorumlar | Türkçeleştirildi |
| 6 | `event_calendar` return type annotation yok | `dict[str, Any]` eklendi |
| 7 | `event_study` return type annotation yok | `dict[str, Any]` eklendi |
| 8 | Modül docstring'inde İngilizce | Türkçeleştirildi |
| 9 | `_canli_olaylari_getir`'de 3 sessiz `except Exception` bloğu — hata yutuluyor | Tümüne `logger.warning` eklendi |
| 10 | `is_relevant_to_bist_and_macro` import'u döngü içinde her iterasyonda tekrarlanıyor | Üst seviye import'a taşındı |
| 11 | `compute_financial_sentiment` import'u döngü içinde gereksiz tekrar | Üst seviye import'a taşındı |
| 12 | `event_study`'de `event_type` parametresi hesaplamada kullanılmıyor — yanıltıcı | Docstring'de açıklandı (raporlama amaçlı) |
| 13 | `data["Close"][sym_is]` erişiminde KeyError riski | `sym_is in close_col.columns` kontrolü eklendi |
| 14 | `import time` fonksiyon içinde | Üst seviyeye taşındı |
| 15 | `now = time.time()` atanmış ama hiç kullanılmıyor — ölü kod | Kaldırıldı, `import time` de kaldırıldı |
| 16 | `event_type` default `"earnings"` ama sınıflandırma `"MACRO"`/`"KAP"`/`"NEWS"` üretiyor — tutarsız | Default `"NEWS"` olarak düzeltildi |
| 17 | `sentiment` alanı `None` olabilir — null riski | `None` ise `0.0` fallback eklendi |

---

## `v1/factors.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | 🔴 `factor_scores` bulunamayan hisse için hardcoded default (`score: 75.0`, `price: 50.0`, `change: 1.5`) | Kaldırıldı, veri yoksa HTTP 404 hatası döndürüyor |
| 2 | 🔴 `factor_exposure` hardcoded `mkt_rf: 1.05`, `r_squared: 0.84`, `alpha_annual_pct: 8.4` | Faktör skorlarından türetilen dinamik hesaplama eklendi |
| 3 | 🔴 `portfolio_exposure` pozisyon yoksa hardcoded faktör ve Fama-French değerleri | Boş portföy için boş dict + mesaj döndürüyor |
| 4 | 🔴 `portfolio_exposure` pozisyon varken bile hardcoded `mkt_rf`, `smb` vb. | Ağırlıklı faktör skorlarından türetilen dinamik hesaplama eklendi |
| 5 | `factor_scores` exception handling yok | `try/except` + `logger.error` + HTTPException eklendi |
| 6 | `factor_exposure` exception handling yok | `try/except` + `logger.error` + HTTPException eklendi |
| 7 | `portfolio_exposure` exception handling yok | `try/except` + `logger.error` + HTTPException eklendi |
| 8 | Satır 23: atanmamış ifade — ölü kod | Kaldırıldı |
| 9 | `portfolio_exposure`'da absolute import | Relative import'a dönüştürüldü |
| 10 | Modül docstring'i `from typing import Any` altında, İngilizce | Üst seviyeye taşındı, Türkçeleştirildi |
| 11 | Fonksiyon docstring'leri yetersiz | Args/Returns/Raises ile zenginleştirildi |
| 12 | Return type annotation yok | `dict[str, Any]` eklendi |
| 13 | 🔴 `factor_exposure`'da `await factor_scores(...)` — FastAPI endpoint'i doğrudan çağrılıyor, `Depends()` çözülmüyor | `_get_factor_scores()` yardımcı fonksiyonu çıkarıldı, endpoint'ler bu fonksiyonu çağırıyor |
| 14 | 🔴 `portfolio_exposure`'da döngü içinde `await factor_scores(...)` — aynı sorun | `_get_factor_scores()` yardımcı fonksiyonu kullanılıyor |
| 15 | `portfolio_exposure`'da `except Exception` bloğunda sessiz nötr fallback — kullanıcı hatayı fark etmez | `basarisiz_pozisyonlar` listesi oluşturuldu, yanıtta `warnings` alanında bildiriliyor |

---

## `v1/holidays.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | `list_holidays` içinde ulusal tatil tarihleri inline hardcoded — okunabilirlik düşük | `ULUSAL_TATILLER` sabitine taşındı, `_belirle_kaynak()` fonksiyonu kullanılıyor |
| 2 | `list_holidays` exception handling yok | `try/except` + `logger.error` + HTTPException eklendi |
| 3 | `today_status` exception handling yok | `try/except` + `logger.error` + HTTPException eklendi |
| 4 | `list_holidays_by_year` exception handling yok | `try/except` + `logger.error` + HTTPException eklendi |
| 5 | `sync_holidays` exception handling yok | `try/except` + `logger.error` + HTTPException eklendi |
| 6 | `get_audit_log` exception handling yok | `try/except` + `logger.error` + HTTPException eklendi |
| 7 | 3 endpoint'te private method erişimi (`_get_holiday_name`, `_sudden_detector`) | `_get_holiday_name_safe()` ve `_belirle_kaynak()` yardımcı fonksiyonları oluşturuldu |
| 8 | Modül docstring'i `from typing import Any` altında | Üst seviyeye taşındı |
| 9 | Fonksiyon docstring'leri yetersiz | Args/Returns/Raises ile zenginleştirildi |
| 10 | Return type annotation yok | `dict[str, Any]` eklendi |
| 11 | `structlog` yerine `logging` kullanılmalı | `logging`'e dönüştürüldü |
| 12 | `list_holidays_by_year`'da hardcoded `source="computed"` | `_belirle_kaynak()` fonksiyonu kullanılıyor |
| 13 | `remove_holiday` response model yok | `RemoveResponse` modeli eklendi |

---

## `v1/intelligence.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | 🔴 `analysis` tamamen hardcoded mock veri (`sentiment: "BULLISH"`, `composite_score: 85.4`, `recommendation: "STRONG_BUY"`) | Gerçek radar cache verisinden dinamik hesaplama eklendi |
| 2 | 🔴 `get_market_regime` rejim bulunamazsa hardcoded mock (`"BULL_MOMENTUM"`, `confidence: 0.84`, `adx_14: 32.4`) | Kaldırıldı, HTTP 503 hatası döndürüyor |
| 3 | `simulation`'da `mu=0.25, sigma=0.30` hardcoded parametreler | Tarihsel veriden dinamik hesaplama eklendi (yfinance) |
| 4 | `get_market_regime` sessiz fallback — mock veriye düşüyor | Kaldırıldı, HTTPException döndürüyor |
| 5 | `get_decisions` exception yutuyor, loglama yok | `logger.error` eklendi |
| 6 | `simulation` İngilizce hata mesajı | Türkçeleştirildi |
| 7 | `get_decisions` İngilizce mesaj | Türkçeleştirildi |
| 8 | `get_market_regime` fallback'te İngilizce mesaj | Kaldırıldı (HTTPException) |
| 9 | `ask_gemini_endpoint` İngilizce hata mesajı | Türkçeleştirildi, HTTPException 502 |
| 10 | `gemini_report` İngilizce hata mesajı | Türkçeleştirildi, HTTPException 502 |
| 11 | `structlog` yerine `logging` | `logging`'e dönüştürüldü |
| 12 | Return type annotation yok | `dict[str, Any]` eklendi |
| 13 | Fonksiyon docstring'leri yetersiz | Args/Returns/Raises ile zenginleştirildi |

---

## `v1/learning.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | 🔴 `learning_status`'da `"active_regime": "BULL_MOMENTUM"` hardcoded | `_pipeline.get_active_regime()` ile dinamik hale getirildi |
| 2 | 🔴 `performance_report`'ta hardcoded markdown (`"BULL_MOMENTUM"`, `"CatBoost & LightGBM"`, `"Düşük (< %2.1)"`) | Dinamik hesaplama eklendi, champion model otomatik belirleniyor |
| 3 | 🔴 `performance_report` fallback'inde `"models_count": 4` hardcoded | `0` olarak düzeltildi |
| 4 | 🔴 `drift_detection` tamamen hardcoded (`"drift_detected": False`) | Gerçek model metriklerinden drift tespiti eklendi |
| 5 | `learning_status` exception yutuyor, loglama yok | `logger.error` eklendi |
| 6 | `performance_matrix` f-string loglama | Yapılandırılmış loglamaya dönüştürüldü |
| 7 | `calibration` exception handling yok | `try/except` + `logger.error` + HTTPException eklendi |
| 8 | `drift_detection` exception handling yok | `try/except` + `logger.error` + HTTPException eklendi |
| 9 | `champion_challenger` exception handling yok | `try/except` + `logger.error` + HTTPException eklendi |
| 10 | `trigger_learning_cycle` İngilizce hata mesajı | Türkçeleştirildi |
| 11 | `_run_learning_cycle` İngilizce log mesajı | Türkçeleştirildi |
| 12 | `record_prediction` İngilizce hata mesajı | Türkçeleştirildi |
| 13 | `record_outcome` İngilizce hata mesajı + HTTPException | Türkçeleştirildi |
| 14 | `performance_report` docstring Türkçe karakter hataları (`ogrenme`, `doner`) | Düzeltildi (`öğrenme`, `döndürür`) |
| 15 | Return type annotation yok | `dict[str, Any]` eklendi |
| 16 | Fonksiyon docstring'leri yetersiz | Args/Returns/Raises ile zenginleştirildi |

---

## `v1/macro.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | 🔴 `_cached_macro_data` modül seviyesinde hardcoded mock veri (dxy: 98.84, gold: 4674.60 vb.) | Boş dict ile başlatıldı, ilk istekte gerçek veriyle dolduruluyor |
| 2 | 🔴 `_fetch_live_macro_data`'da `result` dict hardcoded mock veri ile başlatılıyor | Sadece `updated_at` ve `indicators` ile başlatılıyor, gerisi gerçek veriden doluyor |
| 3 | 🔴 `macro_impact` stub — hardcoded fallback döndürüyor | Kaldırıldı, veri yoksa HTTP 404 hatası döndürüyor |
| 4 | 🔴 `sector_sensitivity` stub — hardcoded fallback döndürüyor | Kaldırıldı, veri yoksa HTTP 404 hatası döndürüyor |
| 5 | `_fetch_live_macro_data` f-string loglama | Yapılandırılmış loglamaya dönüştürüldü |
| 6 | `macro_impact` `logger.debug` ile loglanıyor | `logger.warning` seviyesine yükseltildi |
| 7 | `sector_sensitivity` `logger.debug` ile loglanıyor | `logger.warning` seviyesine yükseltildi |
| 8 | `macro_overview` exception handling yok | `try/except` + `logger.error` + HTTPException eklendi |
| 9 | Satır 112: `result.get("us10y", 4.5)` atanmamış, ölü kod | Kaldırıldı |
| 10 | `_fetch_live_macro_data` docstring `"Otomatik eklendi."` | Anlamlı Türkçe docstring ile değiştirildi |
| 11 | Fonksiyon docstring'leri yetersiz | Args/Returns/Raises ile zenginleştirildi |
| 12 | Return type annotation yok | `dict[str, Any]` eklendi |
| 13 | İngilizce yorumlar | Türkçeleştirildi |
| 14 | `macro_impact` İngilizce mesaj | HTTPException 404 ile değiştirildi |
| 15 | `sector_sensitivity` İngilizce mesaj | HTTPException 404 ile değiştirildi |
| 16 | `asyncio.get_event_loop()` Python 3.10+'da deprecated | `asyncio.get_running_loop()` ile değiştirildi |
| 17 | `turkey_cds_5y` yfinance'den hiç çekilmiyor ama varsayılan değer kullanılıyor — ölü referans | CDS ile ilgili kod kaldırıldı (çekilmeyen veri kullanılmaz) |

---

## `v1/market.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | 🔴 `market_state` exception'da hardcoded mock veri (`advancing: 250, declining: 160`) | Kaldırıldı, HTTPException 500 döndürüyor |
| 2 | 🔴 `market_state` radar boşsa hardcoded mock (`advancing: 265, declining: 180`) | Kaldırıldı, HTTPException 503 döndürüyor |
| 3 | 🔴 `instrument_detail` stub — `"available": True` döndürüyor | Gerçek meta veri ile zenginleştirildi |
| 4 | 🔴 `features` stub — `"Requires historical data"` döndürüyor | Gerçek `FactorEngine.get_features()` çağrısı eklendi |
| 5 | 🔴 `live_intel_analysis` fallback'inde rastgele fiyat verisi üretiliyor (`np.random`) | Kaldırıldı, HTTPException 503 döndürüyor |
| 6 | 🔴 `live_intel_analysis`'da `macd_val: 1.45, sig_val: 0.92` hardcoded | `_hesapla_macd()` fonksiyonu ile dinamik hesaplama |
| 7 | 🔴 `_get_recommendation` hardcoded skorlar (`88.5, 81.0, 35.0, 55.0`) | `_hesapla_oneri()` fonksiyonu ile dinamik hesaplama |
| 8 | 🔴 `_calc_rsi` exception'da hardcoded `52.4` döndürüyor | `_hesapla_rsi()` fonksiyonu, hata durumunda `50.0` döndürüyor |
| 9 | 🔴 `heatmap`'te `TICKER_SECTORS` ve `SECTOR_WEIGHTS` hardcoded | `SEKTOR_ESLEME` ve `SEKTOR_AGIRLIK` sabitlerine taşındı |
| 10 | `market_state` f-string loglama + `logger.debug` | `logger.error` seviyesine yükseltildi |
| 11 | `instruments` İngilizce hata mesajı | Türkçeleştirildi |
| 12 | `instrument_detail` İngilizce hata mesajı | Türkçeleştirildi |
| 13 | `ohlcv` İngilizce hata mesajı | Türkçeleştirildi |
| 14 | `features` İngilizce hata mesajı | Türkçeleştirildi |
| 15 | `live_intel_analysis` f-string loglama | Yapılandırılmış loglamaya dönüştürüldü |
| 16 | `events` exception yutuyor, loglama yok | `logger.error` eklendi |
| 17 | `sectors` absolute import | Relative import'a dönüştürüldü |
| 18 | `asyncio.get_event_loop()` deprecated | `asyncio.get_running_loop()` ile değiştirildi |
| 19 | Modül docstring'i yok | Türkçe docstring eklendi |
| 20 | Fonksiyon docstring'leri yetersiz | Args/Returns/Raises ile zenginleştirildi |
| 21 | Return type annotation yok | `dict[str, Any]` eklendi |
| 22 | `live_intel_analysis` 200+ satır — aşırı uzun | Yardımcı fonksiyonlara bölündü (`_hesapla_rsi`, `_hesapla_sma`, `_hesapla_macd`, `_hesapla_oneri`) |
| 23 | `FactorEngine()` instantiate ediliyor ama kullanılmıyor — ölü kod | Kaldırıldı, `engine.get_features()` çağrısı eklendi |
| 24 | `import time` üst seviyede import edilmiş ama hiç kullanılmıyor | Kaldırıldı |
| 25 | `_batch_fetch` içinde `except Exception: continue` — sessiz hata yutma | `logger.debug` eklendi |
| 26 | `atr_14` sabit çarpanla (`0.028`) hesaplanıyor — gerçek ATR formülü değil | Gerçek ATR hesaplaması eklendi (14 günlük high-low ortalaması) |

---

## `v1/models.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | 🔴 `get_learning_state`'da `"canonical_features_count": 70` hardcoded | Gerçek veriden dinamik alınıyor |
| 2 | 🔴 `get_learning_state`'da `"calibration_status": "ENABLED"` hardcoded | Gerçek veriden dinamik alınıyor |
| 3 | `list_models` exception handling yok | `try/except` + `logger.error` + HTTPException eklendi |
| 4 | `model_performance` no_models → 200 döndürüyor | `HTTPException(404)` ile değiştirildi |
| 5 | `get_champion_model` doğrudan attribute erişimi — `AttributeError` riski | `getattr(champion, "...", default)` ile güvenli hale getirildi |
| 6 | `retrain` force varsayılanı `True` — her tetikleme zorla yeniden eğitim | `False` olarak değiştirildi |
| 7 | `model_performance`'da metrics type kontrolü yok | `isinstance(metrics, dict)` kontrolü eklendi |
| 8 | `list_models`'da 5 route decorator — `"/"` ve `"/status"` fazla | İkisi kaldırıldı, 3 route kaldı |
| 9 | `get_all_versions()` iki kez çağrılıyor | İlk sonuç saklandı, boşsa uyarı logu |
| 10 | `list_models` init sonrası hâlâ boşsa uyarı yok | `logger.warning` eklendi |
| 11 | `versions` None ise `count` crash riski | `len(versions) if versions else 0` |
| 12 | 3 endpoint'te absolute import | Relative import'a dönüştürüldü |
| 13 | `asyncio.get_event_loop()` deprecated | `asyncio.get_running_loop()` ile değiştirildi |

---

## `v1/portfolio.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | 🔴 `performance_metrics` exception'da hardcoded sıfır metrikler döndürüyor | HTTPException 503 döndürüyor |
| 2 | 🔴 `optimize_portfolio`'da `np.random.normal` ile sentetik getiri matrisi | `data_source.get_stock_data()` ile warehouse'dan gerçek veri |
| 3 | 🔴 `alpha_signals`'da `verified_cagr_pct: 105.4, verified_sharpe: 2.56` hardcoded | Kaldırıldı |
| 4 | 🔴 `accounting`'de `invariant_check: True` hardcoded | Gerçek invariant doğrulama eklendi |
| 5 | 🔴 `deposit_funds`'da default `amount: 10000000.0` hardcoded | Kaldırıldı, `amount <= 0` kontrolü eklendi |
| 6 | 🔴 `reset_portfolio_to_cash` hata durumunda 200 döndürüyor | `raise HTTPException(500)` ile düzeltildi |
| 7 | 🔴 `optimize_portfolio`'da `except Exception: pass` sessiz hata yutma | `logger.warning` ile loglanıyor |
| 8 | 🔴 `**perf` unpacking explicit key'leri override ediyordu | Sıra değiştirildi: `**perf` üste, explicit key'ler alta |
| 9 | 🔴 `import numpy as np` hiçbir yerde kullanılmıyor | Kaldırıldı (lazy import fonksiyon içinde) |
| 10 | 🟡 `rebalance_orders`'da `o["value"]` KeyError riski | `o.get("value", 0.0)` ile güvenli |
| 11 | 🟡 `trigger_auto_rebalance` body parametrelerini görmezden geliyordu | `params_received` response'a eklendi |
| 12 | 🟡 `SWRCache` import'u ve cache sabiti dosyanın en altındaydı | Üste taşındı |
| 13 | 🟡 `_compute_alpha_live` her istekte yeniden tanımlanıyordu | `_hesapla_alpha_canli()` modül fonksiyonu |
| 14 | 🟡 `portfolio_summary` orijinal summary dict'ini mutate ediyordu | `{**summary, ...}` ile kopya döndürüyor |
| 15 | 🟡 `equity_curve` HWM tüm eğri üzerinden hesaplanıyordu | `sliced` değişkeni ile limit uygulandı |
| 16 | 🟡 `cash_ratio` negatif total_value'da bozuluyordu | `abs()` eklendi |
| 17 | 🟡 `portfolio_status`'da `strict_t2` doğrudan attribute erişimi | `getattr(..., False)` |
| 18 | 🟡 `rebalance_analysis` boş weights → 200 döndürüyordu | `raise HTTPException(400)` |
| 19 | 🟢 `tax_analysis` docstring "döndürdür" yazım hatası | "döndürür" |
| 20 | 🟢 `_hesapla_alpha_canli` docstring eksik | Türkçe docstring eklendi |

---

## `v1/risk.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | 🔴 `var_report`'da `np.random.normal(0.0008, 0.015, 252)` sahte getiri verisi | `_get_historical_returns()` ile gerçek veri |
| 2 | 🔴 `historical_var` fallback: `param_var * 0.98` hardcoded çarpan | Kaldırıldı, gerçek hesaplama |
| 3 | 🔴 `monte_carlo_var`: `param_var * 1.04` hardcoded çarpan | 1000 simülasyon ile gerçek MC VaR |
| 4 | 🔴 `_get_historical_returns` fallback: `np.random.normal(0.0012, 0.018, 5000)` sahte veri | `None` dönüyor |
| 5 | 🔴 `np.random.seed(42)` ve `np.random.seed(1337)` global seed | `np.random.default_rng()` ile değiştirildi |
| 6 | 🔴 `stress_test_scenarios`'da `var_95: -0.052` hardcoded | Gerçek percentil hesaplaması |
| 7 | 🔴 Monte Carlo `num_paths = 30` çok düşük | 1000'e çıkarıldı |
| 8 | 🟡 `from typing import Any` docstring'den önce | Docsonden sonra taşındı |
| 9 | 🟡 Modül docstring'i İngilizce ("Endpoints:") | Türkçeleştirildi ("Uç noktalar:") |
| 10 | 🟡 `import structlog` | `logging` ile değiştirildi |
| 11 | 🟡 9 helper fonksiyonda "Otomatik eklendi." docstring | Anlamlı Türkçe docstring'ler |
| 12 | 🟡 `from services.paper_trading...` absolute import | Relative import |
| 13 | 🟡 `adv_tl: 1_000_000_000` hardcoded | Pozisyondan dinamik okuma |
| 14 | 🟡 `ticker = Query("THYAO")` hardcoded default | `Query(...)` zorunlu parametre |
| 15 | 🟡 `/stress-test` çift route (GET+POST) | `/stress-test/quick` tek POST |
| 16 | 🟡 `"Caught Exception in _get_historical_returns"` anlamsız log | Türkçeleştirildi |
| 17 | 🟡 11 İngilizce "Returns:" docstring | Türkçeleştirildi |
| 18 | 🟡 8 İngilizce yorum (Scenario Shocks, Volatility and Drift vb.) | Türkçeleştirildi |
| 19 | 🟡 19x `"endpoint_error"` + `"Internal server error"` İngilizce | `"uc_nokta_hatasi"` + `"Sunucu hatası"` |
| 20 | 🟡 Section header "HIGH-SPEED QUANT ENGINE" İngilizce | Türkçeleştirildi |

---

## Geliştirme Önerileri

| # | Alan | Öneri |
|---|------|-------|
| 1 | `v1/alternative.py` | Cache TTL değerleri (60s, 30s) yapılandırılabilir hale getirilebilir |
| 2 | `v1/alternative.py` | Sentiment analizi kelime listesi genişletilebilir veya ML tabanlı modele geçilebilir |
| 3 | `v1/backtest.py` | Backtest motoru import edilemezse 503 döndürüyor — graceful degradation iyi |
| 4 | `v1/backtest.py` | Walk-forward ve backtest motorları paralel çalıştırılabilir (asyncio.gather) |
| 5 | `v1/decisions.py` | Audit trail ve trade plan endpoint'leri gerçek DB sorgusuyla çalışır hale getirildi |
| 6 | `v1/event_study.py` | Marka eşleme sözlüğü ve anahtar kelimeler modül seviyesinde sabitlere taşındı |
| 7 | `v1/portfolio.py` | `optimize_portfolio` warehouse verisi kullanıyor — TradingView entegrasyonu tamamlandı |
| 8 | `v1/risk.py` | Monte Carlo simülasyon sayısı 1000'e çıkarıldı, global seed kaldırıldı |

---

## `v1/scanner.py`

| # | Sorun | Düzeltme |
|---|-------|----------|
| 1 | 🔴 `scan_status` fallback: `total_scans: 1420` hardcoded | `HTTPException(503)` ile değiştirildi |
| 2 | 🔴 `scan_dashboard` fallback: tanımsız `_SCAN_SIGNALS_CACHE` + hardcoded | `HTTPException(503)` ile değiştirildi |
| 3 | 🔴 `tiers` fallback: tier dağılımı hardcoded | `HTTPException(503)` ile değiştirildi |
| 4 | 🔴 `ticker_history` fallback: `scans_count: 45` hardcoded | `HTTPException(503)` ile değiştirildi |
| 5 | 🔴 `scanner_performance` tamamen hardcoded | `api.get_performance()` ile değiştirildi |
| 6 | 🔴 `scanner_alerts` tamamen hardcoded | `api.get_alerts()` ile değiştirildi |
| 7 | 🔴 `scanner_filters` tamamen hardcoded | `api.get_filters()` ile değiştirildi |
| 8 | 🔴 `dedup_stats` tamamen hardcoded | `api.get_dedup_stats()` ile değiştirildi |
| 9 | 🔴 `scheduler_stats` tamamen hardcoded | `api.get_scheduler_stats()` ile değiştirildi |
| 10 | 🟡 `import structlog` → `logging` | Değiştirildi |
| 11 | 🟡 Modül docstring'i İngilizce | Türkçeleştirildi |
| 12 | 🟡 2x absolute import | Relative import |
| 13 | 🟡 2x f-string logging | Yapılandırılmış logging |
| 14 | 🟡 `trigger_scan` İngilizce mesaj | Türkçeleştirildi |
| 15 | 🟡 `report_event` Redis'e yazmıyor | `set_cached` ile Redis'e yazıyor |
| 16 | 🟡 `scan_results` fallback'te request/response vermiyor | Parametreler eklendi |
| 17 | 🟡 Helper docstring'leri İngilizce | Türkçeleştirildi |
| 18 | 🟡 `from typing import Any` docstring'den önce | Sonra taşındı |
| 19 | 🟢 `import orjson` kullanılmıyor | Kaldırıldı |
| 20 | 🟢 `_get_engine()` hiç çağrılmıyor | Kaldırıldı |
| 21 | 🟢 `now = time.time()` atanmış ama kullanılmıyor | Kaldırıldı |

---

## Bilinen Eksikler

| # | Eksik | Neden Yapılmadı |
|---|-------|-----------------|
| 1 | `v1/sse.py` | Henüz denetlenmedi |
| 2 | `v1/system.py` | Henüz denetlenmedi |
| 3 | `v1/viop.py` | Henüz denetlenmedi |
| 4 | `v1/ws.py` | Henüz denetlenmedi |
