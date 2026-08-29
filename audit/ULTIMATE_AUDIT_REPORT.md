# ALPHA BIST — Nihai Kapsamli Sistem Audit Raporu

> **Olusturulma Tarihi:** 2026-08-29 14:16:13
> **Motor:** Ultimate Audit Engine v2.0 (16 Boyut, 0 Token)
> **Taranan Dosya:** 844  |  **Taranan Satir:** 245,931
> **Sistem Saglik Puani:** **47 / 100**
> **Tarama Suresi:** 3.27 saniye

---

## 1. Genel Bulgular Ozeti

| Seviye | Adet | Etki |
|---|---|---|
| KRITIK | **120** | Sistem cokebilir, data butunlugu tehlikede, guvenlik acigi |
| YUKSEK | **571** | Performans kaybi, hata maskeleme, mimari ihlal |
| ORTA   | **1722** | Kod kalitesi, standart ihlali |
| DUSUK  | **1452** | Dokumantasyon, bicimlendirme |
| **TOPLAM** | **3865** | |

## 2. 16 Boyut Bazli Analiz

| Boyut | Alan | Bulunan |
|---|---|---|
| B01 | Sozdizimi & Dosya Butunlugu | 94 (X KRITIK) |
| B02 | Bos/Yarim Birakilan Kod | 26 (X KRITIK) |
| B03 | Fail-Closed & Hata Yonetimi | 64 (X KRITIK) |
| B04 | Async Butunlugu | 3 (X KRITIK) |
| B05 | Teknoloji Yigini Uyumu | 47 (! YUKSEK) |
| B06 | Guvenlik & Sir Tespiti | 502 (X KRITIK) |
| B07 | Kod Kalitesi & Standartlar | 6 (X KRITIK) |
| B08 | Tip Guvenligi | 2151 (~ ORTA) |
| B09 | PIT & Quant Dogrulugu | 1 (! YUKSEK) |
| B10 | Mimari & Katman Uyumu | 1 (X KRITIK) |
| B11 | Servis Saglik & Init | 1 (~ ORTA) |
| B12 | Docker & .env Uyumu | 25 (X KRITIK) |
| B13 | Loglama Standardi | 86 (~ ORTA) |
| B14 | Kaynak Sizintisi | 8 (! YUKSEK) |
| B15 | Test Kapsami | 8 (! YUKSEK) |
| B16 | Dokumantasyon Butunlugu | 842 (~ ORTA) |

## 3. Kategori Bazli Bulgu Tablosu

| Kategori | Adet | Seviye | Aciklama |
|---|---|---|---|
| `MISSING_RETURN_TYPE` | **1610** | MEDIUM | Return tip annotation eksik |
| `MISSING_DOCSTRING` | **842** | LOW | Public fonksiyon docstring eksik |
| `MISSING_PARAM_TYPE` | **541** | LOW | Parametre tip annotation eksik |
| `INSECURE_DEFAULT` | **501** | HIGH | Guvensiz varsayilan deger |
| `PRINT_IN_PROD` | **86** | MEDIUM | print() (structlog ile loglanmali) |
| `CRLF_LINE_ENDINGS` | **69** | LOW | Windows CRLF satir sonu |
| `EXCEPT_PASS` | **58** | CRITICAL | except X: pass — hata maskeleme |
| `PANDAS_IN_PROD` | **44** | HIGH | Uretim servisinde pandas (Polars zorunlu) |
| `ENV_VAR_MISSING_FROM_DOTENV` | **20** | MEDIUM | .env.example'da var, .env'de yok |
| `SYNTAX_ERROR` | **13** | CRITICAL | Bozuk Python sozdizimi |
| `EMPTY_FUNC_PASS` | **12** | CRITICAL | Sadece 'pass' olan fonksiyon |
| `BOM_CHAR` | **11** | CRITICAL | UTF-8 BOM karakteri — Python'i cokertir |
| `EMPTY_FUNC_ELLIPSIS` | **9** | CRITICAL | Sadece '...' olan fonksiyon (stub) |
| `OPEN_WITHOUT_CONTEXT_MANAGER` | **8** | HIGH | open() with blogu olmadan |
| `MISSING_TEST_FOR_CRITICAL_MODULE` | **8** | HIGH | Kritik modul icin test yok |
| `TODO_MARKER` | **5** | MEDIUM | Tamamlanmamis TODO/FIXME isareti |
| `EMPTY_FUNC_NIE` | **5** | CRITICAL | NotImplementedError ile bos birakilan |
| `INSECURE_ENV_VALUE` | **5** | CRITICAL | .env'de guvensiz deger |
| `BARE_EXCEPT` | **4** | HIGH | Bare except: (tum istisnalari yakalar) |
| `SYNC_REQUESTS_IN_PROD` | **3** | HIGH | Uretim servisinde senkron requests |
| `BARE_EXCEPT_PASS` | **2** | CRITICAL | except: pass — tam sessiz yutma |
| `ASYNC_BLOCKING_SLEEP` | **2** | HIGH | async icinde time.sleep() |
| `HARDCODED_SECRET` | **1** | CRITICAL | Hardcoded sifre/anahtar |
| `NULL_BYTES` | **1** | CRITICAL | Null byte — SyntaxError'a yol acar |
| `ASYNC_BLOCKING_REQUESTS` | **1** | CRITICAL | async icinde senkron requests |
| `POTENTIAL_LEAKAGE_SHIFT` | **1** | HIGH | Negatif shift — lookahead bias riski |
| `FAKE_ASSERT_OR_TRUE` | **1** | CRITICAL | assert ... or True — hileli test |
| `CIRCULAR_IMPORT` | **1** | CRITICAL | Dongusel bagimlilık (A <-> B) |
| `MISSING_INIT` | **1** | MEDIUM | __init__.py eksik modül dizini |

## 4. Kritik & Yuksek Oncelikli Duzeltme Listesi (691 adet)

