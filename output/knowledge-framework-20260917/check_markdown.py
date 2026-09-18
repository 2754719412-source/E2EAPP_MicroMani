from pathlib import Path
import json
import re

root = Path(__file__).resolve().parents[2]
reports = []
for name in ('平台架构与全栈知识学习框架.md', '平台源码知识索引.md'):
    path = root / 'docs' / name
    if not path.exists():
        reports.append({'file': name, 'pending': True})
        continue
    text = path.read_text(encoding='utf-8')
    targets = re.findall(r'\]\((?:<([^>]+)>|([^\s)]+))\)', text)
    missing = []
    local_links = 0
    for pair in targets:
        target = pair[0] or pair[1]
        if target.startswith('#'):
            anchor = target[1:]
            if not re.search(rf'<a id="{re.escape(anchor)}"', text):
                missing.append(target)
        elif re.match(r'^[A-Za-z]:[/\\]', target):
            local_links += 1
            target_path = re.sub(r':\d+$', '', target.split('#')[0])
            if not Path(target_path).exists():
                missing.append(target)
    fences = [line for line in text.splitlines() if line.startswith('```')]
    leftovers = [term for term in ('供整合者', '根代理', '子代理', '整合时仍需', '待根代理') if term in text]
    table_errors = []
    in_fence = False
    expected_columns = None
    for number, line in enumerate(text.splitlines(), 1):
        if line.startswith('```'):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if line.startswith('|'):
            columns = len(re.split(r'(?<!\\)\|', line)) - 2
            if expected_columns is None:
                expected_columns = columns
            elif columns != expected_columns:
                table_errors.append({'line': number, 'expected': expected_columns, 'actual': columns})
        else:
            expected_columns = None
    reports.append({
        'file': name, 'lines': len(text.splitlines()), 'characters': len(text),
        'local_links': local_links, 'missing_links': sorted(set(missing)),
        'balanced_fences': len(fences) % 2 == 0,
        'handoff_leftovers': leftovers,
        'table_column_errors': table_errors,
        'mermaid_diagrams': text.count('```mermaid'),
    })
print(json.dumps(reports, ensure_ascii=True, indent=2))
if any(r.get('missing_links') or r.get('handoff_leftovers') or r.get('table_column_errors') or r.get('balanced_fences') is False for r in reports):
    raise SystemExit(1)
