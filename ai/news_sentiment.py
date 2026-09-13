"""
ALPHA BIST — News Sentiment Analyzer

KAP haber akışı için duygu analizi.
Türkçe finansal kelime dağarcığı.
"""

import re
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class NewsSentimentAnalyzer:
    """Kurumsal Türkçe Finansal ve KAP Bildirimi Duygu Analiz Motoru.

    Özellikler:
    - Kapsamlı BIST finansal sözlüğü (bilanço, temettü, kurumsal eylemler, regülasyon)
    - Olumsuzluk eki ve kelimesi analizi (negation handling: 'artmadı', 'kâr açıklayamadı', 'zarar yok')
    - Şiddet belirteçleri (intensifiers: 'rekor', 'fahiş', 'tarihi zirve', 'hafif')
    - KAP regülasyon ve piyasa tedbirleri etiketlemesi (VBTS, brüt takas, temerrüt, konkordato, pay geri alım)
    - Ağırlıklı polarite ve güven skoru hesabı (-1.0 ile +1.0)
    """

    # Pozitif finansal terimler ve ağırlıkları (1.0 - 3.0)
    POSITIVE_LEXICON: dict[str, float] = {
        # Bilanço ve Büyüme
        "artış": 1.0,
        "yükseliş": 1.0,
        "kâr": 1.5,
        "kar": 1.5,
        "büyüme": 1.2,
        "rekor": 2.5,
        "zirve": 2.0,
        "güçlü": 1.2,
        "olumlu": 1.0,
        "başarı": 1.2,
        "iyileşme": 1.2,
        "toparlanma": 1.2,
        "yükseldi": 1.0,
        "arttı": 1.0,
        "kazandı": 1.0,
        "değerlendi": 1.0,
        "pozitif": 1.0,
        "katlandı": 2.0,
        "patlama": 1.8,
        "gelir": 0.8,
        "hasılat": 0.8,
        "favök": 1.0,
        "ebitda": 1.0,
        "marj": 0.8,
        "genişleme": 1.0,
        "canlanma": 1.0,
        "ivme": 1.0,
        "karlılık": 1.2,
        "kârlılık": 1.2,
        # Kurumsal ve Sermaye Eylemleri
        "temettü": 1.8,
        "bedelsiz": 1.5,
        "geri_alım": 2.0,
        "ihale": 1.5,
        "sipariş": 1.5,
        "anlaşma": 1.2,
        "sözleşme": 1.2,
        "ortaklık": 1.2,
        "ihracat": 1.2,
        "yatırım": 1.5,
        "kapasite": 1.0,
        "lisans": 1.0,
        "onay": 1.2,
        "not_artışı": 2.5,
        "not_artırımı": 2.5,
        "görünüm_pozitif": 1.8,
        "tavsiye_al": 2.0,
        "hedef_fiyat_artışı": 1.8,
    }

    # Negatif finansal terimler ve ağırlıkları (-1.0 ile -3.0)
    NEGATIVE_LEXICON: dict[str, float] = {
        # Bilanço ve Küçülme
        "düşüş": -1.0,
        "kayıp": -1.2,
        "zarar": -1.8,
        "gerileme": -1.0,
        "çöküş": -2.5,
        "dip": -1.5,
        "kriz": -2.0,
        "zayıf": -1.0,
        "olumsuz": -1.0,
        "başarısızlık": -1.5,
        "kötüleşme": -1.5,
        "düşürdü": -1.0,
        "azaldı": -1.0,
        "kaybetti": -1.0,
        "negatif": -1.0,
        "daralma": -1.2,
        "fren": -1.0,
        "baskı": -1.0,
        "bozulma": -1.5,
        "erime": -1.5,
        "küçülme": -1.2,
        "tasfiye": -2.5,
        # Kredi, Risk ve Hukuki Tehditler
        "risk": -0.8,
        "iflas": -3.0,
        "konkordato": -3.0,
        "temerrüt": -3.0,
        "borç": -0.8,
        "borçlanma": -0.5,
        "dava": -1.2,
        "ceza": -2.0,
        "soruşturma": -1.8,
        "haciz": -2.5,
        "tedbir": -1.5,
        "brüt_takas": -1.8,
        "kredili_yasak": -1.5,
        "askıya_alma": -2.5,
        "faaliyet_durdurma": -3.0,
        "not_indirimi": -2.5,
        "not_düşüşü": -2.5,
        "görünüm_negatif": -1.8,
        "tavsiye_sat": -2.0,
        "hedef_fiyat_indirimi": -1.8,
        "iptal": -1.5,
        "fesih": -2.0,
    }

    # Şiddet artıran zarflar / çarpanlar
    INTENSIFIERS: dict[str, float] = {
        "çok": 1.5,
        "fazla": 1.3,
        "aşırı": 1.7,
        "rekor": 2.0,
        "tarihi": 1.8,
        "fahiş": 2.0,
        "şiddetli": 1.7,
        "belirgin": 1.4,
        "ciddi": 1.5,
        "büyük": 1.3,
        "dev": 1.5,
        "muazzam": 1.8,
        "keskin": 1.6,
        "hızlı": 1.3,
        "kuvvetli": 1.4,
        "hafif": 0.5,
        "sınırlı": 0.5,
        "kısmi": 0.6,
    }

    # Cümle içi olumsuzluk yaratan yapılar (negation indicators)
    NEGATION_WORDS: set[str] = {
        "değil",
        "yok",
        "olmadı",
        "etmedi",
        "ulaşamadı",
        "sağlanamadı",
        "gerçekleşmedi",
        "beklenmiyor",
        "reddedildi",
        "yapılmayacak",
        "açıklanmadı",
    }

    def __init__(self) -> None:
        """Duygu analiz motorunu hazırlar."""
        self._compiled_pos = {k: v for k, v in self.POSITIVE_LEXICON.items()}
        self._compiled_neg = {k: v for k, v in self.NEGATIVE_LEXICON.items()}

    def __repr__(self) -> str:
        """Sınıfın temsil dizesi."""
        return f"NewsSentimentAnalyzer(lexicon_terms={len(self.POSITIVE_LEXICON) + len(self.NEGATIVE_LEXICON)})"

    def analyze(self, text: str, ticker: str | None = None) -> dict[str, Any]:
        """Haber veya KAP metnini dilbilgisel ve finansal polarite kurallarıyla analiz eder.

        Args:
            text: İncelenecek metin gövdesi veya başlık.
            ticker: İlgili hisse senedi sembolü (opsiyonel).

        Returns:
            dict[str, Any]: Duygu sınıfı, sürekli polarite skoru, güven derecesi ve tespit edilen terimler.
        """
        if not text or not text.strip():
            return {
                "sentiment": "NEUTRAL",
                "score": 0.0,
                "confidence": 0.0,
                "positive_words": [],
                "negative_words": [],
                "kap_flags": [],
            }

        text_clean = text.lower().replace("\n", " ")
        # Bileşik terimleri koru ('brüt takas' -> 'brüt_takas', 'pay geri alımı' -> 'geri_alım')
        text_clean = re.sub(r"brüt\s+takas", "brüt_takas", text_clean)
        text_clean = re.sub(r"pay\s+geri\s+al[ıi]m[ıi]?", "geri_alım", text_clean)
        text_clean = re.sub(r"hedef\s+fiyat\s+art[ıi][şs][ıi]?", "hedef_fiyat_artışı", text_clean)
        text_clean = re.sub(r"hedef\s+fiyat\s+d[üu][şs][üu][şs][üu]?", "hedef_fiyat_indirimi", text_clean)
        text_clean = re.sub(r"kredi[li]?\s+[ıi][şs]lem\s+yasa[gğ][ıi]?", "kredili_yasak", text_clean)
        text_clean = re.sub(r"kredi\s+notu\s+art[ıi][şs][ıi]?", "not_artışı", text_clean)
        text_clean = re.sub(r"kredi\s+notu\s+d[üu][şs][üu][şs][üu]?", "not_indirimi", text_clean)

        words = re.findall(r"[\w_]+", text_clean)
        pos_detected: list[str] = []
        neg_detected: list[str] = []
        kap_flags: list[str] = []

        total_weight: float = 0.0
        word_count = len(words)

        for i, word in enumerate(words):
            # Şiddet katsayısı kontrolü (önceki 2 kelimeye bak)
            intensity_multiplier = 1.0
            for offset in (1, 2):
                if i - offset >= 0:
                    prev_w = words[i - offset]
                    if prev_w in self.INTENSIFIERS:
                        intensity_multiplier = self.INTENSIFIERS[prev_w]
                        break

            # Olumsuzluk kontrolü (sonraki 2 veya önceki 2 kelimede negation var mı veya kelime -medi/-madı ile mi bitiyor?)
            is_negated = False
            for offset in (-2, -1, 1, 2):
                idx = i + offset
                if 0 <= idx < word_count:
                    if words[idx] in self.NEGATION_WORDS:
                        is_negated = True
                        break

            if word.endswith(("medi", "madı", "mediği", "madığı", "mıyor", "miyor")):
                is_negated = True

            # Pozitif terim eşlemesi
            if word in self.POSITIVE_LEXICON:
                w_weight = self.POSITIVE_LEXICON[word] * intensity_multiplier
                if is_negated:
                    # Pozitif tersine dönerse negatif baskı yaratır ('artmadı', 'büyümedi')
                    total_weight -= w_weight * 0.8
                    neg_detected.append(f"{word}(olumsuzlanmış)")
                else:
                    total_weight += w_weight
                    pos_detected.append(word)

            # Negatif terim eşlemesi
            elif word in self.NEGATIVE_LEXICON:
                w_weight = abs(self.NEGATIVE_LEXICON[word]) * intensity_multiplier
                if is_negated:
                    # Negatif tersine dönerse hafif pozitif rahatlama ('zarar yok', 'kriz aşılmadı' hariç)
                    total_weight += w_weight * 0.5
                    pos_detected.append(f"{word}(yok)")
                else:
                    total_weight -= w_weight
                    neg_detected.append(word)

            # KAP Spesifik Regülasyon ve Eylem Bayrakları
            if word in {
                "brüt_takas",
                "kredili_yasak",
                "tedbir",
                "konkordato",
                "iflas",
                "temerrüt",
                "geri_alım",
                "temettü",
                "bedelsiz",
            }:
                kap_flags.append(word.upper())

        # Polarite skoru hesaplama (Sigmoid/Hiperbolik benzeri normalize sıkıştırma)
        hit_count = len(pos_detected) + len(neg_detected)
        if hit_count == 0:
            score = 0.0
            sentiment = "NEUTRAL"
            confidence = 0.0
        else:
            # -1.0 ile +1.0 arasında dengelenmiş skor
            raw_score = total_weight / (hit_count + 1.0)
            score = max(-1.0, min(1.0, raw_score))

            if score >= 0.20:
                sentiment = "POSITIVE"
            elif score <= -0.20:
                sentiment = "NEGATIVE"
            else:
                sentiment = "NEUTRAL"

            # Güven skoru: hit sayısı ve metin uzunluğuna göre
            confidence = min(1.0, (hit_count * 0.25) + (min(word_count, 100) / 200.0))

        result: dict[str, Any] = {
            "sentiment": sentiment,
            "score": round(score, 4),
            "confidence": round(confidence, 3),
            "hit_count": hit_count,
            "positive_words": pos_detected,
            "negative_words": neg_detected,
            "kap_flags": list(set(kap_flags)),
        }
        if ticker:
            result["ticker"] = ticker.upper()

        return result

    def analyze_batch(self, texts: list[dict[str, str]]) -> list[dict[str, Any]]:
        """Çoklu haber metinlerini toplu olarak duygu analizinden geçirir."""
        return [self.analyze(item.get("text", ""), item.get("ticker")) for item in texts]

    def get_market_sentiment(self, analyses: list[dict[str, Any]]) -> dict[str, Any]:
        """Tüm haber analizlerinin güven ağırlıklı ortalamasını alarak genel piyasa duygu skorunu hesaplar."""
        if not analyses:
            return {"overall": "NEUTRAL", "score": 0.0, "confidence": 0.0, "total_analyzed": 0}

        weighted_scores: list[float] = []
        weights: list[float] = []

        for a in analyses:
            score = float(a.get("score", 0.0))
            conf = float(a.get("confidence", 0.1))
            weighted_scores.append(score * conf)
            weights.append(conf)

        sum_weights = sum(weights)
        if sum_weights > 0:
            avg_score = sum(weighted_scores) / sum_weights
        else:
            avg_score = 0.0

        if avg_score >= 0.18:
            overall = "POSITIVE"
        elif avg_score <= -0.18:
            overall = "NEGATIVE"
        else:
            overall = "NEUTRAL"

        return {
            "overall": overall,
            "average_score": round(avg_score, 4),
            "mean_confidence": round(sum_weights / len(analyses), 3) if analyses else 0.0,
            "total_analyzed": len(analyses),
        }


news_sentiment = NewsSentimentAnalyzer()

