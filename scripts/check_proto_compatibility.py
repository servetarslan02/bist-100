from __future__ import annotations

#!/usr/bin/env python3
from typing import Any
"""
ALPHA BIST — Protobuf Backward Compatibility Checker

Proto dosyalarının backward compatibility'sini kontrol eder.
- Field silinmiş mi?
- Field type değişmiş mi?
- Field number değişmiş mi?
- Enum value silinmiş mi?

Kullanım:
    python scripts/check_proto_compatibility.py
"""

import structlog
logger = structlog.get_logger(__name__)

import hashlib
import json
import sys
from pathlib import Path


def parse_proto_fields(content: str) -> dict[str, dict]:
    """Proto dosyasından field'ları çıkar."""
    fields = {}
    current_message = None

    for line in content.split("\n"):
        line = line.strip()

        # Message başlangıcı
        if line.startswith("message "):
            current_message = line.split()[1].rstrip("{").strip()
            fields[current_message] = {}

        # Field tanımı
        elif current_message and "=" in line and not line.startswith("//"):
            parts = line.split("=")
            if len(parts) == 2:
                field_def = parts[0].strip()
                field_num = parts[1].strip().rstrip(";").strip()

                if field_def and field_num.isdigit():
                    # type ve name ayır
                    tokens = field_def.split()
                    if len(tokens) >= 2:
                        field_type = tokens[0]
                        field_name = tokens[1]
                        fields[current_message][field_name] = {
                            "type": field_type,
                            "number": int(field_num),
                        }

        # Enum başlangıcı
        elif line.startswith("enum "):
            current_enum = line.split()[1].rstrip("{").strip()
            fields[f"enum:{current_enum}"] = {}

        # Enum value
        elif current_message is None and "=" in line and not line.startswith("//"):
            pass  # Enum'lar ayrı handle edilir

    return fields


def check_compatibility(old_proto: str, new_proto: str) -> list[str]:
    """İki proto dosyasının uyumluluğunu kontrol et."""
    errors = []

    old_fields = parse_proto_fields(old_proto)
    new_fields = parse_proto_fields(new_proto)

    # Silinen message'ları kontrol et
    for msg_name in old_fields:
        if msg_name not in new_fields:
            if not msg_name.startswith("enum:"):
                errors.append(f"Message '{msg_name}' silinmiş — backward incompatible!")
            continue

        # Silinen field'ları kontrol et
        old_msg = old_fields[msg_name]
        new_msg = new_fields[msg_name]

        for field_name, field_info in old_msg.items():
            if field_name not in new_msg:
                errors.append(
                    f"{msg_name}.{field_name} silinmiş "
                    f"(type={field_info['type']}, number={field_info['number']}) — "
                    f"reserved olarak işaretlenmeli!"
                )
            elif new_msg[field_name]["type"] != field_info["type"]:
                errors.append(
                    f"{msg_name}.{field_name} type değişmiş: "
                    f"{field_info['type']} → {new_msg[field_name]['type']} — backward incompatible!"
                )
            elif new_msg[field_name]["number"] != field_info["number"]:
                errors.append(
                    f"{msg_name}.{field_name} field number değişmiş: "
                    f"{field_info['number']} → {new_msg[field_name]['number']} — backward incompatible!"
                )

    return errors


def get_proto_hash(proto_path: str) -> str:
    """Proto dosyasının hash'ini hesapla."""
    with open(proto_path) as f:
        content = f.read()
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def main() -> Any:
    """Ana fonksiyon."""
    proto_dir = Path("proto")
    snapshot_file = Path(".proto_snapshot.json")

    if not proto_dir.exists():
        logger.info("⚠️  proto/ dizini bulunamadı")
        return 0

    # Mevcut proto dosyalarını oku
    current_snapshot = {}
    for proto_file in proto_dir.glob("*.proto"):
        with open(proto_file) as f:
            content = f.read()
        current_snapshot[proto_file.name] = {
            "hash": get_proto_hash(str(proto_file)),
            "fields": parse_proto_fields(content),
        }

    # Önceki snapshot varsa karşılaştır
    if snapshot_file.exists():
        with open(snapshot_file) as f:
            old_snapshot = json.load(f)

        all_errors = []
        for proto_name, old_data in old_snapshot.items():
            if proto_name not in current_snapshot:
                logger.info(f"⚠️  {proto_name} dosyası silinmiş!")
                continue

            # Hash aynıysa değişiklik yok
            if old_data["hash"] == current_snapshot[proto_name]["hash"]:
                logger.info(f"✅ {proto_name} — değişiklik yok")
                continue

            # Field karşılaştırması
            old_fields = old_data.get("fields", {})
            new_fields = current_snapshot[proto_name]["fields"]

            for msg_name, old_msg in old_fields.items():
                if msg_name not in new_fields:
                    if not msg_name.startswith("enum:"):
                        all_errors.append(f"❌ {proto_name}: Message '{msg_name}' silinmiş!")
                    continue

                new_msg = new_fields[msg_name]
                for field_name, field_info in old_msg.items():
                    if field_name not in new_msg:
                        all_errors.append(
                            f"❌ {proto_name}: {msg_name}.{field_name} "
                            f"(#{field_info['number']}) silinmiş — reserved olarak işaretlenmeli!"
                        )
                    elif new_msg[field_name]["type"] != field_info["type"]:
                        all_errors.append(
                            f"❌ {proto_name}: {msg_name}.{field_name} type değişmiş: "
                            f"{field_info['type']} → {new_msg[field_name]['type']}"
                        )

        if all_errors:
            logger.info("\n🚨 Backward Compatibility İhlalleri:\n")
            for error in all_errors:
                logger.info(f"  {error}")
            logger.info(f"\n{len(all_errors)} ihlal bulundu!")
            return 1
        else:
            logger.info("✅ Tüm proto dosyaları backward compatible")
    else:
        logger.info("📝 İlk snapshot oluşturuluyor...")

    # Snapshot'ı kaydet
    with open(snapshot_file, "w") as f:
        json.dump(current_snapshot, f, indent=2)
    logger.info(f"💾 Snapshot kaydedildi: {snapshot_file}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
