# ALPHA BIST — Derin Sistem Bütünlük Denetim Raporu

> **Tarih:** 2026-08-29 14:50:22  
> **Motor:** Deep System Integrity Auditor v3.0 (28 Boyut, 0 Token)  
> **Kapsam:** Kod Kalitesi + Motor Mantığı + Sinyal Zinciri + Veri Akışı  
> **Taranan:** 850 dosya, 247,906 satır  
> **Süre:** 6.03 saniye  
> **Sistem Sağlık Puanı:** **30 / 100**

---

## 1. Genel Özet

| Seviye | Adet | Etki |
|---|---|---|
| **KRİTİK** | **104** | Sistem çökebilir, data bütünlüğü tehlikede, güvenlik açığı |
| **YÜKSEK**  | **987** | Motor zinciri kırık, hata maskeleme, mimari ihlal |
| **ORTA**    | **1950** | Kod kalitesi, standart ihlali, uyarı |
| **DÜŞÜK**   | **2473** | Dokümantasyon, tip eksikliği, biçim |
| **TOPLAM**  | **5516** | |

## 2. 28 Boyut Bazlı Analiz

| Boyut | Alan | Bulunan | Durum |
|---|---|---|---|
| **B01** | Sozdizimi & Dosya Butunlugu | 1 | 🔴 KRİTİK |
| **B02** | Bos/Yarim Birakilan Kod | 26 | 🔴 KRİTİK |
| **B03** | Fail-Closed & Hata Yonetimi | 68 | 🔴 KRİTİK |
| **B04** | Async Butunlugu | 3 | 🔴 KRİTİK |
| **B05** | Teknoloji Yigini Uyumu | 52 | 🟠 YÜKSEK |
| **B06** | Guvenlik & Sir Tespiti | 507 | 🔴 KRİTİK |
| **B07** | Kod Kalitesi & Standartlar | 5 | 🟡 ORTA |
| **B08** | Tip Guvenligi | 1654 | 🟡 ORTA |
| **B09** | PIT & Quant Dogrulugu | 40 | 🟠 YÜKSEK |
| **B10** | Mimari & Katman Uyumu | 1 | 🔴 KRİTİK |
| **B11** | Servis Init Butunlugu | 1 | 🟡 ORTA |
| **B12** | Docker & .env Uyumu | 19 | 🔴 KRİTİK |
| **B13** | Loglama Standardi | 84 | 🟡 ORTA |
| **B14** | Kaynak Sizintisi | 10 | 🟠 YÜKSEK |
| **B15** | Test Kapsami | 12 | 🟠 YÜKSEK |
| **B16** | Dokumantasyon Butunlugu | 909 | 🟡 ORTA |
| **B17** | Orchestrator Servis Kaydi | 0 | ✅ TEMİZ |
| **B18** | Servis Arayzü Uyumu | 4 | 🟠 YÜKSEK |
| **B19** | Sinyal Fuzyon Agirlik Butunlugu | 0 | ✅ TEMİZ |
| **B20** | DecisionInput Kapsamı | 1 | 🟠 YÜKSEK |
| **B21** | RiskGate Parametre Uyumu | 3 | 🟠 YÜKSEK |
| **B22** | ML Pipeline Zinciri | 0 | ✅ TEMİZ |
| **B23** | Feature Contract Butunlugu | 1 | 🟠 YÜKSEK |
| **B24** | Event Schema Butunlugu | 0 | ✅ TEMİZ |
| **B25** | Portfolio Manager Baglantisi | 2 | 🔴 KRİTİK |
| **B26** | Olü Kod Tespiti | 1564 | 🟡 ORTA |
| **B27** | Coklu Tanim Cakismasi | 82 | 🟡 ORTA |
| **B28** | Supheli Dosya Tespiti | 9 | 🔴 KRİTİK |
| **B29** | Docker Compose Derin Validasyon | 0 | ✅ TEMİZ |
| **B30** | pyproject Bagimlilik Uyumu | 328 | 🟠 YÜKSEK |
| **B31** | ML Model Dosya Varligi | 2 | 🔴 KRİTİK |
| **B32** | NATS-Redis Mesaj Semasi | 1 | 🟡 ORTA |
| **B33** | Coklu Adim Dongüsel Bagimlilik | 0 | ✅ TEMİZ |
| **B34** | Config-Docker Cross-Ref | 16 | 🟠 YÜKSEK |
| **B35** | Veritabani Sema-SQL Tutarliligi | 104 | 🟡 ORTA |
| **B36** | Async Guvenlik Yaris Kosulu | 7 | 🟠 YÜKSEK |

## 3. Kategori Bazlı Bulgu Tablosu

| Kategori | Boyut | Adet | Seviye |
|---|---|---|---|
| `MISSING_RETURN_TYPE` | B08 | **1654** | MEDIUM |
| `DEAD_CODE_FUNC` | B26 | **1564** | LOW |
| `FUNC_MISSING_DOCSTRING` | B16 | **788** | LOW |
| `INSECURE_DEFAULT` | B06 | **506** | HIGH |
| `UNDECLARED_DEPENDENCY` | B30 | **328** | HIGH |
| `CLASS_MISSING_DOCSTRING` | B16 | **121** | LOW |
| `SQL_TABLE_NOT_IN_SCHEMA` | B35 | **103** | MEDIUM |
| `PRINT_IN_PROD` | B13 | **84** | MEDIUM |
| `DUPLICATE_CLASS_NAME` | B27 | **82** | MEDIUM |
| `EXCEPT_PASS` | B03 | **60** | CRITICAL |
| `PANDAS_IN_PROD` | B05 | **49** | HIGH |
| `LOOKAHEAD_SHIFT_NEGATIVE` | B09 | **40** | HIGH |
| `DOCKER_ENV_VAR_MISSING_IN_DOTENV` | B34 | **16** | HIGH |
| `ENV_EXAMPLE_VAR_MISSING` | B12 | **15** | MEDIUM |
| `EMPTY_FUNC_PASS` | B02 | **12** | CRITICAL |
| `MISSING_CRITICAL_TEST` | B15 | **12** | HIGH |
| `OPEN_WITHOUT_WITH` | B14 | **10** | HIGH |
| `STUB_ELLIPSIS` | B02 | **9** | CRITICAL |
| `FIRE_AND_FORGET_TASK` | B36 | **7** | HIGH |
| `TODO_MARKER` | B07 | **5** | MEDIUM |
| `BARE_EXCEPT` | B03 | **5** | HIGH |
| `NOT_IMPLEMENTED_STUB` | B02 | **5** | CRITICAL |
| `SUSPICIOUS_EXTENSIONLESS_FILE` | B28 | **5** | MEDIUM |
| `INSECURE_ENV_VALUE` | B12 | **4** | CRITICAL |
| `SERVICE_INTERFACE_MISSING` | B18 | **4** | HIGH |
| `CERTIFICATE_IN_REPO` | B28 | **4** | CRITICAL |
| `BARE_EXCEPT_PASS` | B03 | **3** | CRITICAL |
| `SYNC_REQUESTS_IN_PROD` | B05 | **3** | HIGH |
| `RISK_GATE_MISSING_PARAM` | B21 | **3** | HIGH |
| `ASYNC_BLOCKING_SLEEP` | B04 | **2** | HIGH |
| `HARDCODED_SECRET` | B06 | **1** | CRITICAL |
| `SYNTAX_ERROR` | B01 | **1** | CRITICAL |
| `ASYNC_BLOCKING_REQUESTS` | B04 | **1** | CRITICAL |
| `CIRCULAR_IMPORT` | B10 | **1** | CRITICAL |
| `MISSING_INIT` | B11 | **1** | MEDIUM |
| `DECISION_INPUT_FIELD_NOT_SET` | B20 | **1** | HIGH |
| `FEATURE_REGISTERED_NOT_COMPUTED` | B23 | **1** | HIGH |
| `PORTFOLIO_CHAIN_BROKEN` | B25 | **1** | CRITICAL |
| `EXECUTE_DECISION_METHOD_MISSING` | B25 | **1** | CRITICAL |
| `MODELS_DIR_MISSING` | B31 | **1** | CRITICAL |
| `MLFLOW_TRACKING_USED` | B31 | **1** | INFO |
| `REDIS_KEY_NO_PREFIX` | B32 | **1** | MEDIUM |
| `DB_TABLES_FOUND` | B35 | **1** | INFO |

## 4. Kritik & Yüksek Öncelikli Duzeltme Listesi (1091 adet)

