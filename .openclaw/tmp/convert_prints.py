#!/usr/bin/env python3
"""Convert print() → logger calls in services/**/*.py

Handles:
- Single-line print("...") / print(f"...")
- Multi-line print(\n  ...\n)
- print(..., file=sys.stderr) → logger.warning(...)
- print(str(e)) in except → logger.error(..., error=str(e))
- Adds structlog import if missing
"""
import re, os, sys

SERVICES = "/home/work/.openclaw/workspace/bist-100/services"

def find_files_with_prints():
    files = []
    for root, dirs, fnames in os.walk(SERVICES):
        dirs[:] = [d for d in dirs if d != '__pycache__']
        for fn in fnames:
            if fn.endswith('.py'):
                fp = os.path.join(root, fn)
                with open(fp) as f:
                    if re.search(r'(?<!\w)print\s*\(', f.read()):
                        files.append(fp)
    return sorted(files)

def ensure_imports(content):
    """Insert structlog import + logger assignment if missing."""
    if 'import structlog' in content and 'logger = structlog.get_logger()' in content:
        return content
    lines = content.split('\n')
    # Find insert point: after last import/from line at module level
    insert_after = -1
    in_doc = False
    doc_end = -1
    for i, ln in enumerate(lines):
        s = ln.strip()
        if s.startswith('"""') or s.startswith("'''"):
            q = s[:3]
            if not in_doc:
                if s.count(q) >= 2 and len(s) > 3:  # single-line docstring
                    doc_end = i
                else:
                    in_doc = True
            else:
                in_doc = False
                doc_end = i
        elif not in_doc and (s.startswith('import ') or s.startswith('from ')):
            insert_after = i
    pos = max(insert_after, doc_end)
    if pos < 0:
        pos = 0
    to_add = []
    if 'import structlog' not in content:
        to_add.append("import structlog")
    if 'logger = structlog.get_logger()' not in content:
        to_add.append("logger = structlog.get_logger()")
    if to_add:
        for j, line in enumerate(to_add):
            lines.insert(pos + 1 + j, line)
        lines.insert(pos + 1 + len(to_add), "")
    return '\n'.join(lines)

def extract_balanced(text, start):
    """Starting at text[start] = '(', find the matching ')'.
    Returns (inner_text, end_pos) where end_pos is index AFTER closing paren."""
    depth = 0
    i = start
    in_str = None
    esc = False
    while i < len(text):
        c = text[i]
        if esc:
            esc = False
            i += 1
            continue
        if c == '\\':
            esc = True
            i += 1
            continue
        if in_str:
            if c == in_str:
                # check triple quote
                if text[i:i+3] == in_str * 3:
                    j = text.find(in_str*3, i+3)
                    i = (j + 3) if j != -1 else len(text)
                else:
                    in_str = None
            i += 1
            continue
        if c in ('"', "'"):
            if text[i:i+3] in ('"""', "'''"):
                in_str = c
                i += 3
                continue
            in_str = c
            i += 1
            continue
        if c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
            if depth == 0:
                return text[start+1:i], i + 1
        i += 1
    return text[start+1:], len(text)

def convert_file(fpath):
    with open(fpath) as f:
        text = f.read()
    
    original = text
    result = []
    pos = 0
    
    # Check for except blocks context
    # We'll do a simple approach: look for 'except' before each print
    
    for m in re.finditer(r'(?<!\w)print\s*\(', text):
        start = m.start()
        paren_pos = m.end() - 1  # position of '('
        
        # Skip if in a comment
        line_start = text.rfind('\n', 0, start) + 1
        prefix = text[line_start:start]
        if '#' in prefix:
            continue
        
        inner, end_pos = extract_balanced(text, paren_pos)
        full_match = text[start:end_pos]
        
        # Skip if this looks like a method def or class (e.g., _print_*)
        before = text[max(0,start-5):start]
        if before and before[-1] not in (' ', '\t', '\n', '(', ',', '=', '!', '&', '|', ';', ':'):
            continue
        
        # Determine log level
        level = "info"
        
        # Check for file=sys.stderr
        is_stderr = False
        stderr_re = re.search(r',\s*file\s*=\s*sys\.stderr\s*$', inner)
        if stderr_re:
            is_stderr = True
            inner = inner[:stderr_re.start()].strip()
        
        # Check for end= param
        end_re = re.search(r',\s*end\s*=\s*(?:"[^"]*"|\'[^\']*\')\s*$', inner)
        if end_re:
            inner = inner[:end_re.start()].strip()
        
        if is_stderr:
            level = "warning"
        
        # Check if in except block → error level for error vars
        ctx = text[max(0, start-300):start]
        if re.search(r'except\b.*:\s*$', ctx, re.MULTILINE):
            stripped_inner = inner.strip()
            if re.match(r'^(str\(\w+\)|\w+)$', stripped_inner) and (
                'e' in stripped_inner.lower() or 'err' in stripped_inner.lower() or 'exc' in stripped_inner.lower()
            ):
                level = "error"
        
        result.append(text[pos:start])
        result.append(f'logger.{level}({inner})')
        pos = end_pos
    
    result.append(text[pos:])
    new_text = ''.join(result)
    
    if new_text == original:
        return 0
    
    new_text = ensure_imports(new_text)
    
    with open(fpath, 'w') as f:
        f.write(new_text)
    
    orig_count = len(re.findall(r'(?<!\w)print\s*\(', original))
    new_count = len(re.findall(r'(?<!\w)print\s*\(', new_text))
    return orig_count - new_count

total = 0
files = find_files_with_prints()
print(f"Found {len(files)} files with print()")

for fp in files:
    rel = os.path.relpath(fp, SERVICES)
    n = convert_file(fp)
    if n > 0:
        print(f"  ✓ {rel}: {n} converted")
        total += n
    else:
        print(f"  - {rel}: no changes")

print(f"\nTotal: {total} print() calls converted")
