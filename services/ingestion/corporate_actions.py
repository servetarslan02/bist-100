"""
ALPHA BIST — Corporate Actions Handler v1.0

Temettü, bölünme, bedelsiz, bedelli, birleşme gibi şirket olaylarını
fiyat ve portföy geçmişine doğru şekilde yansıtır.

FAZ 1.5: Corporate Actions
"""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any

import structlog

logger = structlog.get_logger()


class ActionType(StrEnum):
    DIVIDEND = "DIVIDEND"  # Temettü
    STOCK_SPLIT = "STOCK_SPLIT"  # Bölünme
    BONUS_SHARE = "BONUS_SHARE"  # Bedelsiz sermaye artırımı
    RIGHTS_ISSUE = "RIGHTS_ISSUE"  # Bedelli sermaye artırımı
    MERGER = "MERGER"  # Birleşme
    ACQUISITION = "ACQUISITION"  # Devralma
    DELISTING = "DELISTING"  # Borsadan çıkış
    NAME_CHANGE = "NAME_CHANGE"  # İsim değişikliği


@dataclass
class CorporateAction:
    """Şirket olayı."""

    action_id: str
    ticker: str
    action_type: ActionType
    ex_date: date  # Eski tarih (fiyat düzeltmesi bu tarihte yapılır)
    record_date: date | None = None  # Kayıt tarihi
    payment_date: date | None = None  # Ödeme tarihi

    # Temettü
    dividend_per_share: float = 0.0
    dividend_currency: str = "TRY"

    # Bölünme / Bedelsiz
    split_ratio: float = 1.0  # ör: 2.0 = 1'e 2 bölünme, 10.0 = 1'e 10
    bonus_ratio: float = 0.0  # ör: 0.5 = her 1 hisseye 0.5 bedelsiz

    # Bedelli
    rights_ratio: float = 0.0  # ör: 0.2 = her 5 hisseye 1 yeni
    rights_price: float = 0.0  # Bedelli fiyat

    # Meta
    description: str = ""
    source: str = "KAP"
    is_confirmed: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class CorporateActionsHandler:
    """Şirket olaylarını yönetir ve fiyat/portföy düzeltmeleri yapar."""

    def __init__(self):
        self._actions: dict[str, list[CorporateAction]] = {}  # ticker -> actions
        self._applied: set = set()  # action_id'leri

    def add_action(self, action: CorporateAction):
        """Şirket olayı ekle."""
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
        self, ticker: str, start_date: date | None = None, end_date: date | None = None
    ) -> list[CorporateAction]:
        """Şirket olaylarını getir."""
        actions = self._actions.get(ticker, [])

        if start_date:
            actions = [a for a in actions if a.ex_date >= start_date]
        if end_date:
            actions = [a for a in actions if a.ex_date <= end_date]

        return actions

    def adjust_price(self, ticker: str, price: float, price_date: date) -> float:
        """Geçmiş fiyatı şirket olaylarına göre düzelt.

        Kritik: Bu fonksiyon backtest'te kullanılır.
        Fiyat, o tarihteki bilinen olaylara göre düzeltilir.

        Args:
            ticker: Hisse kodu
            price: Düzeltilmemiş fiyat
            price_date: Fiyat tarihi

        Returns:
            Düzeltilmiş fiyat
        """
        adjusted = price
        actions = self._actions.get(ticker, [])

        for action in actions:
            # Sadece price_date'ten ÖNCEKİ olayları düzelt
            # (price_date = ex_date ise o günkü fiyat henüz düzeltilmemiş)
            if action.ex_date >= price_date:
                continue

            if action.action_type == ActionType.DIVIDEND:
                # Temettü: fiyat temettü miktarı kadar düşürülür
                if action.dividend_per_share > 0:
                    adjusted = adjusted - action.dividend_per_share

            elif action.action_type == ActionType.STOCK_SPLIT:
                # Bölünme: fiyat bölünme oranına göre düşürülür, lot sayısı artar
                if action.split_ratio > 1:
                    adjusted = adjusted / action.split_ratio

            elif action.action_type == ActionType.BONUS_SHARE:
                # Bedelsiz: fiyat düzeltilir
                if action.bonus_ratio > 0:
                    # Yeni fiyat = eski fiyat / (1 + bonus_ratio)
                    adjusted = adjusted / (1 + action.bonus_ratio)

            elif action.action_type == ActionType.RIGHTS_ISSUE:
                # Bedelli: ağırlıklı ortalama fiyat hesaplanır
                if action.rights_ratio > 0 and action.rights_price > 0:
                    # Teorik fiyat = (eski fiyat + yeni fiyat × ratio) / (1 + ratio)
                    # Ama bu fiyat düzeltmesi için basitleştirilmiş hali
                    adjusted = (adjusted + action.rights_price * action.rights_ratio) / (1 + action.rights_ratio)

        return round(adjusted, 4)

    def adjust_position(self, ticker: str, quantity: int, action: CorporateAction) -> int:
        """Pozisyon miktarını şirket olayına göre düzelt.

        Args:
            ticker: Hisse kodu
            quantity: Mevcut lot sayısı
            action: Şirket olayı

        Returns:
            Düzeltilmiş lot sayısı
        """
        if action.action_type == ActionType.STOCK_SPLIT:
            if action.split_ratio > 1:
                return int(quantity * action.split_ratio)

        elif action.action_type == ActionType.BONUS_SHARE:
            if action.bonus_ratio > 0:
                return int(quantity * (1 + action.bonus_ratio))

        elif action.action_type == ActionType.RIGHTS_ISSUE and action.rights_ratio > 0:
            # Her N hisseye 1 yeni hisse
            new_shares = int(quantity * action.rights_ratio)
            return quantity + new_shares

        return quantity

    def compute_dividend_income(self, ticker: str, quantity: int, action: CorporateAction) -> float:
        """Temettü gelirini hesapla.

        Returns:
            Toplam temettü geliri (brüt)
        """
        if action.action_type != ActionType.DIVIDEND:
            return 0.0

        return quantity * action.dividend_per_share

    def adjust_historical_prices(
        self,
        ticker: str,
        prices: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Geçmiş fiyat serisini şirket olaylarına göre düzelt.

        Backtest'te kullanılır: bugünün bilinen olaylarıyla geçmişi düzelt.

        Args:
            ticker: Hisse kodu
            prices: [{"date": date, "open": float, "high": float, "low": float, "close": float, "volume": int}, ...]

        Returns:
            Düzeltilmiş fiyat serisi
        """
        actions = self._actions.get(ticker, [])
        if not actions:
            return prices

        adjusted = []
        for bar in prices:
            bar_date = bar["date"] if isinstance(bar["date"], date) else date.fromisoformat(str(bar["date"]))

            adj_bar = dict(bar)
            for action in actions:
                if action.ex_date > bar_date:
                    # Bu tarihten sonraki olayları düzelt
                    adj_bar["open"] = self._adjust_single_price(bar["open"], action)
                    adj_bar["high"] = self._adjust_single_price(bar["high"], action)
                    adj_bar["low"] = self._adjust_single_price(bar["low"], action)
                    adj_bar["close"] = self._adjust_single_price(bar["close"], action)

                    # Hacim de düzeltilir (bölünme/bedelsiz durumunda)
                    if action.action_type == ActionType.STOCK_SPLIT and action.split_ratio > 1:
                        adj_bar["volume"] = int(bar["volume"] * action.split_ratio)
                    elif action.action_type == ActionType.BONUS_SHARE and action.bonus_ratio > 0:
                        adj_bar["volume"] = int(bar["volume"] * (1 + action.bonus_ratio))

            adjusted.append(adj_bar)

        return adjusted

    def _adjust_single_price(self, price: float, action: CorporateAction) -> float:
        """Tek bir fiyatı tek bir olaya göre düzelt."""
        if action.action_type == ActionType.DIVIDEND:
            return max(0, price - action.dividend_per_share)
        elif action.action_type == ActionType.STOCK_SPLIT and action.split_ratio > 1:
            return price / action.split_ratio
        elif action.action_type == ActionType.BONUS_SHARE and action.bonus_ratio > 0:
            return price / (1 + action.bonus_ratio)
        elif action.action_type == ActionType.RIGHTS_ISSUE and action.rights_ratio > 0:
            return (price + action.rights_price * action.rights_ratio) / (1 + action.rights_ratio)
        return price

    def load_from_kap(self, kap_events: list[dict[str, Any]]):
        """KAP'tan gelen şirket olaylarını yükle."""
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

                # Temettü miktarını çıkar
                if action_type == ActionType.DIVIDEND:
                    action.dividend_per_share = self._extract_dividend_amount(event)

                # Bölünme oranını çıkar
                if action_type in (ActionType.STOCK_SPLIT, ActionType.BONUS_SHARE):
                    action.split_ratio = self._extract_split_ratio(event)

                if action.ticker:
                    self.add_action(action)
            except Exception as e:
                logger.warning("Failed to process KAP event", error=str(e))
                continue

    def _classify_kap_event(self, event: dict) -> ActionType | None:
        """KAP olayını sınıflandır."""
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

    def _extract_dividend_amount(self, event: dict) -> float:
        """Temettü miktarını KAP açıklamasından çıkar."""
        import re

        text = event.get("title", "") + " " + event.get("summary", "")

        # "hisseye 5,25 TL" veya "5.25 TL/hisse" gibi pattern'ler
        patterns = [
            r"hisseye\s+(\d+[.,]\d+)\s*(?:TL|₺)",
            r"(\d+[.,]\d+)\s*(?:TL|₺)\s*/?\s*hisse",
            r"kar\s+payı\s+(\d+[.,]\d+)",
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                amount_str = match.group(1).replace(",", ".")
                try:
                    return float(amount_str)
                except ValueError:
                    continue

        return 0.0

    def _extract_split_ratio(self, event: dict) -> float:
        """Bölünme oranını KAP açıklamasından çıkar."""
        import re

        text = event.get("title", "") + " " + event.get("summary", "")

        # "1'e 10" veya "10:1" gibi pattern'ler
        patterns = [
            r"1[''e]\s*(\d+)",
            r"(\d+)\s*:\s*1",
            r"(\d+)\s*kata\s*çıkar",
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    return float(match.group(1))
                except ValueError:
                    continue

        return 1.0

    def _parse_date(self, date_str: str) -> date:
        """Tarih string'ini date objesine çevir."""
        if not date_str:
            return date.today()

        for fmt in ["%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y", "%Y-%m-%dT%H:%M:%S"]:
            try:
                return datetime.strptime(date_str[:10], fmt[: len(date_str[:10])]).date()
            except ValueError:
                continue

        return date.today()


# Singleton
corporate_actions = CorporateActionsHandler()