| Dosya | Satir | Boyut | Kategori | Sorun | Kod |
|---|---|---|---|---|---|
| `.env` | `1` | B12 | **INSECURE_ENV_VALUE** | 'POSTGRES_PASSWORD' insecure varsayılan değer içeriyor: 'alpha_secure_pass_123' | `` |
| `.env` | `1` | B12 | **INSECURE_ENV_VALUE** | 'REPLICATION_PASSWORD' insecure varsayılan değer içeriyor: 'alpha_secure_pass_123' | `` |
| `.env` | `1` | B12 | **INSECURE_ENV_VALUE** | 'CLICKHOUSE_USER' insecure varsayılan değer içeriyor: 'default' | `` |
| `.env` | `1` | B12 | **INSECURE_ENV_VALUE** | 'CLICKHOUSE_PASSWORD' insecure varsayılan değer içeriyor: 'alpha_secure_pass_123' | `` |
| `.env` | `1` | B12 | **INSECURE_ENV_VALUE** | 'REDIS_PASSWORD' insecure varsayılan değer içeriyor: 'alpha_secure_pass_123' | `` |
| `ml/models.py` | `257` | B03 | **EXCEPT_PASS** | Hata tamamen yutulmuş (except: pass) — fail-closed ihlali, sistem kör! | `except Exception:` |
| `mock_redis.py` | `1` | B01 | **BOM_CHAR** | Dosya UTF-8 BOM (\ufeff) karakteriyle başlıyor — Python'ı çökertir | `﻿import json import redis from datetime import` |
| `mock_redis.py` | `1` | B01 | **SYNTAX_ERROR** | SyntaxError: invalid non-printable character U+FEFF | `﻿import json` |
| `mock_redis.py` | `5` | B06 | **HARDCODED_SECRET** | Muhtemel hardcoded kimlik bilgisi: 'alpha_se...' | `r = redis.Redis(host='redis', port=6379, db=0, password='alpha_secure_pass_123')` |
| `scratch/engine.py` | `463` | B03 | **EXCEPT_PASS** | Hata tamamen yutulmuş (except: pass) — fail-closed ihlali, sistem kör! | `except ImportError:` |
| `scratch/engine.py` | `470` | B03 | **EXCEPT_PASS** | Hata tamamen yutulmuş (except: pass) — fail-closed ihlali, sistem kör! | `except ImportError:` |
| `scratch/engine.py` | `477` | B03 | **EXCEPT_PASS** | Hata tamamen yutulmuş (except: pass) — fail-closed ihlali, sistem kör! | `except ImportError:` |
| `scratch/engine.py` | `484` | B03 | **EXCEPT_PASS** | Hata tamamen yutulmuş (except: pass) — fail-closed ihlali, sistem kör! | `except ImportError:` |
| `scratch/engine.py` | `491` | B03 | **EXCEPT_PASS** | Hata tamamen yutulmuş (except: pass) — fail-closed ihlali, sistem kör! | `except ImportError:` |
| `scratch/engine.py` | `498` | B03 | **EXCEPT_PASS** | Hata tamamen yutulmuş (except: pass) — fail-closed ihlali, sistem kör! | `except ImportError:` |
| `scratch/engine.py` | `505` | B03 | **EXCEPT_PASS** | Hata tamamen yutulmuş (except: pass) — fail-closed ihlali, sistem kör! | `except ImportError:` |
| `scratch/main_backup.py` | `1` | B01 | **NULL_BYTES** | Dosya null byte içeriyor — SyntaxError'a yol açar | `` |
| `scratch/main_backup.py` | `1` | B01 | **SYNTAX_ERROR** | SyntaxError: source code string cannot contain null bytes | `` |
| `scratch/massive_454_backtest.py` | `1` | B01 | **BOM_CHAR** | Dosya UTF-8 BOM (\ufeff) karakteriyle başlıyor — Python'ı çökertir | `﻿import os import sys import gc import json impo` |
| `scratch/massive_454_backtest.py` | `1` | B01 | **SYNTAX_ERROR** | SyntaxError: invalid non-printable character U+FEFF | `﻿import os` |
| `scratch/run_backtest_extract.py` | `427` | B01 | **SYNTAX_ERROR** | SyntaxError: expected an indented block after function definition on line 427 | `def run_paper_trading(start_date: str, end_date: str):` |
| `scripts/align_risk_parity_targets.py` | `19` | B03 | **EXCEPT_PASS** | Hata tamamen yutulmuş (except: pass) — fail-closed ihlali, sistem kör! | `except Exception:` |
| `scripts/audit_timescaledb_health.py` | `250` | B03 | **EXCEPT_PASS** | Hata tamamen yutulmuş (except: pass) — fail-closed ihlali, sistem kör! | `except Exception:` |
| `scripts/audit_timescaledb_health.py` | `284` | B03 | **EXCEPT_PASS** | Hata tamamen yutulmuş (except: pass) — fail-closed ihlali, sistem kör! | `except Exception:` |
| `scripts/audit_timescaledb_health.py` | `311` | B03 | **EXCEPT_PASS** | Hata tamamen yutulmuş (except: pass) — fail-closed ihlali, sistem kör! | `except Exception:` |
| `scripts/audit_timescaledb_health.py` | `331` | B03 | **EXCEPT_PASS** | Hata tamamen yutulmuş (except: pass) — fail-closed ihlali, sistem kör! | `except Exception:` |
| `scripts/audit_timescaledb_health.py` | `357` | B03 | **EXCEPT_PASS** | Hata tamamen yutulmuş (except: pass) — fail-closed ihlali, sistem kör! | `except Exception:` |
| `scripts/deep_comprehensive_audit.py` | `42` | B03 | **EXCEPT_PASS** | Hata tamamen yutulmuş (except: pass) — fail-closed ihlali, sistem kör! | `except Exception:` |
| `scripts/run_final_locked_blind_test.py` | `19` | B03 | **EXCEPT_PASS** | Hata tamamen yutulmuş (except: pass) — fail-closed ihlali, sistem kör! | `except Exception:` |
| `scripts/run_mass_metric_optimization.py` | `22` | B03 | **EXCEPT_PASS** | Hata tamamen yutulmuş (except: pass) — fail-closed ihlali, sistem kör! | `except Exception:` |
| `scripts/run_rigorous_quant_audit.py` | `20` | B03 | **EXCEPT_PASS** | Hata tamamen yutulmuş (except: pass) — fail-closed ihlali, sistem kör! | `except Exception:` |
| `scripts/test_risk_parity_audit.py` | `20` | B03 | **EXCEPT_PASS** | Hata tamamen yutulmuş (except: pass) — fail-closed ihlali, sistem kör! | `except Exception:` |
| `scripts/train_bist_ensemble.py` | `19` | B03 | **EXCEPT_PASS** | Hata tamamen yutulmuş (except: pass) — fail-closed ihlali, sistem kör! | `except Exception:` |
| `scripts/ultimate_audit_engine.py` | `44` | B03 | **EXCEPT_PASS** | Hata tamamen yutulmuş (except: pass) — fail-closed ihlali, sistem kör! | `except Exception:` |
| `services/agents/llm_client.py` | `448` | B03 | **EXCEPT_PASS** | Hata tamamen yutulmuş (except: pass) — fail-closed ihlali, sistem kör! | `except orjson.JSONDecodeError:` |
| `services/agents/llm_client.py` | `456` | B03 | **EXCEPT_PASS** | Hata tamamen yutulmuş (except: pass) — fail-closed ihlali, sistem kör! | `except orjson.JSONDecodeError:` |
| `services/agents/llm_client.py` | `464` | B03 | **EXCEPT_PASS** | Hata tamamen yutulmuş (except: pass) — fail-closed ihlali, sistem kör! | `except orjson.JSONDecodeError:` |
| `services/api/app.py` | `260` | B03 | **EXCEPT_PASS** | Hata tamamen yutulmuş (except: pass) — fail-closed ihlali, sistem kör! | `except ImportError:` |
| `services/api/v1/market.py` | `571` | B04 | **ASYNC_BLOCKING_REQUESTS** | async fonksiyon içinde senkron 'requests.post()' — event loop kilitlenir! httpx.AsyncClient kullan | `resp = requests.post(url, json=payload, headers=headers, timeout=2.0)` |
| `services/backtest/persistence.py` | `63` | B03 | **EXCEPT_PASS** | Hata tamamen yutulmuş (except: pass) — fail-closed ihlali, sistem kör! | `except Exception:` |
| `services/backtest/walk_forward_engine.py` | `117` | B02 | **EMPTY_FUNC_ELLIPSIS** | 'fit' yalnızca '...' içeriyor — stub/placeholder bırakılmış | `def fit(self, X: np.ndarray, y: np.ndarray, **kwargs) -> None: ...` |
| `services/backtest/walk_forward_engine.py` | `118` | B02 | **EMPTY_FUNC_ELLIPSIS** | 'predict' yalnızca '...' içeriyor — stub/placeholder bırakılmış | `def predict(self, X: np.ndarray) -> np.ndarray: ...` |
| `services/backtest/walk_forward_engine.py` | `119` | B02 | **EMPTY_FUNC_ELLIPSIS** | 'get_feature_importance' yalnızca '...' içeriyor — stub/placeholder bırakılmış | `def get_feature_importance(self) -> dict[str, float]: ...` |
| `services/backtest/walk_forward_engine.py` | `120` | B02 | **EMPTY_FUNC_ELLIPSIS** | 'get_params' yalnızca '...' içeriyor — stub/placeholder bırakılmış | `def get_params(self) -> dict[str, Any]: ...` |
| `services/backtest/walk_forward_engine.py` | `126` | B02 | **EMPTY_FUNC_ELLIPSIS** | 'compute_features' yalnızca '...' içeriyor — stub/placeholder bırakılmış | `def compute_features(` |
| `services/backtest/walk_forward_engine.py` | `476` | B03 | **EXCEPT_PASS** | Hata tamamen yutulmuş (except: pass) — fail-closed ihlali, sistem kör! | `except Exception:` |
| `services/backtest/walk_forward_engine.py` | `484` | B03 | **EXCEPT_PASS** | Hata tamamen yutulmuş (except: pass) — fail-closed ihlali, sistem kör! | `except Exception:` |
| `services/backtest/walk_forward_engine.py` | `946` | B03 | **EXCEPT_PASS** | Hata tamamen yutulmuş (except: pass) — fail-closed ihlali, sistem kör! | `except ImportError:` |
| `services/backtest/walk_forward_engine.py` | `1183` | B03 | **EXCEPT_PASS** | Hata tamamen yutulmuş (except: pass) — fail-closed ihlali, sistem kör! | `except Exception:` |
| `services/backtest/walk_forward_engine.py` | `1212` | B03 | **EXCEPT_PASS** | Hata tamamen yutulmuş (except: pass) — fail-closed ihlali, sistem kör! | `except ImportError:` |
| `services/backtest/walk_forward_engine.py` | `1334` | B03 | **EXCEPT_PASS** | Hata tamamen yutulmuş (except: pass) — fail-closed ihlali, sistem kör! | `except (ValueError, TypeError):` |
| `services/backtest/walk_forward_engine.py` | `1722` | B03 | **EXCEPT_PASS** | Hata tamamen yutulmuş (except: pass) — fail-closed ihlali, sistem kör! | `except (IndexError, KeyError, TypeError, ValueError):` |
| `services/backtest/walk_forward_engine.py` | `1986` | B03 | **EXCEPT_PASS** | Hata tamamen yutulmuş (except: pass) — fail-closed ihlali, sistem kör! | `except (ImportError, Exception):` |
| `services/backtest/walk_forward_engine.py` | `2119` | B03 | **EXCEPT_PASS** | Hata tamamen yutulmuş (except: pass) — fail-closed ihlali, sistem kör! | `except Exception:` |
| `services/backtest/walk_forward_engine.py` | `2324` | B03 | **EXCEPT_PASS** | Hata tamamen yutulmuş (except: pass) — fail-closed ihlali, sistem kör! | `except Exception:` |
| `services/backtest/walk_forward_engine.py` | `2350` | B03 | **EXCEPT_PASS** | Hata tamamen yutulmuş (except: pass) — fail-closed ihlali, sistem kör! | `except Exception:` |
| `services/core/alerting.py` | `240` | B02 | **EMPTY_FUNC_ELLIPSIS** | 'send' yalnızca '...' içeriyor — stub/placeholder bırakılmış | `async def send(self, alert: Alert) -> bool: ...` |
| `services/core/alerting.py` | `241` | B02 | **EMPTY_FUNC_ELLIPSIS** | 'name' yalnızca '...' içeriyor — stub/placeholder bırakılmış | `def name(self) -> str: ...` |
| `services/core/alerting.py` | `242` | B02 | **EMPTY_FUNC_ELLIPSIS** | 'min_severity' yalnızca '...' içeriyor — stub/placeholder bırakılmış | `def min_severity(self) -> str: ...` |
| `services/core/alerting.py` | `243` | B02 | **EMPTY_FUNC_ELLIPSIS** | 'close' yalnızca '...' içeriyor — stub/placeholder bırakılmış | `async def close(self) -> None: ...` |
| `services/core/alerting.py` | `271` | B02 | **EMPTY_FUNC_PASS** | 'close' yalnızca 'pass' içeriyor — tamamlanmamış implementasyon | `async def close(self) -> None:` |
| `services/core/alerting.py` | `484` | B02 | **EMPTY_FUNC_PASS** | 'close' yalnızca 'pass' içeriyor — tamamlanmamış implementasyon | `async def close(self) -> None:` |
| `services/core/alerting.py` | `526` | B03 | **EXCEPT_PASS** | Hata tamamen yutulmuş (except: pass) — fail-closed ihlali, sistem kör! | `except Exception:` |
| `services/core/alerting.py` | `672` | B03 | **EXCEPT_PASS** | Hata tamamen yutulmuş (except: pass) — fail-closed ihlali, sistem kör! | `except RuntimeError:` |
| `services/core/alpha_engine.py` | `57` | B03 | **EXCEPT_PASS** | Hata tamamen yutulmuş (except: pass) — fail-closed ihlali, sistem kör! | `except Exception:` |
| `services/core/broker.py` | `63` | B02 | **EMPTY_FUNC_NIE** | 'submit_order' yalnızca NotImplementedError fırlatıyor — eksik implementasyon | `def submit_order(self, order: Order) -> Order:` |
| `services/core/broker.py` | `66` | B02 | **EMPTY_FUNC_NIE** | 'cancel_order' yalnızca NotImplementedError fırlatıyor — eksik implementasyon | `def cancel_order(self, order_id: str) -> bool:` |
| `services/core/broker.py` | `69` | B02 | **EMPTY_FUNC_NIE** | 'get_order_status' yalnızca NotImplementedError fırlatıyor — eksik implementasyon | `def get_order_status(self, order_id: str) -> Order \| None:` |
| `services/core/broker.py` | `72` | B02 | **EMPTY_FUNC_NIE** | 'get_positions' yalnızca NotImplementedError fırlatıyor — eksik implementasyon | `def get_positions(self) -> dict[str, Any]:` |
| `services/core/broker.py` | `75` | B02 | **EMPTY_FUNC_NIE** | 'is_connected' yalnızca NotImplementedError fırlatıyor — eksik implementasyon | `def is_connected(self) -> bool:` |
| `services/core/circuit_breaker.py` | `89` | B03 | **EXCEPT_PASS** | Hata tamamen yutulmuş (except: pass) — fail-closed ihlali, sistem kör! | `except Exception:` |
| `services/core/connectivity.py` | `173` | B03 | **EXCEPT_PASS** | Hata tamamen yutulmuş (except: pass) — fail-closed ihlali, sistem kör! | `except asyncio.CancelledError:` |
| `services/core/data_quality.py` | `507` | B03 | **EXCEPT_PASS** | Hata tamamen yutulmuş (except: pass) — fail-closed ihlali, sistem kör! | `except Exception:` |
| `services/core/database.py` | `708` | B03 | **EXCEPT_PASS** | Hata tamamen yutulmuş (except: pass) — fail-closed ihlali, sistem kör! | `except Exception:` |
| `services/core/duckdb_store.py` | `216` | B03 | **EXCEPT_PASS** | Hata tamamen yutulmuş (except: pass) — fail-closed ihlali, sistem kör! | `except (ValueError, OSError):` |
| `services/core/observability.py` | `143` | B02 | **EMPTY_FUNC_PASS** | '__init__' yalnızca 'pass' içeriyor — tamamlanmamış implementasyon | `def __init__(self):` |
| `services/core/observability.py` | `221` | B03 | **EXCEPT_PASS** | Hata tamamen yutulmuş (except: pass) — fail-closed ihlali, sistem kör! | `except Exception:` |
| `services/core/state_store.py` | `83` | B02 | **EMPTY_FUNC_PASS** | 'commit' yalnızca 'pass' içeriyor — tamamlanmamış implementasyon | `def commit(self):` |
| `services/core/state_store.py` | `86` | B02 | **EMPTY_FUNC_PASS** | 'close' yalnızca 'pass' içeriyor — tamamlanmamış implementasyon | `def close(self):` |
| `services/features/doc_generator.py` | `43` | B02 | **EMPTY_FUNC_PASS** | '__init__' yalnızca 'pass' içeriyor — tamamlanmamış implementasyon | `def __init__(self):` |
| `services/grpc/client.py` | `64` | B03 | **EXCEPT_PASS** | Hata tamamen yutulmuş (except: pass) — fail-closed ihlali, sistem kör! | `except ImportError:` |
| `services/grpc/server.py` | `59` | B03 | **EXCEPT_PASS** | Hata tamamen yutulmuş (except: pass) — fail-closed ihlali, sistem kör! | `except (ImportError, Exception):` |
| `services/institutional_backtest.py` | `125` | B03 | **BARE_EXCEPT_PASS** | Hata tamamen yutulmuş (except: pass) — fail-closed ihlali, sistem kör! | `except:` |
| `services/learning/alpha_engine_v2.py` | `1` | B01 | **BOM_CHAR** | Dosya UTF-8 BOM (\ufeff) karakteriyle başlıyor — Python'ı çökertir | `﻿""" import structlog logger = structlog.get_l` |
| `services/learning/alpha_engine_v2.py` | `1` | B01 | **SYNTAX_ERROR** | SyntaxError: invalid non-printable character U+FEFF | `﻿"""` |
| `services/learning/alpha_hunt.py` | `1` | B01 | **BOM_CHAR** | Dosya UTF-8 BOM (\ufeff) karakteriyle başlıyor — Python'ı çökertir | `﻿""" import structlog logger = structlog.get_l` |
| `services/learning/alpha_hunt.py` | `1` | B01 | **SYNTAX_ERROR** | SyntaxError: invalid non-printable character U+FEFF | `﻿"""` |
| `services/learning/continuous_learning.py` | `1` | B10 | **CIRCULAR_IMPORT** | Döngüsel bağımlılık: 'services/learning/continuous_learning.py' ↔ 'services/learning/super_intelligence.py' birbirini import ediyor! | `` |
| `services/learning/model_memory_store.py` | `38` | B02 | **EMPTY_FUNC_PASS** | 'commit' yalnızca 'pass' içeriyor — tamamlanmamış implementasyon | `def commit(self):` |
| `services/learning/model_memory_store.py` | `40` | B02 | **EMPTY_FUNC_PASS** | 'close' yalnızca 'pass' içeriyor — tamamlanmamış implementasyon | `def close(self):` |
| `services/learning/model_memory_store.py` | `44` | B02 | **EMPTY_FUNC_PASS** | '__exit__' yalnızca 'pass' içeriyor — tamamlanmamış implementasyon | `def __exit__(self, *args):` |
| `services/learning/outcome_tracker.py` | `90` | B03 | **EXCEPT_PASS** | Hata tamamen yutulmuş (except: pass) — fail-closed ihlali, sistem kör! | `except Exception:` |
| `services/learning/phase21_alpha_orthogonality.py` | `130` | B03 | **EXCEPT_PASS** | Hata tamamen yutulmuş (except: pass) — fail-closed ihlali, sistem kör! | `except Exception as e:` |
| `services/learning/phase29_statistical_arbitrage.py` | `1` | B01 | **BOM_CHAR** | Dosya UTF-8 BOM (\ufeff) karakteriyle başlıyor — Python'ı çökertir | `﻿"""FAZ 29 v2 - Duzeltilmis PnL hesabi (getiri b` |
| `services/learning/phase29_statistical_arbitrage.py` | `1` | B01 | **SYNTAX_ERROR** | SyntaxError: invalid non-printable character U+FEFF | `﻿"""FAZ 29 v2 - Duzeltilmis PnL hesabi (getiri bazli)"""` |
| `services/learning/phase30_walkforward.py` | `1` | B01 | **BOM_CHAR** | Dosya UTF-8 BOM (\ufeff) karakteriyle başlıyor — Python'ı çökertir | `﻿""" import structlog logger = structlog.get_l` |
| `services/learning/phase30_walkforward.py` | `1` | B01 | **SYNTAX_ERROR** | SyntaxError: invalid non-printable character U+FEFF | `﻿"""` |
| `services/learning/real_bist_walkforward_backtest.py` | `241` | B03 | **EXCEPT_PASS** | Hata tamamen yutulmuş (except: pass) — fail-closed ihlali, sistem kör! | `except Exception as e:` |
| `services/learning/utils/shap_helpers.py` | `605` | B03 | **EXCEPT_PASS** | Hata tamamen yutulmuş (except: pass) — fail-closed ihlali, sistem kör! | `except Exception:` |
| `services/massive_454_backtest.py` | `106` | B03 | **BARE_EXCEPT_PASS** | Hata tamamen yutulmuş (except: pass) — fail-closed ihlali, sistem kör! | `except:` |
| `services/ml/calibration_enhanced.py` | `149` | B03 | **EXCEPT_PASS** | Hata tamamen yutulmuş (except: pass) — fail-closed ihlali, sistem kör! | `except Exception:` |
| `services/ml/calibration_enhanced.py` | `156` | B03 | **EXCEPT_PASS** | Hata tamamen yutulmuş (except: pass) — fail-closed ihlali, sistem kör! | `except Exception:` |
| `services/nats/client.py` | `187` | B03 | **EXCEPT_PASS** | Hata tamamen yutulmuş (except: pass) — fail-closed ihlali, sistem kör! | `except Exception:` |
| `services/nats/client.py` | `258` | B03 | **EXCEPT_PASS** | Hata tamamen yutulmuş (except: pass) — fail-closed ihlali, sistem kör! | `except Exception:` |
| `services/nats/client.py` | `360` | B03 | **EXCEPT_PASS** | Hata tamamen yutulmuş (except: pass) — fail-closed ihlali, sistem kör! | `except (ImportError, LookupError):` |
| `services/nats/client.py` | `378` | B03 | **EXCEPT_PASS** | Hata tamamen yutulmuş (except: pass) — fail-closed ihlali, sistem kör! | `except (ImportError, LookupError):` |
| `services/tasks/queue.py` | `186` | B02 | **EMPTY_FUNC_PASS** | 'update_state' yalnızca 'pass' içeriyor — tamamlanmamış implementasyon | `def update_state(self, state=None, meta=None):` |
| `services/test_engine2.py` | `1` | B01 | **BOM_CHAR** | Dosya UTF-8 BOM (\ufeff) karakteriyle başlıyor — Python'ı çökertir | `﻿import asyncio from services.core.alpha_engine` |
| `services/test_engine2.py` | `1` | B01 | **SYNTAX_ERROR** | SyntaxError: invalid non-printable character U+FEFF | `﻿import asyncio` |
| `test_engine.py` | `1` | B01 | **BOM_CHAR** | Dosya UTF-8 BOM (\ufeff) karakteriyle başlıyor — Python'ı çökertir | `﻿import pandas as pd import yfinance as yf fro` |
| `test_engine.py` | `1` | B01 | **SYNTAX_ERROR** | SyntaxError: invalid non-printable character U+FEFF | `﻿import pandas as pd` |
| `test_engine2.py` | `1` | B01 | **BOM_CHAR** | Dosya UTF-8 BOM (\ufeff) karakteriyle başlıyor — Python'ı çökertir | `﻿import asyncio from services.core.alpha_engine` |
| `test_engine2.py` | `1` | B01 | **SYNTAX_ERROR** | SyntaxError: invalid non-printable character U+FEFF | `﻿import asyncio` |
| `test_len.py` | `1` | B01 | **BOM_CHAR** | Dosya UTF-8 BOM (\ufeff) karakteriyle başlıyor — Python'ı çökertir | `﻿import pandas as pd import yfinance as yf fro` |
| `test_len.py` | `1` | B01 | **SYNTAX_ERROR** | SyntaxError: invalid non-printable character U+FEFF | `﻿import pandas as pd` |
| `test_providers_live.py` | `1` | B01 | **BOM_CHAR** | Dosya UTF-8 BOM (\ufeff) karakteriyle başlıyor — Python'ı çökertir | `﻿import asyncio import time  async def run_al` |
| `test_providers_live.py` | `1` | B01 | **SYNTAX_ERROR** | SyntaxError: invalid non-printable character U+FEFF | `﻿import asyncio` |
| `tests/test_celery_queue.py` | `118` | B07 | **FAKE_ASSERT_OR_TRUE** | Hileli test: 'assert ... or True' — her zaman geçer, hiçbir şeyi doğrulamaz! | `assert mock_dlq_push.called or True` |
| `tests/test_policy_resilience.py` | `467` | B02 | **EMPTY_FUNC_PASS** | 'execute' yalnızca 'pass' içeriyor — tamamlanmamış implementasyon | `def execute(self, *args):` |
| `tests/test_policy_resilience.py` | `473` | B02 | **EMPTY_FUNC_PASS** | 'rollback' yalnızca 'pass' içeriyor — tamamlanmamış implementasyon | `def rollback(self):` |
| `benchmarks/tech_benchmarks.py` | `60` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'test' | `"test": "JSON Serialization (ORJSON vs json)",` |
| `benchmarks/tech_benchmarks.py` | `122` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'test' | `"test": "DataFrame Processing (Polars vs Pandas)",` |
| `benchmarks/tech_benchmarks.py` | `130` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'test' | `return {"test": "DataFrame Processing", "error": str(e)}` |
| `benchmarks/tech_benchmarks.py` | `157` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'test' | `results = {"test": "ML Training (LightGBM vs CatBoost vs XGBoost)", "models": {}` |
| `benchmarks/tech_benchmarks.py` | `209` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'test' | `return {"test": "ML Training", "error": str(e)}` |
| `mock_redis.py` | `5` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'alpha_secure_pass_123' | `r = redis.Redis(host='redis', port=6379, db=0, password='alpha_secure_pass_123')` |
| `scratch/audit_generator.py` | `83` | B03 | **BARE_EXCEPT** | Bare 'except:' kullanılmış — KeyboardInterrupt dahil her şeyi yakalar, maskeleme riski | `except:` |
| `scratch/debug_engine.py` | `9` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'Test' | `res = backtest_engine.run_backtest("Test", signals, price_data)` |
| `scratch/engine.py` | `170` | B14 | **OPEN_WITHOUT_CONTEXT_MANAGER** | open() çağrısı 'with' bloğu olmadan yapılmış — dosya kapanmayabilir (kaynak sızıntısı) | `trades_file = open(trades_csv_path, 'w', newline='', encoding='utf-8')` |
| `scratch/engine.py` | `171` | B14 | **OPEN_WITHOUT_CONTEXT_MANAGER** | open() çağrısı 'with' bloğu olmadan yapılmış — dosya kapanmayabilir (kaynak sızıntısı) | `daily_file = open(daily_csv_path, 'w', newline='', encoding='utf-8')` |
| `scratch/generate_folds.py` | `12` | B03 | **BARE_EXCEPT** | Bare 'except:' kullanılmış — KeyboardInterrupt dahil her şeyi yakalar, maskeleme riski | `except:` |
| `scratch/patch_continuous.py` | `52` | B14 | **OPEN_WITHOUT_CONTEXT_MANAGER** | open() çağrısı 'with' bloğu olmadan yapılmış — dosya kapanmayabilir (kaynak sızıntısı) | `trades_file = open(trades_csv_path, 'w', newline='', encoding='utf-8')` |
| `scratch/patch_continuous.py` | `53` | B14 | **OPEN_WITHOUT_CONTEXT_MANAGER** | open() çağrısı 'with' bloğu olmadan yapılmış — dosya kapanmayabilir (kaynak sızıntısı) | `daily_file = open(daily_csv_path, 'w', newline='', encoding='utf-8')` |
| `scratch/patch_engine_canonical.py` | `45` | B14 | **OPEN_WITHOUT_CONTEXT_MANAGER** | open() çağrısı 'with' bloğu olmadan yapılmış — dosya kapanmayabilir (kaynak sızıntısı) | `trades_file = open(trades_csv_path, 'a', newline='', encoding='utf-8')` |
| `scratch/patch_engine_canonical.py` | `46` | B14 | **OPEN_WITHOUT_CONTEXT_MANAGER** | open() çağrısı 'with' bloğu olmadan yapılmış — dosya kapanmayabilir (kaynak sızıntısı) | `daily_file = open(daily_csv_path, 'a', newline='', encoding='utf-8')` |
| `scripts/deep_comprehensive_audit.py` | `305` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'test' | `if m_sec and not any(safe in line.lower() for safe in ("os.getenv", "settings.",` |
| `scripts/full_system_audit.py` | `353` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'TEST' | `ticker="TEST", open_price=0, high=-1, low=-2, close=-1, volume=0, prev_close=100` |
| `scripts/full_system_audit.py` | `1171` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'TEST' | `calibrator.add_trade(score=2.0, return_pct=5.0, ticker="TEST", date="2024-01-01"` |
| `scripts/full_system_audit.py` | `1224` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'TEST' | `{"ticker": "TEST", "score": 2.0, "confidence": 0.6, "expected_return": 0.05, "vo` |
| `scripts/full_system_audit.py` | `2131` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'TEST' | `"TEST", df["Open"].values, df["High"].values, df["Low"].values, df["Close"].valu` |
| `scripts/full_system_audit.py` | `2134` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'TEST' | `features1 = feature_calculator.compute_all_features(df, mask=mask.mask, ticker="` |
| `scripts/full_system_audit.py` | `2140` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'TEST' | `"TEST",` |
| `scripts/full_system_audit.py` | `2147` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'TEST' | `features2 = feature_calculator.compute_all_features(df_modified, mask=mask2.mask` |
| `scripts/ultimate_audit_engine.py` | `81` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'change-this' | `"change-this", "change-me", "password", "secret",` |
| `scripts/ultimate_audit_engine.py` | `82` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'alpha_secure_2026' | `"alpha_secure_2026", "admin", "default", "test",` |
| `scripts/ultimate_audit_engine.py` | `83` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'alpha_secure_pass_123' | `"alpha_secure_pass_123",` |
| `scripts/ultimate_audit_engine.py` | `476` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'test' | `if not rel.endswith((".example", ".sample", "_test.py")) and "test" not in rel:` |
| `scripts/verify_full_system_holiday_integration.py` | `112` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'Test' | `hm.add_manual_holiday(date(2026,12,31), "Test")` |
| `scripts/verify_holiday_system_real_world.py` | `452` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'Test' | `hm.add_manual_holiday(test_date, "Test")` |
| `services/alternative/kariyer_net.py` | `169` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'test' | `"test",` |
| `services/alternative/llm_sentiment.py` | `278` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'default' | `"source": "default",` |
| `services/alternative/satellite_adapter.py` | `236` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'default' | `"responses": [{"identifier": "default", "format": {"type": "image/tiff"}}],` |
| `services/api/rate_limiter.py` | `35` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'default' | `"default": RateLimitConfig(max_requests=1000, window_seconds=60),` |
| `services/api/rate_limiter.py` | `62` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'default' | `group: str = "default",` |
| `services/api/rate_limiter.py` | `73` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'default' | `config = RATE_LIMITS.get(group, RATE_LIMITS["default"])` |
| `services/api/rate_limiter.py` | `114` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'default' | `return "default"` |
| `services/api/rate_limiter.py` | `116` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'default' | `def reset(self, client_id: str, group: str = "default"):` |
| `services/api/v1/market.py` | `298` | B05 | **PANDAS_IN_PROD** | Üretim servisinde 'pandas' import edilmiş — proje standardı Polars zorunludur! | `import pandas as pd` |
| `services/api/v1/market.py` | `536` | B05 | **SYNC_REQUESTS_IN_PROD** | 'requests' import edilmiş — async servislerde httpx.AsyncClient kullanılmalı | `import requests` |
| `services/backtest/engine.py` | `459` | B14 | **OPEN_WITHOUT_CONTEXT_MANAGER** | open() çağrısı 'with' bloğu olmadan yapılmış — dosya kapanmayabilir (kaynak sızıntısı) | `trades_file = open(trades_csv_path, "w", newline="", encoding="utf-8")` |
| `services/backtest/engine.py` | `460` | B14 | **OPEN_WITHOUT_CONTEXT_MANAGER** | open() çağrısı 'with' bloğu olmadan yapılmış — dosya kapanmayabilir (kaynak sızıntısı) | `daily_file = open(daily_csv_path, "w", newline="", encoding="utf-8")` |
| `services/backtest/walk_forward.py` | `192` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'TEST' | `ticker = s.get("ticker", "TEST")` |
| `services/backtest/walk_forward_engine.py` | `1` | B15 | **MISSING_TEST_FOR_CRITICAL_MODULE** | Kritik modül 'services/backtest/walk_forward_engine.py' için test dosyası bulunamadı (beklenen: 'tests/test_walk_forward.py') | `` |
| `services/core/circuit_breaker.py` | `1` | B15 | **MISSING_TEST_FOR_CRITICAL_MODULE** | Kritik modül 'services/core/circuit_breaker.py' için test dosyası bulunamadı (beklenen: 'tests/test_circuit_breaker.py') | `` |
| `services/core/config_loader.py` | `145` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'test' | `return self._environment == "test"` |
| `services/core/data_quality.py` | `1` | B15 | **MISSING_TEST_FOR_CRITICAL_MODULE** | Kritik modül 'services/core/data_quality.py' için test dosyası bulunamadı (beklenen: 'tests/test_data_quality.py') | `` |
| `services/core/database.py` | `1` | B15 | **MISSING_TEST_FOR_CRITICAL_MODULE** | Kritik modül 'services/core/database.py' için test dosyası bulunamadı (beklenen: 'tests/test_database.py') | `` |
| `services/core/db_lock.py` | `208` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'default' | `key: str = "default",` |
| `services/core/db_lock.py` | `573` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'default' | `def __init__(self, db, dialect: str = "postgresql", key: str = "default", timeou` |
| `services/core/immutable_audit.py` | `104` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'admin' | `audit.log(user_id="admin", action="UPDATE", resource_type="config", ...)` |
| `services/core/jwt_manager.py` | `105` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'ADMIN' | `token = jwt_mgr.generate_token("user123", "ADMIN", ["READ", "WRITE"])` |
| `services/core/jwt_manager.py` | `271` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'default' | `name: str = "default",` |
| `services/core/monitoring_security.py` | `359` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'admin' | `"admin": ["read", "write", "admin", "metrics", "alerts", "portfolio"],` |
| `services/core/monitoring_security.py` | `396` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'admin' | `if permission in perms or "admin" in perms:` |
| `services/core/orchestrator.py` | `76` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'default' | `def _publish_event_async(event: Any, key: str = "default") -> None:` |
| `services/core/polars_utils.py` | `45` | B05 | **PANDAS_IN_PROD** | Üretim servisinde 'pandas' import edilmiş — proje standardı Polars zorunludur! | `import pandas as pd` |
| `services/core/security.py` | `55` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'ADMIN' | `ADMIN = "ADMIN"` |
| `services/data/data_source.py` | `23` | B05 | **SYNC_REQUESTS_IN_PROD** | 'requests' import edilmiş — async servislerde httpx.AsyncClient kullanılmalı | `import requests` |
| `services/event_study/estimation_window.py` | `46` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'DEFAULT' | `"DEFAULT": 60,` |
| `services/event_study/estimation_window.py` | `71` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'DEFAULT' | `def get_window(self, event_date: datetime, event_type: str = "DEFAULT") -> tuple` |
| `services/event_study/estimation_window.py` | `82` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'DEFAULT' | `trading_days = ESTIMATION_WINDOWS.get(event_type, ESTIMATION_WINDOWS["DEFAULT"])` |
| `services/event_study/estimation_window.py` | `104` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'DEFAULT' | `def get_window_trading_days(self, event_type: str = "DEFAULT") -> int:` |
| `services/event_study/estimation_window.py` | `106` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'DEFAULT' | `return ESTIMATION_WINDOWS.get(event_type, ESTIMATION_WINDOWS["DEFAULT"])` |
| `services/event_study/estimation_window.py` | `111` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'DEFAULT' | `event_type: str = "DEFAULT",` |
| `services/event_study/estimation_window.py` | `139` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'DEFAULT' | `event_type: str = "DEFAULT",` |
| `services/event_study/estimation_window.py` | `181` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'DEFAULT' | `def get_estimation_window_size_calendar_days(self, event_date: datetime, event_t` |
| `services/event_study/event_window.py` | `46` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'DEFAULT' | `"DEFAULT": (-5, 5),` |
| `services/event_study/event_window.py` | `64` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'DEFAULT' | `def get_window(self, event_type: str = "DEFAULT") -> tuple[int, int]:` |
| `services/event_study/event_window.py` | `70` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'DEFAULT' | `return EVENT_WINDOWS.get(event_type, EVENT_WINDOWS["DEFAULT"])` |
| `services/event_study/event_window.py` | `72` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'DEFAULT' | `def get_window_size(self, event_type: str = "DEFAULT") -> int:` |
| `services/event_study/event_window.py` | `77` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'DEFAULT' | `def get_window_dates(self, event_date: datetime, event_type: str = "DEFAULT") ->` |
| `services/event_study/event_window.py` | `106` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'DEFAULT' | `event_type: str = "DEFAULT",` |
| `services/event_study/event_window.py` | `159` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'DEFAULT' | `event_type: str = "DEFAULT",` |
| `services/event_study/event_window.py` | `187` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'DEFAULT' | `def get_sub_windows(self, event_type: str = "DEFAULT") -> dict[str, tuple[int, i` |
| `services/event_study/event_window.py` | `201` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'DEFAULT' | `def get_window_calendar_days(self, event_date: datetime, event_type: str = "DEFA` |
| `services/event_study/impact.py` | `26` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'DEFAULT' | `"DEFAULT": {"significance": 0.25, "volume": 0.25, "statistical": 0.25, "magnitud` |
| `services/event_study/impact.py` | `34` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'DEFAULT' | `event_type: str = "DEFAULT",` |
| `services/event_study/impact.py` | `49` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'DEFAULT' | `weights = EVENT_WEIGHTS.get(event_type, EVENT_WEIGHTS["DEFAULT"])` |
| `services/event_study/impact.py` | `130` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'DEFAULT' | `event_type=event.get("event_type", "DEFAULT"),` |
| `services/features/contract.py` | `1` | B15 | **MISSING_TEST_FOR_CRITICAL_MODULE** | Kritik modül 'services/features/contract.py' için test dosyası bulunamadı (beklenen: 'tests/test_feature_contract.py') | `` |
| `services/features/feature_tests.py` | `214` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'test' | `failures=[{"test": t.test_name, "msg": t.message} for t in failed_tests_detail],` |
| `services/grpc/client.py` | `323` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'default' | `request = market_pb2.PortfolioRequest(portfolio_id="default")` |
| `services/grpc/client.py` | `362` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'default' | `request = market_pb2.PortfolioRequest(portfolio_id="default")` |
| `services/grpc/client.py` | `404` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'default' | `request = market_pb2.RiskRequest(portfolio_id="default")` |
| `services/grpc/client.py` | `433` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'default' | `request = market_pb2.RiskRequest(portfolio_id="default")` |
| `services/ingestion/circuit_breaker.py` | `80` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'default' | `name: str = "default",` |
| `services/ingestion/providers/universe_provider.py` | `12` | B05 | **SYNC_REQUESTS_IN_PROD** | 'requests' import edilmiş — async servislerde httpx.AsyncClient kullanılmalı | `import requests` |
| `services/institutional_backtest.py` | `7` | B05 | **PANDAS_IN_PROD** | Üretim servisinde 'pandas' import edilmiş — proje standardı Polars zorunludur! | `import pandas as pd` |
| `services/institutional_backtest.py` | `137` | B03 | **BARE_EXCEPT** | Bare 'except:' kullanılmış — KeyboardInterrupt dahil her şeyi yakalar, maskeleme riski | `except:` |
| `services/intelligence/ml_signal_fusion.py` | `54` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'default' | `weights_source: str = "default"  # "default", "optimized", "regime_override"` |
| `services/intelligence/scenario.py` | `319` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'test' | `scenario = ScenarioInput(name="test", **{variable: mid})` |
| `services/learning/alpha_bist_v4_max_alpha.py` | `7` | B05 | **PANDAS_IN_PROD** | Üretim servisinde 'pandas' import edilmiş — proje standardı Polars zorunludur! | `import pandas as pd` |
| `services/learning/drift_monitor.py` | `79` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'test' | `feature_drift_gauge.set(float(p_value), {"feature": feature_name, "test": "KS"})` |
| `services/learning/drift_monitor.py` | `139` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'test' | `prediction_drift_gauge.set(psi_score, {"model": model_name, "test": "PSI"})` |
| `services/learning/final_confirmation_holdout.py` | `15` | B05 | **PANDAS_IN_PROD** | Üretim servisinde 'pandas' import edilmiş — proje standardı Polars zorunludur! | `import pandas as pd` |
| `services/learning/final_holdout_validator.py` | `21` | B05 | **PANDAS_IN_PROD** | Üretim servisinde 'pandas' import edilmiş — proje standardı Polars zorunludur! | `import pandas as pd` |
| `services/learning/inspect_june_2026_vdip.py` | `12` | B05 | **PANDAS_IN_PROD** | Üretim servisinde 'pandas' import edilmiş — proje standardı Polars zorunludur! | `import pandas as pd` |
| `services/learning/institutional_portfolio_optimizer.py` | `15` | B05 | **PANDAS_IN_PROD** | Üretim servisinde 'pandas' import edilmiş — proje standardı Polars zorunludur! | `import pandas as pd` |
| `services/learning/model_memory_store.py` | `36` | B05 | **PANDAS_IN_PROD** | Üretim servisinde 'pandas' import edilmiş — proje standardı Polars zorunludur! | `import pandas as pd` |
| `services/learning/phase10_label_forensics.py` | `5` | B05 | **PANDAS_IN_PROD** | Üretim servisinde 'pandas' import edilmiş — proje standardı Polars zorunludur! | `import pandas as pd` |
| `services/learning/phase11_alpha_redesign.py` | `5` | B05 | **PANDAS_IN_PROD** | Üretim servisinde 'pandas' import edilmiş — proje standardı Polars zorunludur! | `import pandas as pd` |
| `services/learning/phase12_model_rebuild.py` | `6` | B05 | **PANDAS_IN_PROD** | Üretim servisinde 'pandas' import edilmiş — proje standardı Polars zorunludur! | `import pandas as pd` |
| `services/learning/phase13_integration.py` | `5` | B05 | **PANDAS_IN_PROD** | Üretim servisinde 'pandas' import edilmiş — proje standardı Polars zorunludur! | `import pandas as pd` |
| `services/learning/phase14_architecture.py` | `5` | B05 | **PANDAS_IN_PROD** | Üretim servisinde 'pandas' import edilmiş — proje standardı Polars zorunludur! | `import pandas as pd` |
| `services/learning/phase15_random_forensics.py` | `5` | B05 | **PANDAS_IN_PROD** | Üretim servisinde 'pandas' import edilmiş — proje standardı Polars zorunludur! | `import pandas as pd` |
| `services/learning/phase16_portfolio_alpha_forensics.py` | `5` | B05 | **PANDAS_IN_PROD** | Üretim servisinde 'pandas' import edilmiş — proje standardı Polars zorunludur! | `import pandas as pd` |
| `services/learning/phase17_alpha_stability.py` | `5` | B05 | **PANDAS_IN_PROD** | Üretim servisinde 'pandas' import edilmiş — proje standardı Polars zorunludur! | `import pandas as pd` |
| `services/learning/phase18_feature_alpha_discovery.py` | `5` | B05 | **PANDAS_IN_PROD** | Üretim servisinde 'pandas' import edilmiş — proje standardı Polars zorunludur! | `import pandas as pd` |
| `services/learning/phase19_economic_alpha_validation.py` | `5` | B05 | **PANDAS_IN_PROD** | Üretim servisinde 'pandas' import edilmiş — proje standardı Polars zorunludur! | `import pandas as pd` |
| `services/learning/phase1_2_upside_audit.py` | `7` | B05 | **PANDAS_IN_PROD** | Üretim servisinde 'pandas' import edilmiş — proje standardı Polars zorunludur! | `import pandas as pd` |
| `services/learning/phase20_residual_alpha_discovery.py` | `5` | B05 | **PANDAS_IN_PROD** | Üretim servisinde 'pandas' import edilmiş — proje standardı Polars zorunludur! | `import pandas as pd` |
| `services/learning/phase21_alpha_orthogonality.py` | `5` | B05 | **PANDAS_IN_PROD** | Üretim servisinde 'pandas' import edilmiş — proje standardı Polars zorunludur! | `import pandas as pd` |
| `services/learning/phase22_alpha_model_rebuild.py` | `5` | B05 | **PANDAS_IN_PROD** | Üretim servisinde 'pandas' import edilmiş — proje standardı Polars zorunludur! | `import pandas as pd` |
| `services/learning/phase23_pure_lowvol_validation.py` | `5` | B05 | **PANDAS_IN_PROD** | Üretim servisinde 'pandas' import edilmiş — proje standardı Polars zorunludur! | `import pandas as pd` |
| `services/learning/phase24_liquidity_alpha_validation.py` | `5` | B05 | **PANDAS_IN_PROD** | Üretim servisinde 'pandas' import edilmiş — proje standardı Polars zorunludur! | `import pandas as pd` |
| `services/learning/phase25_alternative_alpha_discovery.py` | `5` | B05 | **PANDAS_IN_PROD** | Üretim servisinde 'pandas' import edilmiş — proje standardı Polars zorunludur! | `import pandas as pd` |
| `services/learning/phase26_market_regime_discovery.py` | `5` | B05 | **PANDAS_IN_PROD** | Üretim servisinde 'pandas' import edilmiş — proje standardı Polars zorunludur! | `import pandas as pd` |
| `services/learning/phase27_volatility_portfolio_integration.py` | `5` | B05 | **PANDAS_IN_PROD** | Üretim servisinde 'pandas' import edilmiş — proje standardı Polars zorunludur! | `import pandas as pd` |
| `services/learning/phase28_volatility_stress_test.py` | `5` | B05 | **PANDAS_IN_PROD** | Üretim servisinde 'pandas' import edilmiş — proje standardı Polars zorunludur! | `import pandas as pd` |
| `services/learning/phase2_decomposition.py` | `6` | B05 | **PANDAS_IN_PROD** | Üretim servisinde 'pandas' import edilmiş — proje standardı Polars zorunludur! | `import pandas as pd` |
| `services/learning/phase3_4_alternative_optimizer.py` | `9` | B05 | **PANDAS_IN_PROD** | Üretim servisinde 'pandas' import edilmiş — proje standardı Polars zorunludur! | `import pandas as pd` |
| `services/learning/phase4_fact_check.py` | `7` | B05 | **PANDAS_IN_PROD** | Üretim servisinde 'pandas' import edilmiş — proje standardı Polars zorunludur! | `import pandas as pd` |
| `services/learning/phase4_mechanisms.py` | `6` | B05 | **PANDAS_IN_PROD** | Üretim servisinde 'pandas' import edilmiş — proje standardı Polars zorunludur! | `import pandas as pd` |
| `services/learning/phase4_optimizer.py` | `6` | B05 | **PANDAS_IN_PROD** | Üretim servisinde 'pandas' import edilmiş — proje standardı Polars zorunludur! | `import pandas as pd` |
| `services/learning/phase7_robustness.py` | `5` | B05 | **PANDAS_IN_PROD** | Üretim servisinde 'pandas' import edilmiş — proje standardı Polars zorunludur! | `import pandas as pd` |
| `services/learning/phase8_discovery.py` | `6` | B05 | **PANDAS_IN_PROD** | Üretim servisinde 'pandas' import edilmiş — proje standardı Polars zorunludur! | `import pandas as pd` |
| `services/learning/phase9_alpha_forensics.py` | `5` | B05 | **PANDAS_IN_PROD** | Üretim servisinde 'pandas' import edilmiş — proje standardı Polars zorunludur! | `import pandas as pd` |
| `services/learning/production_alpha_engine.py` | `18` | B05 | **PANDAS_IN_PROD** | Üretim servisinde 'pandas' import edilmiş — proje standardı Polars zorunludur! | `import pandas as pd` |
| `services/learning/real_bist_walkforward_backtest.py` | `19` | B05 | **PANDAS_IN_PROD** | Üretim servisinde 'pandas' import edilmiş — proje standardı Polars zorunludur! | `import pandas as pd` |
| `services/learning/real_bist_walkforward_backtest.py` | `109` | B09 | **POTENTIAL_LEAKAGE_SHIFT** | '.shift(-5)' tespit edildi — negatif shift genellikle geleceği gösterir (lookahead bias)! | `labels["future_price_5d"] = close.shift(-5)` |
| `services/learning/train_val_multi_fold_optimizer.py` | `12` | B05 | **PANDAS_IN_PROD** | Üretim servisinde 'pandas' import edilmiş — proje standardı Polars zorunludur! | `import pandas as pd` |
| `services/learning/train_val_research_engine.py` | `12` | B05 | **PANDAS_IN_PROD** | Üretim servisinde 'pandas' import edilmiş — proje standardı Polars zorunludur! | `import pandas as pd` |
| `services/learning/upside_capture_root_cause.py` | `11` | B05 | **PANDAS_IN_PROD** | Üretim servisinde 'pandas' import edilmiş — proje standardı Polars zorunludur! | `import pandas as pd` |
| `services/learning/walkforward_root_cause_analyzer.py` | `11` | B05 | **PANDAS_IN_PROD** | Üretim servisinde 'pandas' import edilmiş — proje standardı Polars zorunludur! | `import pandas as pd` |
| `services/massive_454_backtest.py` | `7` | B05 | **PANDAS_IN_PROD** | Üretim servisinde 'pandas' import edilmiş — proje standardı Polars zorunludur! | `import pandas as pd` |
| `services/massive_454_backtest.py` | `119` | B03 | **BARE_EXCEPT** | Bare 'except:' kullanılmış — KeyboardInterrupt dahil her şeyi yakalar, maskeleme riski | `except:` |
| `services/ml/feature_engine.py` | `1` | B15 | **MISSING_TEST_FOR_CRITICAL_MODULE** | Kritik modül 'services/ml/feature_engine.py' için test dosyası bulunamadı (beklenen: 'tests/test_feature_engine.py') | `` |
| `services/ml/lightgbm_trainer.py` | `1` | B15 | **MISSING_TEST_FOR_CRITICAL_MODULE** | Kritik modül 'services/ml/lightgbm_trainer.py' için test dosyası bulunamadı (beklenen: 'tests/test_lightgbm.py') | `` |
| `services/ml/qlib_integration.py` | `113` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'test' | `"test": {"X": [], "y": [], "tickers": []},` |
| `services/ml/qlib_integration.py` | `147` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'test' | `dataset["test"]["X"].append(features[valid_end:])` |
| `services/ml/qlib_integration.py` | `148` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'test' | `dataset["test"]["y"].append(returns[valid_end:])` |
| `services/ml/qlib_integration.py` | `149` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'test' | `dataset["test"]["tickers"].append(ticker)` |
| `services/ml/qlib_integration.py` | `152` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'test' | `for split in ["train", "valid", "test"]:` |
| `services/ml/qlib_integration.py` | `164` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'test' | `test_samples=len(dataset["test"]["X"]),` |
| `services/portfolio/main.py` | `69` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'Default' | `"INSERT INTO portfolios (name, initial_capital, current_capital, cash_balance) V` |
| `services/portfolio/portfolio_manager.py` | `1` | B15 | **MISSING_TEST_FOR_CRITICAL_MODULE** | Kritik modül 'services/portfolio/portfolio_manager.py' için test dosyası bulunamadı (beklenen: 'tests/test_portfolio_manager.py') | `` |
| `test_core_regressions.py` | `10` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'test' | `"THYAO", "2026-08-21T00:00:00Z", is_tradable=False, reasons=["test"], price_mask` |
| `test_core_regressions.py` | `35` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'test' | `await redis.publish("test", "data")` |
| `test_llm_system.py` | `70` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'Test' | `"reason": "Test",` |
| `tests/test_agent_system.py` | `97` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'test' | `model_version="test",` |
| `tests/test_agent_system.py` | `297` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'test' | `prompt="test",` |
| `tests/test_agent_system.py` | `304` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'test' | `prompt="test",` |
| `tests/test_agent_system.py` | `392` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'test' | `reasoning="test",` |
| `tests/test_agent_system.py` | `479` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'test' | `mem.record_task("t1", "THYAO", "LONG", 0.7, "test")` |
| `tests/test_agent_system.py` | `530` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'test' | `payload={"data": "test"},` |
| `tests/test_agent_system.py` | `535` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'test' | `assert messages[0].payload["data"] == "test"` |
| `tests/test_agent_system.py` | `628` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'test' | `mem.record_task(task_id, "THYAO", "LONG", 0.7, "test")` |
| `tests/test_agent_system.py` | `759` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'test' | `mem.record_task(tid, "THYAO", "LONG", 0.7, "test")` |
| `tests/test_agent_system.py` | `782` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'test' | `mem.record_task(f"t{i}", "THYAO", "LONG", 0.7, "test")` |
| `tests/test_alternative_data.py` | `183` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'test' | `report = validator.validate(data, source="test")` |
| `tests/test_alternative_data.py` | `189` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'test' | `report = validator.validate(None, source="test")` |
| `tests/test_alternative_data.py` | `195` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'test' | `report = validator.validate({}, source="test")` |
| `tests/test_alternative_data.py` | `203` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'test' | `report = validator.validate(data, source="test")` |
| `tests/test_alternative_data.py` | `210` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'test' | `report = validator.validate(data, source="test", expected_fields=["sentiment", "` |
| `tests/test_alternative_data.py` | `217` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'test' | `report = validator.validate(data, source="test")` |
| `tests/test_alternative_data.py` | `630` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'test' | `source="test",` |
| `tests/test_alternative_data.py` | `697` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'TEST' | `features = compute_social_features(data, "TEST")` |
| `tests/test_api.py` | `147` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'default' | `allowed, info = await limiter.check("client1", "default")` |
| `tests/test_api.py` | `156` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'default' | `await limiter.check("client1", "default")` |
| `tests/test_api.py` | `158` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'default' | `allowed, info = await limiter.check("client1", "default")` |
| `tests/test_api.py` | `165` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'default' | `await limiter.check("client1", "default")` |
| `tests/test_api.py` | `167` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'default' | `allowed, info = await limiter.check("client2", "default")` |
| `tests/test_api.py` | `174` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'default' | `await limiter.check("client1", "default")` |
| `tests/test_api.py` | `181` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'default' | `assert limiter.get_endpoint_group("/api/v1/market/state", "GET") == "default"` |
| `tests/test_api.py` | `254` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'ADMIN' | `assert "ADMIN" in roles` |
| `tests/test_api.py` | `261` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'default' | `assert "default" in RATE_LIMITS` |
| `tests/test_api.py` | `271` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'default' | `assert RATE_LIMITS["default"].max_requests == 1000` |
| `tests/test_api.py` | `295` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'default' | `assert limiter.get_endpoint_group("/api/v1/market/state", "GET") == "default"` |
| `tests/test_autonomous_ops.py` | `46` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'test' | `alert = Alert(alert_type=AlertType.CASH_NEGATIVE, severity="CRITICAL", message="` |
| `tests/test_autonomous_ops.py` | `62` | B06 | **INSECURE_DEFAULT** | Güvensiz varsayılan değer kullanılmış: 'test' | `alert2 = Alert(alert_type=AlertType.HEALTH_CHANGE, severity="WARNING", message="` |

