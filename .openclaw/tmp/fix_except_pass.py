#!/usr/bin/env python3
"""
Fix all 'except: pass' and 'except X: pass' patterns across the codebase.
Handles both same-line and multi-line patterns.
"""
import re
import os
import sys

def get_logger_name(content):
    """Find the logger variable name used in the file."""
    m = re.search(r'(\w+)\s*=\s*structlog\.get_logger\(', content)
    if m:
        return m.group(1), 'structlog'
    m = re.search(r'(\w+)\s*=\s*logging\.getLogger\(', content)
    if m:
        return m.group(1), 'logging'
    return None, None

def get_function_context(lines, line_idx):
    """Get the function name containing the given line."""
    for i in range(line_idx, -1, -1):
        m = re.match(r'^\s*(?:async\s+)?def\s+(\w+)', lines[i])
        if m:
            return m.group(1)
    return 'module_level'

def get_except_type(line):
    """Extract the exception type from the except line."""
    stripped = line.strip()
    if re.match(r'^except\s*:', stripped):
        return None, True
    m = re.match(r'^except\s+([\w.]+)\s*:', stripped)
    if m:
        return m.group(1), False
    m = re.match(r'^except\s+\(([^)]+)\)\s*:', stripped)
    if m:
        return f"({m.group(1)})", False
    return 'Exception', False

def determine_log_level(exc_type, bare, func_name):
    """Determine appropriate log level and message."""
    if bare:
        return 'error', f"Unexpected error in {func_name}"
    if exc_type == 'ImportError':
        return 'debug', f"Optional import not available in {func_name}"
    if exc_type in ('RuntimeError', 'RuntimeWarning'):
        return 'warning', f"Runtime error in {func_name}"
    if exc_type in ('ValueError', 'TypeError', 'KeyError', 'IndexError', 'AttributeError'):
        return 'warning', f"Data error in {func_name}: {exc_type}"
    if exc_type in ('asyncio.CancelledError', 'asyncio.TimeoutError', 'TimeoutError'):
        return 'warning', f"Timeout/cancellation in {func_name}"
    if exc_type and 'JSONDecodeError' in str(exc_type):
        return 'warning', f"JSON parse error in {func_name}"
    if exc_type and 'Error' in str(exc_type):
        return 'warning', f"Error in {func_name}: {exc_type}"
    return 'warning', f"Caught {exc_type or 'Exception'} in {func_name}"

def fix_file(filepath, dry_run=False):
    """Fix all except:pass patterns in a file."""
    with open(filepath, 'r') as f:
        content = f.read()
    
    lines = content.split('\n')
    logger_name, logger_type = get_logger_name(content)
    changes = []
    i = 0
    
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        
        # Pattern 1: except: pass (same line)
        is_same_line_bare = bool(re.match(r'^except\s*:\s*pass$', stripped))
        is_same_line_except = bool(re.match(r'^except\s*(?:\([^)]+\)|[\w.]+)(?:\s+as\s+\w+)?\s*:\s*pass$', stripped))
        
        # Pattern 2: except:\n    pass (separate lines)
        is_multiline_bare = False
        is_multiline_except = False
        pass_line_idx = None
        
        if re.match(r'^except\s*:\s*$', stripped):
            # Check if next non-empty line is just 'pass'
            for j in range(i + 1, min(i + 4, len(lines))):
                next_stripped = lines[j].strip()
                if next_stripped == 'pass':
                    is_multiline_bare = True
                    pass_line_idx = j
                    break
                elif next_stripped and not next_stripped.startswith('#'):
                    break
        
        elif re.match(r'^except\s*(?:\([^)]+\)|[\w.]+)(?:\s+as\s+\w+)?\s*:\s*$', stripped):
            for j in range(i + 1, min(i + 4, len(lines))):
                next_stripped = lines[j].strip()
                if next_stripped == 'pass':
                    is_multiline_except = True
                    pass_line_idx = j
                    break
                elif next_stripped and not next_stripped.startswith('#'):
                    break
        
        if is_same_line_bare or is_same_line_except or is_multiline_bare or is_multiline_except:
            indent = re.match(r'^(\s*)', line).group(1)
            func_name = get_function_context(lines, i)
            exc_type, bare = get_except_type(line)
            log_level, log_msg = determine_log_level(exc_type, bare, func_name)
            
            # Build replacement
            if bare:
                new_except_line = f"{indent}except Exception:"
            else:
                # Keep the except type, just remove trailing colon+pass
                new_except_line = re.sub(r'\s*:\s*pass\s*$', ':', line.rstrip())
                if not new_except_line.endswith(':'):
                    new_except_line = new_except_line.rstrip() + ':'
            
            # Log line
            if logger_name:
                log_line = f"{indent}    {logger_name}.{log_level}(\"{log_msg}\", exc_info=True)"
            else:
                log_line = f"{indent}    pass  # FIXME: add proper logging"
            
            if is_same_line_bare or is_same_line_except:
                # Replace single line with two lines
                old_line = line.rstrip()
                lines[i] = new_except_line
                lines.insert(i + 1, log_line)
                changes.append({
                    'line': i + 1,
                    'old': old_line,
                    'new': f"{new_except_line}\n{log_line}",
                    'func': func_name,
                    'exc_type': exc_type,
                    'bare': bare
                })
                i += 2
            else:
                # Multi-line: replace except line and pass line
                old_except = line.rstrip()
                old_pass = lines[pass_line_idx].rstrip()
                lines[i] = new_except_line
                lines[pass_line_idx] = log_line
                changes.append({
                    'line': i + 1,
                    'old': f"{old_except}\n{old_pass}",
                    'new': f"{new_except_line}\n{log_line}",
                    'func': func_name,
                    'exc_type': exc_type,
                    'bare': bare
                })
                i = pass_line_idx + 1
        else:
            i += 1
    
    if changes:
        new_content = '\n'.join(lines)
        if not dry_run:
            with open(filepath, 'w') as f:
                f.write(new_content)
        return changes
    return []

