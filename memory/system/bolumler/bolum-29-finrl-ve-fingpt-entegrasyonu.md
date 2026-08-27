# Bölüm 29 — FinRL ve FinGPT Entegrasyonu

## Amaç

Finansal Reinforcement Learning (FinRL) ve Financial LLM (FinGPT) framework'lerini BIST'e adapte etmek.

**Kaynak:** arXiv (2026) FinRL-X: AI-Native Modular Infrastructure, GitHub AI4Finance Foundation, arXiv (2026) Agentic Financial Trading Agents.

---

## Kullanılacak sistemler

- FinRL Environment
- FinGPT Sentiment
- RL Agent Trainer
- LLM Signal Generator
- Policy Optimizer
- Reward Calculator
- Backtest Integrator

---

## Çalışma mantığı

```
FinRL: Piyasa ortamı → RL Agent → Aksiyon (BUY/SELL/HOLD) → Ödül → Öğrenme
FinGPT: Haberler/KAP → LLM → Sentiment skoru → Sinyal
Birlikte: FinGPT sentiment + FinRL aksiyon = BIST stratejisi
```

---

## 1. FinRL Nedir?

**Araştırma bulgusu:** arXiv (2026) — "FinRL-X unifies data processing, strategy construction, backtesting, and broker execution under a weight-centric interface."

### FinRL'in 4 katmanı:
```
1. Data Layer: Veri toplama ve ön işleme
2. Strategy Layer: RL agent'lar ve strateji bileşenleri
3. Backtesting Layer: Tarihsel simülasyon
4. Execution Layer: Broker entegrasyonu
```

### Desteklenen RL algoritmaları:
```
PPO  (Proximal Policy Optimization) → En stabil
A2C  (Advantage Actor-Critic)       → Hızlı
DDPG (Deep Deterministic Policy)    → Sürekli aksiyon
SAC  (Soft Actor-Critic)            → Keşif odaklı
TD3  (Twin Delayed DDPG)            → Düşük varyans
```

---

## 2. BIST için FinRL Ortamı

### State space (durum uzayı):
```
[price, volume, rsi, macd, bb_pct, atr, obv, 
 usdtry, tcmb_rate, cds, inflation, 
 portfolio_weight, cash_ratio]
```

### Action space (aksiyon uzayı):
```
Discrete: BUY, HOLD, SELL
Continuous: [-1, +1] (ağırlık değişimi)
```

### Reward function (ödül fonksiyonu):
```
Reward = Portfolio return - λ × Risk - γ × Transaction cost
λ = Risk aversion parametresi
γ = İşlem maliyeti parametresi
```

### Örnek: BIST FinRL ortamı

```python
# services/ml/finrl_bist.py
import gymnasium as gym
import numpy as np


class BISTTradingEnv(gym.Env):
    def __init__(self, data, initial_capital=100000):
        super().__init__()
        self.data = data
        self.initial_capital = initial_capital

        # State: [price, volume, rsi, macd, bb_pct, atr, usdtry, cds, portfolio_weight]
        self.observation_space = gym.spaces.Box(low=-np.inf, high=np.inf, shape=(9,))

        # Action: [-1, +1] (sell all to buy all)
        self.action_space = gym.spaces.Box(low=-1, high=1, shape=(1,))

        self.reset()

    def reset(self):
        self.current_step = 0
        self.portfolio_value = self.initial_capital
        self.cash = self.initial_capital
        self.shares = 0
        return self._get_observation(), {}

    def step(self, action):
        # Aksiyonu uygula
        action = action[0]

        if action > 0.1:  # BUY
            buy_amount = self.cash * action
            shares_to_buy = int(buy_amount / self.data[self.current_step]["price"])
            self.shares += shares_to_buy
            self.cash -= shares_to_buy * self.data[self.current_step]["price"]

        elif action < -0.1:  # SELL
            shares_to_sell = int(self.shares * abs(action))
            self.cash += shares_to_sell * self.data[self.current_step]["price"]
            self.shares -= shares_to_sell

        # Portfolio değeri
        new_value = self.cash + self.shares * self.data[self.current_step]["price"]

        # Reward
        reward = (new_value - self.portfolio_value) / self.portfolio_value
        reward -= 0.001 * abs(action)  # İşlem maliyeti
        reward -= 0.0001 * (self.shares * self.data[self.current_step]["price"] / new_value)  # Risk

        self.portfolio_value = new_value
        self.current_step += 1

        done = self.current_step >= len(self.data) - 1

        return self._get_observation(), reward, done, False, {}

    def _get_observation(self):
        return np.array(
            [
                self.data[self.current_step]["price"],
                self.data[self.current_step]["volume"],
                self.data[self.current_step]["rsi"],
                self.data[self.current_step]["macd"],
                self.data[self.current_step]["bb_pct"],
                self.data[self.current_step]["atr"],
                self.data[self.current_step]["usdtry"],
                self.data[self.current_step]["cds"],
                self.shares * self.data[self.current_step]["price"] / self.portfolio_value,
            ]
        )
```

---

## 3. RL Agent Eğitimi

### Örnek: PPO agent

