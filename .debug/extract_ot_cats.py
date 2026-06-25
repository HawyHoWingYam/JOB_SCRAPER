#!/usr/bin/env python3
"""Extract offertoday categories by code and save as JSON."""
import json, sys

sys.stdout.reconfigure(encoding='utf-8')

# Read the fetch result (it's a JSON response body)
with open('.debug/offertoday-filter-via-fetch.json', 'r', encoding='utf-8') as f:
    content = f.read().strip()
    # The file may contain the JSON body directly (a string)
    # or could be already parsed. Try to parse and if it's a string in a string,
    # parse again.
    data = json.loads(content)
    if isinstance(data, str):
        data = json.loads(data)
d = data.get('data', {})
tc_data = d.get('tc', {})
en_data = d.get('en', {})

pos_tc = tc_data.get('POSITION', {})
pos_en = en_data.get('POSITION', {})

result = []
for i, child_tc in enumerate(pos_tc.get('children', [])):
    code = child_tc['code']
    name_tc = child_tc['name']
    name_en = pos_en['children'][i]['name'] if i < len(pos_en.get('children', [])) else ''
    result.append({'code': code, 'name_tc': name_tc, 'name_en': name_en})

with open('.debug/ot_categories.json', 'w', encoding='utf-8') as out:
    json.dump(result, out, ensure_ascii=False, indent=2)

# Write a summary log too
with open('.debug/ot_categories_summary.txt', 'w', encoding='utf-8') as out:
    out.write(f'Extracted {len(result)} categories\n')
    for c in result:
        out.write(f"  {c['code']}: {c['name_tc']} ({c['name_en']})\n")
