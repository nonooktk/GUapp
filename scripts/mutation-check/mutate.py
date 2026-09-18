"""防御外し確認（テスト設計書 1.4 #8）の文字列置換ヘルパー。run.ps1 から呼ぶ。

    python mutate.py --cases cases.json --root <repo> --case 1 --mode check   # 置換元が 1 回ずつあるか
    python mutate.py --cases cases.json --root <repo> --case 1 --mode apply   # 防御を外す（上書き）

- 置換元 `old` がちょうど 1 回見つからなければ何も書かず exit 2（中止して報告）
- 改行は元ファイルのまま保つ（newline="" で読み書き。old が LF で書かれていて
  ファイルが CRLF なら CRLF 版で探す）
- 復元はこのスクリプトでは行わない（run.ps1 がバックアップからコピーで戻す）
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _load_cases(cases_path: Path) -> list[dict]:
    with cases_path.open(encoding="utf-8") as f:
        return json.load(f)["cases"]


def _select(cases: list[dict], case: str) -> list[dict]:
    if case == "all":
        return cases
    picked = [c for c in cases if str(c["id"]) == case]
    if not picked:
        raise SystemExit(f"ケース {case!r} が cases.json にありません")
    return picked


def _find(content: str, old: str) -> tuple[str, int]:
    """old（LF 表記）を、必要なら CRLF 表記に直して数える。(実際に使う old, 出現回数)。"""
    n = content.count(old)
    if n == 0 and "\n" in old and "\r\n" in content:
        crlf = old.replace("\n", "\r\n")
        return crlf, content.count(crlf)
    return old, n


def run(cases_path: Path, root: Path, case: str, mode: str) -> int:
    problems: list[str] = []
    planned: list[tuple[Path, str, str, str]] = []
    for c in _select(_load_cases(cases_path), case):
        for spec in c["files"]:
            path = root / spec["path"]
            if not path.is_file():
                problems.append(f"[case {c['id']}] ファイルが無い: {path}")
                continue
            content = path.read_text(encoding="utf-8", newline="")
            old, n = _find(content, spec["old"])
            if n != 1:
                problems.append(
                    f"[case {c['id']}] {spec['path']}: 置換元が {n} 回（1 回でなければ中止）: {spec['old']!r}"
                )
                continue
            planned.append((path, content, old, spec["new"]))
    if problems:
        for p in problems:
            print("NG " + p)
        return 2
    for path, content, old, new in planned:
        print(f"OK {path.relative_to(root)}: 置換元 1 回")
        if mode == "apply":
            path.write_text(content.replace(old, new, 1), encoding="utf-8", newline="")
            print(f"   -> 防御を外しました: {old.strip()!r} => {new.strip()!r}")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cases", required=True, type=Path)
    ap.add_argument("--root", required=True, type=Path, help="リポジトリ（worktree）のルート")
    ap.add_argument("--case", required=True, help="1 / 2 / 3 / all")
    ap.add_argument("--mode", required=True, choices=["check", "apply"])
    args = ap.parse_args()
    sys.exit(run(args.cases, args.root.resolve(), args.case, args.mode))


if __name__ == "__main__":
    main()
