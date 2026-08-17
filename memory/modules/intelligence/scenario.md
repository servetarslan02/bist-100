# intelligence/scenario

**Dosya:** `services/intelligence/scenario.py`
**Satır:** 313

## Açıklama

ALPHA BIST — Scenario & Stress Test Engine v1.0

Senaryo analizi ve stres testleri:
- Makro senaryo girdileri → etki hesaplama
- Önceden tanımlı senaryolar (TCMB, USDTRY, BIST crash, vb.)
- Stres testleri (2008, 2020 benzeri)
- Breaking point analizi

FAZ 6.1-6.3: Scenario & Stress Test Engine

## Sınıflar (6)

- `ScenarioInput`
- `AssetImpact`
- `ScenarioResult`
- `StressTestResult`
- `BreakingPoint`
- `ScenarioEngine`

## Fonksiyonlar (4)

- `run_scenario()`
- `_simplified_impact()`
- `run_stress_test()`
- `find_breaking_point()`

