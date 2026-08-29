"""
Patch2: B29-B36 fonksiyon tanımlarini deep_system_integrity_auditor.py dosyasina ekler.
B28 fonksiyonunun bitisinden sonra, run() fonksiyonundan once eklenir.
"""
import sys

SRC = "scripts/deep_system_integrity_auditor.py"

NEW_FUNCTIONS = r'''

# ══════════════════════════════════════════════════════════════════════════════
# YENİ BOYUTLAR: B29-B36
# ══════════════════════════════════════════════════════════════════════════════

# ─── B29: Docker Compose Derin Validasyonu ─────────────────────────────────
def b29_docker_compose_deep() -> list[Finding]:
    """Docker Compose servis bagimlilikları, volume mount varligi, healthcheck,
    network alias tutarliligi ve servis adi kod ici host adi eslesmesini kontrol eder."""
    finds = []
    dc_path = PROJECT_ROOT / "docker-compose.yml"
    if not dc_path.exists():
        return [F(29, "DOCKER_COMPOSE_MISSING", "CRITICAL", "docker-compose.yml", 1,
            "docker-compose.yml yok!")]
    try:
        import yaml  # type: ignore
        with open(dc_path, encoding="utf-8", errors="replace") as f:
            dc = yaml.safe_load(f)
    except ImportError:
        content = dc_path.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r'\s-\s\./([^:]+):', content):
            host_path = PROJECT_ROOT / m.group(1)
            if not host_path.exists():
                lineno = content[:m.start()].count("\n") + 1
                finds.append(F(29, "DOCKER_VOLUME_MISSING", "HIGH",
                    "docker-compose.yml", lineno,
                    f"Volume mount host yolu yok: './{m.group(1)}'"))
        return finds
    except Exception as e:
        return [F(29, "DOCKER_COMPOSE_PARSE_ERROR", "HIGH", "docker-compose.yml", 1,
            f"docker-compose.yml parse hatasi: {e}")]

    services = dc.get("services", {})
    service_names = set(services.keys())

    for svc_name, svc in services.items():
        if not isinstance(svc, dict):
            continue
        deps = svc.get("depends_on", {})
        if isinstance(deps, list):
            deps = {d: {} for d in deps}
        for dep in deps:
            if dep not in service_names:
                finds.append(F(29, "DOCKER_INVALID_DEPENDS", "HIGH",
                    "docker-compose.yml", 1,
                    f"'{svc_name}' -> depends_on '{dep}' servisi tanimli degil"))
        for vol in svc.get("volumes", []):
            if isinstance(vol, str) and vol.startswith("./"):
                host_part = vol.split(":")[0].lstrip("./")
                host_path = PROJECT_ROOT / host_part
                if not host_path.exists():
                    finds.append(F(29, "DOCKER_VOLUME_MISSING", "HIGH",
                        "docker-compose.yml", 1,
                        f"'{svc_name}' volume mount yolu yok: '{vol.split(':')[0]}'"))
        critical_svcs = {"postgres", "redis", "nats", "api", "clickhouse"}
        if svc_name in critical_svcs and not svc.get("healthcheck"):
            finds.append(F(29, "DOCKER_MISSING_HEALTHCHECK", "HIGH",
                "docker-compose.yml", 1,
                f"Kritik servis '{svc_name}' icin healthcheck tanimlanmamis"))
        image = svc.get("image", "")
        if image == "alpha-bist-base" and "build" not in svc:
            finds.append(F(29, "DOCKER_IMAGE_NO_BUILD", "MEDIUM",
                "docker-compose.yml", 1,
                f"'{svc_name}' alpha-bist-base image kullaniyor ama build tanimi yok"))

    for py_path in (PROJECT_ROOT / "services").rglob("*.py"):
        try:
            content = py_path.read_text(encoding="utf-8", errors="replace")
            rel = py_path.relative_to(PROJECT_ROOT).as_posix()
            for m in re.finditer(r'["\'](?:localhost|127\.0\.0\.1):(5432|6379|4222|8123|9000)["\']', content):
                port_map = {"5432": "postgres", "6379": "redis", "4222": "nats",
                            "8123": "clickhouse", "9000": "clickhouse"}
                port = m.group(1)
                lineno = content[:m.start()].count("\n") + 1
                finds.append(F(29, "DOCKER_LOCALHOST_HARDCODED", "HIGH",
                    rel, lineno,
                    f"Docker icinde 'localhost:{port}' hardcoded - env var kullan ({port_map.get(port,'')} host)"))
        except Exception:
            pass
    return finds


# ─── B30: pyproject.toml <-> Gercek Import Uyumu ──────────────────────────
def b30_dependency_check(all_imports_map: dict[str, set[str]]) -> list[Finding]:
    """pyproject.toml'da tanimli olmayan ama kullanilan ucuncu taraf kutuphaneler."""
    finds = []
    pyproject = PROJECT_ROOT / "pyproject.toml"
    if not pyproject.exists():
        return [F(30, "PYPROJECT_MISSING", "CRITICAL", "pyproject.toml", 1,
            "pyproject.toml yok - bagimlilik yonetimi belirsiz")]
    content = pyproject.read_text(encoding="utf-8", errors="replace")
    declared: set[str] = set()
    for m in re.finditer(r'["\'](([a-zA-Z][a-zA-Z0-9_\-]+?))(?:[>=<\[!]|["\'])', content):
        name = m.group(1).replace("-", "_").lower()
        if len(name) > 2:
            declared.add(name)
    STDLIB = {
        "os","sys","re","json","time","datetime","pathlib","typing","collections",
        "functools","itertools","math","random","copy","io","abc","enum","dataclasses",
        "contextlib","asyncio","concurrent","threading","multiprocessing","subprocess",
        "socket","ssl","logging","traceback","inspect","importlib","pkgutil","ast",
        "hashlib","hmac","secrets","base64","uuid","struct","array","queue","heapq",
        "bisect","weakref","gc","platform","shutil","tempfile","glob","fnmatch","stat",
        "gzip","zipfile","tarfile","csv","configparser","argparse","unittest","warnings",
        "builtins","__future__","types","string","textwrap","pprint","decimal","fractions",
        "statistics","operator","urllib","http","email","html","xml","sqlite3","pickle",
        "shelve","lzma","bz2","zlib","signal","atexit","ctypes","mmap","msvcrt","winreg",
        "dis","tokenize","reprlib","cmath",
    }
    INTERNAL = {"services","workers","ml","ai","backtest","config","scripts"}
    IMPORT_TO_PKG = {
        "sklearn": "scikit_learn","cv2":"opencv_python","PIL":"Pillow",
        "yaml":"pyyaml","jwt":"python_jose","dotenv":"python_dotenv",
        "bs4":"beautifulsoup4","dateutil":"python_dateutil",
        "attr":"attrs","nats":"nats_py","aiofiles":"aiofiles","aiohttp":"aiohttp",
    }
    all_third_party: dict[str, list[str]] = defaultdict(list)
    for rel, imports in all_imports_map.items():
        is_prod = any(rel.startswith(d + "/") for d in PRODUCTION_DIRS)
        if not is_prod:
            continue
        for imp in imports:
            top = imp.split(".")[0].replace("-","_").lower()
            if top in STDLIB or top in INTERNAL or top.startswith("_") or not top:
                continue
            all_third_party[top].append(rel)
    for pkg, files in all_third_party.items():
        normalized = IMPORT_TO_PKG.get(pkg, pkg)
        if normalized not in declared and pkg not in declared:
            finds.append(F(30, "UNDECLARED_DEPENDENCY", "HIGH",
                files[0], 1,
                f"'{pkg}' import ediliyor ama pyproject.toml'da tanimli degil ({len(files)} dosyada)"))
    return finds


# ─── B31: ML Model Dosya Varligi ───────────────────────────────────────────
def b31_ml_model_files(all_files_content: dict[str, str]) -> list[Finding]:
    """Kod icinde yuklenen model dosyalarinin fiziksel varligini kontrol eder."""
    finds = []
    models_dir = PROJECT_ROOT / "models"
    if not models_dir.exists():
        finds.append(F(31, "MODELS_DIR_MISSING", "CRITICAL", "models/", 1,
            "models/ dizini yok! Egitilmis ML model dosyalari burada olmali - inference calissamaz"))
    else:
        model_files = (list(models_dir.rglob("*.pkl")) + list(models_dir.rglob("*.lgbm")) +
                       list(models_dir.rglob("*.pt")) + list(models_dir.rglob("*.onnx")) +
                       list(models_dir.rglob("*.joblib")) + list(models_dir.rglob("*.cbm")))
        if not model_files:
            finds.append(F(31, "NO_TRAINED_MODELS", "CRITICAL", "models/", 1,
                "models/ dizini var ama hic egitilmis model dosyasi yok (.pkl/.lgbm/.pt/.onnx)"))
    load_pattern = re.compile(
        r'(?:joblib\.load|pickle\.load|torch\.load|lgb\.Booster|load_model)\s*\(["\']([^"\']+)["\']',
        re.MULTILINE)
    for rel, content in all_files_content.items():
        for m in load_pattern.finditer(content):
            model_path_str = m.group(1)
            if not model_path_str.startswith("/"):
                full = PROJECT_ROOT / model_path_str
                if not full.exists():
                    lineno = content[:m.start()].count("\n") + 1
                    finds.append(F(31, "MODEL_FILE_NOT_FOUND", "CRITICAL",
                        rel, lineno, f"Yuklenen model dosyasi yok: '{model_path_str}'"))
    for rel, content in all_files_content.items():
        if "mlflow" in content and "set_tracking_uri" in content:
            finds.append(F(31, "MLFLOW_TRACKING_USED", "INFO", rel, 1,
                "MLflow tracking kullaniliyor - tracking server calisir durumda olmali"))
            break
    return finds


# ─── B32: NATS/Redis Mesaj Semasi Tutarliligi ─────────────────────────────
def b32_messaging_schema(all_files_content: dict[str, str]) -> list[Finding]:
    """NATS subject adlari ve Redis key naming convention tutarliligi."""
    finds = []
    nats_publish = re.compile(r'nc\.publish\s*\(\s*["\'](([^"\']+))["\']', re.MULTILINE)
    nats_subscribe = re.compile(r'nc\.subscribe\s*\(\s*["\'](([^"\']+))["\']', re.MULTILINE)
    published_subjects: dict[str, str] = {}
    subscribed_subjects: dict[str, str] = {}
    for rel, content in all_files_content.items():
        for m in nats_publish.finditer(content):
            published_subjects[m.group(1)] = rel
        for m in nats_subscribe.finditer(content):
            subscribed_subjects[m.group(1)] = rel
    for subj, rel in subscribed_subjects.items():
        if "*" in subj or ">" in subj:
            continue
        if subj not in published_subjects:
            finds.append(F(32, "NATS_ORPHAN_SUBSCRIBER", "HIGH", rel, 1,
                f"NATS subscribe '{subj}' icin hic publisher bulunamadi - veri hic gelmeyebilir"))
    for subj, rel in published_subjects.items():
        if subj not in subscribed_subjects:
            finds.append(F(32, "NATS_ORPHAN_PUBLISHER", "LOW", rel, 1,
                f"NATS publish '{subj}' icin hic subscriber bulunamadi - veri kaybolabilir"))
    redis_key_pattern = re.compile(r'r(?:edis)?\.(?:set|get|hset|hget)\s*\(\s*["\'](([^"\']+))["\']', re.MULTILINE)
    key_prefixes: dict[str, list[str]] = defaultdict(list)
    for rel, content in all_files_content.items():
        for m in redis_key_pattern.finditer(content):
            key = m.group(1)
            prefix = key.split(":")[0] if ":" in key else "NO_PREFIX"
            key_prefixes[prefix].append(rel)
    if "NO_PREFIX" in key_prefixes:
        finds.append(F(32, "REDIS_KEY_NO_PREFIX", "MEDIUM",
            key_prefixes["NO_PREFIX"][0], 1,
            f"{len(key_prefixes['NO_PREFIX'])} dosyada prefix'siz Redis key kullaniliyor - cakisma riski"))
    return finds


# ─── B33: Coklu Adim Dongüsel Bagimlilik (A->B->C->A) ─────────────────────
def b33_multi_hop_cycles(all_imports_map: dict[str, set[str]]) -> list[Finding]:
    """3+ modullu dongüsel bagimliligi DFS ile tespit eder."""
    finds = []
    rel_to_mod: dict[str, str] = {}
    mod_to_rel: dict[str, str] = {}
    for rel in all_imports_map:
        mod = rel.replace("/", ".").replace(".py", "")
        rel_to_mod[rel] = mod
        mod_to_rel[mod] = rel
    graph: dict[str, set[str]] = defaultdict(set)
    for rel, imports in all_imports_map.items():
        src_mod = rel_to_mod.get(rel, "")
        if not any(rel.startswith(d + "/") for d in PRODUCTION_DIRS):
            continue
        for imp in imports:
            imp_mod = imp.split(".")[0]
            if imp_mod in ("services", "ml", "workers"):
                target_rel = imp.replace(".", "/") + ".py"
                if target_rel in all_imports_map:
                    graph[src_mod].add(rel_to_mod.get(target_rel, imp))
    visited: set[str] = set()
    reported_cycles: set[tuple] = set()

    def dfs(node: str, path: list, path_set: set):
        if node in path_set:
            cycle_start = path.index(node)
            cycle = tuple(path[cycle_start:])
            if len(cycle) >= 3 and cycle not in reported_cycles:
                reported_cycles.add(cycle)
                finds.append(F(33, "MULTI_HOP_CYCLE", "HIGH",
                    mod_to_rel.get(node, node + ".py"), 1,
                    f"Dongüsel bagimlilik ({len(cycle)} adim): {' -> '.join(str(x) for x in cycle[:6])}"))
            return
        if node in visited:
            return
        visited.add(node)
        path.append(node)
        path_set.add(node)
        for neighbor in graph.get(node, set()):
            if len(path) < 8:
                dfs(neighbor, path, path_set)
        path.pop()
        path_set.discard(node)

    for node in list(graph.keys())[:200]:
        if node not in visited:
            dfs(node, [], set())
    return finds


# ─── B34: Config <-> Docker-Compose Cross-Reference ───────────────────────
def b34_config_docker_crossref() -> list[Finding]:
    """settings.py'deki env var isimleri docker-compose.yml'daki environment
    key'leriyle ve .env.example'daki key'lerle ortusüyor mu?"""
    finds = []
    config_path = PROJECT_ROOT / "services/core/config.py"
    if not config_path.exists():
        config_path = PROJECT_ROOT / "config/settings.py"
    if not config_path.exists():
        return [F(34, "CONFIG_FILE_MISSING", "HIGH", "services/core/config.py", 1,
            "settings/config dosyasi bulunamadi")]
    config_src = config_path.read_text(encoding="utf-8", errors="replace")
    config_rel = config_path.relative_to(PROJECT_ROOT).as_posix()
    field_env_vars: set[str] = set()
    for m in re.finditer(r'([A-Z][A-Z0-9_]{3,})\s*[=:]', config_src):
        field_env_vars.add(m.group(1))
    dc_path = PROJECT_ROOT / "docker-compose.yml"
    dc_env_vars: set[str] = set()
    if dc_path.exists():
        dc_content = dc_path.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r'\$\{([A-Z_][A-Z0-9_]+)\}', dc_content):
            dc_env_vars.add(m.group(1))
        for m in re.finditer(r'- ([A-Z][A-Z0-9_]{3,})=', dc_content):
            dc_env_vars.add(m.group(1))
    example_env_vars: set[str] = set()
    example = PROJECT_ROOT / ".env.example"
    if example.exists():
        for line in example.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                example_env_vars.add(line.split("=")[0].strip())
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        env_keys: set[str] = set()
        for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                env_keys.add(line.split("=")[0].strip())
        for var in sorted(dc_env_vars):
            if var not in env_keys:
                finds.append(F(34, "DOCKER_ENV_VAR_MISSING_IN_DOTENV", "HIGH",
                    ".env", 1,
                    f"docker-compose.yml'de '${{{var}}}' kullaniliyor ama .env'de tanimsiz - servis baslamaz"))
    return finds


# ─── B35: Veritabani Semasi <-> SQL Sorgu Tutarliligi ─────────────────────
def b35_db_schema_consistency() -> list[Finding]:
    """Migration SQL dosyalarindaki tablo adlari ile kod icindeki SQL sorgulari."""
    finds = []
    db_tables: set[str] = set()
    init_dir = PROJECT_ROOT / "database/init"
    if not init_dir.exists():
        finds.append(F(35, "DB_INIT_MISSING", "HIGH", "database/init/", 1,
            "database/init/ dizini yok - schema migration tanimsiz"))
    else:
        sql_files = list(init_dir.rglob("*.sql"))
        if not sql_files:
            finds.append(F(35, "NO_SQL_MIGRATIONS", "HIGH", "database/init/", 1,
                "database/init/ icinde hic .sql migration dosyasi yok"))
        else:
            for sql_file in sql_files:
                try:
                    sql_content = sql_file.read_text(encoding="utf-8", errors="replace")
                    for m in re.finditer(
                        r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:["\']?\w+["\']?\.)?["\']?(\w+)["\']?\s*\(',
                        sql_content, re.IGNORECASE):
                        db_tables.add(m.group(1).lower())
                except Exception:
                    pass
        if db_tables:
            finds.append(F(35, "DB_TABLES_FOUND", "INFO", "database/init/", 1,
                f"Schema'da {len(db_tables)} tablo tanimli: {sorted(db_tables)[:8]}"))

    from_pattern = re.compile(
        r'(?:FROM|JOIN|INTO|UPDATE|TABLE)\s+["\']?(\w+)["\']?',
        re.IGNORECASE | re.MULTILINE)
    code_tables: dict[str, list[str]] = defaultdict(list)
    for root, dirs, files in os.walk(PROJECT_ROOT / "services"):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
        for fname in files:
            if not fname.endswith(".py"):
                continue
            p = Path(root) / fname
            rel = p.relative_to(PROJECT_ROOT).as_posix()
            try:
                content = p.read_text(encoding="utf-8", errors="replace")
                if "SELECT" not in content and "INSERT" not in content and "asyncpg" not in content:
                    continue
                for m in from_pattern.finditer(content):
                    tbl = m.group(1).lower()
                    if tbl in ("select","where","and","or","not","null","true","false",
                               "inner","left","right","outer","cross","natural","values",
                               "set","case","when","then","else","end","by","order",
                               "group","having","limit","offset","join","on"):
                        continue
                    if len(tbl) > 3:
                        code_tables[tbl].append(rel)
            except Exception:
                pass

    KNOWN_SCHEMAS = {"alpha_bist","public","information_schema","pg_catalog",
                     "timescaledb","alpha","data","result","record","row",
                     "column","index","type","text","json","boolean","integer"}
    if db_tables:
        for tbl, files in code_tables.items():
            if tbl not in db_tables and tbl not in KNOWN_SCHEMAS:
                finds.append(F(35, "SQL_TABLE_NOT_IN_SCHEMA", "MEDIUM",
                    files[0], 1,
                    f"Sorgularda '{tbl}' tablosu kullaniliyor ama schema migration'da tanimsiz ({len(files)} dosyada)"))
    return finds


# ─── B36: Async Güvenlik & Yaris Kosulu ───────────────────────────────────
def b36_async_safety(all_files_content: dict[str, str]) -> list[Finding]:
    """Thread-unsafe global state, fire-and-forget task, lock eksikligi tespiti."""
    finds = []
    global_mutable = re.compile(
        r'^(?!\s*#)\s*([a-z_][a-zA-Z0-9_]*)\s*:\s*(?:dict|list|set)\s*=\s*(?:\{\}|\[\]|set\(\))',
        re.MULTILINE)

    for rel, content in all_files_content.items():
        is_prod = any(rel.startswith(d + "/") for d in PRODUCTION_DIRS)
        if not is_prod:
            continue

        # 1. asyncio.create_task() sonucu degiskene atilmamis (fire-and-forget)
        for m in re.finditer(r'^\s*asyncio\.create_task\s*\(', content, re.MULTILINE):
            lineno = content[:m.start()].count("\n") + 1
            line = content[m.start():m.start()+120]
            if "=" not in content[max(0, m.start()-60):m.start()]:
                finds.append(F(36, "FIRE_AND_FORGET_TASK", "HIGH",
                    rel, lineno,
                    "asyncio.create_task() sonucu degiskene atilmamis - exception sessizce kaybolur"))

        # 2. Modul seviyesi mutasyona acik global dict/list
        for m in global_mutable.finditer(content):
            var_name = m.group(1)
            if var_name not in ("logger", "tracer", "app", "router"):
                lineno = content[:m.start()].count("\n") + 1
                finds.append(F(36, "GLOBAL_MUTABLE_STATE", "MEDIUM",
                    rel, lineno,
                    f"Modul seviyesi mutasyona acik global '{var_name}' - async/thread ortaminda race condition riski"))

        # 3. asyncio.run() zaten calisan loop icinde cagriliyor mu?
        try:
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, ast.AsyncFunctionDef):
                    for child in ast.walk(node):
                        if isinstance(child, ast.Call):
                            func = child.func
                            if (isinstance(func, ast.Attribute) and func.attr == "run" and
                                    isinstance(func.value, ast.Name) and func.value.id == "asyncio"):
                                finds.append(F(36, "ASYNCIO_RUN_IN_ASYNC", "CRITICAL",
                                    rel, child.lineno,
                                    "asyncio.run() async fonksiyon icinde cagriliyor - RuntimeError: event loop zaten calisiyor!"))
        except Exception:
            pass

    return finds

'''

# Dosyayi oku
src = open(SRC, "r", encoding="utf-8", errors="replace").read()

# "# ─── ANA MOTOR" satirini bul - bunun hemen oncesine ekle
INSERT_MARKER = "# ─── ANA MOTOR"
idx = src.find(INSERT_MARKER)
if idx == -1:
    INSERT_MARKER = "def run():"
    idx = src.find(INSERT_MARKER)

if idx == -1:
    print("ERROR: Insert marker bulunamadi!")
    sys.exit(1)

# Yeni fonksiyonlari ekle
new_src = src[:idx] + NEW_FUNCTIONS + "\n" + src[idx:]

with open(SRC, "w", encoding="utf-8") as f:
    f.write(new_src)

print(f"Patch2 tamamlandi. Toplam satir: {len(new_src.splitlines())}")
print(f"b29 def in src: {'def b29_docker' in new_src}")
print(f"b36 def in src: {'def b36_async' in new_src}")