| # | Boyut | Seviye | Dosya | Satır | Kategori | Açıklama | Kod |
|---|---|---|---|---|---|---|---|
| 1 | B12 | **CRITICAL** | `.env` | `1` | `INSECURE_ENV_VALUE` | 'POSTGRES_PASSWORD' insecure varsayılan değer içeriyor: 'alpha_secure_pass_123' | `` |
| 2 | B12 | **CRITICAL** | `.env` | `1` | `INSECURE_ENV_VALUE` | 'CLICKHOUSE_PASSWORD' insecure varsayılan değer içeriyor: 'alpha_secure_pass_123' | `` |
| 3 | B12 | **CRITICAL** | `.env` | `1` | `INSECURE_ENV_VALUE` | 'REPLICATION_PASSWORD' insecure varsayılan değer içeriyor: 'alpha_secure_pass_123' | `` |
| 4 | B12 | **CRITICAL** | `.env` | `1` | `INSECURE_ENV_VALUE` | 'REDIS_PASSWORD' insecure varsayılan değer içeriyor: 'alpha_secure_pass_123' | `` |
| 5 | B28 | **CRITICAL** | `infrastructure/mtls/certs/ca.key` | `1` | `CERTIFICATE_IN_REPO` | Sertifika/private key dosyası repoda: 'ca.key' — versiyon kontrolünden kaldırılmalı! | `` |
| 6 | B28 | **CRITICAL** | `infrastructure/mtls/certs/client.key` | `1` | `CERTIFICATE_IN_REPO` | Sertifika/private key dosyası repoda: 'client.key' — versiyon kontrolünden kaldırılmalı! | `` |
| 7 | B28 | **CRITICAL** | `infrastructure/mtls/certs/dhparam.pem` | `1` | `CERTIFICATE_IN_REPO` | Sertifika/private key dosyası repoda: 'dhparam.pem' — versiyon kontrolünden kaldırılmalı! | `` |
| 8 | B28 | **CRITICAL** | `infrastructure/mtls/certs/server.key` | `1` | `CERTIFICATE_IN_REPO` | Sertifika/private key dosyası repoda: 'server.key' — versiyon kontrolünden kaldırılmalı! | `` |
| 9 | B03 | **CRITICAL** | `ml/models.py` | `257` | `EXCEPT_PASS` | except X: pass — fail-closed ihlali, hata maskelendi! | `except Exception:` |
| 10 | B06 | **CRITICAL** | `mock_redis.py` | `5` | `HARDCODED_SECRET` | Hardcoded kimlik bilgisi: 'alpha_se...' | `r = redis.Redis(host='redis', port=6379, db=0, password='alpha_secure_` |
| 11 | B31 | **CRITICAL** | `models/` | `1` | `MODELS_DIR_MISSING` | models/ dizini yok! Egitilmis ML model dosyalari burada olmali - inference calissamaz | `` |
| 12 | B03 | **CRITICAL** | `scratch/engine.py` | `463` | `EXCEPT_PASS` | except X: pass — fail-closed ihlali, hata maskelendi! | `except ImportError:` |
| 13 | B03 | **CRITICAL** | `scratch/engine.py` | `470` | `EXCEPT_PASS` | except X: pass — fail-closed ihlali, hata maskelendi! | `except ImportError:` |
| 14 | B03 | **CRITICAL** | `scratch/engine.py` | `477` | `EXCEPT_PASS` | except X: pass — fail-closed ihlali, hata maskelendi! | `except ImportError:` |
| 15 | B03 | **CRITICAL** | `scratch/engine.py` | `484` | `EXCEPT_PASS` | except X: pass — fail-closed ihlali, hata maskelendi! | `except ImportError:` |
| 16 | B03 | **CRITICAL** | `scratch/engine.py` | `491` | `EXCEPT_PASS` | except X: pass — fail-closed ihlali, hata maskelendi! | `except ImportError:` |
| 17 | B03 | **CRITICAL** | `scratch/engine.py` | `498` | `EXCEPT_PASS` | except X: pass — fail-closed ihlali, hata maskelendi! | `except ImportError:` |
| 18 | B03 | **CRITICAL** | `scratch/engine.py` | `505` | `EXCEPT_PASS` | except X: pass — fail-closed ihlali, hata maskelendi! | `except ImportError:` |
| 19 | B01 | **CRITICAL** | `scratch/main_backup.py` | `1` | `SYNTAX_ERROR` | SyntaxError: invalid character '�' (U+FFFD) | `��#!/usr/bin/env python3` |
| 20 | B03 | **CRITICAL** | `scratch/massive_454_backtest.py` | `104` | `BARE_EXCEPT_PASS` | except: pass — tüm hatalar yutulur, sistem kör! | `except:` |
| 21 | B03 | **CRITICAL** | `scripts/align_risk_parity_targets.py` | `19` | `EXCEPT_PASS` | except X: pass — fail-closed ihlali, hata maskelendi! | `except Exception:` |
| 22 | B03 | **CRITICAL** | `scripts/audit_timescaledb_health.py` | `250` | `EXCEPT_PASS` | except X: pass — fail-closed ihlali, hata maskelendi! | `except Exception:` |
| 23 | B03 | **CRITICAL** | `scripts/audit_timescaledb_health.py` | `284` | `EXCEPT_PASS` | except X: pass — fail-closed ihlali, hata maskelendi! | `except Exception:` |
| 24 | B03 | **CRITICAL** | `scripts/audit_timescaledb_health.py` | `311` | `EXCEPT_PASS` | except X: pass — fail-closed ihlali, hata maskelendi! | `except Exception:` |
| 25 | B03 | **CRITICAL** | `scripts/audit_timescaledb_health.py` | `331` | `EXCEPT_PASS` | except X: pass — fail-closed ihlali, hata maskelendi! | `except Exception:` |
| 26 | B03 | **CRITICAL** | `scripts/audit_timescaledb_health.py` | `357` | `EXCEPT_PASS` | except X: pass — fail-closed ihlali, hata maskelendi! | `except Exception:` |
| 27 | B03 | **CRITICAL** | `scripts/deep_comprehensive_audit.py` | `42` | `EXCEPT_PASS` | except X: pass — fail-closed ihlali, hata maskelendi! | `except Exception:` |
| 28 | B03 | **CRITICAL** | `scripts/deep_system_integrity_auditor.py` | `62` | `EXCEPT_PASS` | except X: pass — fail-closed ihlali, hata maskelendi! | `except Exception:` |
| 29 | B03 | **CRITICAL** | `scripts/deep_system_integrity_auditor.py` | `987` | `EXCEPT_PASS` | except X: pass — fail-closed ihlali, hata maskelendi! | `except Exception:` |
| 30 | B03 | **CRITICAL** | `scripts/deep_system_integrity_auditor.py` | `1236` | `EXCEPT_PASS` | except X: pass — fail-closed ihlali, hata maskelendi! | `except Exception:` |
| 31 | B03 | **CRITICAL** | `scripts/deep_system_integrity_auditor.py` | `1266` | `EXCEPT_PASS` | except X: pass — fail-closed ihlali, hata maskelendi! | `except Exception:` |
| 32 | B03 | **CRITICAL** | `scripts/deep_system_integrity_auditor.py` | `1325` | `EXCEPT_PASS` | except X: pass — fail-closed ihlali, hata maskelendi! | `except Exception:` |
| 33 | B03 | **CRITICAL** | `scripts/run_final_locked_blind_test.py` | `19` | `EXCEPT_PASS` | except X: pass — fail-closed ihlali, hata maskelendi! | `except Exception:` |
| 34 | B03 | **CRITICAL** | `scripts/run_mass_metric_optimization.py` | `22` | `EXCEPT_PASS` | except X: pass — fail-closed ihlali, hata maskelendi! | `except Exception:` |
| 35 | B03 | **CRITICAL** | `scripts/run_rigorous_quant_audit.py` | `20` | `EXCEPT_PASS` | except X: pass — fail-closed ihlali, hata maskelendi! | `except Exception:` |
| 36 | B03 | **CRITICAL** | `scripts/test_risk_parity_audit.py` | `20` | `EXCEPT_PASS` | except X: pass — fail-closed ihlali, hata maskelendi! | `except Exception:` |
| 37 | B03 | **CRITICAL** | `scripts/train_bist_ensemble.py` | `19` | `EXCEPT_PASS` | except X: pass — fail-closed ihlali, hata maskelendi! | `except Exception:` |
| 38 | B03 | **CRITICAL** | `scripts/ultimate_audit_engine.py` | `44` | `EXCEPT_PASS` | except X: pass — fail-closed ihlali, hata maskelendi! | `except Exception:` |
| 39 | B03 | **CRITICAL** | `services/agents/llm_client.py` | `448` | `EXCEPT_PASS` | except X: pass — fail-closed ihlali, hata maskelendi! | `except orjson.JSONDecodeError:` |
| 40 | B03 | **CRITICAL** | `services/agents/llm_client.py` | `456` | `EXCEPT_PASS` | except X: pass — fail-closed ihlali, hata maskelendi! | `except orjson.JSONDecodeError:` |
| 41 | B03 | **CRITICAL** | `services/agents/llm_client.py` | `464` | `EXCEPT_PASS` | except X: pass — fail-closed ihlali, hata maskelendi! | `except orjson.JSONDecodeError:` |
| 42 | B03 | **CRITICAL** | `services/api/app.py` | `260` | `EXCEPT_PASS` | except X: pass — fail-closed ihlali, hata maskelendi! | `except ImportError:` |
| 43 | B04 | **CRITICAL** | `services/api/v1/market.py` | `571` | `ASYNC_BLOCKING_REQUESTS` | async içinde senkron requests.post() — event loop kilitlenir! httpx.AsyncClient kullan | `resp = requests.post(url, json=payload, headers=headers, timeout=2.0)` |
| 44 | B03 | **CRITICAL** | `services/backtest/persistence.py` | `63` | `EXCEPT_PASS` | except X: pass — fail-closed ihlali, hata maskelendi! | `except Exception:` |
| 45 | B02 | **CRITICAL** | `services/backtest/walk_forward_engine.py` | `117` | `STUB_ELLIPSIS` | 'fit' sadece '...' — stub/placeholder kalmış | `def fit(self, X: np.ndarray, y: np.ndarray, **kwargs) -> None: ...` |
| 46 | B02 | **CRITICAL** | `services/backtest/walk_forward_engine.py` | `118` | `STUB_ELLIPSIS` | 'predict' sadece '...' — stub/placeholder kalmış | `def predict(self, X: np.ndarray) -> np.ndarray: ...` |
| 47 | B02 | **CRITICAL** | `services/backtest/walk_forward_engine.py` | `119` | `STUB_ELLIPSIS` | 'get_feature_importance' sadece '...' — stub/placeholder kalmış | `def get_feature_importance(self) -> dict[str, float]: ...` |
| 48 | B02 | **CRITICAL** | `services/backtest/walk_forward_engine.py` | `120` | `STUB_ELLIPSIS` | 'get_params' sadece '...' — stub/placeholder kalmış | `def get_params(self) -> dict[str, Any]: ...` |
| 49 | B02 | **CRITICAL** | `services/backtest/walk_forward_engine.py` | `126` | `STUB_ELLIPSIS` | 'compute_features' sadece '...' — stub/placeholder kalmış | `def compute_features(` |
| 50 | B03 | **CRITICAL** | `services/backtest/walk_forward_engine.py` | `476` | `EXCEPT_PASS` | except X: pass — fail-closed ihlali, hata maskelendi! | `except Exception:` |
| 51 | B03 | **CRITICAL** | `services/backtest/walk_forward_engine.py` | `484` | `EXCEPT_PASS` | except X: pass — fail-closed ihlali, hata maskelendi! | `except Exception:` |
| 52 | B03 | **CRITICAL** | `services/backtest/walk_forward_engine.py` | `946` | `EXCEPT_PASS` | except X: pass — fail-closed ihlali, hata maskelendi! | `except ImportError:` |
| 53 | B03 | **CRITICAL** | `services/backtest/walk_forward_engine.py` | `1183` | `EXCEPT_PASS` | except X: pass — fail-closed ihlali, hata maskelendi! | `except Exception:` |
| 54 | B03 | **CRITICAL** | `services/backtest/walk_forward_engine.py` | `1212` | `EXCEPT_PASS` | except X: pass — fail-closed ihlali, hata maskelendi! | `except ImportError:` |
| 55 | B03 | **CRITICAL** | `services/backtest/walk_forward_engine.py` | `1334` | `EXCEPT_PASS` | except X: pass — fail-closed ihlali, hata maskelendi! | `except (ValueError, TypeError):` |
| 56 | B03 | **CRITICAL** | `services/backtest/walk_forward_engine.py` | `1722` | `EXCEPT_PASS` | except X: pass — fail-closed ihlali, hata maskelendi! | `except (IndexError, KeyError, TypeError, ValueError):` |
| 57 | B03 | **CRITICAL** | `services/backtest/walk_forward_engine.py` | `1986` | `EXCEPT_PASS` | except X: pass — fail-closed ihlali, hata maskelendi! | `except (ImportError, Exception):` |
| 58 | B03 | **CRITICAL** | `services/backtest/walk_forward_engine.py` | `2119` | `EXCEPT_PASS` | except X: pass — fail-closed ihlali, hata maskelendi! | `except Exception:` |
| 59 | B03 | **CRITICAL** | `services/backtest/walk_forward_engine.py` | `2324` | `EXCEPT_PASS` | except X: pass — fail-closed ihlali, hata maskelendi! | `except Exception:` |
| 60 | B03 | **CRITICAL** | `services/backtest/walk_forward_engine.py` | `2350` | `EXCEPT_PASS` | except X: pass — fail-closed ihlali, hata maskelendi! | `except Exception:` |
| 61 | B02 | **CRITICAL** | `services/core/alerting.py` | `240` | `STUB_ELLIPSIS` | 'send' sadece '...' — stub/placeholder kalmış | `async def send(self, alert: Alert) -> bool: ...` |
| 62 | B02 | **CRITICAL** | `services/core/alerting.py` | `241` | `STUB_ELLIPSIS` | 'name' sadece '...' — stub/placeholder kalmış | `def name(self) -> str: ...` |
| 63 | B02 | **CRITICAL** | `services/core/alerting.py` | `242` | `STUB_ELLIPSIS` | 'min_severity' sadece '...' — stub/placeholder kalmış | `def min_severity(self) -> str: ...` |
| 64 | B02 | **CRITICAL** | `services/core/alerting.py` | `243` | `STUB_ELLIPSIS` | 'close' sadece '...' — stub/placeholder kalmış | `async def close(self) -> None: ...` |
| 65 | B02 | **CRITICAL** | `services/core/alerting.py` | `271` | `EMPTY_FUNC_PASS` | 'close' sadece 'pass' — tamamlanmamış implementasyon | `async def close(self) -> None:` |
| 66 | B02 | **CRITICAL** | `services/core/alerting.py` | `484` | `EMPTY_FUNC_PASS` | 'close' sadece 'pass' — tamamlanmamış implementasyon | `async def close(self) -> None:` |
| 67 | B02 | **CRITICAL** | `services/core/broker.py` | `63` | `NOT_IMPLEMENTED_STUB` | 'submit_order' NotImplementedError — tamamlanmamış implementasyon | `def submit_order(self, order: Order) -> Order:` |
| 68 | B02 | **CRITICAL** | `services/core/broker.py` | `66` | `NOT_IMPLEMENTED_STUB` | 'cancel_order' NotImplementedError — tamamlanmamış implementasyon | `def cancel_order(self, order_id: str) -> bool:` |
| 69 | B02 | **CRITICAL** | `services/core/broker.py` | `69` | `NOT_IMPLEMENTED_STUB` | 'get_order_status' NotImplementedError — tamamlanmamış implementasyon | `def get_order_status(self, order_id: str) -> Order \| None:` |
| 70 | B02 | **CRITICAL** | `services/core/broker.py` | `72` | `NOT_IMPLEMENTED_STUB` | 'get_positions' NotImplementedError — tamamlanmamış implementasyon | `def get_positions(self) -> dict[str, Any]:` |
| 71 | B02 | **CRITICAL** | `services/core/broker.py` | `75` | `NOT_IMPLEMENTED_STUB` | 'is_connected' NotImplementedError — tamamlanmamış implementasyon | `def is_connected(self) -> bool:` |
| 72 | B03 | **CRITICAL** | `services/core/connectivity.py` | `173` | `EXCEPT_PASS` | except X: pass — fail-closed ihlali, hata maskelendi! | `except asyncio.CancelledError:` |
| 73 | B03 | **CRITICAL** | `services/core/data_quality.py` | `507` | `EXCEPT_PASS` | except X: pass — fail-closed ihlali, hata maskelendi! | `except Exception:` |
| 74 | B03 | **CRITICAL** | `services/core/database.py` | `708` | `EXCEPT_PASS` | except X: pass — fail-closed ihlali, hata maskelendi! | `except Exception:` |
| 75 | B03 | **CRITICAL** | `services/core/duckdb_store.py` | `216` | `EXCEPT_PASS` | except X: pass — fail-closed ihlali, hata maskelendi! | `except (ValueError, OSError):` |
| 76 | B02 | **CRITICAL** | `services/core/observability.py` | `143` | `EMPTY_FUNC_PASS` | '__init__' sadece 'pass' — tamamlanmamış implementasyon | `def __init__(self):` |
| 77 | B03 | **CRITICAL** | `services/core/observability.py` | `221` | `EXCEPT_PASS` | except X: pass — fail-closed ihlali, hata maskelendi! | `except Exception:` |
| 78 | B25 | **CRITICAL** | `services/core/orchestrator.py` | `1` | `PORTFOLIO_CHAIN_BROKEN` | Orchestrator risk_gate.check_order çağırıyor ama portfolio_manager.execute_decision ÇAĞRILMIYOR — karar zinciri kırık! | `` |
| 79 | B02 | **CRITICAL** | `services/core/state_store.py` | `83` | `EMPTY_FUNC_PASS` | 'commit' sadece 'pass' — tamamlanmamış implementasyon | `def commit(self):` |
| 80 | B02 | **CRITICAL** | `services/core/state_store.py` | `86` | `EMPTY_FUNC_PASS` | 'close' sadece 'pass' — tamamlanmamış implementasyon | `def close(self):` |
| 81 | B02 | **CRITICAL** | `services/features/doc_generator.py` | `43` | `EMPTY_FUNC_PASS` | '__init__' sadece 'pass' — tamamlanmamış implementasyon | `def __init__(self):` |
| 82 | B03 | **CRITICAL** | `services/grpc/client.py` | `64` | `EXCEPT_PASS` | except X: pass — fail-closed ihlali, hata maskelendi! | `except ImportError:` |
| 83 | B03 | **CRITICAL** | `services/grpc/generated/market_pb2.py` | `15` | `EXCEPT_PASS` | except X: pass — fail-closed ihlali, hata maskelendi! | `except Exception:` |
| 84 | B03 | **CRITICAL** | `services/grpc/server.py` | `59` | `EXCEPT_PASS` | except X: pass — fail-closed ihlali, hata maskelendi! | `except (ImportError, Exception):` |
| 85 | B03 | **CRITICAL** | `services/institutional_backtest.py` | `125` | `BARE_EXCEPT_PASS` | except: pass — tüm hatalar yutulur, sistem kör! | `except:` |
| 86 | B10 | **CRITICAL** | `services/learning/continuous_learning.py` | `1` | `CIRCULAR_IMPORT` | Döngüsel bağımlılık: 'services/learning/continuous_learning.py' ↔ 'services/learning/super_intelligence.py' | `` |
| 87 | B02 | **CRITICAL** | `services/learning/model_memory_store.py` | `38` | `EMPTY_FUNC_PASS` | 'commit' sadece 'pass' — tamamlanmamış implementasyon | `def commit(self):` |
| 88 | B02 | **CRITICAL** | `services/learning/model_memory_store.py` | `40` | `EMPTY_FUNC_PASS` | 'close' sadece 'pass' — tamamlanmamış implementasyon | `def close(self):` |
| 89 | B02 | **CRITICAL** | `services/learning/model_memory_store.py` | `44` | `EMPTY_FUNC_PASS` | '__exit__' sadece 'pass' — tamamlanmamış implementasyon | `def __exit__(self, *args):` |
| 90 | B03 | **CRITICAL** | `services/learning/outcome_tracker.py` | `90` | `EXCEPT_PASS` | except X: pass — fail-closed ihlali, hata maskelendi! | `except Exception:` |
| 91 | B03 | **CRITICAL** | `services/learning/phase21_alpha_orthogonality.py` | `130` | `EXCEPT_PASS` | except X: pass — fail-closed ihlali, hata maskelendi! | `except Exception as e:` |
| 92 | B03 | **CRITICAL** | `services/learning/real_bist_walkforward_backtest.py` | `241` | `EXCEPT_PASS` | except X: pass — fail-closed ihlali, hata maskelendi! | `except Exception as e:` |
| 93 | B03 | **CRITICAL** | `services/learning/utils/shap_helpers.py` | `605` | `EXCEPT_PASS` | except X: pass — fail-closed ihlali, hata maskelendi! | `except Exception:` |
| 94 | B03 | **CRITICAL** | `services/massive_454_backtest.py` | `106` | `BARE_EXCEPT_PASS` | except: pass — tüm hatalar yutulur, sistem kör! | `except:` |
| 95 | B03 | **CRITICAL** | `services/ml/calibration_enhanced.py` | `149` | `EXCEPT_PASS` | except X: pass — fail-closed ihlali, hata maskelendi! | `except Exception:` |
| 96 | B03 | **CRITICAL** | `services/ml/calibration_enhanced.py` | `156` | `EXCEPT_PASS` | except X: pass — fail-closed ihlali, hata maskelendi! | `except Exception:` |
| 97 | B03 | **CRITICAL** | `services/nats/client.py` | `187` | `EXCEPT_PASS` | except X: pass — fail-closed ihlali, hata maskelendi! | `except Exception:` |
| 98 | B03 | **CRITICAL** | `services/nats/client.py` | `258` | `EXCEPT_PASS` | except X: pass — fail-closed ihlali, hata maskelendi! | `except Exception:` |
| 99 | B03 | **CRITICAL** | `services/nats/client.py` | `360` | `EXCEPT_PASS` | except X: pass — fail-closed ihlali, hata maskelendi! | `except (ImportError, LookupError):` |
| 100 | B03 | **CRITICAL** | `services/nats/client.py` | `378` | `EXCEPT_PASS` | except X: pass — fail-closed ihlali, hata maskelendi! | `except (ImportError, LookupError):` |
| 101 | B25 | **CRITICAL** | `services/portfolio/portfolio_manager.py` | `1` | `EXECUTE_DECISION_METHOD_MISSING` | PortfolioManager.execute_decision metodu tanımlı değil — portfolio güncellenemiyor! | `` |
| 102 | B02 | **CRITICAL** | `services/tasks/queue.py` | `186` | `EMPTY_FUNC_PASS` | 'update_state' sadece 'pass' — tamamlanmamış implementasyon | `def update_state(self, state=None, meta=None):` |
| 103 | B02 | **CRITICAL** | `tests/test_policy_resilience.py` | `467` | `EMPTY_FUNC_PASS` | 'execute' sadece 'pass' — tamamlanmamış implementasyon | `def execute(self, *args):` |
| 104 | B02 | **CRITICAL** | `tests/test_policy_resilience.py` | `473` | `EMPTY_FUNC_PASS` | 'rollback' sadece 'pass' — tamamlanmamış implementasyon | `def rollback(self):` |
| 105 | B34 | **HIGH** | `.env` | `1` | `DOCKER_ENV_VAR_MISSING_IN_DOTENV` | docker-compose.yml'de '${API_URL}' kullaniliyor ama .env'de tanimsiz - servis baslamaz | `` |
| 106 | B34 | **HIGH** | `.env` | `1` | `DOCKER_ENV_VAR_MISSING_IN_DOTENV` | docker-compose.yml'de '${AUTOHEAL_CONTAINER_LABEL}' kullaniliyor ama .env'de tanimsiz - servis baslamaz | `` |
| 107 | B34 | **HIGH** | `.env` | `1` | `DOCKER_ENV_VAR_MISSING_IN_DOTENV` | docker-compose.yml'de '${AUTOHEAL_INTERVAL}' kullaniliyor ama .env'de tanimsiz - servis baslamaz | `` |
| 108 | B34 | **HIGH** | `.env` | `1` | `DOCKER_ENV_VAR_MISSING_IN_DOTENV` | docker-compose.yml'de '${AUTOHEAL_START_PERIOD}' kullaniliyor ama .env'de tanimsiz - servis baslamaz | `` |
| 109 | B34 | **HIGH** | `.env` | `1` | `DOCKER_ENV_VAR_MISSING_IN_DOTENV` | docker-compose.yml'de '${GRPC_HOSTS}' kullaniliyor ama .env'de tanimsiz - servis baslamaz | `` |
| 110 | B34 | **HIGH** | `.env` | `1` | `DOCKER_ENV_VAR_MISSING_IN_DOTENV` | docker-compose.yml'de '${GRPC_PORT}' kullaniliyor ama .env'de tanimsiz - servis baslamaz | `` |
| 111 | B34 | **HIGH** | `.env` | `1` | `DOCKER_ENV_VAR_MISSING_IN_DOTENV` | docker-compose.yml'de '${MTLS_CA_CERT}' kullaniliyor ama .env'de tanimsiz - servis baslamaz | `` |
| 112 | B34 | **HIGH** | `.env` | `1` | `DOCKER_ENV_VAR_MISSING_IN_DOTENV` | docker-compose.yml'de '${MTLS_CLIENT_CERT}' kullaniliyor ama .env'de tanimsiz - servis baslamaz | `` |
| 113 | B34 | **HIGH** | `.env` | `1` | `DOCKER_ENV_VAR_MISSING_IN_DOTENV` | docker-compose.yml'de '${MTLS_CLIENT_KEY}' kullaniliyor ama .env'de tanimsiz - servis baslamaz | `` |
| 114 | B34 | **HIGH** | `.env` | `1` | `DOCKER_ENV_VAR_MISSING_IN_DOTENV` | docker-compose.yml'de '${MTLS_SERVER_CERT}' kullaniliyor ama .env'de tanimsiz - servis baslamaz | `` |
| 115 | B34 | **HIGH** | `.env` | `1` | `DOCKER_ENV_VAR_MISSING_IN_DOTENV` | docker-compose.yml'de '${MTLS_SERVER_KEY}' kullaniliyor ama .env'de tanimsiz - servis baslamaz | `` |
| 116 | B34 | **HIGH** | `.env` | `1` | `DOCKER_ENV_VAR_MISSING_IN_DOTENV` | docker-compose.yml'de '${NATS_URL}' kullaniliyor ama .env'de tanimsiz - servis baslamaz | `` |
| 117 | B34 | **HIGH** | `.env` | `1` | `DOCKER_ENV_VAR_MISSING_IN_DOTENV` | docker-compose.yml'de '${NVIDIA_DRIVER_CAPABILITIES}' kullaniliyor ama .env'de tanimsiz - servis baslamaz | `` |
| 118 | B34 | **HIGH** | `.env` | `1` | `DOCKER_ENV_VAR_MISSING_IN_DOTENV` | docker-compose.yml'de '${NVIDIA_VISIBLE_DEVICES}' kullaniliyor ama .env'de tanimsiz - servis baslamaz | `` |
| 119 | B34 | **HIGH** | `.env` | `1` | `DOCKER_ENV_VAR_MISSING_IN_DOTENV` | docker-compose.yml'de '${REDIS_SENTINEL_HOSTS}' kullaniliyor ama .env'de tanimsiz - servis baslamaz | `` |
| 120 | B34 | **HIGH** | `.env` | `1` | `DOCKER_ENV_VAR_MISSING_IN_DOTENV` | docker-compose.yml'de '${REDIS_SENTINEL_MASTER}' kullaniliyor ama .env'de tanimsiz - servis baslamaz | `` |
| 121 | B06 | **HIGH** | `benchmarks/tech_benchmarks.py` | `60` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'test' | `"test": "JSON Serialization (ORJSON vs json)",` |
| 122 | B06 | **HIGH** | `benchmarks/tech_benchmarks.py` | `122` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'test' | `"test": "DataFrame Processing (Polars vs Pandas)",` |
| 123 | B06 | **HIGH** | `benchmarks/tech_benchmarks.py` | `130` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'test' | `return {"test": "DataFrame Processing", "error": str(e)}` |
| 124 | B06 | **HIGH** | `benchmarks/tech_benchmarks.py` | `157` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'test' | `results = {"test": "ML Training (LightGBM vs CatBoost vs XGBoost)", "m` |
| 125 | B06 | **HIGH** | `benchmarks/tech_benchmarks.py` | `209` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'test' | `return {"test": "ML Training", "error": str(e)}` |
| 126 | B30 | **HIGH** | `ml/feature_discovery.py` | `1` | `UNDECLARED_DEPENDENCY` | 'shap' import ediliyor ama pyproject.toml'da tanimli degil (7 dosyada) | `` |
| 127 | B06 | **HIGH** | `mock_redis.py` | `5` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'alpha_secure_pass_123' | `r = redis.Redis(host='redis', port=6379, db=0, password='alpha_secure_` |
| 128 | B03 | **HIGH** | `scratch/audit_generator.py` | `83` | `BARE_EXCEPT` | Bare 'except:' — KeyboardInterrupt dahil her şeyi yakalar | `except:` |
| 129 | B06 | **HIGH** | `scratch/debug_engine.py` | `9` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'Test' | `res = backtest_engine.run_backtest("Test", signals, price_data)` |
| 130 | B14 | **HIGH** | `scratch/engine.py` | `170` | `OPEN_WITHOUT_WITH` | open() 'with' bloğu olmadan — dosya kapanmayabilir (kaynak sızıntısı) | `trades_file = open(trades_csv_path, 'w', newline='', encoding='utf-8')` |
| 131 | B14 | **HIGH** | `scratch/engine.py` | `171` | `OPEN_WITHOUT_WITH` | open() 'with' bloğu olmadan — dosya kapanmayabilir (kaynak sızıntısı) | `daily_file = open(daily_csv_path, 'w', newline='', encoding='utf-8')` |
| 132 | B03 | **HIGH** | `scratch/generate_folds.py` | `12` | `BARE_EXCEPT` | Bare 'except:' — KeyboardInterrupt dahil her şeyi yakalar | `except:` |
| 133 | B03 | **HIGH** | `scratch/massive_454_backtest.py` | `117` | `BARE_EXCEPT` | Bare 'except:' — KeyboardInterrupt dahil her şeyi yakalar | `except:` |
| 134 | B14 | **HIGH** | `scratch/patch_continuous.py` | `52` | `OPEN_WITHOUT_WITH` | open() 'with' bloğu olmadan — dosya kapanmayabilir (kaynak sızıntısı) | `trades_file = open(trades_csv_path, 'w', newline='', encoding='utf-8')` |
| 135 | B14 | **HIGH** | `scratch/patch_continuous.py` | `53` | `OPEN_WITHOUT_WITH` | open() 'with' bloğu olmadan — dosya kapanmayabilir (kaynak sızıntısı) | `daily_file = open(daily_csv_path, 'w', newline='', encoding='utf-8')` |
| 136 | B14 | **HIGH** | `scratch/patch_engine_canonical.py` | `45` | `OPEN_WITHOUT_WITH` | open() 'with' bloğu olmadan — dosya kapanmayabilir (kaynak sızıntısı) | `trades_file = open(trades_csv_path, 'a', newline='', encoding='utf-8')` |
| 137 | B14 | **HIGH** | `scratch/patch_engine_canonical.py` | `46` | `OPEN_WITHOUT_WITH` | open() 'with' bloğu olmadan — dosya kapanmayabilir (kaynak sızıntısı) | `daily_file = open(daily_csv_path, 'a', newline='', encoding='utf-8')` |
| 138 | B14 | **HIGH** | `scripts/_patch_auditor.py` | `5` | `OPEN_WITHOUT_WITH` | open() 'with' bloğu olmadan — dosya kapanmayabilir (kaynak sızıntısı) | `p = open(SRC, "rb").read()` |
| 139 | B14 | **HIGH** | `scripts/_patch_auditor2.py` | `433` | `OPEN_WITHOUT_WITH` | open() 'with' bloğu olmadan — dosya kapanmayabilir (kaynak sızıntısı) | `src = open(SRC, "r", encoding="utf-8", errors="replace").read()` |
| 140 | B06 | **HIGH** | `scripts/deep_comprehensive_audit.py` | `305` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'test' | `if m_sec and not any(safe in line.lower() for safe in ("os.getenv", "s` |
| 141 | B06 | **HIGH** | `scripts/deep_system_integrity_auditor.py` | `74` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'change-this' | `"change-this", "change-me", "password", "secret",` |
| 142 | B06 | **HIGH** | `scripts/deep_system_integrity_auditor.py` | `75` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'alpha_secure_2026' | `"alpha_secure_2026", "admin", "default", "test",` |
| 143 | B06 | **HIGH** | `scripts/deep_system_integrity_auditor.py` | `76` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'alpha_secure_pass_123' | `"alpha_secure_pass_123",` |
| 144 | B06 | **HIGH** | `scripts/deep_system_integrity_auditor.py` | `409` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'test' | `if not rel.endswith((".example", "_test.py")) and "test" not in rel:` |
| 145 | B21 | **HIGH** | `scripts/deep_system_integrity_auditor.py` | `594` | `RISK_GATE_MISSING_PARAM` | risk_gate.check_order() çağrısında zorunlu parametreler eksik: ['price', 'portfolio_value', 'side', 'current_positions', 'ticker', 'quantity'] | `` |
| 146 | B06 | **HIGH** | `scripts/deep_system_integrity_auditor.py` | `768` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'test' | `if "test" in rel or rel.startswith("scripts/") or "scratch" in rel:` |
| 147 | B06 | **HIGH** | `scripts/full_system_audit.py` | `353` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'TEST' | `ticker="TEST", open_price=0, high=-1, low=-2, close=-1, volume=0, prev` |
| 148 | B06 | **HIGH** | `scripts/full_system_audit.py` | `1171` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'TEST' | `calibrator.add_trade(score=2.0, return_pct=5.0, ticker="TEST", date="2` |
| 149 | B06 | **HIGH** | `scripts/full_system_audit.py` | `1224` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'TEST' | `{"ticker": "TEST", "score": 2.0, "confidence": 0.6, "expected_return":` |
| 150 | B06 | **HIGH** | `scripts/full_system_audit.py` | `2131` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'TEST' | `"TEST", df["Open"].values, df["High"].values, df["Low"].values, df["Cl` |
| 151 | B06 | **HIGH** | `scripts/full_system_audit.py` | `2134` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'TEST' | `features1 = feature_calculator.compute_all_features(df, mask=mask.mask` |
| 152 | B06 | **HIGH** | `scripts/full_system_audit.py` | `2140` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'TEST' | `"TEST",` |
| 153 | B06 | **HIGH** | `scripts/full_system_audit.py` | `2147` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'TEST' | `features2 = feature_calculator.compute_all_features(df_modified, mask=` |
| 154 | B06 | **HIGH** | `scripts/ultimate_audit_engine.py` | `81` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'change-this' | `"change-this", "change-me", "password", "secret",` |
| 155 | B06 | **HIGH** | `scripts/ultimate_audit_engine.py` | `82` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'alpha_secure_2026' | `"alpha_secure_2026", "admin", "default", "test",` |
| 156 | B06 | **HIGH** | `scripts/ultimate_audit_engine.py` | `83` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'alpha_secure_pass_123' | `"alpha_secure_pass_123",` |
| 157 | B06 | **HIGH** | `scripts/ultimate_audit_engine.py` | `476` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'test' | `if not rel.endswith((".example", ".sample", "_test.py")) and "test" no` |
| 158 | B06 | **HIGH** | `scripts/verify_full_system_holiday_integration.py` | `112` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'Test' | `hm.add_manual_holiday(date(2026,12,31), "Test")` |
| 159 | B06 | **HIGH** | `scripts/verify_holiday_system_real_world.py` | `452` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'Test' | `hm.add_manual_holiday(test_date, "Test")` |
| 160 | B30 | **HIGH** | `services/agents/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'agent_pipeline' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 161 | B30 | **HIGH** | `services/agents/agent_pipeline.py` | `1` | `UNDECLARED_DEPENDENCY` | 'conflict_detector' import ediliyor ama pyproject.toml'da tanimli degil (2 dosyada) | `` |
| 162 | B30 | **HIGH** | `services/agents/agent_pipeline.py` | `1` | `UNDECLARED_DEPENDENCY` | 'agent_system' import ediliyor ama pyproject.toml'da tanimli degil (8 dosyada) | `` |
| 163 | B30 | **HIGH** | `services/agents/agent_pipeline.py` | `1` | `UNDECLARED_DEPENDENCY` | 'communication_bus' import ediliyor ama pyproject.toml'da tanimli degil (3 dosyada) | `` |
| 164 | B30 | **HIGH** | `services/agents/agent_pipeline.py` | `1` | `UNDECLARED_DEPENDENCY` | 'prompts' import ediliyor ama pyproject.toml'da tanimli degil (5 dosyada) | `` |
| 165 | B30 | **HIGH** | `services/agents/agent_pipeline.py` | `1` | `UNDECLARED_DEPENDENCY` | 'synthesis_engine' import ediliyor ama pyproject.toml'da tanimli degil (2 dosyada) | `` |
| 166 | B30 | **HIGH** | `services/agents/agent_pipeline.py` | `1` | `UNDECLARED_DEPENDENCY` | 'risk_assessor' import ediliyor ama pyproject.toml'da tanimli degil (2 dosyada) | `` |
| 167 | B30 | **HIGH** | `services/agents/agent_pipeline.py` | `1` | `UNDECLARED_DEPENDENCY` | 'self_evaluator' import ediliyor ama pyproject.toml'da tanimli degil (2 dosyada) | `` |
| 168 | B30 | **HIGH** | `services/agents/agent_pipeline.py` | `1` | `UNDECLARED_DEPENDENCY` | 'parallel_runner' import ediliyor ama pyproject.toml'da tanimli degil (2 dosyada) | `` |
| 169 | B30 | **HIGH** | `services/agents/agent_pipeline.py` | `1` | `UNDECLARED_DEPENDENCY` | 'llm_client' import ediliyor ama pyproject.toml'da tanimli degil (7 dosyada) | `` |
| 170 | B30 | **HIGH** | `services/agents/agent_pipeline.py` | `1` | `UNDECLARED_DEPENDENCY` | 'debate_engine' import ediliyor ama pyproject.toml'da tanimli degil (3 dosyada) | `` |
| 171 | B30 | **HIGH** | `services/agents/agent_pipeline.py` | `1` | `UNDECLARED_DEPENDENCY` | 'agent_memory' import ediliyor ama pyproject.toml'da tanimli degil (4 dosyada) | `` |
| 172 | B30 | **HIGH** | `services/agents/agent_system.py` | `1` | `UNDECLARED_DEPENDENCY` | 'schemas' import ediliyor ama pyproject.toml'da tanimli degil (2 dosyada) | `` |
| 173 | B30 | **HIGH** | `services/agents/llm_client.py` | `1` | `UNDECLARED_DEPENDENCY` | 'aiohttp' import ediliyor ama pyproject.toml'da tanimli degil (21 dosyada) | `` |
| 174 | B30 | **HIGH** | `services/alternative/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'credit_card' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 175 | B30 | **HIGH** | `services/alternative/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'web_scraping' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 176 | B30 | **HIGH** | `services/alternative/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'social' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 177 | B30 | **HIGH** | `services/alternative/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'feature_engine' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 178 | B30 | **HIGH** | `services/alternative/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'satellite' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 179 | B30 | **HIGH** | `services/alternative/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'jobs' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 180 | B30 | **HIGH** | `services/alternative/bkm_adapter.py` | `1` | `UNDECLARED_DEPENDENCY` | 'bs4' import ediliyor ama pyproject.toml'da tanimli degil (4 dosyada) | `` |
| 181 | B30 | **HIGH** | `services/alternative/bkm_adapter.py` | `1` | `UNDECLARED_DEPENDENCY` | 'base' import ediliyor ama pyproject.toml'da tanimli degil (8 dosyada) | `` |
| 182 | B30 | **HIGH** | `services/alternative/feature_engine.py` | `1` | `UNDECLARED_DEPENDENCY` | 'satellite_adapter' import ediliyor ama pyproject.toml'da tanimli degil (2 dosyada) | `` |
| 183 | B30 | **HIGH** | `services/alternative/feature_engine.py` | `1` | `UNDECLARED_DEPENDENCY` | 'bkm_adapter' import ediliyor ama pyproject.toml'da tanimli degil (2 dosyada) | `` |
| 184 | B30 | **HIGH** | `services/alternative/feature_engine.py` | `1` | `UNDECLARED_DEPENDENCY` | 'llm_sentiment' import ediliyor ama pyproject.toml'da tanimli degil (2 dosyada) | `` |
| 185 | B30 | **HIGH** | `services/alternative/feature_engine.py` | `1` | `UNDECLARED_DEPENDENCY` | 'eksi_sozluk' import ediliyor ama pyproject.toml'da tanimli degil (2 dosyada) | `` |
| 186 | B30 | **HIGH** | `services/alternative/feature_engine.py` | `1` | `UNDECLARED_DEPENDENCY` | 'investing_adapter' import ediliyor ama pyproject.toml'da tanimli degil (2 dosyada) | `` |
| 187 | B30 | **HIGH** | `services/alternative/feature_engine.py` | `1` | `UNDECLARED_DEPENDENCY` | 'google_trends' import ediliyor ama pyproject.toml'da tanimli degil (2 dosyada) | `` |
| 188 | B30 | **HIGH** | `services/alternative/feature_engine.py` | `1` | `UNDECLARED_DEPENDENCY` | 'kariyer_net' import ediliyor ama pyproject.toml'da tanimli degil (2 dosyada) | `` |
| 189 | B30 | **HIGH** | `services/alternative/feature_engine.py` | `1` | `UNDECLARED_DEPENDENCY` | 'feature_store' import ediliyor ama pyproject.toml'da tanimli degil (2 dosyada) | `` |
| 190 | B30 | **HIGH** | `services/alternative/feature_engine.py` | `1` | `UNDECLARED_DEPENDENCY` | 'reconciliation' import ediliyor ama pyproject.toml'da tanimli degil (4 dosyada) | `` |
| 191 | B30 | **HIGH** | `services/alternative/google_trends.py` | `1` | `UNDECLARED_DEPENDENCY` | 'pytrends' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 192 | B06 | **HIGH** | `services/alternative/kariyer_net.py` | `169` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'test' | `"test",` |
| 193 | B06 | **HIGH** | `services/alternative/llm_sentiment.py` | `278` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'default' | `"source": "default",` |
| 194 | B30 | **HIGH** | `services/alternative/satellite_adapter.py` | `1` | `UNDECLARED_DEPENDENCY` | 'rasterio' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 195 | B06 | **HIGH** | `services/alternative/satellite_adapter.py` | `236` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'default' | `"responses": [{"identifier": "default", "format": {"type": "image/tiff` |
| 196 | B30 | **HIGH** | `services/api/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'dependencies' import ediliyor ama pyproject.toml'da tanimli degil (18 dosyada) | `` |
| 197 | B30 | **HIGH** | `services/api/app.py` | `1` | `UNDECLARED_DEPENDENCY` | 'core' import ediliyor ama pyproject.toml'da tanimli degil (86 dosyada) | `` |
| 198 | B30 | **HIGH** | `services/api/app.py` | `1` | `UNDECLARED_DEPENDENCY` | 'starlette' import ediliyor ama pyproject.toml'da tanimli degil (3 dosyada) | `` |
| 199 | B30 | **HIGH** | `services/api/app.py` | `1` | `UNDECLARED_DEPENDENCY` | 'v1' import ediliyor ama pyproject.toml'da tanimli degil (3 dosyada) | `` |
| 200 | B30 | **HIGH** | `services/api/app.py` | `1` | `UNDECLARED_DEPENDENCY` | 'grpc' import ediliyor ama pyproject.toml'da tanimli degil (7 dosyada) | `` |
| 201 | B30 | **HIGH** | `services/api/app.py` | `1` | `UNDECLARED_DEPENDENCY` | 'nats' import ediliyor ama pyproject.toml'da tanimli degil (4 dosyada) | `` |
| 202 | B30 | **HIGH** | `services/api/app.py` | `1` | `UNDECLARED_DEPENDENCY` | 'background_tasks' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 203 | B30 | **HIGH** | `services/api/app.py` | `1` | `UNDECLARED_DEPENDENCY` | 'opentelemetry' import ediliyor ama pyproject.toml'da tanimli degil (110 dosyada) | `` |
| 204 | B30 | **HIGH** | `services/api/app.py` | `1` | `UNDECLARED_DEPENDENCY` | 'rate_limiter' import ediliyor ama pyproject.toml'da tanimli degil (6 dosyada) | `` |
| 205 | B30 | **HIGH** | `services/api/background_tasks.py` | `1` | `UNDECLARED_DEPENDENCY` | 'learning' import ediliyor ama pyproject.toml'da tanimli degil (4 dosyada) | `` |
| 206 | B30 | **HIGH** | `services/api/dependencies.py` | `1` | `UNDECLARED_DEPENDENCY` | 'auth' import ediliyor ama pyproject.toml'da tanimli degil (2 dosyada) | `` |
| 207 | B30 | **HIGH** | `services/api/main.py` | `1` | `UNDECLARED_DEPENDENCY` | 'app' import ediliyor ama pyproject.toml'da tanimli degil (2 dosyada) | `` |
| 208 | B06 | **HIGH** | `services/api/rate_limiter.py` | `35` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'default' | `"default": RateLimitConfig(max_requests=1000, window_seconds=60),` |
| 209 | B06 | **HIGH** | `services/api/rate_limiter.py` | `62` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'default' | `group: str = "default",` |
| 210 | B06 | **HIGH** | `services/api/rate_limiter.py` | `73` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'default' | `config = RATE_LIMITS.get(group, RATE_LIMITS["default"])` |
| 211 | B06 | **HIGH** | `services/api/rate_limiter.py` | `114` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'default' | `return "default"` |
| 212 | B06 | **HIGH** | `services/api/rate_limiter.py` | `116` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'default' | `def reset(self, client_id: str, group: str = "default"):` |
| 213 | B30 | **HIGH** | `services/api/v1/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'decisions' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 214 | B30 | **HIGH** | `services/api/v1/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'holidays' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 215 | B30 | **HIGH** | `services/api/v1/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'alternative' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 216 | B30 | **HIGH** | `services/api/v1/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'models' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 217 | B30 | **HIGH** | `services/api/v1/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'system' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 218 | B30 | **HIGH** | `services/api/v1/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'sse' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 219 | B30 | **HIGH** | `services/api/v1/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'market' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 220 | B30 | **HIGH** | `services/api/v1/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'agents' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 221 | B30 | **HIGH** | `services/api/v1/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'event_study' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 222 | B30 | **HIGH** | `services/api/v1/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'ws' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 223 | B30 | **HIGH** | `services/api/v1/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'factors' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 224 | B30 | **HIGH** | `services/api/v1/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'macro' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 225 | B30 | **HIGH** | `services/api/v1/alternative.py` | `1` | `UNDECLARED_DEPENDENCY` | 'ingestion' import ediliyor ama pyproject.toml'da tanimli degil (15 dosyada) | `` |
| 226 | B30 | **HIGH** | `services/api/v1/intelligence.py` | `1` | `UNDECLARED_DEPENDENCY` | 'scanner' import ediliyor ama pyproject.toml'da tanimli degil (5 dosyada) | `` |
| 227 | B30 | **HIGH** | `services/api/v1/intelligence.py` | `1` | `UNDECLARED_DEPENDENCY` | 'intelligence' import ediliyor ama pyproject.toml'da tanimli degil (11 dosyada) | `` |
| 228 | B30 | **HIGH** | `services/api/v1/market.py` | `1` | `UNDECLARED_DEPENDENCY` | 'requests' import ediliyor ama pyproject.toml'da tanimli degil (3 dosyada) | `` |
| 229 | B30 | **HIGH** | `services/api/v1/market.py` | `1` | `UNDECLARED_DEPENDENCY` | 'data' import ediliyor ama pyproject.toml'da tanimli degil (5 dosyada) | `` |
| 230 | B05 | **HIGH** | `services/api/v1/market.py` | `298` | `PANDAS_IN_PROD` | 'pandas' import — proje standardı Polars zorunludur! | `import pandas as pd` |
| 231 | B05 | **HIGH** | `services/api/v1/market.py` | `536` | `SYNC_REQUESTS_IN_PROD` | 'requests' import — async servislerde httpx.AsyncClient kullanılmalı | `import requests` |
| 232 | B30 | **HIGH** | `services/api/v1/portfolio.py` | `1` | `UNDECLARED_DEPENDENCY` | 'pipeline' import ediliyor ama pyproject.toml'da tanimli degil (5 dosyada) | `` |
| 233 | B30 | **HIGH** | `services/api/v1/portfolio.py` | `1` | `UNDECLARED_DEPENDENCY` | 'portfolio' import ediliyor ama pyproject.toml'da tanimli degil (3 dosyada) | `` |
| 234 | B30 | **HIGH** | `services/api/v1/risk.py` | `1` | `UNDECLARED_DEPENDENCY` | 'risk' import ediliyor ama pyproject.toml'da tanimli degil (14 dosyada) | `` |
| 235 | B36 | **HIGH** | `services/api/v1/scanner.py` | `464` | `FIRE_AND_FORGET_TASK` | asyncio.create_task() sonucu degiskene atilmamis - exception sessizce kaybolur | `` |
| 236 | B30 | **HIGH** | `services/api/v1/viop.py` | `1` | `UNDECLARED_DEPENDENCY` | 'viop' import ediliyor ama pyproject.toml'da tanimli degil (4 dosyada) | `` |
| 237 | B30 | **HIGH** | `services/api/v1/ws.py` | `1` | `UNDECLARED_DEPENDENCY` | 'binary_ws' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 238 | B30 | **HIGH** | `services/backtest/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'pit_validator' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 239 | B30 | **HIGH** | `services/backtest/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'benchmark' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 240 | B30 | **HIGH** | `services/backtest/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'scanner_parity' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 241 | B30 | **HIGH** | `services/backtest/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'multi_asset_engine' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 242 | B30 | **HIGH** | `services/backtest/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'deterministic' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 243 | B30 | **HIGH** | `services/backtest/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'survivorship' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 244 | B30 | **HIGH** | `services/backtest/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'event_replay' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 245 | B30 | **HIGH** | `services/backtest/engine.py` | `1` | `UNDECLARED_DEPENDENCY` | 'canonical_adapter' import ediliyor ama pyproject.toml'da tanimli degil (2 dosyada) | `` |
| 246 | B30 | **HIGH** | `services/backtest/engine.py` | `1` | `UNDECLARED_DEPENDENCY` | 'enhanced_walk_forward' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 247 | B30 | **HIGH** | `services/backtest/engine.py` | `1` | `UNDECLARED_DEPENDENCY` | 'engine_v4' import ediliyor ama pyproject.toml'da tanimli degil (3 dosyada) | `` |
| 248 | B30 | **HIGH** | `services/backtest/engine.py` | `1` | `UNDECLARED_DEPENDENCY` | 'portfolio_sim' import ediliyor ama pyproject.toml'da tanimli degil (3 dosyada) | `` |
| 249 | B30 | **HIGH** | `services/backtest/engine.py` | `1` | `UNDECLARED_DEPENDENCY` | 'persistence' import ediliyor ama pyproject.toml'da tanimli degil (3 dosyada) | `` |
| 250 | B30 | **HIGH** | `services/backtest/engine.py` | `1` | `UNDECLARED_DEPENDENCY` | 'walk_forward' import ediliyor ama pyproject.toml'da tanimli degil (3 dosyada) | `` |
| 251 | B30 | **HIGH** | `services/backtest/engine.py` | `1` | `UNDECLARED_DEPENDENCY` | 'walk_forward_runner' import ediliyor ama pyproject.toml'da tanimli degil (2 dosyada) | `` |
| 252 | B14 | **HIGH** | `services/backtest/engine.py` | `459` | `OPEN_WITHOUT_WITH` | open() 'with' bloğu olmadan — dosya kapanmayabilir (kaynak sızıntısı) | `trades_file = open(trades_csv_path, "w", newline="", encoding="utf-8")` |
| 253 | B14 | **HIGH** | `services/backtest/engine.py` | `460` | `OPEN_WITHOUT_WITH` | open() 'with' bloğu olmadan — dosya kapanmayabilir (kaynak sızıntısı) | `daily_file = open(daily_csv_path, "w", newline="", encoding="utf-8")` |
| 254 | B30 | **HIGH** | `services/backtest/engine_v4.py` | `1` | `UNDECLARED_DEPENDENCY` | 'features' import ediliyor ama pyproject.toml'da tanimli degil (7 dosyada) | `` |
| 255 | B30 | **HIGH** | `services/backtest/multi_asset_engine.py` | `1` | `UNDECLARED_DEPENDENCY` | 'transaction_costs' import ediliyor ama pyproject.toml'da tanimli degil (4 dosyada) | `` |
| 256 | B30 | **HIGH** | `services/backtest/multi_asset_engine.py` | `1` | `UNDECLARED_DEPENDENCY` | 'bias_detector' import ediliyor ama pyproject.toml'da tanimli degil (2 dosyada) | `` |
| 257 | B06 | **HIGH** | `services/backtest/walk_forward.py` | `192` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'TEST' | `ticker = s.get("ticker", "TEST")` |
| 258 | B30 | **HIGH** | `services/backtest/walk_forward_engine.py` | `1` | `UNDECLARED_DEPENDENCY` | 'deflated_sharpe' import ediliyor ama pyproject.toml'da tanimli degil (2 dosyada) | `` |
| 259 | B30 | **HIGH** | `services/backtest/walk_forward_runner.py` | `1` | `UNDECLARED_DEPENDENCY` | 'walk_forward_engine' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 260 | B30 | **HIGH** | `services/core/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'short_selling' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 261 | B30 | **HIGH** | `services/core/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'config_hot_reload' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 262 | B30 | **HIGH** | `services/core/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'price_limits' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 263 | B30 | **HIGH** | `services/core/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'distributed_tracing' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 264 | B30 | **HIGH** | `services/core/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'circuit_breaker_metrics' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 265 | B30 | **HIGH** | `services/core/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'tax' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 266 | B30 | **HIGH** | `services/core/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'gross_settlement' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 267 | B30 | **HIGH** | `services/core/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'system_governor' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 268 | B30 | **HIGH** | `services/core/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'fee_calculator' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 269 | B30 | **HIGH** | `services/core/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'settlement' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 270 | B30 | **HIGH** | `services/core/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'immutable_audit' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 271 | B30 | **HIGH** | `services/core/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'bist_tick_size' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 272 | B30 | **HIGH** | `services/core/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'tradability_mask' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 273 | B30 | **HIGH** | `services/core/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'market_calendar' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 274 | B30 | **HIGH** | `services/core/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'risk_gate' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 275 | B30 | **HIGH** | `services/core/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'halt_monitor' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 276 | B30 | **HIGH** | `services/core/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'compliance' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 277 | B30 | **HIGH** | `services/core/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'transaction_helper' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 278 | B30 | **HIGH** | `services/core/alerting.py` | `1` | `UNDECLARED_DEPENDENCY` | 'smtplib' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 279 | B30 | **HIGH** | `services/core/alerting.py` | `1` | `UNDECLARED_DEPENDENCY` | 'alert_policy' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 280 | B30 | **HIGH** | `services/core/arrow_pipeline.py` | `1` | `UNDECLARED_DEPENDENCY` | 'pyarrow' import ediliyor ama pyproject.toml'da tanimli degil (3 dosyada) | `` |
| 281 | B30 | **HIGH** | `services/core/cache_warmer.py` | `1` | `UNDECLARED_DEPENDENCY` | 'api' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 282 | B15 | **HIGH** | `services/core/circuit_breaker.py` | `1` | `MISSING_CRITICAL_TEST` | Kritik modül 'services/core/circuit_breaker.py' için test yok (beklenen: test_circuit_breaker.py) | `` |
| 283 | B30 | **HIGH** | `services/core/circuit_breaker.py` | `1` | `UNDECLARED_DEPENDENCY` | 'state_store' import ediliyor ama pyproject.toml'da tanimli degil (5 dosyada) | `` |
| 284 | B30 | **HIGH** | `services/core/clickhouse_replication_health.py` | `1` | `UNDECLARED_DEPENDENCY` | 'database' import ediliyor ama pyproject.toml'da tanimli degil (7 dosyada) | `` |
| 285 | B06 | **HIGH** | `services/core/config_loader.py` | `145` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'test' | `return self._environment == "test"` |
| 286 | B15 | **HIGH** | `services/core/data_quality.py` | `1` | `MISSING_CRITICAL_TEST` | Kritik modül 'services/core/data_quality.py' için test yok (beklenen: test_data_quality.py) | `` |
| 287 | B15 | **HIGH** | `services/core/database.py` | `1` | `MISSING_CRITICAL_TEST` | Kritik modül 'services/core/database.py' için test yok (beklenen: test_database.py) | `` |
| 288 | B30 | **HIGH** | `services/core/database.py` | `1` | `UNDECLARED_DEPENDENCY` | 'redis_sentinel' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 289 | B30 | **HIGH** | `services/core/database.py` | `1` | `UNDECLARED_DEPENDENCY` | 'questdb_client' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 290 | B06 | **HIGH** | `services/core/db_lock.py` | `208` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'default' | `key: str = "default",` |
| 291 | B06 | **HIGH** | `services/core/db_lock.py` | `573` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'default' | `def __init__(self, db, dialect: str = "postgresql", key: str = "defaul` |
| 292 | B30 | **HIGH** | `services/core/dead_letter_queue.py` | `1` | `UNDECLARED_DEPENDENCY` | 'persistent_dlq' import ediliyor ama pyproject.toml'da tanimli degil (2 dosyada) | `` |
| 293 | B15 | **HIGH** | `services/core/decision_engine.py` | `1` | `MISSING_CRITICAL_TEST` | Kritik modül 'services/core/decision_engine.py' için test yok (beklenen: test_decision_engine.py) | `` |
| 294 | B18 | **HIGH** | `services/core/decision_engine.py` | `1` | `SERVICE_INTERFACE_MISSING` | Servis 'decision_engine' → beklenen 'make_decision' metodu/attribute'u eksik | `` |
| 295 | B30 | **HIGH** | `services/core/distributed_tracing.py` | `1` | `UNDECLARED_DEPENDENCY` | 'contextvars' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 296 | B30 | **HIGH** | `services/core/event_bus.py` | `1` | `UNDECLARED_DEPENDENCY` | 'event_schema' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 297 | B30 | **HIGH** | `services/core/event_bus.py` | `1` | `UNDECLARED_DEPENDENCY` | 'dead_letter_queue' import ediliyor ama pyproject.toml'da tanimli degil (2 dosyada) | `` |
| 298 | B30 | **HIGH** | `services/core/health_reporter.py` | `1` | `UNDECLARED_DEPENDENCY` | 'connectivity' import ediliyor ama pyproject.toml'da tanimli degil (2 dosyada) | `` |
| 299 | B30 | **HIGH** | `services/core/health_reporter.py` | `1` | `UNDECLARED_DEPENDENCY` | 'offline_queue' import ediliyor ama pyproject.toml'da tanimli degil (2 dosyada) | `` |
| 300 | B30 | **HIGH** | `services/core/health_reporter.py` | `1` | `UNDECLARED_DEPENDENCY` | 'data_integrity' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 301 | B30 | **HIGH** | `services/core/health_reporter.py` | `1` | `UNDECLARED_DEPENDENCY` | 'downtime_tracker' import ediliyor ama pyproject.toml'da tanimli degil (2 dosyada) | `` |
| 302 | B06 | **HIGH** | `services/core/immutable_audit.py` | `104` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'admin' | `audit.log(user_id="admin", action="UPDATE", resource_type="config", ..` |
| 303 | B06 | **HIGH** | `services/core/jwt_manager.py` | `105` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'ADMIN' | `token = jwt_mgr.generate_token("user123", "ADMIN", ["READ", "WRITE"])` |
| 304 | B06 | **HIGH** | `services/core/jwt_manager.py` | `271` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'default' | `name: str = "default",` |
| 305 | B30 | **HIGH** | `services/core/market_calendar.py` | `1` | `UNDECLARED_DEPENDENCY` | 'market_session_fsm' import ediliyor ama pyproject.toml'da tanimli degil (3 dosyada) | `` |
| 306 | B30 | **HIGH** | `services/core/market_calendar.py` | `1` | `UNDECLARED_DEPENDENCY` | 'holiday_manager' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 307 | B30 | **HIGH** | `services/core/market_session.py` | `1` | `UNDECLARED_DEPENDENCY` | 'auto_circuit_breaker' import ediliyor ama pyproject.toml'da tanimli degil (2 dosyada) | `` |
| 308 | B30 | **HIGH** | `services/core/monitoring.py` | `1` | `UNDECLARED_DEPENDENCY` | 'alerting' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 309 | B30 | **HIGH** | `services/core/monitoring.py` | `1` | `UNDECLARED_DEPENDENCY` | 'observability' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 310 | B30 | **HIGH** | `services/core/monitoring.py` | `1` | `UNDECLARED_DEPENDENCY` | 'db_lock' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 311 | B30 | **HIGH** | `services/core/monitoring_security.py` | `1` | `UNDECLARED_DEPENDENCY` | 'jose' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 312 | B06 | **HIGH** | `services/core/monitoring_security.py` | `359` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'admin' | `"admin": ["read", "write", "admin", "metrics", "alerts", "portfolio"],` |
| 313 | B06 | **HIGH** | `services/core/monitoring_security.py` | `396` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'admin' | `if permission in perms or "admin" in perms:` |
| 314 | B15 | **HIGH** | `services/core/orchestrator.py` | `1` | `MISSING_CRITICAL_TEST` | Kritik modül 'services/core/orchestrator.py' için test yok (beklenen: test_orchestrator.py) | `` |
| 315 | B20 | **HIGH** | `services/core/orchestrator.py` | `1` | `DECISION_INPUT_FIELD_NOT_SET` | DecisionInput'ta 1 alan orchestrator tarafından set edilmiyor: ['news_sentiment'] | `` |
| 316 | B06 | **HIGH** | `services/core/orchestrator.py` | `76` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'default' | `def _publish_event_async(event: Any, key: str = "default") -> None:` |
| 317 | B05 | **HIGH** | `services/core/polars_utils.py` | `45` | `PANDAS_IN_PROD` | 'pandas' import — proje standardı Polars zorunludur! | `import pandas as pd` |
| 318 | B30 | **HIGH** | `services/core/recovery.py` | `1` | `UNDECLARED_DEPENDENCY` | 'scheduler' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 319 | B15 | **HIGH** | `services/core/risk_gate.py` | `1` | `MISSING_CRITICAL_TEST` | Kritik modül 'services/core/risk_gate.py' için test yok (beklenen: test_risk_gate.py) | `` |
| 320 | B30 | **HIGH** | `services/core/security.py` | `1` | `UNDECLARED_DEPENDENCY` | 'cryptography' import ediliyor ama pyproject.toml'da tanimli degil (5 dosyada) | `` |
| 321 | B30 | **HIGH** | `services/core/security.py` | `1` | `UNDECLARED_DEPENDENCY` | 'jwt_manager' import ediliyor ama pyproject.toml'da tanimli degil (2 dosyada) | `` |
| 322 | B06 | **HIGH** | `services/core/security.py` | `55` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'ADMIN' | `ADMIN = "ADMIN"` |
| 323 | B30 | **HIGH** | `services/data/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'data_source' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 324 | B30 | **HIGH** | `services/data/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'historical_adapter' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 325 | B05 | **HIGH** | `services/data/data_source.py` | `23` | `SYNC_REQUESTS_IN_PROD` | 'requests' import — async servislerde httpx.AsyncClient kullanılmalı | `import requests` |
| 326 | B30 | **HIGH** | `services/data/historical_adapter.py` | `1` | `UNDECLARED_DEPENDENCY` | 'historical_contracts' import ediliyor ama pyproject.toml'da tanimli degil (3 dosyada) | `` |
| 327 | B30 | **HIGH** | `services/data/historical_adapter.py` | `1` | `UNDECLARED_DEPENDENCY` | 'persistent_repository' import ediliyor ama pyproject.toml'da tanimli degil (3 dosyada) | `` |
| 328 | B30 | **HIGH** | `services/data/ingestion_pipeline.py` | `1` | `UNDECLARED_DEPENDENCY` | 'historical_fundamental_provider' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 329 | B30 | **HIGH** | `services/event_study/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'event_window' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 330 | B30 | **HIGH** | `services/event_study/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'macro_event' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 331 | B30 | **HIGH** | `services/event_study/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'estimation_window' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 332 | B30 | **HIGH** | `services/event_study/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'fama_french_factors' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 333 | B30 | **HIGH** | `services/event_study/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'event_clustering' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 334 | B30 | **HIGH** | `services/event_study/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'kap_event' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 335 | B30 | **HIGH** | `services/event_study/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'sector_event' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 336 | B30 | **HIGH** | `services/event_study/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'multi_factor' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 337 | B30 | **HIGH** | `services/event_study/estimation_window.py` | `1` | `UNDECLARED_DEPENDENCY` | 'trading_calendar' import ediliyor ama pyproject.toml'da tanimli degil (3 dosyada) | `` |
| 338 | B06 | **HIGH** | `services/event_study/estimation_window.py` | `46` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'DEFAULT' | `"DEFAULT": 60,` |
| 339 | B06 | **HIGH** | `services/event_study/estimation_window.py` | `71` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'DEFAULT' | `def get_window(self, event_date: datetime, event_type: str = "DEFAULT"` |
| 340 | B06 | **HIGH** | `services/event_study/estimation_window.py` | `82` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'DEFAULT' | `trading_days = ESTIMATION_WINDOWS.get(event_type, ESTIMATION_WINDOWS["` |
| 341 | B06 | **HIGH** | `services/event_study/estimation_window.py` | `104` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'DEFAULT' | `def get_window_trading_days(self, event_type: str = "DEFAULT") -> int:` |
| 342 | B06 | **HIGH** | `services/event_study/estimation_window.py` | `106` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'DEFAULT' | `return ESTIMATION_WINDOWS.get(event_type, ESTIMATION_WINDOWS["DEFAULT"` |
| 343 | B06 | **HIGH** | `services/event_study/estimation_window.py` | `111` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'DEFAULT' | `event_type: str = "DEFAULT",` |
| 344 | B06 | **HIGH** | `services/event_study/estimation_window.py` | `139` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'DEFAULT' | `event_type: str = "DEFAULT",` |
| 345 | B06 | **HIGH** | `services/event_study/estimation_window.py` | `181` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'DEFAULT' | `def get_estimation_window_size_calendar_days(self, event_date: datetim` |
| 346 | B06 | **HIGH** | `services/event_study/event_window.py` | `46` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'DEFAULT' | `"DEFAULT": (-5, 5),` |
| 347 | B06 | **HIGH** | `services/event_study/event_window.py` | `64` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'DEFAULT' | `def get_window(self, event_type: str = "DEFAULT") -> tuple[int, int]:` |
| 348 | B06 | **HIGH** | `services/event_study/event_window.py` | `70` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'DEFAULT' | `return EVENT_WINDOWS.get(event_type, EVENT_WINDOWS["DEFAULT"])` |
| 349 | B06 | **HIGH** | `services/event_study/event_window.py` | `72` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'DEFAULT' | `def get_window_size(self, event_type: str = "DEFAULT") -> int:` |
| 350 | B06 | **HIGH** | `services/event_study/event_window.py` | `77` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'DEFAULT' | `def get_window_dates(self, event_date: datetime, event_type: str = "DE` |
| 351 | B06 | **HIGH** | `services/event_study/event_window.py` | `106` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'DEFAULT' | `event_type: str = "DEFAULT",` |
| 352 | B06 | **HIGH** | `services/event_study/event_window.py` | `159` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'DEFAULT' | `event_type: str = "DEFAULT",` |
| 353 | B06 | **HIGH** | `services/event_study/event_window.py` | `187` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'DEFAULT' | `def get_sub_windows(self, event_type: str = "DEFAULT") -> dict[str, tu` |
| 354 | B06 | **HIGH** | `services/event_study/event_window.py` | `201` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'DEFAULT' | `def get_window_calendar_days(self, event_date: datetime, event_type: s` |
| 355 | B30 | **HIGH** | `services/event_study/impact.py` | `1` | `UNDECLARED_DEPENDENCY` | 'event_decay' import ediliyor ama pyproject.toml'da tanimli degil (2 dosyada) | `` |
| 356 | B06 | **HIGH** | `services/event_study/impact.py` | `26` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'DEFAULT' | `"DEFAULT": {"significance": 0.25, "volume": 0.25, "statistical": 0.25,` |
| 357 | B06 | **HIGH** | `services/event_study/impact.py` | `34` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'DEFAULT' | `event_type: str = "DEFAULT",` |
| 358 | B06 | **HIGH** | `services/event_study/impact.py` | `49` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'DEFAULT' | `weights = EVENT_WEIGHTS.get(event_type, EVENT_WEIGHTS["DEFAULT"])` |
| 359 | B06 | **HIGH** | `services/event_study/impact.py` | `130` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'DEFAULT' | `event_type=event.get("event_type", "DEFAULT"),` |
| 360 | B30 | **HIGH** | `services/event_study/kap_event.py` | `1` | `UNDECLARED_DEPENDENCY` | 'impact' import ediliyor ama pyproject.toml'da tanimli degil (2 dosyada) | `` |
| 361 | B30 | **HIGH** | `services/event_study/kap_event.py` | `1` | `UNDECLARED_DEPENDENCY` | 'car' import ediliyor ama pyproject.toml'da tanimli degil (4 dosyada) | `` |
| 362 | B30 | **HIGH** | `services/event_study/kap_event.py` | `1` | `UNDECLARED_DEPENDENCY` | 'expected_return' import ediliyor ama pyproject.toml'da tanimli degil (3 dosyada) | `` |
| 363 | B30 | **HIGH** | `services/event_study/kap_event.py` | `1` | `UNDECLARED_DEPENDENCY` | 'abnormal_return' import ediliyor ama pyproject.toml'da tanimli degil (3 dosyada) | `` |
| 364 | B30 | **HIGH** | `services/event_study/kap_event.py` | `1` | `UNDECLARED_DEPENDENCY` | 'statistical_test' import ediliyor ama pyproject.toml'da tanimli degil (3 dosyada) | `` |
| 365 | B30 | **HIGH** | `services/event_study/kap_event.py` | `1` | `UNDECLARED_DEPENDENCY` | 'cross_sectional' import ediliyor ama pyproject.toml'da tanimli degil (2 dosyada) | `` |
| 366 | B30 | **HIGH** | `services/factors/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'piotroski' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 367 | B30 | **HIGH** | `services/factors/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'beneish' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 368 | B30 | **HIGH** | `services/factors/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'performance' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 369 | B30 | **HIGH** | `services/factors/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'factor_correlation' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 370 | B30 | **HIGH** | `services/factors/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'altman' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 371 | B30 | **HIGH** | `services/factors/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'bist_anomalies' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 372 | B30 | **HIGH** | `services/factors/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'factor_rotation' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 373 | B30 | **HIGH** | `services/factors/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'factor_time_series' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 374 | B30 | **HIGH** | `services/factors/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'ranking' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 375 | B30 | **HIGH** | `services/factors/factor_rotation.py` | `1` | `UNDECLARED_DEPENDENCY` | 'fama_french' import ediliyor ama pyproject.toml'da tanimli degil (2 dosyada) | `` |
| 376 | B30 | **HIGH** | `services/features/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'bist_features' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 377 | B15 | **HIGH** | `services/features/contract.py` | `1` | `MISSING_CRITICAL_TEST` | Kritik modül 'services/features/contract.py' için test yok (beklenen: test_feature_contract.py) | `` |
| 378 | B23 | **HIGH** | `services/features/contract.py` | `1` | `FEATURE_REGISTERED_NOT_COMPUTED` | 3 kayıtlı feature feature engine'de hesaplanmıyor: ['breadth_advance_ratio', 'cs_rank_rsi_14', 'momentum_10d'] | `` |
| 379 | B30 | **HIGH** | `services/features/doc_generator.py` | `1` | `UNDECLARED_DEPENDENCY` | 'contract' import ediliyor ama pyproject.toml'da tanimli degil (3 dosyada) | `` |
| 380 | B06 | **HIGH** | `services/features/feature_tests.py` | `214` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'test' | `failures=[{"test": t.test_name, "msg": t.message} for t in failed_test` |
| 381 | B30 | **HIGH** | `services/features/main.py` | `1` | `UNDECLARED_DEPENDENCY` | 'calculator' import ediliyor ama pyproject.toml'da tanimli degil (2 dosyada) | `` |
| 382 | B30 | **HIGH** | `services/features/pipeline.py` | `1` | `UNDECLARED_DEPENDENCY` | 'store' import ediliyor ama pyproject.toml'da tanimli degil (2 dosyada) | `` |
| 383 | B15 | **HIGH** | `services/features/seven_motors.py` | `1` | `MISSING_CRITICAL_TEST` | Kritik modül 'services/features/seven_motors.py' için test yok (beklenen: test_seven_motors.py) | `` |
| 384 | B30 | **HIGH** | `services/grpc/client.py` | `1` | `UNDECLARED_DEPENDENCY` | 'generated' import ediliyor ama pyproject.toml'da tanimli degil (2 dosyada) | `` |
| 385 | B06 | **HIGH** | `services/grpc/client.py` | `323` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'default' | `request = market_pb2.PortfolioRequest(portfolio_id="default")` |
| 386 | B06 | **HIGH** | `services/grpc/client.py` | `362` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'default' | `request = market_pb2.PortfolioRequest(portfolio_id="default")` |
| 387 | B06 | **HIGH** | `services/grpc/client.py` | `404` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'default' | `request = market_pb2.RiskRequest(portfolio_id="default")` |
| 388 | B06 | **HIGH** | `services/grpc/client.py` | `433` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'default' | `request = market_pb2.RiskRequest(portfolio_id="default")` |
| 389 | B30 | **HIGH** | `services/grpc/generated/market_pb2.py` | `1` | `UNDECLARED_DEPENDENCY` | 'google' import ediliyor ama pyproject.toml'da tanimli degil (5 dosyada) | `` |
| 390 | B30 | **HIGH** | `services/grpc/server.py` | `1` | `UNDECLARED_DEPENDENCY` | 'grpc_reflection' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 391 | B30 | **HIGH** | `services/grpc/server.py` | `1` | `UNDECLARED_DEPENDENCY` | 'grpc_health' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 392 | B30 | **HIGH** | `services/ingestion/__init__.py` | `1` | `UNDECLARED_DEPENDENCY` | 'orchestrator_integration' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 393 | B30 | **HIGH** | `services/ingestion/bist_universe.py` | `1` | `UNDECLARED_DEPENDENCY` | 'providers' import ediliyor ama pyproject.toml'da tanimli degil (14 dosyada) | `` |
| 394 | B06 | **HIGH** | `services/ingestion/circuit_breaker.py` | `80` | `INSECURE_DEFAULT` | Güvensiz varsayılan değer: 'default' | `name: str = "default",` |
| 395 | B30 | **HIGH** | `services/ingestion/main.py` | `1` | `UNDECLARED_DEPENDENCY` | 'bist_universe' import ediliyor ama pyproject.toml'da tanimli degil (5 dosyada) | `` |
| 396 | B30 | **HIGH** | `services/ingestion/main.py` | `1` | `UNDECLARED_DEPENDENCY` | 'questdb_consumer' import ediliyor ama pyproject.toml'da tanimli degil (1 dosyada) | `` |
| 397 | B36 | **HIGH** | `services/ingestion/main.py` | `71` | `FIRE_AND_FORGET_TASK` | asyncio.create_task() sonucu degiskene atilmamis - exception sessizce kaybolur | `` |
| 398 | B36 | **HIGH** | `services/ingestion/main.py` | `72` | `FIRE_AND_FORGET_TASK` | asyncio.create_task() sonucu degiskene atilmamis - exception sessizce kaybolur | `` |
| 399 | B36 | **HIGH** | `services/ingestion/main.py` | `73` | `FIRE_AND_FORGET_TASK` | asyncio.create_task() sonucu degiskene atilmamis - exception sessizce kaybolur | `` |
| 400 | B36 | **HIGH** | `services/ingestion/main.py` | `74` | `FIRE_AND_FORGET_TASK` | asyncio.create_task() sonucu degiskene atilmamis - exception sessizce kaybolur | `` |

## 5. Motor & Sinyal Zinciri Bulguları (11 adet)

| Boyut | Dosya | Kategori | Açıklama |
|---|---|---|---|
| B18 | `services/core/decision_engine.py` | `SERVICE_INTERFACE_MISSING` | Servis 'decision_engine' → beklenen 'make_decision' metodu/attribute'u eksik |
| B18 | `services/portfolio/portfolio_manager.py` | `SERVICE_INTERFACE_MISSING` | Servis 'portfolio_manager' → beklenen 'execute_decision' metodu/attribute'u eksik |
| B18 | `services/portfolio/portfolio_manager.py` | `SERVICE_INTERFACE_MISSING` | Servis 'portfolio_manager' → beklenen 'get_portfolio_summary' metodu/attribute'u eksik |
| B18 | `services/risk/position_sizing.py` | `SERVICE_INTERFACE_MISSING` | Servis 'position_sizing' → beklenen 'calculate_position_size' metodu/attribute'u eksik |
| B20 | `services/core/orchestrator.py` | `DECISION_INPUT_FIELD_NOT_SET` | DecisionInput'ta 1 alan orchestrator tarafından set edilmiyor: ['news_sentiment'] |
| B21 | `test_phase5_end_to_end.py` | `RISK_GATE_MISSING_PARAM` | risk_gate.check_order() çağrısında zorunlu parametreler eksik: ['price', 'portfolio_value', 'side', 'current_positions', 'ticker', 'quantity'] |
| B21 | `test_phase5_end_to_end.py` | `RISK_GATE_MISSING_PARAM` | risk_gate.check_order() çağrısında zorunlu parametreler eksik: ['price', 'portfolio_value', 'side', 'current_positions', 'ticker'] |
| B21 | `scripts/deep_system_integrity_auditor.py` | `RISK_GATE_MISSING_PARAM` | risk_gate.check_order() çağrısında zorunlu parametreler eksik: ['price', 'portfolio_value', 'side', 'current_positions', 'ticker', 'quantity'] |
| B23 | `services/features/contract.py` | `FEATURE_REGISTERED_NOT_COMPUTED` | 3 kayıtlı feature feature engine'de hesaplanmıyor: ['breadth_advance_ratio', 'cs_rank_rsi_14', 'momentum_10d'] |
| B25 | `services/core/orchestrator.py` | `PORTFOLIO_CHAIN_BROKEN` | Orchestrator risk_gate.check_order çağırıyor ama portfolio_manager.execute_decision ÇAĞRILMIYOR — karar zinciri kırık! |
| B25 | `services/portfolio/portfolio_manager.py` | `EXECUTE_DECISION_METHOD_MISSING` | PortfolioManager.execute_decision metodu tanımlı değil — portfolio güncellenemiyor! |

## 6. Orta Seviye Bulgular (1950 adet)

| Boyut | Dosya | Satır | Kategori | Açıklama |
|---|---|---|---|---|
| B07 | `ml/feature_discovery.py` | `112` | TODO_MARKER | Tamamlanmamış 'TODO' işareti bırakılmış |
| B08 | `ml/models.py` | `178` | MISSING_RETURN_TYPE | 'train' dönüş tipi annotation eksik |
| B08 | `ml/models.py` | `209` | MISSING_RETURN_TYPE | 'save' dönüş tipi annotation eksik |
| B08 | `ml/models.py` | `240` | MISSING_RETURN_TYPE | 'load' dönüş tipi annotation eksik |
| B08 | `ml/models.py` | `278` | MISSING_RETURN_TYPE | 'train' dönüş tipi annotation eksik |
| B08 | `ml/models.py` | `315` | MISSING_RETURN_TYPE | 'train' dönüş tipi annotation eksik |
| B08 | `ml/models.py` | `349` | MISSING_RETURN_TYPE | 'add_model' dönüş tipi annotation eksik |
| B07 | `scripts/deep_comprehensive_audit.py` | `290` | TODO_MARKER | Tamamlanmamış 'TODO' işareti bırakılmış |
| B07 | `scripts/ultimate_audit_engine.py` | `461` | TODO_MARKER | Tamamlanmamış 'TODO' işareti bırakılmış |
| B08 | `services/clear.py` | `10` | MISSING_RETURN_TYPE | 'run' dönüş tipi annotation eksik |
| B08 | `services/clear2.py` | `4` | MISSING_RETURN_TYPE | 'run' dönüş tipi annotation eksik |
| B13 | `services/clear2.py` | `7` | PRINT_IN_PROD | print() — production'da structlog kullanılmalı |
| B08 | `services/institutional_backtest.py` | `15` | MISSING_RETURN_TYPE | 'run_institutional' dönüş tipi annotation eksik |
| B13 | `services/institutional_backtest.py` | `16` | PRINT_IN_PROD | print() — production'da structlog kullanılmalı |
| B13 | `services/institutional_backtest.py` | `23` | PRINT_IN_PROD | print() — production'da structlog kullanılmalı |
| B13 | `services/institutional_backtest.py` | `25` | PRINT_IN_PROD | print() — production'da structlog kullanılmalı |
| B13 | `services/institutional_backtest.py` | `53` | PRINT_IN_PROD | print() — production'da structlog kullanılmalı |
| B13 | `services/institutional_backtest.py` | `62` | PRINT_IN_PROD | print() — production'da structlog kullanılmalı |
| B13 | `services/institutional_backtest.py` | `69` | PRINT_IN_PROD | print() — production'da structlog kullanılmalı |
| B13 | `services/institutional_backtest.py` | `79` | PRINT_IN_PROD | print() — production'da structlog kullanılmalı |
| B13 | `services/institutional_backtest.py` | `86` | PRINT_IN_PROD | print() — production'da structlog kullanılmalı |
| B13 | `services/institutional_backtest.py` | `106` | PRINT_IN_PROD | print() — production'da structlog kullanılmalı |
| B13 | `services/institutional_backtest.py` | `140` | PRINT_IN_PROD | print() — production'da structlog kullanılmalı |
| B13 | `services/institutional_backtest.py` | `142` | PRINT_IN_PROD | print() — production'da structlog kullanılmalı |
| B13 | `services/institutional_backtest.py` | `150` | PRINT_IN_PROD | print() — production'da structlog kullanılmalı |
| B13 | `services/institutional_backtest.py` | `151` | PRINT_IN_PROD | print() — production'da structlog kullanılmalı |
| B13 | `services/institutional_backtest.py` | `154` | PRINT_IN_PROD | print() — production'da structlog kullanılmalı |
| B13 | `services/institutional_backtest.py` | `155` | PRINT_IN_PROD | print() — production'da structlog kullanılmalı |
| B08 | `services/massive_454_backtest.py` | `14` | MISSING_RETURN_TYPE | 'run_massive' dönüş tipi annotation eksik |
| B13 | `services/massive_454_backtest.py` | `15` | PRINT_IN_PROD | print() — production'da structlog kullanılmalı |
| B13 | `services/massive_454_backtest.py` | `22` | PRINT_IN_PROD | print() — production'da structlog kullanılmalı |
| B13 | `services/massive_454_backtest.py` | `24` | PRINT_IN_PROD | print() — production'da structlog kullanılmalı |
| B13 | `services/massive_454_backtest.py` | `50` | PRINT_IN_PROD | print() — production'da structlog kullanılmalı |
| B13 | `services/massive_454_backtest.py` | `60` | PRINT_IN_PROD | print() — production'da structlog kullanılmalı |
| B13 | `services/massive_454_backtest.py` | `64` | PRINT_IN_PROD | print() — production'da structlog kullanılmalı |
| B13 | `services/massive_454_backtest.py` | `69` | PRINT_IN_PROD | print() — production'da structlog kullanılmalı |
| B13 | `services/massive_454_backtest.py` | `79` | PRINT_IN_PROD | print() — production'da structlog kullanılmalı |
| B13 | `services/massive_454_backtest.py` | `86` | PRINT_IN_PROD | print() — production'da structlog kullanılmalı |
| B13 | `services/massive_454_backtest.py` | `92` | PRINT_IN_PROD | print() — production'da structlog kullanılmalı |
| B13 | `services/massive_454_backtest.py` | `122` | PRINT_IN_PROD | print() — production'da structlog kullanılmalı |
| B13 | `services/massive_454_backtest.py` | `126` | PRINT_IN_PROD | print() — production'da structlog kullanılmalı |
| B13 | `services/massive_454_backtest.py` | `135` | PRINT_IN_PROD | print() — production'da structlog kullanılmalı |
| B13 | `services/massive_454_backtest.py` | `136` | PRINT_IN_PROD | print() — production'da structlog kullanılmalı |
| B13 | `services/massive_454_backtest.py` | `137` | PRINT_IN_PROD | print() — production'da structlog kullanılmalı |
| B13 | `services/massive_454_backtest.py` | `141` | PRINT_IN_PROD | print() — production'da structlog kullanılmalı |
| B13 | `services/massive_454_backtest.py` | `142` | PRINT_IN_PROD | print() — production'da structlog kullanılmalı |
| B08 | `services/recreate.py` | `4` | MISSING_RETURN_TYPE | 'run' dönüş tipi annotation eksik |
| B13 | `services/recreate.py` | `15` | PRINT_IN_PROD | print() — production'da structlog kullanılmalı |
| B13 | `services/test_engine2.py` | `11` | PRINT_IN_PROD | print() — production'da structlog kullanılmalı |
| B13 | `services/test_engine2.py` | `14` | PRINT_IN_PROD | print() — production'da structlog kullanılmalı |
| B08 | `services/agents/agent_memory.py` | `63` | MISSING_RETURN_TYPE | 'add' dönüş tipi annotation eksik |
| B08 | `services/agents/agent_memory.py` | `90` | MISSING_RETURN_TYPE | 'clear' dönüş tipi annotation eksik |
| B08 | `services/agents/agent_memory.py` | `116` | MISSING_RETURN_TYPE | 'add' dönüş tipi annotation eksik |
| B08 | `services/agents/agent_memory.py` | `124` | MISSING_RETURN_TYPE | 'record_outcome' dönüş tipi annotation eksik |
| B08 | `services/agents/agent_memory.py` | `266` | MISSING_RETURN_TYPE | 'add_pattern' dönüş tipi annotation eksik |
| B08 | `services/agents/agent_memory.py` | `317` | MISSING_RETURN_TYPE | 'prune_low_accuracy' dönüş tipi annotation eksik |
| B08 | `services/agents/agent_memory.py` | `359` | MISSING_RETURN_TYPE | 'record_task' dönüş tipi annotation eksik |
| B08 | `services/agents/agent_memory.py` | `384` | MISSING_RETURN_TYPE | 'record_outcome' dönüş tipi annotation eksik |
| B08 | `services/agents/agent_memory.py` | `421` | MISSING_RETURN_TYPE | 'save' dönüş tipi annotation eksik |
| B08 | `services/agents/agent_memory.py` | `442` | MISSING_RETURN_TYPE | 'load' dönüş tipi annotation eksik |
| B08 | `services/agents/agent_pipeline.py` | `314` | MISSING_RETURN_TYPE | '_update_memories' dönüş tipi annotation eksik |
| B08 | `services/agents/agent_system.py` | `524` | MISSING_RETURN_TYPE | 'register_agent' dönüş tipi annotation eksik |
| B08 | `services/agents/agent_system.py` | `528` | MISSING_RETURN_TYPE | 'set_llm_client' dönüş tipi annotation eksik |
| B08 | `services/agents/agent_system.py` | `557` | MISSING_RETURN_TYPE | '_run_agent' dönüş tipi annotation eksik |
| B08 | `services/agents/communication_bus.py` | `73` | MISSING_RETURN_TYPE | 'send' dönüş tipi annotation eksik |
| B08 | `services/agents/communication_bus.py` | `94` | MISSING_RETURN_TYPE | 'broadcast' dönüş tipi annotation eksik |
| B08 | `services/agents/communication_bus.py` | `166` | MISSING_RETURN_TYPE | 'clear' dönüş tipi annotation eksik |
| B08 | `services/agents/llm_client.py` | `426` | MISSING_RETURN_TYPE | 'register_provider' dönüş tipi annotation eksik |
| B08 | `services/agents/prompts/__init__.py` | `536` | MISSING_RETURN_TYPE | 'register_template' dönüş tipi annotation eksik |
| B08 | `services/agents/schemas/__init__.py` | `28` | MISSING_RETURN_TYPE | '_normalize_confidence' dönüş tipi annotation eksik |
| B08 | `services/agents/schemas/__init__.py` | `48` | MISSING_RETURN_TYPE | 'validate_confidence' dönüş tipi annotation eksik |
| B08 | `services/agents/schemas/__init__.py` | `102` | MISSING_RETURN_TYPE | 'validate_confidence' dönüş tipi annotation eksik |
| B08 | `services/agents/schemas/__init__.py` | `136` | MISSING_RETURN_TYPE | 'validate_confidence' dönüş tipi annotation eksik |
| B08 | `services/alternative/base.py` | `43` | MISSING_RETURN_TYPE | 'acquire' dönüş tipi annotation eksik |
| B08 | `services/alternative/base.py` | `97` | MISSING_RETURN_TYPE | 'record_success' dönüş tipi annotation eksik |
| B08 | `services/alternative/base.py` | `109` | MISSING_RETURN_TYPE | 'record_failure' dönüş tipi annotation eksik |
| B08 | `services/alternative/base.py` | `399` | MISSING_RETURN_TYPE | '_set_cached' dönüş tipi annotation eksik |
| B08 | `services/alternative/base.py` | `426` | MISSING_RETURN_TYPE | 'register' dönüş tipi annotation eksik |
| B07 | `services/alternative/bkm_adapter.py` | `183` | TODO_MARKER | Tamamlanmamış 'Placeholder' işareti bırakılmış |
| B08 | `services/alternative/feature_engine.py` | `54` | MISSING_RETURN_TYPE | 'initialize' dönüş tipi annotation eksik |

---
*Deep System Integrity Auditor v3.0 — JSON: `audit/full_spectrum_audit_20260829_145022.json`*