## 5. Orta Oncelikli Bulgular (1722 adet)

| Dosya | Satir | Kategori | Sorun |
|---|---|---|---|
| `ml/feature_discovery.py` | `112` | TODO_MARKER | Tamamlanmamış görev: 'TODO' işareti bırakılmış |
| `ml/models.py` | `178` | MISSING_RETURN_TYPE | 'train' fonksiyonu dönüş tipi (return annotation) eksik |
| `ml/models.py` | `209` | MISSING_RETURN_TYPE | 'save' fonksiyonu dönüş tipi (return annotation) eksik |
| `ml/models.py` | `240` | MISSING_RETURN_TYPE | 'load' fonksiyonu dönüş tipi (return annotation) eksik |
| `ml/models.py` | `278` | MISSING_RETURN_TYPE | 'train' fonksiyonu dönüş tipi (return annotation) eksik |
| `ml/models.py` | `315` | MISSING_RETURN_TYPE | 'train' fonksiyonu dönüş tipi (return annotation) eksik |
| `ml/models.py` | `349` | MISSING_RETURN_TYPE | 'add_model' fonksiyonu dönüş tipi (return annotation) eksik |
| `scripts/deep_comprehensive_audit.py` | `290` | TODO_MARKER | Tamamlanmamış görev: 'TODO' işareti bırakılmış |
| `scripts/ultimate_audit_engine.py` | `461` | TODO_MARKER | Tamamlanmamış görev: 'TODO' işareti bırakılmış |
| `services/clear.py` | `10` | MISSING_RETURN_TYPE | 'run' fonksiyonu dönüş tipi (return annotation) eksik |
| `services/clear2.py` | `7` | PRINT_IN_PROD | Üretim kodunda print() kullanımı — structlog ile değiştirilmeli |
| `services/clear2.py` | `4` | MISSING_RETURN_TYPE | 'run' fonksiyonu dönüş tipi (return annotation) eksik |
| `services/institutional_backtest.py` | `16` | PRINT_IN_PROD | Üretim kodunda print() kullanımı — structlog ile değiştirilmeli |
| `services/institutional_backtest.py` | `23` | PRINT_IN_PROD | Üretim kodunda print() kullanımı — structlog ile değiştirilmeli |
| `services/institutional_backtest.py` | `25` | PRINT_IN_PROD | Üretim kodunda print() kullanımı — structlog ile değiştirilmeli |
| `services/institutional_backtest.py` | `53` | PRINT_IN_PROD | Üretim kodunda print() kullanımı — structlog ile değiştirilmeli |
| `services/institutional_backtest.py` | `62` | PRINT_IN_PROD | Üretim kodunda print() kullanımı — structlog ile değiştirilmeli |
| `services/institutional_backtest.py` | `69` | PRINT_IN_PROD | Üretim kodunda print() kullanımı — structlog ile değiştirilmeli |
| `services/institutional_backtest.py` | `79` | PRINT_IN_PROD | Üretim kodunda print() kullanımı — structlog ile değiştirilmeli |
| `services/institutional_backtest.py` | `86` | PRINT_IN_PROD | Üretim kodunda print() kullanımı — structlog ile değiştirilmeli |
| `services/institutional_backtest.py` | `106` | PRINT_IN_PROD | Üretim kodunda print() kullanımı — structlog ile değiştirilmeli |
| `services/institutional_backtest.py` | `140` | PRINT_IN_PROD | Üretim kodunda print() kullanımı — structlog ile değiştirilmeli |
| `services/institutional_backtest.py` | `142` | PRINT_IN_PROD | Üretim kodunda print() kullanımı — structlog ile değiştirilmeli |
| `services/institutional_backtest.py` | `150` | PRINT_IN_PROD | Üretim kodunda print() kullanımı — structlog ile değiştirilmeli |
| `services/institutional_backtest.py` | `151` | PRINT_IN_PROD | Üretim kodunda print() kullanımı — structlog ile değiştirilmeli |
| `services/institutional_backtest.py` | `154` | PRINT_IN_PROD | Üretim kodunda print() kullanımı — structlog ile değiştirilmeli |
| `services/institutional_backtest.py` | `155` | PRINT_IN_PROD | Üretim kodunda print() kullanımı — structlog ile değiştirilmeli |
| `services/institutional_backtest.py` | `15` | MISSING_RETURN_TYPE | 'run_institutional' fonksiyonu dönüş tipi (return annotation) eksik |
| `services/massive_454_backtest.py` | `15` | PRINT_IN_PROD | Üretim kodunda print() kullanımı — structlog ile değiştirilmeli |
| `services/massive_454_backtest.py` | `22` | PRINT_IN_PROD | Üretim kodunda print() kullanımı — structlog ile değiştirilmeli |
| `services/massive_454_backtest.py` | `24` | PRINT_IN_PROD | Üretim kodunda print() kullanımı — structlog ile değiştirilmeli |
| `services/massive_454_backtest.py` | `50` | PRINT_IN_PROD | Üretim kodunda print() kullanımı — structlog ile değiştirilmeli |
| `services/massive_454_backtest.py` | `60` | PRINT_IN_PROD | Üretim kodunda print() kullanımı — structlog ile değiştirilmeli |
| `services/massive_454_backtest.py` | `64` | PRINT_IN_PROD | Üretim kodunda print() kullanımı — structlog ile değiştirilmeli |
| `services/massive_454_backtest.py` | `69` | PRINT_IN_PROD | Üretim kodunda print() kullanımı — structlog ile değiştirilmeli |
| `services/massive_454_backtest.py` | `79` | PRINT_IN_PROD | Üretim kodunda print() kullanımı — structlog ile değiştirilmeli |
| `services/massive_454_backtest.py` | `86` | PRINT_IN_PROD | Üretim kodunda print() kullanımı — structlog ile değiştirilmeli |
| `services/massive_454_backtest.py` | `92` | PRINT_IN_PROD | Üretim kodunda print() kullanımı — structlog ile değiştirilmeli |
| `services/massive_454_backtest.py` | `122` | PRINT_IN_PROD | Üretim kodunda print() kullanımı — structlog ile değiştirilmeli |
| `services/massive_454_backtest.py` | `126` | PRINT_IN_PROD | Üretim kodunda print() kullanımı — structlog ile değiştirilmeli |
| `services/massive_454_backtest.py` | `135` | PRINT_IN_PROD | Üretim kodunda print() kullanımı — structlog ile değiştirilmeli |
| `services/massive_454_backtest.py` | `136` | PRINT_IN_PROD | Üretim kodunda print() kullanımı — structlog ile değiştirilmeli |
| `services/massive_454_backtest.py` | `137` | PRINT_IN_PROD | Üretim kodunda print() kullanımı — structlog ile değiştirilmeli |
| `services/massive_454_backtest.py` | `141` | PRINT_IN_PROD | Üretim kodunda print() kullanımı — structlog ile değiştirilmeli |
| `services/massive_454_backtest.py` | `142` | PRINT_IN_PROD | Üretim kodunda print() kullanımı — structlog ile değiştirilmeli |
| `services/massive_454_backtest.py` | `14` | MISSING_RETURN_TYPE | 'run_massive' fonksiyonu dönüş tipi (return annotation) eksik |
| `services/recreate.py` | `15` | PRINT_IN_PROD | Üretim kodunda print() kullanımı — structlog ile değiştirilmeli |
| `services/recreate.py` | `4` | MISSING_RETURN_TYPE | 'run' fonksiyonu dönüş tipi (return annotation) eksik |
| `services/test_engine2.py` | `11` | PRINT_IN_PROD | Üretim kodunda print() kullanımı — structlog ile değiştirilmeli |
| `services/test_engine2.py` | `14` | PRINT_IN_PROD | Üretim kodunda print() kullanımı — structlog ile değiştirilmeli |
| `services/agents/agent_memory.py` | `63` | MISSING_RETURN_TYPE | 'add' fonksiyonu dönüş tipi (return annotation) eksik |
| `services/agents/agent_memory.py` | `90` | MISSING_RETURN_TYPE | 'clear' fonksiyonu dönüş tipi (return annotation) eksik |
| `services/agents/agent_memory.py` | `116` | MISSING_RETURN_TYPE | 'add' fonksiyonu dönüş tipi (return annotation) eksik |
| `services/agents/agent_memory.py` | `124` | MISSING_RETURN_TYPE | 'record_outcome' fonksiyonu dönüş tipi (return annotation) eksik |
| `services/agents/agent_memory.py` | `266` | MISSING_RETURN_TYPE | 'add_pattern' fonksiyonu dönüş tipi (return annotation) eksik |
| `services/agents/agent_memory.py` | `317` | MISSING_RETURN_TYPE | 'prune_low_accuracy' fonksiyonu dönüş tipi (return annotation) eksik |
| `services/agents/agent_memory.py` | `359` | MISSING_RETURN_TYPE | 'record_task' fonksiyonu dönüş tipi (return annotation) eksik |
| `services/agents/agent_memory.py` | `384` | MISSING_RETURN_TYPE | 'record_outcome' fonksiyonu dönüş tipi (return annotation) eksik |
| `services/agents/agent_memory.py` | `421` | MISSING_RETURN_TYPE | 'save' fonksiyonu dönüş tipi (return annotation) eksik |
| `services/agents/agent_memory.py` | `442` | MISSING_RETURN_TYPE | 'load' fonksiyonu dönüş tipi (return annotation) eksik |
| `services/agents/agent_pipeline.py` | `314` | MISSING_RETURN_TYPE | '_update_memories' fonksiyonu dönüş tipi (return annotation) eksik |
| `services/agents/agent_system.py` | `524` | MISSING_RETURN_TYPE | 'register_agent' fonksiyonu dönüş tipi (return annotation) eksik |
| `services/agents/agent_system.py` | `528` | MISSING_RETURN_TYPE | 'set_llm_client' fonksiyonu dönüş tipi (return annotation) eksik |
| `services/agents/agent_system.py` | `557` | MISSING_RETURN_TYPE | '_run_agent' fonksiyonu dönüş tipi (return annotation) eksik |
| `services/agents/communication_bus.py` | `73` | MISSING_RETURN_TYPE | 'send' fonksiyonu dönüş tipi (return annotation) eksik |
| `services/agents/communication_bus.py` | `94` | MISSING_RETURN_TYPE | 'broadcast' fonksiyonu dönüş tipi (return annotation) eksik |
| `services/agents/communication_bus.py` | `166` | MISSING_RETURN_TYPE | 'clear' fonksiyonu dönüş tipi (return annotation) eksik |
| `services/agents/llm_client.py` | `426` | MISSING_RETURN_TYPE | 'register_provider' fonksiyonu dönüş tipi (return annotation) eksik |
| `services/agents/prompts/__init__.py` | `536` | MISSING_RETURN_TYPE | 'register_template' fonksiyonu dönüş tipi (return annotation) eksik |
| `services/agents/schemas/__init__.py` | `28` | MISSING_RETURN_TYPE | '_normalize_confidence' fonksiyonu dönüş tipi (return annotation) eksik |
| `services/agents/schemas/__init__.py` | `48` | MISSING_RETURN_TYPE | 'validate_confidence' fonksiyonu dönüş tipi (return annotation) eksik |
| `services/agents/schemas/__init__.py` | `102` | MISSING_RETURN_TYPE | 'validate_confidence' fonksiyonu dönüş tipi (return annotation) eksik |
| `services/agents/schemas/__init__.py` | `136` | MISSING_RETURN_TYPE | 'validate_confidence' fonksiyonu dönüş tipi (return annotation) eksik |
| `services/alternative/base.py` | `43` | MISSING_RETURN_TYPE | 'acquire' fonksiyonu dönüş tipi (return annotation) eksik |
| `services/alternative/base.py` | `97` | MISSING_RETURN_TYPE | 'record_success' fonksiyonu dönüş tipi (return annotation) eksik |
| `services/alternative/base.py` | `109` | MISSING_RETURN_TYPE | 'record_failure' fonksiyonu dönüş tipi (return annotation) eksik |
| `services/alternative/base.py` | `399` | MISSING_RETURN_TYPE | '_set_cached' fonksiyonu dönüş tipi (return annotation) eksik |
| `services/alternative/base.py` | `426` | MISSING_RETURN_TYPE | 'register' fonksiyonu dönüş tipi (return annotation) eksik |
| `services/alternative/bkm_adapter.py` | `183` | TODO_MARKER | Tamamlanmamış görev: 'Placeholder' işareti bırakılmış |
| `services/alternative/feature_engine.py` | `54` | MISSING_RETURN_TYPE | 'initialize' fonksiyonu dönüş tipi (return annotation) eksik |
| `services/alternative/feature_store.py` | `67` | MISSING_RETURN_TYPE | 'register_feature' fonksiyonu dönüş tipi (return annotation) eksik |
| `services/alternative/feature_store.py` | `72` | MISSING_RETURN_TYPE | 'put' fonksiyonu dönüş tipi (return annotation) eksik |
| `services/alternative/feature_store.py` | `189` | MISSING_RETURN_TYPE | 'save' fonksiyonu dönüş tipi (return annotation) eksik |
| `services/alternative/feature_store.py` | `207` | MISSING_RETURN_TYPE | 'load' fonksiyonu dönüş tipi (return annotation) eksik |
| `services/alternative/feature_store.py` | `236` | MISSING_RETURN_TYPE | 'shutdown' fonksiyonu dönüş tipi (return annotation) eksik |
| `services/alternative/google_trends.py` | `63` | MISSING_RETURN_TYPE | '_get_pytrends' fonksiyonu dönüş tipi (return annotation) eksik |
| `services/alternative/llm_sentiment.py` | `63` | MISSING_RETURN_TYPE | 'set_llm_client' fonksiyonu dönüş tipi (return annotation) eksik |
| `services/api/app.py` | `49` | MISSING_RETURN_TYPE | 'otel_trace' fonksiyonu dönüş tipi (return annotation) eksik |
| `services/api/app.py` | `51` | MISSING_RETURN_TYPE | 'decorator' fonksiyonu dönüş tipi (return annotation) eksik |
| `services/api/app.py` | `53` | MISSING_RETURN_TYPE | 'wrapper' fonksiyonu dönüş tipi (return annotation) eksik |
| `services/api/app.py` | `111` | MISSING_RETURN_TYPE | '_start_grpc' fonksiyonu dönüş tipi (return annotation) eksik |
| `services/api/app.py` | `127` | MISSING_RETURN_TYPE | '_start_nats' fonksiyonu dönüş tipi (return annotation) eksik |
| `services/api/app.py` | `138` | MISSING_RETURN_TYPE | '_start_service_mesh' fonksiyonu dönüş tipi (return annotation) eksik |
| `services/api/app.py` | `151` | MISSING_RETURN_TYPE | '_shutdown' fonksiyonu dönüş tipi (return annotation) eksik |
| `services/api/app.py` | `193` | MISSING_RETURN_TYPE | 'lifespan' fonksiyonu dönüş tipi (return annotation) eksik |
| `services/api/app.py` | `238` | MISSING_RETURN_TYPE | 'timing_middleware' fonksiyonu dönüş tipi (return annotation) eksik |
| `services/api/app.py` | `247` | MISSING_RETURN_TYPE | 'request_id_middleware' fonksiyonu dönüş tipi (return annotation) eksik |
| `services/api/app.py` | `276` | MISSING_RETURN_TYPE | 'timeout_middleware' fonksiyonu dönüş tipi (return annotation) eksik |
| `services/api/app.py` | `316` | MISSING_RETURN_TYPE | 'rate_limit_middleware' fonksiyonu dönüş tipi (return annotation) eksik |
| `services/api/app.py` | `355` | MISSING_RETURN_TYPE | 'http_exception_handler' fonksiyonu dönüş tipi (return annotation) eksik |

---
*Bu rapor Ultimate Audit Engine v2.0 tarafindan 0 token harcanarak uretilmistir.*
*JSON verisi: `audit/ultimate_audit_findings.json`*
