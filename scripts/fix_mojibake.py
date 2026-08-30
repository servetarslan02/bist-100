"""Fix mojibake encoding in services/core files."""

files = [
    "services/core/audit_log.py",
    "services/core/auto_circuit_breaker.py",
    "services/core/data_quality.py",
    "services/core/decision_engine.py",
    "services/core/jwt_manager.py",
    "services/core/monitoring.py",
    "services/core/risk_gate.py",
    "services/core/state_store.py",
    "services/core/transaction_helper.py",
    "services/core/worker.py",
]

charmap = {
    "Ã§": "ç",
    "Ã‡": "Ç",
    "Ã¼": "ü",
    "Ãœ": "Ü",
    "Ã¶": "ö",
    "Ã–": "Ö",
    "Ä±": "ı",
    "Ä°": "İ",
    "ÅŸ": "ş",
    "Åž": "Ş",
    "ÄŸ": "ğ",
    "Äž": "Ğ",
    "â€”": "—",
    "â†’": "→",
    "â€¢": "•",
    "â€¦": "...",
    "Ã©": "é",
    "Ã ": "à",
    "â€œ": '"',
    "â€ ": '"',
    "â€˜": "'",
    "â€™": "'",
}

total_replaces = 0
for path in files:
    with open(path, encoding="utf-8") as f:
        content = f.read()

    file_count = 0
    for k, v in charmap.items():
        if k in content:
            c = content.count(k)
            file_count += c
            content = content.replace(k, v)

    total_replaces += file_count
    print(f"{path}: {file_count} replacements")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

print(f"Total {total_replaces} mojibake characters repaired across {len(files)} files!")
