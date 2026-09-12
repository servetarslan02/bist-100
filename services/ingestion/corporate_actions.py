"""
ALPHA BIST — Corporate Actions Handler v1.0

Temettü, bölünme, bedelsiz, bedelli, birleşme gibi şirket olaylarını
fiyat ve portföy geçmişine doğru şekilde yansıtır.

FAZ 1.5: Corporate Actions

Kullanım:
    from services.ingestion.corporate_actions import corporate_actions

    corporate_actions.load_from_kap(kap_events)
    adj_price = corporate_actions.adjust_price("THYAO", 250.0, date(2025, 3, 1))
"""

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any

import structlog

logger = structlog.get_logger()

# Temettü çıkarma regex kalıpları
_DIVIDEND_PATTERNS: list[str] = [
    r"hisseye\s+(\d+[.,]\d+)\s*(?:TL|₺)",
    r"(\d+[.,]\d+)\s*(?:TL|₺)\s*/?\s*hisse",
    r"kar\s+payı\s+(\d+[.,]\d+)",
]

# Bölünme çıkarma regex kalıpları
_SPLIT_PATTERNS: list[str] = [
    r"1[''e]\s*(\d+)",
    r"(\d+)\s*:\s*1",
    r"(\d+)\s*kata\s*çıkar",
]


class ActionType(StrEnum):
    """Şirket olayı türleri.

    Attributes:
        DIVIDEND: Temettü (kar payı) dağıtımı.
        STOCK_SPLIT: Hisse bölünmesi.
        BONUS_SHARE: Bedelsiz sermaye artırımı.
        RIGHTS_ISSUE: Bedelli sermaye artırımı.
        MERGER: Birleşme.
        ACQUISITION: Devralma.
        DELISTING: Borsadan çıkış.
        NAME_CHANGE: İsim değişikliği.
    """

    DIVIDEND = "DIVIDEND"
    STOCK_SPLIT = "STOCK_SPLIT"
    BONUS_SHARE = "BONUS_SHARE"
    RIGHTS_ISSUE = "RIGHTS_ISSUE"
    MERGER = "MERGER"
    ACQUISITION = "ACQUISITION"
    DELISTING = "DELISTING"
    NAME_CHANGE = "NAME_CHANGE"


@dataclass
class CorporateAction:
    """Şirket olayı veri modeli.

    Attributes:
        action_id: Benzersiz olay kimliği.
        ticker: Hisse sembolü.
        action_type: Olay türü.
        ex_date: Eski tarih (fiyat düzeltmesi bu tarihte yapılır).
        record_date: Kayıt tarihi.
        payment_date: Ödeme tarihi.
        dividend_per_share: Hisse başına temettü.
        dividend_currency: Temettü para birimi.
        split_ratio: Bölünme oranı (ör. 2.0 = 1'e 2).
        bonus_ratio: Bedelsiz oranı (ör. 0.5 = her 1 hisseye 0.5).
        rights_ratio: Bedelli oranı (ör. 0.2 = her 5 hisseye 1 yeni).
        rights_price: Bedelli fiyatı.
        description: Olay açıklaması.
        source: Veri kaynağı.
        is_confirmed: Onaylanmış olay mı.
        created_at: Oluşturulma zamanı.
    """

    action_id: str
    ticker: str
    action_type: ActionType
    ex_date: date
    record_date: date | None = None
    payment_date: date | None = None
    dividend_per_share: float = 0.0
    dividend_currency: str = "TRY"
    split_ratio: float = 1.0
    bonus_ratio: float = 0.0
    rights_ratio: float = 0.0
    rights_price: float = 0.0
    description: str = ""
    source: str = "KAP"
    is_confirmed: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __repr__(self) -> str:
        return (
            f"CorporateAction(ticker={self.ticker!r}, "
            f"type={self.action_type.value!r}, "
            f"ex_date={self.ex_date.isoformat()!r})"
        )


