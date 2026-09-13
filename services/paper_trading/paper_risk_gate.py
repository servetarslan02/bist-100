"""
ALPHA BIST — Paper Risk Gate v1.0

Portfolio Risk Yonetimi:
- Max position weight
- Max sector weight
- Max portfolio exposure
- Max drawdown alarmi + kill-switch
- Gunluk kayip limiti
- Data quality bozulursa NO_TRADE
- Herhangi bir kritik hatada NO_TRADE (fail-safe)

KURAL: Risk Gate 'NO_TRADE' diyebilmeli. Sistem hicbir kosulda
islem yapmak zorunda olmamali.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

import structlog

__all__ = [
    "PaperRiskGate",
]

logger = structlog.get_logger()


class PaperRiskGate:
    """Paper trading risk gate — fail-safe, fail-closed."""

    def __init__(
        self,
        max_position_pct: float = 10.0,
        max_sector_pct: float = 30.0,
        max_portfolio_exposure_pct: float = 100.0,
        max_drawdown_pct: float = 20.0,
        kill_switch_drawdown_pct: float = 25.0,
        daily_loss_limit_pct: float = 5.0,
        liquidity_min_volume: int = 100_000,
        data_quality_min_stocks: int = 50,
        portfolio_dd_shield_pct: float = 15.0,
        vol_spike_shield_pct: float = 40.0,
    ):
        """PaperRiskGate risk kapısı denetleyicisini başlatır.

        Args:
            max_position_pct: Tek bir hisse pozisyonunun portföy değerine maksimum yüzdesi (varsayılan %10).
            max_sector_pct: Tek bir sektörün portföy değerine maksimum yoğunlaşma yüzdesi (varsayılan %30).
            max_portfolio_exposure_pct: Toplam hisse pozisyonlarının portföy değerine maksimum kaldıraçsız oranı.
            max_drawdown_pct: Uyarı verilmesine neden olan maksimum tepe-dip düşüş yüzdesi (varsayılan %20).
            kill_switch_drawdown_pct: Otomatik işlemleri kilitleyen acil durum düşüş eşiği (varsayılan %25).
            daily_loss_limit_pct: Günlük izin verilen maksimum kayıp yüzdesi (varsayılan %5).
            liquidity_min_volume: İşlem görecek hisse için aranan asgari günlük hacim.
            data_quality_min_stocks: Veri kalitesi denetiminde aranan asgari hisse sayısı.
            portfolio_dd_shield_pct: Portföy zirve değerinden bu kadar düşünce yeni alım durdurulur (%15).
            vol_spike_shield_pct: 5 günlük endeks volatilitesi (annualized) bu eşiği geçince yeni alım durdurulur (%40).
        """
        self.max_position_pct = max_position_pct
        self.max_sector_pct = max_sector_pct
        self.max_portfolio_exposure_pct = max_portfolio_exposure_pct
        self.max_drawdown_pct = max_drawdown_pct
        self.kill_switch_drawdown_pct = kill_switch_drawdown_pct
        self.daily_loss_limit_pct = daily_loss_limit_pct
        self.liquidity_min_volume = liquidity_min_volume
        self.data_quality_min_stocks = data_quality_min_stocks
        self.portfolio_dd_shield_pct = portfolio_dd_shield_pct
        self.vol_spike_shield_pct = vol_spike_shield_pct

        self._kill_switch_active = False
        self._kill_switch_reason = ""
        self._consecutive_errors = 0
        self._max_consecutive_errors = 3
        self._portfolio_peak_value: float = 0.0  # Portfoy drawdown kalkani icin

    def __repr__(self) -> str:
        """Sınıfın metinsel temsilini döndürür."""
        return (
            f"PaperRiskGate(kill_switch={self._kill_switch_active}, "
            f"max_pos={self.max_position_pct}%, max_sector={self.max_sector_pct}%, "
            f"kill_dd={self.kill_switch_drawdown_pct}%, "
            f"dd_shield={self.portfolio_dd_shield_pct}%, vol_shield={self.vol_spike_shield_pct}%)"
        )

    def is_kill_switch_active(self) -> bool:
        """Kill switch aktif mi?"""
        return self._kill_switch_active

    def get_kill_switch_reason(self) -> str:
        """Kill switch'in tetiklenme gerekçesini döndürür."""
        return self._kill_switch_reason

    def reset_kill_switch(self) -> Any:
        """Kill switch'i manuel resetle."""
        self._kill_switch_active = False
        self._kill_switch_reason = ""
        logger.warning("Kill switch RESET manually")

    def check_all(
        self,
        portfolio,
        ticker: str,
        side: str,
        quantity: int,
        price: float,
        sector: str = "",
        data_quality_ok: bool = True,
        model_version_valid: bool = True,
        market_regime: str = "",
        index_trend_bullish: bool | None = None,
        index_returns_5d: list[float] | None = None,
    ) -> list[dict[str, Any]]:
        """Tum risk check'lerini calistir."""
        checks = []

        # === 0. KILL SWITCH ===
        checks.append(self._check_kill_switch())

        # === 1. DATA QUALITY ===
        checks.append(self._check_data_quality(data_quality_ok))

        # === 2. MODEL VALIDITY ===
        checks.append(self._check_model_validity(model_version_valid))

        # === 2.1. MARKET REGIME & INDEX SHIELD (ENDEKS REJİM KALKANI) ===
        checks.append(self._check_market_regime(side, market_regime, index_trend_bullish))

        # === 2.2. PORTFOY DRAWDOWN KALKANI (YENİ) ===
        checks.append(self._check_portfolio_drawdown_shield(portfolio, side))

        # === 2.3. VOLATİLİTE SPİKE KALKANI (YENİ) ===
        checks.append(self._check_vol_spike_shield(side, index_returns_5d))

        # === 3. POSITION SIZE ===
        checks.append(self._check_position_size(portfolio, ticker, side, quantity, price))

        # === 4. SECTOR CONCENTRATION ===
        checks.append(self._check_sector_concentration(portfolio, ticker, side, quantity, price, sector))

        # === 5. PORTFOLIO EXPOSURE ===
        checks.append(self._check_portfolio_exposure(portfolio, ticker, side, quantity, price))

        # === 6. DRAWDOWN ===
        checks.append(self._check_drawdown(portfolio))

        # === 7. DAILY LOSS ===
        checks.append(self._check_daily_loss(portfolio))

        blocked = [c for c in checks if c["result"] in ("BLOCK", "NO_TRADE")]
        if blocked:
            logger.warning("Risk gate BLOCKED", ticker=ticker, side=side, reasons=[c["check_name"] for c in blocked])
        else:
            logger.info("Risk gate PASSED", ticker=ticker, side=side)

        return checks

    def is_trade_allowed(self, checks: list[dict[str, Any]]) -> bool:
        """Tum check'lerden gecildi mi?"""
        return all(check["result"] not in ("BLOCK", "NO_TRADE") for check in checks)

    def get_block_reason(self, checks: list[dict[str, Any]]) -> str:
        """Block sebebini birlestir."""
        blocks = [c for c in checks if c["result"] in ("BLOCK", "NO_TRADE")]
        return "; ".join(f"{c['check_name']}: {c['details']}" for c in blocks)

    # ===================== INDIVIDUAL CHECKS =====================

    def _check_kill_switch(self) -> dict[str, Any]:
        """Kill switch'in aktif olup olmadığını kontrol eder."""
        if self._kill_switch_active:
            return {
                "check_name": "kill_switch",
                "result": "BLOCK",
                "details": f"KILL SWITCH ACTIVE: {self._kill_switch_reason}",
                "severity": "BLOCK",
            }
        return {"check_name": "kill_switch", "result": "PASS", "details": "OK", "severity": "INFO"}

    def _check_data_quality(self, ok: bool) -> dict[str, Any]:
        """Veri kalitesi durumunu denetler; yetersizse NO_TRADE üretir."""
        if not ok:
            return {
                "check_name": "data_quality",
                "result": "NO_TRADE",
                "details": "Data quality check FAILED — NO_TRADE",
                "severity": "BLOCK",
            }
        return {"check_name": "data_quality", "result": "PASS", "details": "OK", "severity": "INFO"}

    def _check_model_validity(self, valid: bool) -> dict[str, Any]:
        """Şampiyon ML modelinin geçerli ve yüklü olup olmadığını doğrular."""
        if not valid:
            return {
                "check_name": "model_validity",
                "result": "NO_TRADE",
                "details": "Champion model invalid or not loaded — NO_TRADE",
                "severity": "BLOCK",
            }
        return {"check_name": "model_validity", "result": "PASS", "details": "OK", "severity": "INFO"}

    def _check_market_regime(
        self, side: str, market_regime: str, index_trend_bullish: bool | None
    ) -> dict[str, Any]:
        """Endeks rejimini ve ana piyasa trendini denetler.

        Ayı piyasasında (XU100 < SMA200 veya BEAR/CRISIS rejimi) yeni ALIM (BUY) emirlerini
        kesin olarak engeller ve portföyü Nakit Kalkanı (Cash Shield) moduna alır.
        Pozisyon azaltma veya stop çıkışları için SATIŞ (SELL) emirlerine izin verilir.
        """
        if side == "SELL":
            return {
                "check_name": "market_regime_shield",
                "result": "PASS",
                "details": "SELL side — risk azaltma/çıkış serbest",
                "severity": "INFO",
            }

        regime_upper = (market_regime or "").upper()
        is_bear_regime = regime_upper in ("BEAR", "CRISIS", "RISK_OFF", "BEAR_TREND", "PANIC")
        is_below_sma200 = (index_trend_bullish is False)

        if is_bear_regime or is_below_sma200:
            reason = []
            if is_bear_regime:
                reason.append(f"Ayı Rejimi ({regime_upper})")
            if is_below_sma200:
                reason.append("Endeks SMA200 Altında (Trend Negatif)")
            reason_str = " & ".join(reason)

            logger.warning(
                "Risk gate CASH SHIELD: Alım emri reddedildi",
                regime=regime_upper,
                index_trend_bullish=index_trend_bullish,
                reason=reason_str,
            )
            return {
                "check_name": "market_regime_shield",
                "result": "NO_TRADE",
                "details": f"Nakit Kalkanı Aktif ({reason_str}) — Ayı piyasasında yeni alım yasak",
                "severity": "BLOCK",
            }

        return {
            "check_name": "market_regime_shield",
            "result": "PASS",
            "details": f"Piyasa rejimi uygun ({regime_upper or 'BULL/NEUTRAL'})",
            "severity": "INFO",
        }

    def _check_portfolio_drawdown_shield(
        self, portfolio, side: str
    ) -> dict[str, Any]:
        """Portfoy drawdown kalkani: Zirve degerinden portfolio_dd_shield_pct dusunce yeni alim durdurur.

        Bu kalkan 2023 gibi yillarda portfoy kayip yaparken yeni pozisyon acilmasini engeller.
        Endeks BULL gorunsede portfoy zirve degerinden bu kadar geri cekildiyse yeni alim yasaktir.
        SELL emirlerine dokunmaz.

        Args:
            portfolio: Guncel portfoy nesnesi.
            side: Islem yonu ('BUY' veya 'SELL').

        Returns:
            Risk check sonuc sozlugu.
        """
        if side == "SELL":
            return {
                "check_name": "portfolio_dd_shield",
                "result": "PASS",
                "details": "SELL side — cikis serbest",
                "severity": "INFO",
            }

        current_value = portfolio.get_total_value()
        if current_value <= 0:
            return {"check_name": "portfolio_dd_shield", "result": "PASS", "details": "Portfolio bos", "severity": "INFO"}

        # Zirve guncelle
        if current_value > self._portfolio_peak_value:
            self._portfolio_peak_value = current_value

        if self._portfolio_peak_value <= 0:
            return {"check_name": "portfolio_dd_shield", "result": "PASS", "details": "Henuz zirve yok", "severity": "INFO"}

        dd_pct = (1.0 - current_value / self._portfolio_peak_value) * 100.0
        if dd_pct >= self.portfolio_dd_shield_pct:
            logger.warning(
                "Portfoy drawdown kalkani aktif — yeni alim durduruldu",
                drawdown_pct=round(dd_pct, 2),
                peak=round(self._portfolio_peak_value, 0),
                current=round(current_value, 0),
                threshold_pct=self.portfolio_dd_shield_pct,
            )
            return {
                "check_name": "portfolio_dd_shield",
                "result": "NO_TRADE",
                "details": f"Portfoy zirve degerinden -%{dd_pct:.1f} geriledi (esik: -%{self.portfolio_dd_shield_pct}%) — yeni alim durduruldu",
                "severity": "BLOCK",
            }
        return {
            "check_name": "portfolio_dd_shield",
            "result": "PASS",
            "details": f"Portfoy zirveden -%{dd_pct:.1f}% (esik -%{self.portfolio_dd_shield_pct}% altinda)",
            "severity": "INFO",
        }

    def _check_vol_spike_shield(
        self, side: str, index_returns_5d: list[float] | None
    ) -> dict[str, Any]:
        """Volatilite spike kalkani: 5 gunluk endeks volatilitesi kritik esigi asinca yeni alimi durdurur.

        Bu kalkan darbe, kriz, faiz soku gibi ani volatilite artislarinda tetiklenir.
        index_returns_5d son 5 gunluk XU100 gunluk getiri listesidir.
        SELL emirlerine dokunmaz.

        Args:
            side: Islem yonu.
            index_returns_5d: Son 5 gunluk XU100 gunluk getiri oranlari (float listesi, ornek [-0.02, 0.01, ...]).

        Returns:
            Risk check sonuc sozlugu.
        """
        if side == "SELL":
            return {
                "check_name": "vol_spike_shield",
                "result": "PASS",
                "details": "SELL side — cikis serbest",
                "severity": "INFO",
            }

        if not index_returns_5d or len(index_returns_5d) < 3:
            return {"check_name": "vol_spike_shield", "result": "PASS", "details": "Yeterli veri yok", "severity": "INFO"}

        import math
        rets = list(index_returns_5d[-5:])
        n = len(rets)
        mean_r = sum(rets) / n
        variance = sum((r - mean_r) ** 2 for r in rets) / max(n - 1, 1)
        std_r = math.sqrt(variance)
        vol_annualized = std_r * math.sqrt(252) * 100.0

        if vol_annualized >= self.vol_spike_shield_pct:
            logger.warning(
                "Volatilite spike kalkani aktif — yeni alim durduruldu",
                vol_5d_annualized=round(vol_annualized, 1),
                threshold_pct=self.vol_spike_shield_pct,
            )
            return {
                "check_name": "vol_spike_shield",
                "result": "NO_TRADE",
                "details": f"5g endeks volatilitesi %{vol_annualized:.1f} (annualized) > esik %{self.vol_spike_shield_pct} — kriz kalkani aktif",
                "severity": "BLOCK",
            }
        return {
            "check_name": "vol_spike_shield",
            "result": "PASS",
            "details": f"5g vol %{vol_annualized:.1f} < esik %{self.vol_spike_shield_pct}",
            "severity": "INFO",
        }

    def reset_portfolio_peak(self, new_peak: float = 0.0) -> None:
        """Portfoy drawdown kalkani icin zirve degerini sifirlar (test/reset amacli).

        Args:
            new_peak: Yeni zirve degeri (varsayilan 0 = otomatik guncelleme).
        """
        self._portfolio_peak_value = new_peak
        logger.info("Portfoy zirve degeri sifirlandi", new_peak=new_peak)


    def _check_position_size(self, portfolio, ticker: str, side: str, quantity: int, price: float) -> dict[str, Any]:
        """Yeni hisse alımının tek hisse tavan yüzdesini aşıp aşmadığını denetler."""

        if side == "SELL":
            return {
                "check_name": "position_size",
                "result": "PASS",
                "details": "SELL side — no position size limit",
                "severity": "INFO",
            }

        total_value = portfolio.get_total_value()
        if total_value <= 0:
            return {
                "check_name": "position_size",
                "result": "BLOCK",
                "details": "Portfolio value is zero",
                "severity": "BLOCK",
            }

        new_position_value = quantity * price
        current_position_value = 0.0
        pos = portfolio.get_position(ticker)
        if pos:
            current_position_value = pos["market_value"]

        total_position_value = current_position_value + new_position_value
        position_pct = (total_position_value / total_value) * 100

        if position_pct > self.max_position_pct:
            return {
                "check_name": "position_size",
                "result": "BLOCK",
                "details": f"Position {position_pct:.1f}% > limit {self.max_position_pct}%",
                "severity": "BLOCK",
            }
        return {
            "check_name": "position_size",
            "result": "PASS",
            "details": f"{position_pct:.1f}% <= {self.max_position_pct}%",
            "severity": "INFO",
        }

    def _check_sector_concentration(
        self, portfolio, ticker: str, side: str, quantity: int, price: float, sector: str
    ) -> dict[str, Any]:
        """Yeni hisse alımının sektör yoğunlaşma sınırını aşıp aşmadığını denetler."""
        if not sector or side == "SELL":
            return {
                "check_name": "sector_concentration",
                "result": "PASS",
                "details": "No sector or SELL side",
                "severity": "INFO",
            }

        total_value = portfolio.get_total_value()
        if total_value <= 0:
            return {
                "check_name": "sector_concentration",
                "result": "PASS",
                "details": "Portfolio value is zero",
                "severity": "INFO",
            }

        sector_values = defaultdict(float)
        for pos in portfolio.get_all_positions():
            s = pos.get("sector", "UNKNOWN")
            sector_values[s] += pos["market_value"]

        new_value = quantity * price
        sector_values[sector] += new_value

        max_sector_pct = max((v / total_value) * 100 for v in sector_values.values())

        if max_sector_pct > self.max_sector_pct:
            return {
                "check_name": "sector_concentration",
                "result": "BLOCK",
                "details": f"Sector {sector}: {max_sector_pct:.1f}% > limit {self.max_sector_pct}%",
                "severity": "BLOCK",
            }
        return {
            "check_name": "sector_concentration",
            "result": "PASS",
            "details": f"Max sector {max_sector_pct:.1f}% <= {self.max_sector_pct}%",
            "severity": "INFO",
        }

    def _check_portfolio_exposure(
        self, portfolio, ticker: str, side: str, quantity: int, price: float
    ) -> dict[str, Any]:
        """Toplam portföy hisse risk maruziyetini (exposure %) denetler."""
        total_value = portfolio.get_total_value()
        if total_value <= 0:
            return {
                "check_name": "portfolio_exposure",
                "result": "PASS",
                "details": "Portfolio value is zero",
                "severity": "INFO",
            }

        current_exposure = portfolio.get_invested_value()
        if side == "BUY":
            new_exposure = current_exposure + (quantity * price)
        else:
            pos = portfolio.get_position(ticker)
            sell_value = min(quantity * price, pos["market_value"]) if pos else 0
            new_exposure = max(0, current_exposure - sell_value)

        exposure_pct = (new_exposure / total_value) * 100

        if exposure_pct > self.max_portfolio_exposure_pct:
            return {
                "check_name": "portfolio_exposure",
                "result": "BLOCK",
                "details": f"Exposure {exposure_pct:.1f}% > limit {self.max_portfolio_exposure_pct}%",
                "severity": "BLOCK",
            }
        return {
            "check_name": "portfolio_exposure",
            "result": "PASS",
            "details": f"{exposure_pct:.1f}% <= {self.max_portfolio_exposure_pct}%",
            "severity": "INFO",
        }

    def _check_drawdown(self, portfolio) -> dict[str, Any]:
        """Mevcut tepe-dip düşüşünü alarm ve kill switch sınırlarına göre denetler."""
        current_dd = portfolio.get_current_drawdown()

        if current_dd >= self.kill_switch_drawdown_pct:
            self._kill_switch_active = True
            self._kill_switch_reason = f"Max drawdown {current_dd:.1f}% >= kill-switch {self.kill_switch_drawdown_pct}%"
            return {
                "check_name": "drawdown",
                "result": "BLOCK",
                "details": self._kill_switch_reason,
                "severity": "BLOCK",
            }

        if current_dd >= self.max_drawdown_pct:
            return {
                "check_name": "drawdown",
                "result": "WARN",
                "details": f"Drawdown {current_dd:.1f}% >= alarm {self.max_drawdown_pct}%",
                "severity": "WARN",
            }

        return {
            "check_name": "drawdown",
            "result": "PASS",
            "details": f"{current_dd:.1f}% < {self.max_drawdown_pct}%",
            "severity": "INFO",
        }

    def _check_daily_loss(self, portfolio) -> dict[str, Any]:
        """Günlük kayıp oranını izin verilen günlük limit yüzdesine göre denetler."""
        if len(portfolio._equity_curve) < 2:
            return {"check_name": "daily_loss", "result": "PASS", "details": "Not enough history", "severity": "INFO"}

        recent = portfolio._equity_curve[-2:]
        if len(recent) >= 2:
            daily_return = (recent[-1]["equity"] / recent[-2]["equity"] - 1) * 100
            if daily_return <= -self.daily_loss_limit_pct:
                return {
                    "check_name": "daily_loss",
                    "result": "BLOCK",
                    "details": f"Daily loss {daily_return:.1f}% >= limit {self.daily_loss_limit_pct}%",
                    "severity": "BLOCK",
                }
        return {"check_name": "daily_loss", "result": "PASS", "details": "OK", "severity": "INFO"}

    def record_error(self) -> Any:
        """Ard arda hata sayacini artir."""
        self._consecutive_errors += 1
        if self._consecutive_errors >= self._max_consecutive_errors:
            self._kill_switch_active = True
            self._kill_switch_reason = f"{self._consecutive_errors} consecutive errors — kill switch activated"
            logger.critical(self._kill_switch_reason)

    def clear_errors(self) -> Any:
        """Hata sayacini sifirla."""
        self._consecutive_errors = 0


# Singleton
paper_risk_gate = PaperRiskGate()
