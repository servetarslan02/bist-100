# API Düzeltme ve Raporlama Görevleri

- [x] Yüksek gecikmeli ve hatalı API uç noktalarını ana `AUDIT_REPORT_36_DIM.md` raporuna ekle.
- [x] `services/paper_trading/virtual_portfolio.py` eksik metotlarını düzelt (`get_position_history`, `get_equity_snapshots`, `_commission_total`).
- [x] Risk ve Macro endpointlerindeki (>5 sn) TimeOut (Zaman Aşımı) sorunlarını araştır ve optimize et.
  - *Not: 5000+ ms timeouts are caused by yfinance live fetch (cold start). Subsequent requests take <5ms.*
- [x] Düzeltmeler sonrası uç noktaların durumunu doğrula.
