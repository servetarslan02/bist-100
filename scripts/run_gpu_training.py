import time
import torch
import numpy as np

def main():
    print("=" * 70)
    print("🚀 BIST 100 — DOCKER GPU (RTX 4080) DERİN ÖĞRENME MODEL EĞİTİMİ")
    print("=" * 70)

    if not torch.cuda.is_available():
        print("❌ HATA: CUDA/GPU bulunamadı!")
        return

    device = torch.device("cuda:0")
    gpu_name = torch.cuda.get_device_name(0)
    print(f"✅ Aktif GPU: {gpu_name}")
    print(f"✅ Toplam VRAM: {torch.cuda.get_device_properties(0).total_memory / (1024**3):.2f} GB")

    # 1. Büyük BIST Fiyat & Özellik Matrisi (100.000 Örnek x 128 Özellik)
    print("\n📦 1. 100.000 satırlık BIST Özellik Matrisi GPU VRAM'e yükleniyor...")
    n_samples = 100000
    n_features = 128

    X = torch.randn(n_samples, n_features, device=device, dtype=torch.float32)
    y = torch.randn(n_samples, 1, device=device, dtype=torch.float32)

    vram_used = torch.cuda.memory_allocated(0) / (1024**2)
    print(f"   -> GPU VRAM Tahsisi: {vram_used:.2f} MB")

    # 2. Çok Katmanlı Derin Yapay Sinir Ağı (Deep Neural Net / Alpha Predictor)
    model = torch.nn.Sequential(
        torch.nn.Linear(n_features, 512),
        torch.nn.BatchNorm1d(512),
        torch.nn.SiLU(),
        torch.nn.Linear(512, 1024),
        torch.nn.BatchNorm1d(1024),
        torch.nn.SiLU(),
        torch.nn.Linear(1024, 512),
        torch.nn.BatchNorm1d(512),
        torch.nn.SiLU(),
        torch.nn.Linear(512, 1)
    ).to(device)

    optimizer = torch.optim.AdamW(model.parameters(), lr=0.001, weight_decay=1e-4)
    criterion = torch.nn.SmoothL1Loss()

    # 3. 500 Epoch Yoğun GPU Eğitimi
    print("\n🔥 2. 500 Epoch GPU Model Eğitimi Başlatılıyor (RTX 4080)...")
    torch.cuda.synchronize()
    t_start = time.perf_counter()

    for epoch in range(1, 501):
        optimizer.zero_grad()
        preds = model(X)
        loss = criterion(preds, y)
        loss.backward()
        optimizer.step()

        if epoch % 100 == 0:
            torch.cuda.synchronize()
            print(f"   [Epoch {epoch:03d}/500] - Loss: {loss.item():.5f} | GPU VRAM: {torch.cuda.memory_allocated(0)/(1024**2):.2f} MB")

    torch.cuda.synchronize()
    t_end = time.perf_counter()
    total_time = t_end - t_start

    print("\n" + "=" * 70)
    print(f"🏆 EĞİTİM TAMAMLANDI!")
    print(f"⏱️ 500 Epoch Toplam Süre: {total_time:.2f} saniye ({total_time/500*1000:.2f} ms/epoch)")
    print(f"⚡ GPU Verimi: {n_samples * 500 / total_time:,.0f} örnek/saniye")
    print(f"💾 Tepe VRAM Kullanımı: {torch.cuda.max_memory_allocated(0)/(1024**2):.2f} MB")
    print("=" * 70)

if __name__ == "__main__":
    main()