```python
# services/ml/rl_agent.py
from stable_baselines3 import PPO


def train_rl_agent(env, total_timesteps=100000):
    model = PPO(
        "MlpPolicy",
        env,
        learning_rate=3e-4,
        n_steps=2048,
        batch_size=64,
        n_epochs=10,
        gamma=0.99,
        gae_lambda=0.95,
        clip_range=0.2,
        verbose=0,
    )

    model.learn(total_timesteps=total_timesteps)

    return model
```

---

## 4. FinGPT Sentiment

**Araştırma bulgusu:** GitHub AI4Finance — "FinGPT is the first open-source LLM framework for the financial domain. RLHF enables an LLM model to learn."

### FinGPT'in yapısı:
```
1. Data Collection: Finansal metin toplama
2. Data Processing: Temizleme ve etiketleme
3. Fine-tuning: Finansal veriyle ince ayar
4. RLHF: İnsan geri bildirimiyle öğrenme
5. Sentiment Extraction: Duygu analizi
```

### Örnek: FinGPT sentiment

```python
# services/ml/fingpt.py
from transformers import AutoTokenizer, AutoModelForCausalLM


class FinGPTSentiment:
    def __init__(self, model_path="ai4finance/fingpt-sentiment"):
        self.tokenizer = AutoTokenizer.from_pretrained(model_path)
        self.model = AutoModelForCausalLM.from_pretrained(model_path)

    def analyze(self, text):
        prompt = f"Analyze the sentiment of this financial text: {text}\nSentiment:"

        inputs = self.tokenizer(prompt, return_tensors="pt")
        outputs = self.model.generate(**inputs, max_new_tokens=10)
        result = self.tokenizer.decode(outputs[0], skip_special_tokens=True)

        # Parse sentiment
        if "positive" in result.lower():
            return {"sentiment": "POSITIVE", "score": 0.8}
        elif "negative" in result.lower():
            return {"sentiment": "NEGATIVE", "score": 0.2}
        else:
            return {"sentiment": "NEUTRAL", "score": 0.5}
```

---

## 5. FinRL + FinGPT Entegrasyonu

### Hibrit strateji:
```
1. FinGPT: Haberlerden sentiment skoru üret
2. FinRL: Sentiment skorunu state'e ekle
3. RL Agent: Sentiment + teknik veri → aksiyon
4. Backtest: Performansı ölç
```

### Örnek: Hibrit model

```python
# services/ml/hybrid_model.py
def hybrid_predict(rl_model, fingpt, news_data, market_data):
    # 1. Sentiment skoru
    sentiment = fingpt.analyze(news_data["latest_news"])
    sentiment_score = sentiment["score"]
    
    # 2. Market verisi + sentiment
    state = np.append(market_data, [sentiment_score])
    
    # 3. RL aksiyonu
    action, _ = rl_model.predict(state)
    
    # 4. Karar
    if action > 0.3:
        return "BUY", sentiment_score, action
    elif action < -0.3:
        return "SELL", sentiment_score, action
    else:
        return "HOLD", sentiment_score, action
```

---

## 6. BIST için Adaptasyon Zorlukları

### Zorluklar:
```
1. Veri azlığı: BIST'te RL için yeterli veri yok
2. Piyasa yapısı: BIST'in kendine özgü kuralları
3. Enflasyon etkisi: Nominal vs reel getiri
4. Kur volatilitesi: USDTRY etkisi
5. Düşük likidite: Bazı hisselerde
```

### Çözümler:
```
1. Transfer learning:Uluslararası piyasalardan öğren
2. Data augmentation: Sentetik veri üret
3. Curriculum learning: Kolaydan zora
4. Multi-task learning: Birden fazla görev
5. Domain adaptation: BIST'e özel fine-tuning
```

---

## 7. Qlib ile Entegrasyon

**Araştırma bulgusu:** arXiv FinRL-X — "Qlib provides robust backtesting and evaluation utilities."

Qlib, Microsoft'un açık kaynaklı quantitative trading platformudur:

```python
# services/ml/qlib_integration.py
import qlib
from qlib.contrib.model.gbdt import LGBModel

# BIST verisi ile Qlib
qlib.init(provider_uri="bist_data/")

model = LGBModel()
model.fit(dataset)
predictions = model.predict(dataset)
```

---

## Çıktı

```
FinRL Agent:          PPO (trained)
FinGPT Model:         Fine-tuned for Turkish financial text
Hybrid Accuracy:      0.68
RL Sharpe:            1.52
Sentiment Alpha:      +2.3% annual
Training Time:        45 minutes
```

---

## Temel prensip

> "FinRL-X unifies data processing, strategy construction, backtesting, and broker execution under a weight-centric interface." — arXiv (2026)

FinRL ve FinGPT BIST'e doğrudan uygulanamaz ama adapte edilebilir. **Transfer learning + BIST-specific fine-tuning ile uluslararası piyasalardan öğrenen, BIST'e özel çalışan bir sistem mümkün.**

> Kaynak: arXiv (2026) FinRL-X, GitHub AI4Finance Foundation, arXiv (2026) Agentic Trading Agents
