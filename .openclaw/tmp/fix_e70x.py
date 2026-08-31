#!/usr/bin/env python3
"""Fix E701 (multiple statements on one line, colon) and E702 (semicolon) ruff errors."""
import re
import sys


def fix_line(line):
    """Fix E701/E702 issues in a single line. Returns list of lines (each ending with \\n)."""
    # Preserve the original line ending
    stripped_content = line.rstrip('\n\r')
    line_ending = line[len(stripped_content):]
    if not line_ending:
        line_ending = '\n'

    stripped = stripped_content.lstrip()
    indent = stripped_content[:len(stripped_content) - len(stripped)]

    # Skip comments and empty lines
    if not stripped or stripped.startswith('#'):
        return [line]

    # E702: Split on semicolons (but not inside strings)
    if ';' in stripped:
        parts = split_on_semicolons(stripped)
        if len(parts) > 1:
            result = []
            for part in parts:
                result.append(indent + part + line_ending)
            return result

    # E701: Split on colon for inline if/elif/else/def/class/for/while/try/except/finally
    # Pattern: `keyword ...: statement` where statement is non-empty code
    # Must NOT match ternary expressions like `x = "A" if cond else "B"`
    m = re.match(r'^(if\b.+?|elif\b.+?|else\b|for\b.+?|while\b.+?|def\b.+?|class\b.+?|try\b|except\b.*?|finally\b)\s*:\s*(\S.+)$', stripped)
    if m:
        header = m.group(1).rstrip()
        body = m.group(2).strip()
        # Make sure this isn't inside a dict literal or slice
        colon_pos = len(m.group(1))
        if not is_in_dict_or_slice(stripped, colon_pos):
            return [indent + header + ":" + line_ending, indent + "    " + body + line_ending]

    return [line]


def split_on_semicolons(s):
    """Split a string on semicolons that are not inside string literals."""
    parts = []
    current = []
    in_string = None
    i = 0
    while i < len(s):
        c = s[i]
        if in_string:
            current.append(c)
            if c == in_string and (i == 0 or s[i-1] != '\\'):
                in_string = None
        elif c in ('"', "'"):
            # Check for triple quotes
            if s[i:i+3] in ('"""', "'''"):
                triple = s[i:i+3]
                current.append(s[i:i+3])
                i += 3
                while i < len(s):
                    current.append(s[i])
                    if s[i:i+3] == triple:
                        current.append(s[i+1:i+3])
                        i += 3
                        break
                    i += 1
                continue
            else:
                in_string = c
                current.append(c)
        elif c == ';':
            parts.append(''.join(current).strip())
            current = []
        else:
            current.append(c)
        i += 1
    if current:
        parts.append(''.join(current).strip())
    return parts


def is_in_dict_or_slice(s, colon_pos):
    """Check if a colon at position is inside a dict literal or slice (braces/brackets)."""
    depth = 0
    for i in range(colon_pos):
        if s[i] in '([{':
            depth += 1
        elif s[i] in ')]}':
            depth -= 1
    return depth > 0


def fix_file(filepath):
    with open(filepath) as f:
        lines = f.readlines()

    new_lines = []
    for line in lines:
        fixed = fix_line(line)
        new_lines.extend(fixed)

    with open(filepath, 'w') as f:
        f.writelines(new_lines)

    print(f"Fixed {filepath}: {len(lines)} -> {len(new_lines)} lines")


if __name__ == '__main__':
    for fp in sys.argv[1:]:
        fix_file(fp)
