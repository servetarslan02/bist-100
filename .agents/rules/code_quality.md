# Code Quality, Formatting & Anti-Incomplete Rules

> bist-100 projesinde eksik/hatalı kod üretimini engelleyen kurallar.

1. **Tam ve Eksiksiz Uygulama:**
   - Asla `TODO`, yarım bırakılmış kod veya kesintili fonksiyon yazma.
   - Değiştirilen her fonksiyonun uçtan uca çalışır durumda olması zorunludur.

2. **Ruff & Mypy:**
   - Ruff line length: 120, target: py312.
   - Mypy: strict mode (`python_version = "3.12"`).
   - Type hint'ler (typing / pydantic) eksiksiz yazılmalıdır.

3. **Loglama ve Hata Yönetimi:**
   - Loglama için `structlog` kullanılır (`logger = structlog.get_logger(__name__)`).
   - Sessiz `except: pass` yasaktır; hata ya loglanmalı ya da güvenli şekilde ele alınmalıdır.

4. **Bağımlılık Taraması:**
   - Bir fonksiyonda imza veya dönüş tipi değiştirilirse `services/`, `workers/` ve `tests/` altındaki tüm çağrılar taranmalı ve güncellenmelidir.
