# -*- coding: utf-8 -*-
# 設計仕様書 Markdown 内の mermaid ブロックを抽出し、Mermaid CLI で PNG 化する
import re, subprocess, sys, os, json
sys.stdout.reconfigure(encoding='utf-8')

MD = r'C:\Users\m-oya\Desktop\GUapp\docs\03_設計仕様書\GU_ECsite_設計仕様書_P1_draft-v2.md'
OUT = os.path.dirname(os.path.abspath(__file__))

text = open(MD, encoding='utf-8').read()
blocks = re.findall(r'```mermaid\n(.*?)```', text, flags=re.S)
print('mermaid blocks:', len(blocks))

# 日本語フォントを効かせる設定
cfg = {"theme": "default", "themeVariables": {"fontFamily": "Meiryo, 'Noto Sans JP', sans-serif", "fontSize": "14px"}}
cfg_path = os.path.join(OUT, 'mmd-config.json')
json.dump(cfg, open(cfg_path, 'w', encoding='utf-8'))

for i, src in enumerate(blocks, start=1):
    mmd = os.path.join(OUT, f'diagram_{i}.mmd')
    png = os.path.join(OUT, f'diagram_{i}.png')
    open(mmd, 'w', encoding='utf-8').write(src)
    cmd = ['npx', '-y', '@mermaid-js/mermaid-cli', '-i', mmd, '-o', png, '-c', cfg_path, '-s', '2', '-b', 'white', '-w', '1400']
    r = subprocess.run(cmd, capture_output=True, text=True, shell=True, cwd=OUT)
    ok = os.path.exists(png)
    print(f'[{i}] {"OK" if ok else "FAIL"} {src.strip().splitlines()[0][:40]}  size={os.path.getsize(png) if ok else 0}')
    if not ok:
        print(r.stdout[-800:], r.stderr[-1200:])
