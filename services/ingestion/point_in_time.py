"""
ALPHA BIST — Point-in-Time Validator v1.0

Look-ahead bias önleme:
Backtest'te sadece o anda bilinen veriyi kullan.

Her veri tipi için gecikme süresi tanımlı:
- Market price: 15dk (yfinance gecikmeli)
- KAP disclosure: anında
- Fundamental: ertesi gün
- Macro TCMB: 1 saat
- News: 5 dakika
- Social: 10 dakika

Kullanım:
    pit = PointInTimeValidator()
    available = pit.is_available_at("market_price", data_ts, query_ts)
    filtered = pit.filter_available(data, "market_price", query_ts)
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
import structlog

logger = structlog.get_logger()


@dataclass
class PITConfig:
    """Point-in-time yapılandırması."""
    data_type: str
    delay: timedelta
    description: str


class PointInTimeValidator:
    """
    Look-ahead bias önleme.

    Her veri tipi için tanımlı gecikme süresiyle,
    verinin o anda bilinip bilinmediğini kontrol eder.
    """

    # Veri tipleri için gecikme süreleri
    DATA_DELAYS: Dict[str, PITConfig] = {
        "market_price": PITConfig(
            data_type="market_price",
            delay=timedelta(minutes=15),
            description="yfinance: 15dk gecikmeli",
        ),
        "market_realtime": PITConfig(
            data_type="market_realtime",
            delay=timedelta(seconds=0),
            description="Matriks/BIST realtime: anında",
        ),
        "kap_disclosure": PITConfig(
            data_type="kap_disclosure",
            delay=timedelta(seconds=0),
            description="KAP: anında",
        ),
        "fundamental": PITConfig(
            data_type="fundamental",
            delay=timedelta(days=1),
            description="Bilanço: ertesi gün bilinir",
        ),
        "macro_tcmb": PITConfig(
            data_type="macro_tcmb",
            delay=timedelta(hours=1),
            description="TCMB: 1 saat gecikmeli",
        ),
        "macro_fred": PITConfig(
            data_type="macro_fred",
            delay=timedelta(hours=1),
            description="FRED: 1 saat gecikmeli",
        ),
        "news": PITConfig(
            data_type="news",
            delay=timedelta(minutes=5),
            description="Haberler: 5 dakika gecikmeli",
        ),
        "social": PITConfig(
            data_type="social",
            delay=timedelta(minutes=10),
            description="Sosyal medya: 10 dakika gecikmeli",
        ),
        "corporate_action": PITConfig(
            data_type="corporate_action",
            delay=timedelta(seconds=0),
            description="KAP açıklaması: anında (ama etki ex_date'te)",
        ),
    }

    def is_available_at(
        self,
        data_type: str,
        data_timestamp: datetime,
        query_timestamp: datetime,
    ) -> bool:
        """
        Veri query_timestamp'te biliniyor muydu?

        Args:
            data_type: Veri tipi (ör: "market_price", "fundamental")
            data_timestamp: Verinin oluşturulma/zaman damgası
            query_timestamp: Sorgu zamanı (backtest'te o anki zaman)

        Returns:
            True: Veri o anda biliniyordu
            False: Veri gelecekte (look-ahead bias!)
        """
        config = self.DATA_DELAYS.get(data_type)
        if not config:
            # Bilinmeyen veri tipi — varsayılan: anında
            return data_timestamp <= query_timestamp

        delay = config.delay
        earliest_available = data_timestamp + delay

        return query_timestamp >= earliest_available

    def filter_available(
        self,
        data: List[Dict],
        data_type: str,
        query_timestamp: datetime,
        timestamp_field: str = "timestamp",
    ) -> List[Dict]:
        """
        Sadece o tarihte bilinen veriyi döndür.

        Args:
            data: Veri listesi
            data_type: Veri tipi
            query_timestamp: Sorgu zamanı
            timestamp_field: Timestamp alan adı

        Returns:
            Filtrelenmiş veri listesi
        """
        filtered = []
        removed_count = 0

        for item in data:
            ts_str = item.get(timestamp_field)
            if not ts_str:
                # Timestamp yok → bilinmeyen durum, filtrele
                removed_count += 1
                continue

            try:
                if isinstance(ts_str, datetime):
                    data_ts = ts_str
                else:
                    data_ts = datetime.fromisoformat(str(ts_str))

                if self.is_available_at(data_type, data_ts, query_timestamp):
                    filtered.append(item)
                else:
                    removed_count += 1
            except (ValueError, TypeError):
                removed_count += 1
                continue

        if removed_count > 0:
            logger.debug("PIT filtered",
                        data_type=data_type,
                        removed=removed_count,
                        kept=len(filtered))

        return filtered

    def validate_no_lookahead(
        self,
        data: List[Dict],
        data_type: str,
        query_timestamp: datetime,
        timestamp_field: str = "timestamp",
    ) -> Dict[str, Any]:
        """
        Look-ahead bias kontrolü — sadece doğrulama, filtreleme yapmaz.

        Returns:
            {
                "clean": True/False,
                "violations": [...],
                "total_checked": int,
            }
        """
        violations = []

        for i, item in enumerate(data):
            ts_str = item.get(timestamp_field)
            if not ts_str:
                continue

            try:
                if isinstance(ts_str, datetime):
                    data_ts = ts_str
                else:
                    data_ts = datetime.fromisoformat(str(ts_str))

                if not self.is_available_at(data_type, data_ts, query_timestamp):
                    violations.append({
                        "index": i,
                        "data_timestamp": data_ts.isoformat(),
                        "query_timestamp": query_timestamp.isoformat(),
                        "data_type": data_type,
                    })
            except (ValueError, TypeError):
                continue

        return {
            "clean": len(violations) == 0,
            "violations": violations,
            "total_checked": len(data),
            "violation_count": len(violations),
        }

    def get_delay(self, data_type: str) -> Optional[timedelta]:
        """Veri tipi için gecikme süresini döndür."""
        config = self.DATA_DELAYS.get(data_type)
        return config.delay if config else None

    def set_custom_delay(self, data_type: str, delay: timedelta, description: str = ""):
        """Özel gecikme süresi tanımla."""
        self.DATA_DELAYS[data_type] = PITConfig(
            data_type=data_type,
            delay=delay,
            description=description or f"Custom delay: {delay}",
        )
        logger.info("Custom PIT delay set",
                    data_type=data_type,
                    delay_seconds=delay.total_seconds())


# Singleton
pit_validator = PointInTimeValidator()
