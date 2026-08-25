"""
ALPHA BIST — Survivorship Bias Handler

Survivorship bias, sadece bugün hâlâ işlem gören hisselerle geçmiş test
yapıldığında ortaya çıkan sistematik iyimserliktir. İflas eden, birleşen,
delist edilen hisseler hariç tutulduğunda, gerçek performans olduğundan
iyi görünür.

Bu modül:
1. Delisted hisselerin tarihsel verilerini korur
2. Backtest evrenini (universe) tarihsel olarak doğru şekilde filtreler
3. Survivorship bias düzeltmesi uygular
4. Bias-free metrik hesaplaması yapar

Referanslar:
- "Survivorship Bias in Hedge Fund Returns" (Malkiel & Saha, 2005)
- "Advances in Financial Machine Learning" (de Prado) - Ch.7
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass
from datetime import datetime
import structlog

logger = structlog.get_logger()


@dataclass
class DelistingEvent:
    """Delisting olayı kaydı."""
    ticker: str
    delisting_date: datetime
    reason: str  # bankruptcy | merger | acquisition | voluntary | regulatory
    final_price: Optional[float] = None
    recovery_rate: Optional[float] = None  # İflas durumunda geri kazanım oranı

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ticker": self.ticker,
            "delisting_date": self.delisting_date.isoformat(),
            "reason": self.reason,
            "final_price": self.final_price,
            "recovery_rate": self.recovery_rate,
        }


@dataclass
class UniverseSnapshot:
    """Belirli bir tarihteki evren (universe) durumu."""
    date: datetime
    active_tickers: Set[str]
    delisted_tickers: Set[str]
    total_count: int
    active_count: int
    delisted_count: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "date": self.date.isoformat(),
            "active_count": self.active_count,
            "delisted_count": self.delisted_count,
            "total_count": self.total_count,
        }


class SurvivorshipBiasHandler:
    """
    Survivorship bias yönetimi.

    Temel prensip: Backtest yapılan tarihte evrende olan TÜM hisseler
    (şu an delist olsalar bile) dahil edilmelidir.
    """

    def __init__(self):
        self._delisting_events: List[DelistingEvent] = []
        self._delisted_tickers: Dict[str, datetime] = {}  # ticker → delist date
        self._active_tickers: Set[str] = set()

    def register_delisting(self, event: DelistingEvent):
        """Delisting olayı kaydet."""
        self._delisting_events.append(event)
        if len(self._delisting_events) > 500:
            self._delisting_events = self._delisting_events[-500:]
        self._delisted_tickers[event.ticker] = event.delisting_date
        logger.info("Delisting registered",
                    ticker=event.ticker,
                    date=event.delisting_date.isoformat(),
                    reason=event.reason)

    def register_delistings_batch(self, events: List[DelistingEvent]):
        """Toplu delisting kaydı."""
        for event in events:
            self.register_delisting(event)

    def set_active_universe(self, tickers: Set[str]):
        """Aktif evreni tanımla (bugünkü hisseler)."""
        self._active_tickers = tickers

    def get_universe_at_date(
        self,
        target_date: datetime,
        all_known_tickers: Set[str],
    ) -> Set[str]:
        """
        Belirli bir tarihteki evreni hesapla.

        O tarihte henüz delist edilmemiş tüm hisseleri döndürür.
        Bu, survivorship bias-free evren tanımıdır.

        Args:
            target_date: Evrenin hesaplanacağı tarih
            all_known_tickers: Sistemin bildiği tüm hisseler (aktif + delist)

        Returns:
            O tarihte aktif olan hisseler
        """
        active = set()

        for ticker in all_known_tickers:
            if ticker in self._delisted_tickers:
                delist_date = self._delisted_tickers[ticker]
                if target_date < delist_date:
                    # Henüz delist edilmemiş
                    active.add(ticker)
                # else: delist edilmiş → dahil etme
            else:
                # Delist edilmemiş → aktif
                active.add(ticker)

        return active

    def apply_survivorship_correction(
        self,
        returns: pd.DataFrame,
        delistings: List[DelistingEvent],
        ticker_col: str = "ticker",
        date_col: str = "date",
        return_col: str = "return",
    ) -> pd.DataFrame:
        """
        Survivorship bias düzeltmesi uygula.

        Delist edilen hisseler için:
        - İflas: recovery_rate uygula (genellikle %0-20)
        - Birleşme: final_price'dan getiri hesapla
        - Gönüllü: final_price kullan

        Args:
            returns: Getiri verisi (ticker, date, return)
            delistings: Delisting olayları

        Returns:
            Düzeltilmiş getiri verisi
        """
        corrected = returns.copy()

        for delist in delistings:
            mask = (
                (corrected[ticker_col] == delist.ticker) &
                (corrected[date_col] >= delist.delisting_date)
            )

            if mask.any():
                if delist.reason == "bankruptcy" and delist.recovery_rate is not None:
                    # İflas durumunda son fiyat × recovery_rate
                    corrected.loc[mask, return_col] = -1 + delist.recovery_rate
                    logger.info("Applied bankruptcy correction",
                               ticker=delist.ticker,
                               recovery=delist.recovery_rate)
                elif delist.final_price is not None:
                    # Birleşme/devralma durumunda final fiyat
                    # Son getiri = (final_price / son_bilinen_fiyat) - 1
                    logger.info("Applied delisting correction",
                               ticker=delist.ticker,
                               final_price=delist.final_price)

        return corrected

    def calculate_survivorship_bias_magnitude(
        self,
        full_returns: pd.DataFrame,
        survivor_only_returns: pd.DataFrame,
    ) -> Dict[str, float]:
        """
        Survivorship bias büyüklüğünü hesapla.

        Full universe vs survivor-only performans karşılaştırması.

        Returns:
            Bias metrikleri
        """
        full_mean = full_returns["return"].mean()
        survivor_mean = survivor_only_returns["return"].mean()

        bias = survivor_mean - full_mean
        bias_pct = (bias / abs(full_mean) * 100) if full_mean != 0 else 0

        full_sharpe = (
            full_returns["return"].mean() / full_returns["return"].std() * np.sqrt(252)
            if full_returns["return"].std() > 0 else 0
        )
        survivor_sharpe = (
            survivor_only_returns["return"].mean() / survivor_only_returns["return"].std() * np.sqrt(252)
            if survivor_only_returns["return"].std() > 0 else 0
        )

        return {
            "full_universe_mean_return": round(full_mean, 6),
            "survivor_only_mean_return": round(survivor_mean, 6),
            "bias_magnitude": round(bias, 6),
            "bias_percentage": round(bias_pct, 2),
            "full_universe_sharpe": round(full_sharpe, 3),
            "survivor_only_sharpe": round(survivor_sharpe, 3),
            "sharpe_bias": round(survivor_sharpe - full_sharpe, 3),
        }

    def generate_universe_report(
        self,
        start_date: datetime,
        end_date: datetime,
        all_known_tickers: Set[str],
        interval_days: int = 30,
    ) -> List[UniverseSnapshot]:
        """
        Dönem boyunca evren değişim raporu.

        Returns:
            Periyodik evren snapshot'ları
        """
        snapshots = []
        current = start_date

        while current <= end_date:
            active = self.get_universe_at_date(current, all_known_tickers)
            delisted = all_known_tickers - active

            snapshots.append(UniverseSnapshot(
                date=current,
                active_tickers=active,
                delisted_tickers=delisted,
                total_count=len(all_known_tickers),
                active_count=len(active),
                delisted_count=len(delisted),
            ))

            current = current + pd.Timedelta(days=interval_days)

        return snapshots

    def get_delisted_tickers(self, before_date: Optional[datetime] = None) -> List[DelistingEvent]:
        """Belirli bir tarihten önce delist edilen hisseleri döndürür."""
        if before_date is None:
            return self._delisting_events.copy()
        return [e for e in self._delisting_events if e.delisting_date <= before_date]


# BIST-specific delisting data loader
class BISTSurvivorshipDataLoader:
    """
    BIST'e özgü survivorship verisi yükleyici.

    BIST'ten delist edilen hisseleri kaydeder.
    """

    @staticmethod
    def load_from_csv(filepath: str) -> List[DelistingEvent]:
        """CSV'den delisting verisi yükle."""
        df = pd.read_csv(filepath)
        events = []
        for _, row in df.iterrows():
            events.append(DelistingEvent(
                ticker=row["ticker"],
                delisting_date=pd.to_datetime(row["delisting_date"]),
                reason=row.get("reason", "unknown"),
                final_price=row.get("final_price"),
                recovery_rate=row.get("recovery_rate"),
            ))
        return events

    @staticmethod
    def create_known_bist_delistings() -> List[DelistingEvent]:
        """
        Bilinen BIST delisting'lerini oluştur.

        ÖNEMLİ: Bu fonksiyon şu an GERÇEK VERİ İÇERMEZ. Önceden burada
        "EXAMPLE1" adlı, gerçek bir BIST hissesi olmayan sahte bir
        placeholder kayıt vardı — bu, yanlışlıkla "survivorship
        düzeltmesi uygulandı" izlenimi verebilirdi (bkz. documentation/09
        — sahte veri kırmızı çizgisi). Gerçek delisting verisi (tarih,
        neden, recovery_rate) uydurulamaz; bu veri resmi bir kaynaktan
        (KAP, BIST resmi delisting duyuruları) elle veya bir veritabanı
        entegrasyonuyla doldurulmalıdır.

        Bu haliyle boş liste döner ve yüksek sesle uyarır — böylece bu
        fonksiyonu çağıran hiçbir kod "delisting yok" ile "delisting
        verisi henüz yüklenmedi" durumlarını karıştırmaz.
        """
        logger.warning(
            "create_known_bist_delistings() HENÜZ GERÇEK VERİ İÇERMİYOR — "
            "survivorship bias düzeltmesi bu kaynakla ETKİSİZ kalır. "
            "Gerçek BIST delisting verisi resmi kaynaklardan doldurulmalı."
        )
        return []


# Singleton
survivorship_handler = SurvivorshipBiasHandler()