class CorporateActionsHandler:
    """Şirket olaylarını yönetir ve fiyat/portföy düzeltmeleri yapar.

    KAP'tan gelen olayları sınıflandırır, fiyat ve pozisyon
    düzeltmelerini doğru şekilde uygular.

    Raises:
        ValueError: Geçersiz olay verisi yüklendiğinde.
    """

    def __init__(self) -> None:
        """CorporateActionsHandler örneği oluşturur."""
        self._actions: dict[str, list[CorporateAction]] = {}
        self._applied: set[str] = set()

    def add_action(self, action: CorporateAction) -> None:
        """Şirket olayı ekler.

        Args:
            action: Eklenecek CorporateAction örneği.

        Raises:
            ValueError: Ticker boş olduğunda.
        """
        if not action.ticker or not action.ticker.strip():
            logger.warning("Corporate action rejected: empty ticker", action_id=action.action_id)
            return
        if not action.action_id:
            action.action_id = f"{action.ticker}-{action.action_type.value}-{action.ex_date.isoformat()}"
        if action.ticker not in self._actions:
            self._actions[action.ticker] = []
        self._actions[action.ticker].append(action)
        logger.info(
            "Corporate action added",
            ticker=action.ticker,
            type=action.action_type.value,
            ex_date=action.ex_date.isoformat(),
        )

    def get_actions(
        self,
        ticker: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[CorporateAction]:
        """Şirket olaylarını getirir.

        Args:
            ticker: Hisse sembolü.
            start_date: Başlangıç tarihi filtresi.
            end_date: Bitiş tarihi filtresi.

        Returns:
            Filtrelenmiş CorporateAction listesi.
        """
        actions = self._actions.get(ticker, [])

        if start_date:
            actions = [a for a in actions if a.ex_date >= start_date]
        if end_date:
            actions = [a for a in actions if a.ex_date <= end_date]

        return actions

    def adjust_price(self, ticker: str, price: float, price_date: date) -> float:
        """Geçmiş fiyatı şirket olaylarına göre düzeltir.

        Backtest'te kullanılır. Fiyat, o tarihteki bilinen olaylara göre düzeltilir.

        Args:
            ticker: Hisse kodu.
            price: Düzeltilmemiş fiyat.
            price_date: Fiyat tarihi.

        Returns:
            Düzeltilmiş fiyat.
        """
        adjusted = price
        actions = self._actions.get(ticker, [])

        for action in actions:
            if action.ex_date > price_date:
                adjusted = self._adjust_single_price(adjusted, action)

        return round(adjusted, 4)

    def adjust_position(self, ticker: str, quantity: int, action: CorporateAction) -> int:
        """Pozisyon miktarını şirket olayına göre düzeltir.

        Args:
            ticker: Hisse kodu.
            quantity: Mevcut lot sayısı.
            action: Şirket olayı.

        Returns:
            Düzeltilmiş lot sayısı.
        """
        if action.action_type == ActionType.STOCK_SPLIT:
            if action.split_ratio > 1:
                return int(quantity * action.split_ratio)

        elif action.action_type == ActionType.BONUS_SHARE:
            if action.bonus_ratio > 0:
                return int(quantity * (1 + action.bonus_ratio))

        elif action.action_type == ActionType.RIGHTS_ISSUE and action.rights_ratio > 0:
            new_shares = int(quantity * action.rights_ratio)
            return quantity + new_shares

        return quantity

    def compute_dividend_income(self, ticker: str, quantity: int, action: CorporateAction) -> float:
        """Temettü gelirini hesaplar.

        Args:
            ticker: Hisse kodu.
            quantity: Lot sayısı.
            action: Temettü olayı.

        Returns:
            Toplam temettü geliri (brüt).
        """
        if action.action_type != ActionType.DIVIDEND:
            return 0.0

        return quantity * action.dividend_per_share

    def adjust_historical_prices(
        self,
        ticker: str,
        prices: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Geçmiş fiyat serisini şirket olaylarına göre düzeltir.

        Backtest'te kullanılır: bugünün bilinen olaylarıyla geçmişi düzeltir.
        Her bar bağımsız olarak orijinal değerlerden düzeltilir (compounding yok).

        Args:
            ticker: Hisse kodu.
            prices: [{"date": date, "open": float, "high": float,
                      "low": float, "close": float, "volume": int}, ...]

        Returns:
            Düzeltilmiş fiyat serisi.
        """
        actions = self._actions.get(ticker, [])
        if not actions:
            return prices

        adjusted: list[dict[str, Any]] = []
        for bar in prices:
            bar_date = bar["date"] if isinstance(bar["date"], date) else date.fromisoformat(str(bar["date"]))

            # Orijinal değerleri koru — üst üste düzeltme yapma
            adj_open = float(bar["open"])
            adj_high = float(bar["high"])
            adj_low = float(bar["low"])
            adj_close = float(bar["close"])
            adj_volume = int(bar["volume"])

            for action in actions:
                if action.ex_date > bar_date:
                    adj_open = self._adjust_single_price(adj_open, action)
                    adj_high = self._adjust_single_price(adj_high, action)
                    adj_low = self._adjust_single_price(adj_low, action)
                    adj_close = self._adjust_single_price(adj_close, action)

                    if action.action_type == ActionType.STOCK_SPLIT and action.split_ratio > 1:
                        adj_volume = int(adj_volume * action.split_ratio)
                    elif action.action_type == ActionType.BONUS_SHARE and action.bonus_ratio > 0:
                        adj_volume = int(adj_volume * (1 + action.bonus_ratio))

            adjusted.append({
                "date": bar["date"],
                "open": adj_open,
                "high": adj_high,
                "low": adj_low,
                "close": adj_close,
                "volume": adj_volume,
            })

        return adjusted

    def _adjust_single_price(self, price: float, action: CorporateAction) -> float:
        """Tek bir fiyatı tek bir olaya göre düzeltir.

        Args:
            price: Düzeltilmemiş fiyat.
            action: Uygulanacak şirket olayı.

        Returns:
            Düzeltilmiş fiyat.
        """
        if action.action_type == ActionType.DIVIDEND:
            return max(0, price - action.dividend_per_share)
        elif action.action_type == ActionType.STOCK_SPLIT and action.split_ratio > 1:
            return price / action.split_ratio
        elif action.action_type == ActionType.BONUS_SHARE and action.bonus_ratio > 0:
            return price / (1 + action.bonus_ratio)
        elif action.action_type == ActionType.RIGHTS_ISSUE and action.rights_ratio > 0:
            return (price + action.rights_price * action.rights_ratio) / (1 + action.rights_ratio)
        return price

    def load_from_kap(self, kap_events: list[dict[str, Any]]) -> None:
        """KAP'tan gelen şirket olaylarını yükler.

        Args:
            kap_events: KAP ham olay listesi.
        """
        if not kap_events:
            return

        for event in kap_events:
            try:
                action_type = self._classify_kap_event(event)
                if action_type is None:
                    continue

                action = CorporateAction(
                    action_id=event.get("kap_id", ""),
                    ticker=event.get("ticker", ""),
                    action_type=action_type,
                    ex_date=self._parse_date(event.get("publish_date", "")),
                    description=event.get("title", ""),
                    source="KAP",
                )

                if action_type == ActionType.DIVIDEND:
                    action.dividend_per_share = self._extract_dividend_amount(event)

                if action_type in (ActionType.STOCK_SPLIT, ActionType.BONUS_SHARE):
                    action.split_ratio = self._extract_split_ratio(event)

                if action.ticker:
                    self.add_action(action)
            except Exception as exc:
                logger.warning("Failed to process KAP event", error=str(exc))
                continue

    def _classify_kap_event(self, event: dict[str, Any]) -> ActionType | None:
        """KAP olayını sınıflandırır.

        Args:
            event: KAP ham olay verisi.

        Returns:
            ActionType veya sınıflandırılamazsa None.
        """
        title = event.get("title", "").lower()
        subject = event.get("subject", "").lower()
        text = f"{title} {subject}"

        if any(w in text for w in ["temettü", "kar payı", "dividend"]):
            return ActionType.DIVIDEND
        elif any(w in text for w in ["bedelsiz", "bonus", "sermaye artırımı"]):
            return ActionType.BONUS_SHARE
        elif any(w in text for w in ["bedelli", "rights issue"]):
            return ActionType.RIGHTS_ISSUE
        elif any(w in text for w in ["bölünme", "split", "grup değişimi"]):
            return ActionType.STOCK_SPLIT
        elif any(w in text for w in ["birleşme", "merger"]):
            return ActionType.MERGER
        elif any(w in text for w in ["devralma", "acquisition", "satın alma"]):
            return ActionType.ACQUISITION
        elif any(w in text for w in ["borsadan çıkış", "delisting"]):
            return ActionType.DELISTING

        return None

    def _extract_dividend_amount(self, event: dict[str, Any]) -> float:
        """Temettü miktarını KAP açıklamasından çıkarır.

        Args:
            event: KAP ham olay verisi.

        Returns:
            Hisse başına temettü miktarı (bulunamazsa 0.0).
        """
        text = event.get("title", "") + " " + event.get("summary", "")

        for pattern in _DIVIDEND_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                amount_str = match.group(1).replace(",", ".")
                try:
                    return float(amount_str)
                except ValueError:
                    continue

        return 0.0

    def _extract_split_ratio(self, event: dict[str, Any]) -> float:
        """Bölünme oranını KAP açıklamasından çıkarır.

        Args:
            event: KAP ham olay verisi.

        Returns:
            Bölünme oranı (bulunamazsa 1.0).
        """
        text = event.get("title", "") + " " + event.get("summary", "")

        for pattern in _SPLIT_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    return float(match.group(1))
                except ValueError:
                    continue

        return 1.0

    def _parse_date(self, date_str: str) -> date:
        """Tarih string'ini date objesine çevirir.

        Args:
            date_str: Tarih string'i (çeşitli formatlar desteklenir).

        Returns:
            date objesi.

        Raises:
            ValueError: Hiçbir formata uymayan ve boş olmayan tarih.
        """
        if not date_str:
            return date.today()

        formats = ["%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y", "%Y-%m-%dT%H:%M:%S"]
        for fmt in formats:
            try:
                return datetime.strptime(date_str[:10], fmt[: len(date_str[:10])]).date()
            except ValueError:
                continue

        logger.warning("Tarih parse edilemedi, bugün kullanılıyor", date_str=date_str)
        return date.today()


# Singleton
corporate_actions = CorporateActionsHandler()


__all__ = [
    "ActionType",
    "CorporateAction",
    "CorporateActionsHandler",
    "corporate_actions",
]
