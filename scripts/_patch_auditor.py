"""Patch script: deep_system_integrity_auditor.py'ye B29-B36 boyutlarini ekler."""
import sys

SRC = "scripts/deep_system_integrity_auditor.py"
p = open(SRC, "rb").read()
t = p.decode("utf-8", "replace")
lines = t.splitlines(keepends=True)

# 1. B29-B36 cagrilarini B28'den sonra ekle (1-indexed -> 0-indexed: 1032-1 = 1031)
INSERT_AFTER = 1032  # 1-indexed satirdan sonra ekle
new_calls = (
    "\n"
    "    print('  [B29] Docker Compose derin validasyon...')\n"
    "    all_findings.extend(b29_docker_compose_deep())\n"
    "\n"
    "    print('  [B30] pyproject.toml bagimlilik uyumu...')\n"
    "    all_findings.extend(b30_dependency_check(all_imports_map))\n"
    "\n"
    "    print('  [B31] ML model dosya varlik kontrolu...')\n"
    "    all_findings.extend(b31_ml_model_files(all_files_content))\n"
    "\n"
    "    print('  [B32] NATS/Redis mesaj semasi tutarliligi...')\n"
    "    all_findings.extend(b32_messaging_schema(all_files_content))\n"
    "\n"
    "    print('  [B33] Coklu adim dongüsel bagimlilik...')\n"
    "    all_findings.extend(b33_multi_hop_cycles(all_imports_map))\n"
    "\n"
    "    print('  [B34] Config-Docker cross-reference...')\n"
    "    all_findings.extend(b34_config_docker_crossref())\n"
    "\n"
    "    print('  [B35] Veritabani sema-SQL tutarliligi...')\n"
    "    all_findings.extend(b35_db_schema_consistency())\n"
    "\n"
    "    print('  [B36] Async guvenlik ve yaris kosulu analizi...')\n"
    "    all_findings.extend(b36_async_safety(all_files_content))\n"
    "\n"
)
lines.insert(INSERT_AFTER, new_calls)

result = "".join(lines)

# 2. DIM_NAMES guncelle
OLD_DIM = "        27:\"Coklu Tanim Cakismasi\", 28:\"Supheli Dosya Tespiti\","
NEW_DIM = (
    "        27:\"Coklu Tanim Cakismasi\", 28:\"Supheli Dosya Tespiti\",\n"
    "        29:\"Docker Compose Derin Validasyon\", 30:\"pyproject Bagimlilik Uyumu\",\n"
    "        31:\"ML Model Dosya Varligi\", 32:\"NATS-Redis Mesaj Semasi\",\n"
    "        33:\"Coklu Adim Dongüsel Bagimlilik\", 34:\"Config-Docker Cross-Ref\",\n"
    "        35:\"Veritabani Sema-SQL Tutarliligi\", 36:\"Async Guvenlik Yaris Kosulu\","
)
result = result.replace(OLD_DIM, NEW_DIM, 1)

# 3. Versiyon guncelle
result = result.replace(
    "Deep System Integrity Auditor v3.0 (28 Boyut)",
    "Deep System Integrity Auditor v4.0 (36 Boyut)"
)
result = result.replace(
    "28 Boyut | 0 Token | Kod + Motor + Sinyal Zinciri + Veri Akisi",
    "36 Boyut | 0 Token | Kod + Motor + Sinyal Zinciri + Veri Akisi + Altyapi"
)

with open(SRC, "wb") as f:
    f.write(result.encode("utf-8"))

print(f"Patch tamamlandi. Toplam satir: {len(result.splitlines())}")
print(f"B29 eklendi: {'b29_docker_compose_deep' in result}")
print(f"B36 eklendi: {'b36_async_safety' in result}")