def add_logger_if_missing(filepath, dry_run=False):
    """Add structlog logger import if file doesn't have one."""
    with open(filepath, 'r') as f:
        content = f.read()
    
    logger_name, _ = get_logger_name(content)
    if logger_name:
        return False
    
    lines = content.split('\n')
    
    # Find last import line
    import_end = -1
    has_structlog = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('import ') or stripped.startswith('from '):
            import_end = i
            if 'structlog' in stripped:
                has_structlog = True
    
    if import_end == -1:
        import_end = 0
    
    additions = []
    if not has_structlog:
        additions.append('import structlog')
    additions.append('')
    additions.append('logger = structlog.get_logger(__name__)')
    
    for j, add in enumerate(additions):
        lines.insert(import_end + 1 + j, add)
    
    if not dry_run:
        with open(filepath, 'w') as f:
            f.write('\n'.join(lines))
    
    return True

# Main
dry_run = '--dry-run' in sys.argv
base_dir = os.getcwd()

# Collect all files with issues
files_to_fix = []
for root, dirs, files in os.walk(base_dir):
    rel_root = os.path.relpath(root, base_dir)
    if '.git' in rel_root or '__pycache__' in rel_root or '.openclaw' in rel_root:
        continue
    for f in files:
        if f.endswith('.py'):
            filepath = os.path.join(root, f)
            try:
                with open(filepath) as fh:
                    content = fh.read()
                # Check for except:pass patterns (same line or multi-line)
                if (re.search(r'^\s*except\s*.*:\s*pass\s*$', content, re.MULTILINE) or
                    re.search(r'^\s*except\s*.*:\s*\n\s*pass\s*$', content, re.MULTILINE)):
                    files_to_fix.append(filepath)
            except:
                pass

print(f"Found {len(files_to_fix)} files with except:pass patterns")
print("=" * 70)

total_changes = 0
files_modified = 0

for filepath in sorted(files_to_fix):
    rel_path = os.path.relpath(filepath, base_dir)
    
    logger_added = add_logger_if_missing(filepath, dry_run)
    if logger_added:
        print(f"[LOGGER ADDED] {rel_path}")
    
    changes = fix_file(filepath, dry_run)
    if changes:
        files_modified += 1
        total_changes += len(changes)
        for c in changes:
            bare_mark = 'BARE→Exception' if c['bare'] else 'pass→log'
            print(f"  L{c['line']:4d} | {c['func']:30s} | {str(c['exc_type'] or 'BARE'):25s} | {bare_mark}")

print("=" * 70)
print(f"Total: {total_changes} fixes in {files_modified} files")
if dry_run:
    print("(DRY RUN - no files modified)")
