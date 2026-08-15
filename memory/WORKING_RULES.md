# ALPHA BIST — Çalışma Kuralları

Bu dosya projedeki çalışma disiplinini tanımlar. Her faz başında okunur.

## Temel Kurallar

1. Özetleme, basitleştirme, eksiltme, varsayarak geçme
2. Placeholder/TODO/mock/fake/pass/return None yasak
3. Bir özellik çalışır durumda olmalı veya "tamamlanmadı" demeliyim
4. Önce kodu anla, sonra değiştir (GAP ANALYSIS)
5. Mevcut çalışan özellikleri silme

## "Tamamlandı" Kriterleri (16/16 zorunlu)

1. Kod yazıldı
2. Gerçek sisteme bağlandı
3. Diğer modüllerle entegre
4. Input validation
5. Error handling
6. Logging
7. Testler
8. Edge-case testleri
9. Failure testleri
10. Gerçek veri akışıyla doğrulandı
11. Dokümantasyon
12. Monitoring/observability
13. Security kontrolü
14. Performance kontrolü
15. Regression testi
16. TODO/placeholder kalmadı

## Raporlama

Sayısal: Files inspected, changed, bugs found/fixed, tests added/passed/failed, remaining issues.

## Faz Döngüsü

ANALYZE → PLAN → IMPLEMENT → TEST → INTEGRATE → VERIFY → AUDIT → COMPLETE

Test geçmeden sonraki faza geçme.

## Test Kapsamı

Happy path, edge case, invalid input, missing data, timeout, provider failure, DB failure, duplicate event, concurrent execution.

## Nerede Dur

Ambiguous requirement, destructive operation, irreversible change, missing credential, security-critical decision, conflicting requirements. Diğerlerinde kendim karar ver.

## Kaynak

- ROADMAP.md: Faz planı ve detaylar
- Çalışma şekli: Bu dosya
- Sistem tanımı: Vizyon
- Hatalar: Düzeltme talimatları
