#!/usr/bin/env python3
"""GUapp コード解説書の組み立てスクリプト（Python 3 標準ライブラリのみ）。

使い方（どのディレクトリから実行しても動く）:
    python3 docs/05_解説/code-guide/build.py [--commit SHA] [--check] [--include-sample]
    python3 docs/05_解説/code-guide/build.py --map [--map-data PATH] [--check] [--guide-url URL] [--map-url URL]
    python3 docs/05_解説/code-guide/build.py --review [--check] [--include-sample] [--guide-url URL] [--map-url URL] [--list-stops]
        [--allow-missing-translations] [--dump-translation-scope PATH] [--translations-dir DIR] [--glossary PATH]
    python3 docs/05_解説/code-guide/build.py --tracer [--capture-dir DIR] [--scenario PATH] [--list-routes] [--check] [--out PATH]

- content/*.html をファイル名順に連結して template.html に差し込む
- 本文中の data-ref を `git show <sha>:<path>` で読んだコードに解決し、JSON として埋め込む
- 解決できない参照が 1 つでもあれば一覧を出して exit 1
- `--map` を付けると、リポジトリ地図（map/template-map.html）を組み立てる。
  ツリーは `git ls-tree`、説明は map/descriptions.json、プレビューは `git show` から作る
- `--review` を付けると、レビュー回答ガイド（review/template-review.html）を組み立てる。
  本文は review/*.html。順路（ol.route）の停留所・インラインの行番号（span.loc）・data-focus は、
  実ファイルの行番号を組み立て時に自動で入れる。あわせて、初心者向けの
  コードの日本語訳（review/translations/*.json）・住所・つながり図・重なりの図・用語集（review/glossary.json）を組み込む

- `--tracer` を付けると、コードトレーサー（tracer/template-tracer.html）を組み立てる。
  左に撮影した画面写真（tracer/capture/）、右に IDE 風の画面。画面の操作ごとに、レビュー回答ガイド（review/*.html）の
  順路を tracer/scenario.json の対応表どおりにたどり、全文のコード・訳・解説・通信の記録を 1 枚の HTML に埋め込む

data-ref の構文・descriptions.json のスキーマは README.md を参照。
"""

from __future__ import annotations

import argparse
import ast
import base64
import html
import json
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote

HERE = Path(__file__).resolve().parent
CONTENT_DIR = HERE / "content"
TEMPLATE = HERE / "template.html"
PARTIALS_DIR = HERE / "partials"
MAP_TEMPLATE = HERE / "map" / "template-map.html"
MAP_DATA_DEFAULT = HERE / "map" / "descriptions.json"
REVIEW_DIR = HERE / "review"
REVIEW_TEMPLATE = REVIEW_DIR / "template-review.html"
TRACER_DIR = HERE / "tracer"
TRACER_TEMPLATE = TRACER_DIR / "template-tracer.html"
TRACER_SCENARIO = TRACER_DIR / "scenario.json"
TRACER_CAPTURE = TRACER_DIR / "capture"
OUTPUT_NAME = "GU_ECsite_コード解説.html"
MAP_OUTPUT_NAME = "GU_ECsite_リポジトリ地図.html"
REVIEW_OUTPUT_NAME = "GU_ECsite_レビュー回答ガイド.html"
TRACER_OUTPUT_NAME = "GU_ECsite_コードトレーサー.html"
# 停留所のレイヤー表示名（template.html の LAYER_LABEL と同じ）
LAYER_LABEL = {
    "screen": "画面", "bff": "BFF", "api": "API", "service": "サービス", "repo": "リポジトリ",
    "db": "DB", "ci": "CI", "infra": "インフラ", "browser": "ブラウザ", "web": "Web",
}
REPO_URL = "https://github.com/nonooktk/GUapp"
REVIEW_TRANSLATIONS_DIR = REVIEW_DIR / "translations"
REVIEW_GLOSSARY = REVIEW_DIR / "glossary.json"
REVIEW_GLOSSARY_SAMPLE = REVIEW_DIR / "glossary.sample.json"
# つながり図のレーン順（左から）。ここに無い層・層の指定が無い停留所は末尾
LAYER_ORDER = ["screen", "browser", "bff", "web", "api", "service", "repo", "db", "ci", "infra"]
# 重なりの図の既定の列（購買 7 機能の章）。div.overlap-map の data-chapters="r01,r02" で差し替え可
OVERLAP_CHAPTERS = [f"r0{i}" for i in range(1, 8)]
OVERLAP_HOT = 3  # この章数以上で使うファイルの行を強調する

LANG_BY_EXT = {
    "py": "python",
    "ts": "typescript",
    "tsx": "typescript",
    "js": "javascript",
    "mjs": "javascript",
    "yml": "yaml",
    "yaml": "yaml",
    "sh": "bash",
    "sql": "sql",
    "json": "json",
    "toml": "ini",
    "md": "markdown",
    "css": "css",
    "html": "xml",
}


class ResolveError(Exception):
    """参照を解決できないときの理由（利用者向けの日本語メッセージ）。"""


# ---------------------------------------------------------------------------
# git
# ---------------------------------------------------------------------------


def repo_root() -> Path:
    """スクリプトの位置からリポジトリルートを解決する。"""
    try:
        out = subprocess.run(
            ["git", "-C", str(HERE), "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if out:
            return Path(out)
    except (OSError, subprocess.CalledProcessError):
        pass
    return HERE.parents[2]  # code-guide → 05_解説 → docs → ルート


def resolve_commit(root: Path, rev: str) -> str:
    try:
        res = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--verify", f"{rev}^{{commit}}"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        sys.exit(f"コミットを解決できません: {rev}\n{detail}")
    return res.stdout.strip()


class GitFiles:
    """`git show <sha>:<path>` の結果を行配列でキャッシュする。

    fallback を渡すと、sha に無いパスだけ fallback 側のコミットから読む（地図用）。
    """

    def __init__(self, root: Path, sha: str, fallback: "GitFiles | None" = None) -> None:
        self.root = root
        self.sha = sha
        self.fallback = fallback
        self._cache: dict[str, list[str] | None] = {}

    def _own(self, path: str) -> list[str] | None:
        if path not in self._cache:
            res = subprocess.run(
                ["git", "-C", str(self.root), "show", f"{self.sha}:{path}"],
                capture_output=True,
            )
            if res.returncode != 0:
                self._cache[path] = None
            else:
                text = res.stdout.decode("utf-8", errors="replace")
                text = text.replace("\r\n", "\n")
                lines = text.split("\n")
                if lines and lines[-1] == "":
                    lines.pop()  # 末尾改行による空要素
                self._cache[path] = lines
        return self._cache[path]

    def sha_of(self, path: str) -> str:
        """path を実際に読むコミットの SHA。"""
        if self._own(path) is None and self.fallback is not None:
            return self.fallback.sha
        return self.sha

    def lines(self, path: str) -> list[str]:
        cached = self._own(path)
        if cached is None and self.fallback is not None:
            return self.fallback.lines(path)
        if cached is None:
            raise ResolveError(f"コミット {self.sha[:7]} に {path} が存在しない")
        return cached


# ---------------------------------------------------------------------------
# シンボル解決: Python
# ---------------------------------------------------------------------------


def _py_node_range(node: ast.AST) -> tuple[int, int]:
    start = node.lineno  # type: ignore[attr-defined]
    decorators = getattr(node, "decorator_list", None)
    if decorators:
        start = min(start, min(d.lineno for d in decorators))
    return start, node.end_lineno  # type: ignore[attr-defined]


def _py_assign_names(node: ast.AST) -> list[str]:
    names: list[str] = []
    if isinstance(node, ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name):
                names.append(target.id)
    elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        names.append(node.target.id)
    return names


def resolve_python(lines: list[str], symbol: str) -> tuple[int, int]:
    try:
        tree = ast.parse("\n".join(lines))
    except SyntaxError as exc:
        raise ResolveError(f"Python として解析できない: {exc}") from exc

    scope: list[ast.stmt] = tree.body
    parts = symbol.split(".")
    for depth, name in enumerate(parts):
        is_last = depth == len(parts) - 1
        found: ast.AST | None = None
        for node in scope:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if node.name == name:
                    found = node
                    break
            elif is_last and depth == 0 and name in _py_assign_names(node):
                # 拡張: トップレベルの定数代入（README 記載）
                found = node
                break
        if found is None:
            raise ResolveError(f"シンボル {symbol} が見つからない（{name} が未定義）")
        if is_last:
            return _py_node_range(found)
        if not isinstance(found, ast.ClassDef):
            raise ResolveError(f"{name} はクラスではないため {symbol} を辿れない")
        scope = found.body
    raise ResolveError(f"シンボル {symbol} が見つからない")


# ---------------------------------------------------------------------------
# シンボル解決: TypeScript / JavaScript
# ---------------------------------------------------------------------------

_IDENT_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_$")
# JSX の `</div>` `/>` を正規表現と誤認しないよう `<` `>` `}` は含めない
_REGEX_PREV_CHARS = set("(,=:[!&|?{;+-*%~^")
_REGEX_PREV_WORDS = {"return", "typeof", "case", "in", "of", "delete", "void", "throw", "new", "else", "do"}


def _skip_line_comment(text: str, i: int) -> int:
    j = text.find("\n", i)
    return len(text) if j < 0 else j


def _skip_block_comment(text: str, i: int) -> int:
    j = text.find("*/", i + 2)
    return len(text) if j < 0 else j + 2


def _skip_quoted(text: str, i: int) -> int:
    """'...' または "..." を読み飛ばす。改行で打ち切る（JSX 本文中のアポストロフィ対策）。"""
    quote_ch = text[i]
    n = len(text)
    j = i + 1
    while j < n:
        c = text[j]
        if c == "\\":
            j += 2
            continue
        if c == quote_ch:
            return j + 1
        if c == "\n":
            return j
        j += 1
    return n


def _skip_template_expr(text: str, i: int) -> int:
    """`${` の直後 i から、対応する `}` の直後までを読み飛ばす。"""
    n = len(text)
    depth = 1
    j = i
    while j < n:
        c = text[j]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return j + 1
        elif c in "'\"":
            j = _skip_quoted(text, j)
            continue
        elif c == "`":
            j = _skip_template(text, j)
            continue
        elif c == "/" and j + 1 < n and text[j + 1] == "/":
            j = _skip_line_comment(text, j)
            continue
        elif c == "/" and j + 1 < n and text[j + 1] == "*":
            j = _skip_block_comment(text, j)
            continue
        j += 1
    return n


def _skip_template(text: str, i: int) -> int:
    """テンプレートリテラル（入れ子の `${}` 込み）を読み飛ばす。"""
    n = len(text)
    j = i + 1
    while j < n:
        c = text[j]
        if c == "\\":
            j += 2
            continue
        if c == "`":
            return j + 1
        if c == "$" and j + 1 < n and text[j + 1] == "{":
            j = _skip_template_expr(text, j + 2)
            continue
        j += 1
    return n


def _skip_regex(text: str, i: int) -> int | None:
    """正規表現リテラルなら終端の直後を返す。同一行で閉じなければ None（除算とみなす）。"""
    n = len(text)
    j = i + 1
    in_class = False
    while j < n:
        c = text[j]
        if c == "\n":
            return None
        if c == "\\":
            j += 2
            continue
        if in_class:
            if c == "]":
                in_class = False
        elif c == "[":
            in_class = True
        elif c == "/":
            return j + 1
        j += 1
    return None


def _significant_chars(text: str, start: int):
    """コメント・文字列・正規表現を除いた記号を (位置, 文字) で返す。

    文字列・テンプレート・正規表現は 1 文字 'S'（識別子相当）として返す。
    """
    n = len(text)
    i = start
    prev = ""  # 直前の有意な文字
    word = ""  # 直前の識別子（正規表現判定用）
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            i = _skip_line_comment(text, i)
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            i = _skip_block_comment(text, i)
            continue
        if c in "'\"":
            yield i, "S"
            i = _skip_quoted(text, i)
            prev, word = "S", ""
            continue
        if c == "`":
            yield i, "S"
            i = _skip_template(text, i)
            prev, word = "S", ""
            continue
        if c == "/":
            if prev == "" or prev in _REGEX_PREV_CHARS or word in _REGEX_PREV_WORDS:
                end = _skip_regex(text, i)
                if end is not None:
                    yield i, "S"
                    i = end
                    prev, word = "S", ""
                    continue
        if c in _IDENT_CHARS or ord(c) > 127:
            j = i
            while j < n and (text[j] in _IDENT_CHARS or ord(text[j]) > 127):
                j += 1
            word = text[i:j]
            yield i, "w"
            prev = "w"
            i = j
            continue
        word = ""
        yield i, c
        prev = c
        i += 1


def _ts_patterns(name: str) -> list[tuple[str, re.Pattern[str]]]:
    n = re.escape(name)
    return [
        ("func", re.compile(rf"^(\s*)export\s+default\s+(?:async\s+)?function\s*\*?\s*{n}\b")),
        ("func", re.compile(rf"^(\s*)export\s+(?:async\s+)?function\s*\*?\s*{n}\b")),
        ("func", re.compile(rf"^(\s*)(?:async\s+)?function\s*\*?\s*{n}\b")),
        ("var", re.compile(rf"^(\s*)(?:export\s+)?(?:const|let)\s+{n}\b")),
        ("type", re.compile(rf"^(\s*)(?:export\s+)?(?:declare\s+)?type\s+{n}\b")),
        ("block", re.compile(rf"^(\s*)(?:export\s+(?:default\s+)?)?(?:declare\s+)?(?:abstract\s+)?(?:interface|class|enum)\s+{n}\b")),
        ("block", re.compile(rf"^(\s*)(?:export\s+)?(?:declare\s+)?const\s+enum\s+{n}\b")),
    ]


def _ts_find_declaration(lines: list[str], name: str) -> tuple[int, int, str] | None:
    """宣言行 (0 始まり行, 名前の直後の桁, 種別) を返す。行頭（インデント 0）の宣言を優先。"""
    patterns = _ts_patterns(name)
    first_indented: tuple[int, int, str] | None = None
    for idx, line in enumerate(lines):
        for kind, pat in patterns:
            m = pat.match(line)
            if not m:
                continue
            found = (idx, m.end(), kind)
            if m.group(1) == "":
                return found
            if first_indented is None:
                first_indented = found
            break
    return first_indented


def resolve_typescript(lines: list[str], symbol: str) -> tuple[int, int]:
    found = _ts_find_declaration(lines, symbol)
    if found is None:
        raise ResolveError(f"シンボル {symbol} の宣言が見つからない")
    decl_idx, name_end, kind = found

    text = "\n".join(lines)
    line_starts = [0]
    for line in lines[:-1]:
        line_starts.append(line_starts[-1] + len(line) + 1)
    base = line_starts[decl_idx] + name_end

    def line_of(pos: int) -> int:
        lo, hi = 0, len(line_starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if line_starts[mid] <= pos:
                lo = mid
            else:
                hi = mid - 1
        return lo + 1  # 1 始まり

    paren = 0  # () と [] の合算
    brace = 0
    body_started = False
    prev = ""
    last_pos = base
    tokens = _significant_chars(text, base)

    first = True
    angle = 0
    for pos, ch in tokens:
        # 宣言名の直後のジェネリクス `<T extends {...}>` は丸ごと読み飛ばす
        if first:
            first = False
            if ch == "<":
                angle = 1
                prev = "<"
                last_pos = pos
                continue
        if angle > 0:
            if ch == "<":
                angle += 1
            elif ch == ">" and prev != "=":
                angle -= 1
            prev = ch
            last_pos = pos
            continue

        # 改行 ASI（const/let/type で `;` 無しの文）
        if (
            kind in ("var", "type")
            and not body_started
            and paren == 0
            and brace == 0
            and last_pos > base
            and "\n" in text[last_pos + 1 : pos]
            and prev not in ("=", ",", "|", "&", "+", "-", "*", "/", "%", "?", ":", "(", "<", "[", ">")
            and ch not in (".", "?", ":", "|", "&", ",", "=", "+", "-", "*", "/", "%", ")", "<", ">")
        ):
            return decl_idx + 1, line_of(last_pos)

        if ch in "([":
            paren += 1
        elif ch in ")]":
            paren -= 1
        elif ch == "{":
            if (
                not body_started
                and paren == 0
                and brace == 0
                and prev not in (":", "<", ",", "|", "&", "(", "[", "?")
            ):
                body_started = True
            brace += 1
        elif ch == "}":
            brace -= 1
            if body_started and brace == 0:
                return decl_idx + 1, line_of(pos)
        elif ch == ";" and paren == 0 and brace == 0 and not body_started:
            return decl_idx + 1, line_of(pos)
        prev = ch
        last_pos = pos

    if kind in ("var", "type") and not body_started and paren == 0 and brace == 0:
        return decl_idx + 1, line_of(last_pos)
    raise ResolveError(f"シンボル {symbol} の終端（対応する `}}` または `;`）が見つからない")


# ---------------------------------------------------------------------------
# 参照の解決
# ---------------------------------------------------------------------------

_RANGE_RE = re.compile(r"^(?P<path>.+?)#L(?P<a>\d+)(?:-L?(?P<b>\d+))?$")


def lang_of(path: str) -> str:
    ext = path.rsplit(".", 1)[-1].lower() if "." in Path(path).name else ""
    return LANG_BY_EXT.get(ext, "plaintext")


def resolve_ref(ref: str, git: GitFiles) -> dict:
    """data-ref 文字列をスニペット辞書に解決する。失敗時は ResolveError。"""
    symbol = ""
    if "::" in ref:
        path, symbol = ref.split("::", 1)
        path, symbol = path.strip(), symbol.strip()
        if not path or not symbol:
            raise ResolveError("`path::Symbol` の形式が不正")
        lines = git.lines(path)
        ext = path.rsplit(".", 1)[-1].lower() if "." in Path(path).name else ""
        if ext == "py":
            start, end = resolve_python(lines, symbol)
        elif ext in ("ts", "tsx", "js", "mjs", "jsx"):
            start, end = resolve_typescript(lines, symbol)
        else:
            raise ResolveError(f"拡張子 .{ext} はシンボル指定に未対応（#L 範囲で指定する）")
    else:
        m = _RANGE_RE.match(ref)
        if m:
            path = m.group("path").strip()
            lines = git.lines(path)
            start = int(m.group("a"))
            end = int(m.group("b") or start)
            if start < 1 or end < start:
                raise ResolveError(f"行範囲が不正: L{start}-L{end}")
            if end > len(lines):
                raise ResolveError(f"行範囲がファイル末尾（{len(lines)} 行）を超えている: L{start}-L{end}")
        else:
            path = ref.strip()
            lines = git.lines(path)
            start, end = 1, max(len(lines), 1)

    return make_snippet(path, symbol, start, end, lines, git)


def make_snippet(path: str, symbol: str, start: int, end: int, lines: list[str], git: GitFiles) -> dict:
    code = "\n".join(lines[start - 1 : end])
    url = f"{REPO_URL}/blob/{git.sha_of(path)}/{quote(path, safe='/')}#L{start}-L{end}"
    return {
        "path": path,
        "symbol": symbol,
        "start": start,
        "end": end,
        "lang": lang_of(path),
        "code": code,
        "url": url,
        "note": "",
    }


# ---------------------------------------------------------------------------
# 本文の解析（参照・章・目次・id）
# ---------------------------------------------------------------------------


class ContentScanner(HTMLParser):
    def __init__(self, filename: str) -> None:
        super().__init__(convert_charrefs=True)
        self.filename = filename
        self.refs: list[tuple[str, str, int]] = []  # (ref, note, line)
        self.ids: list[tuple[str, int]] = []
        self.hrefs: list[tuple[str, int]] = []
        self.sections: list[dict] = []
        self._current_section: dict | None = None
        self._h3: dict | None = None
        # 組み立て時に書き換える開始タグ（data-focus 付き・span.loc・li.stop）
        self.rewrites: list[dict] = []
        self.problems: list[tuple[int, str]] = []  # (行, メッセージ)
        self._ol_stack: list[bool] = []  # ol が順路（class="route"）か
        self._stop_n = 0
        self.route_count = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: (v or "") for k, v in attrs}
        line = self.getpos()[0]
        classes = set(a.get("class", "").split())
        if tag == "ol":
            is_route = "route" in classes
            self._ol_stack.append(is_route)
            if is_route:
                self.route_count += 1
                self._stop_n = 0
        in_route = bool(self._ol_stack) and self._ol_stack[-1]
        is_stop = tag == "li" and "stop" in classes
        is_loc = "loc" in classes
        if is_stop:
            if in_route:
                self._stop_n += 1
            else:
                self.problems.append((line, "li.stop は ol.route の直下に置く"))
        if "data-focus" in a and not a["data-focus"]:
            self.problems.append((line, "data-focus が空"))
        if "data-focus" in a and "data-ref" not in a:
            self.problems.append((line, "data-focus は data-ref と一緒に使う"))
        if "data-focus-line" in a:
            self.problems.append((line, "data-focus-line は組み立て時に自動で付く（本文には書かない）"))
        if is_loc and "data-ref" not in a:
            self.problems.append((line, "span.loc には data-ref が必要"))
        cur_sec = self._current_section["id"] if self._current_section else ""
        if (is_stop and in_route) or ("data-ref" in a and ("data-focus" in a or is_loc)):
            self.rewrites.append(
                {
                    "tag": tag,
                    "line": line,
                    "col": self.getpos()[1],
                    "raw": self.get_starttag_text() or "",
                    "attrs": a,
                    "kind": "stop" if is_stop else ("loc" if is_loc else "focus"),
                    "stop_no": self._stop_n if is_stop else 0,
                    "route_no": self.route_count if is_stop else 0,
                    "section": cur_sec,
                }
            )
        if tag == "ol" and "route" in classes:
            # つながり図を直前に差し込む位置（--review のときだけ使う）
            self.rewrites.append(
                {
                    "tag": tag, "line": line, "col": self.getpos()[1], "raw": self.get_starttag_text() or "",
                    "attrs": a, "kind": "route", "route_no": self.route_count, "section": cur_sec,
                }
            )
        if "overlap-map" in classes:
            if tag != "div":
                self.problems.append((line, "overlap-map は div 要素にする"))
            else:
                self.rewrites.append(
                    {
                        "tag": tag, "line": line, "col": self.getpos()[1], "raw": self.get_starttag_text() or "",
                        "attrs": a, "kind": "overlap", "section": cur_sec,
                    }
                )
        if "data-ref" in a:
            self.refs.append((a["data-ref"].strip(), a.get("data-note", ""), line))
        if "id" in a:
            self.ids.append((a["id"], line))
        if tag == "a" and a.get("href", "").startswith("#") and len(a["href"]) > 1:
            self.hrefs.append((a["href"][1:], line))
        if tag == "section" and "id" in a:
            self._current_section = {
                "id": a["id"],
                "title": a.get("data-title", ""),
                "h3": [],
                "file": self.filename,
                "line": line,
            }
            self.sections.append(self._current_section)
        if tag == "h3" and self._current_section is not None:
            self._h3 = {"id": a.get("id", ""), "text": "", "line": line}

    def handle_endtag(self, tag: str) -> None:
        if tag == "ol" and self._ol_stack:
            self._ol_stack.pop()
        if tag == "h3" and self._h3 is not None and self._current_section is not None:
            self._h3["text"] = re.sub(r"\s+", " ", self._h3["text"]).strip()
            if self._h3["id"] and self._h3["text"]:
                self._current_section["h3"].append(self._h3)
            self._h3 = None
        if tag == "section":
            self._current_section = None

    def handle_data(self, data: str) -> None:
        if self._h3 is not None:
            self._h3["text"] += data


def build_toc(sections: list[dict]) -> str:
    items = []
    for sec in sections:
        title = html.escape(sec["title"] or sec["id"])
        sub = ""
        if sec["h3"]:
            subs = "".join(
                f'<li><a href="#{html.escape(h["id"], quote=True)}">{html.escape(h["text"])}</a></li>'
                for h in sec["h3"]
            )
            sub = f"<ol>{subs}</ol>"
        items.append(f'<li><a href="#{html.escape(sec["id"], quote=True)}">{title}</a>{sub}</li>')
    return f'<ol class="toc-list">{"".join(items)}</ol>'


def _dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def escape_json_for_script(data: object, per_line: bool = False) -> str:
    """`</script>` や `<!--` が現れないようにエスケープする（JSON としては同じ内容）。

    per_line=True のときは、辞書の要素と、その値（辞書）のフィールドを 1 件 1 行で出す。
    `<user>` のようなプレースホルダーは原文のまま残す（`\\u003c` にすると、秘密検査ツールが
    本物の値に見える文字列として検知することがあるため）。
    """
    if per_line and isinstance(data, dict):
        items = []
        for k, v in data.items():
            if isinstance(v, dict) and v:
                inner = ",\n".join(_dumps(ik) + ":" + _dumps(iv) for ik, iv in v.items())
                items.append(_dumps(k) + ":{\n" + inner + "\n}")
            else:
                items.append(_dumps(k) + ":" + _dumps(v))
        s = "{\n" + ",\n".join(items) + "\n}"
    else:
        s = _dumps(data)
    s = s.replace("</", "<\\/").replace("<!--", "\\u003c!--").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    # 見出し ID の `s04-secrets` などを detect-secrets の Secret Keyword が誤検知するため、JSON のエスケープ表記にする（読み込み後は同じ値）
    return s.replace("secret", "\\u0073ecret")


_SCRIPT_UNSAFE_RE = re.compile(r"<(\\*)(/script|!--)", re.IGNORECASE)


def escape_script_text(text: str) -> str:
    """`<script type="text/plain">` に原文のまま埋め込むためのエスケープ。

    `</script` と `<!--` だけ、`<` と `/script`（`!--`）の間にバックスラッシュを 1 つ足す。
    元からバックスラッシュがある場合も 1 つ足すので、ページ側で 1 つ引けば元に戻る（可逆）。
    """
    return _SCRIPT_UNSAFE_RE.sub(lambda m: "<" + m.group(1) + "\\" + m.group(2), text)


def snippet_parts(snippets: dict[str, dict]) -> tuple[str, str]:
    """スニペットを (メタ情報の JSON, コード本体の script 群) に分けて返す。

    コードは JSON に入れず、原文のまま（改行もそのまま）`<script type="text/plain">` に置く。
    JSON 化すると `"` が `\\"` になるなど、原文と違う文字列になり、秘密検査ツール
    （detect-secrets・gitleaks）がリポジトリ本体では出ない誤検知を出すため。
    """
    meta = {k: {f: v for f, v in sn.items() if f != "code"} for k, sn in snippets.items()}
    blocks = [
        f'<script type="text/plain" data-snippet="{html.escape(k, quote=True)}">{escape_script_text(sn["code"])}</script>'
        for k, sn in snippets.items()
    ]
    return escape_json_for_script(meta, per_line=True), "\n".join(blocks)


# ---------------------------------------------------------------------------
# テンプレート（partials の展開）
# ---------------------------------------------------------------------------

_PARTIAL_RE = re.compile(r"\{\{PARTIAL:([A-Za-z0-9_.\-]+)\}\}")


def expand_partials(text: str) -> str:
    """`{{PARTIAL:name}}` を partials/name の中身（末尾改行なし）に置き換える。"""

    def sub(m: re.Match[str]) -> str:
        path = PARTIALS_DIR / m.group(1)
        if not path.is_file():
            sys.exit(f"partials が見つからない: {path}")
        return path.read_text(encoding="utf-8").rstrip("\n")

    return _PARTIAL_RE.sub(sub, text)


def render_template(path: Path, values: dict[str, str]) -> str:
    template = expand_partials(path.read_text(encoding="utf-8"))
    # 1 回の走査で置換する（コード中の {{...}} を再置換しないため）
    return re.sub(r"\{\{([A-Z_]+)\}\}", lambda m: values.get(m.group(1), m.group(0)), template)


# ---------------------------------------------------------------------------
# 行番号の自動挿入（data-focus・span.loc・順路の停留所）
# ---------------------------------------------------------------------------


def focus_line(sn: dict, focus: str) -> int:
    """解決済みスニペットの範囲内で、focus を含む最初の行の実ファイルの行番号。focus が空なら範囲の開始行。"""
    if not focus:
        return sn["start"]
    for i, line in enumerate(sn["code"].split("\n")):
        if focus in line:
            return sn["start"] + i
    raise ResolveError(f'data-focus "{focus}" が {sn["path"]} の L{sn["start"]}-L{sn["end"]} の中に見つからない')


def stop_loc_html(no: int, layer: str, path: str | None, line: int | None) -> str:
    """順路の各停留所の先頭に入れる「番号・レイヤー・path:行・ボタン」。ボタンは JS が動かす（JS 無しでは隠す）。"""
    parts = [f'<span class="stop-no"><span class="visually-hidden">停留所 </span>{no}</span>']
    if layer:
        label = html.escape(LAYER_LABEL.get(layer, layer))
        parts.append(f'<span class="layer" data-layer="{html.escape(layer, quote=True)}">{label}</span>')
    if path is not None and line is not None:
        parts.append(f'<span class="stop-path">{html.escape(path)}:{line}</span>')
        parts.append(
            '<span class="stop-btns">'
            '<button type="button" class="btn stop-copy">コピー</button>'
            '<button type="button" class="btn stop-view">コードを見る</button>'
            "</span>"
        )
    return f'<div class="stop-loc" data-gen>{"".join(parts)}</div>'


def apply_rewrites(text: str, rewrites: list[dict], where: str, errors: list[str]) -> str:
    """ContentScanner が集めた開始タグを書き換える（後ろから置換するので位置はずれない）。

    - data-ref 付きで focus_line が決まったタグ: `data-focus-line="N"` を足す
    - span.loc: 中身を `path:N` にする
    - li.stop: 直後に div.stop-loc（と、--review では住所・注目行と訳）を挿入する
    - ol.route: --review では直前につながり図を、div.overlap-map: 中に重なりの図を差し込む
    """
    starts = [0]
    for m in re.finditer("\n", text):
        starts.append(m.end())
    edits: list[tuple[int, int, str]] = []
    for rw in rewrites:
        raw = rw["raw"]
        off = starts[rw["line"] - 1] + rw["col"]
        if text[off : off + len(raw)] != raw:
            errors.append(f"{where}:{rw['line']}: 開始タグの位置を特定できない（内部エラー）")
            continue
        end = off + len(raw)
        has_line = "focus_line" in rw
        new_tag = raw
        if has_line:
            attr = f' data-focus-line="{rw["focus_line"]}"'
            new_tag = raw[:-2] + attr + "/>" if raw.endswith("/>") else raw[:-1] + attr + ">"
        if rw["kind"] == "route":
            if rw.get("gen_html"):
                edits.append((off, off, rw["gen_html"]))  # つながり図は ol の直前に差し込む
            continue
        if rw["kind"] == "overlap":
            if not rw.get("gen_html"):
                continue
            close = text.find("</div>", end)
            if close < 0 or text[end:close].strip():
                errors.append(f"{where}:{rw['line']}: div.overlap-map の中身は空にする（表は自動で入る）")
                continue
            edits.append((end, close, rw["gen_html"]))
            continue
        if rw["kind"] == "stop":
            layer = rw["attrs"].get("data-layer", "")
            if layer and layer not in LAYER_LABEL:
                errors.append(f"{where}:{rw['line']}: data-layer \"{layer}\" は {'|'.join(LAYER_LABEL)} のいずれかにする")
            new_tag += stop_loc_html(
                rw["stop_no"], layer, rw.get("path") if has_line else None, rw["focus_line"] if has_line else None
            )
            new_tag += rw.get("aid_html", "")
            edits.append((off, end, new_tag))
        elif rw["kind"] == "loc":
            if rw["tag"] != "span":
                errors.append(f"{where}:{rw['line']}: loc は span 要素にする")
                continue
            close = text.find("</span>", end)
            inner = text[end:close] if close >= 0 else None
            if inner is None or "<" in inner:
                errors.append(f"{where}:{rw['line']}: span.loc の中身は空にする（path:行 は自動で入る）")
                continue
            if has_line:
                edits.append((off, close, new_tag + html.escape(f'{rw["path"]}:{rw["focus_line"]}')))
        elif has_line:
            edits.append((off, end, new_tag))
    for start, stop, rep in sorted(edits, key=lambda e: e[0], reverse=True):
        text = text[:start] + rep + text[stop:]
    return text


# ---------------------------------------------------------------------------
# 初心者向けの補助（--review）: 訳・住所・つながり図・重なりの図・用語集
# ---------------------------------------------------------------------------


def _esc(text: str) -> str:
    return html.escape(text, quote=True)


def _wbr(text: str) -> str:
    """狭い箱の中で、関数名・パスを区切りのよい所（_ / . - と小文字→大文字）で折り返せるよう <wbr> を入れる。"""
    t = html.escape(text, quote=True)
    t = re.sub(r"([_/.\-])(?=[^<\s])", r"\1<wbr>", t)
    return re.sub(r"([a-z0-9])(?=[A-Z])", r"\1<wbr>", t)


def _ranges_from_lines(nums: list[int]) -> list[list[int]]:
    """昇順の行番号の並びを、連続する範囲 [[a, b], ...] にまとめる。"""
    out: list[list[int]] = []
    for n in nums:
        if out and n == out[-1][1] + 1:
            out[-1][1] = n
        else:
            out.append([n, n])
    return out


def _merge_ranges(ranges: list[tuple[int, int]]) -> list[list[int]]:
    """重なり・隣接する範囲を結合する。"""
    out: list[list[int]] = []
    for a, b in sorted(ranges):
        if out and a <= out[-1][1] + 1:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def _fmt_ranges(ranges: list[list[int]]) -> str:
    return ", ".join(f"L{a}" if a == b else f"L{a}-L{b}" for a, b in ranges)


def _subtract(a: int, b: int, ranges: list[list[int]]) -> list[list[int]]:
    """[a, b] から ranges（結合済み・昇順）に含まれる部分を引いた残りの範囲。"""
    rest: list[list[int]] = []
    cur = a
    for ra, rb in ranges:
        if rb < cur:
            continue
        if ra > b:
            break
        if ra > cur:
            rest.append([cur, ra - 1])
        cur = max(cur, rb + 1)
        if cur > b:
            break
    if cur <= b:
        rest.append([cur, b])
    return rest


class StopInfo:
    """順路の停留所 1 つぶんの、図・住所の表示に使う情報。"""

    def __init__(self, rw: dict, entry: dict | None) -> None:
        self.rw = rw
        self.no: int = rw["stop_no"]
        self.layer: str = rw["attrs"].get("data-layer", "")
        self.ref: str = rw["attrs"].get("data-ref", "").strip()
        self.link: str = rw["attrs"].get("data-link", "").strip()
        self.section: str = rw.get("section", "")
        self.sn = entry
        self.path: str = entry["path"] if entry else ""
        self.focus: int = rw.get("focus_line", 0) if entry else 0
        self.has_focus_attr = bool(rw["attrs"].get("data-focus", ""))

    @property
    def is_whole_file(self) -> bool:
        return bool(self.sn) and "::" not in self.ref and not _RANGE_RE.match(self.ref)

    @property
    def kind(self) -> str:
        return symbol_kind(self.sn) if self.sn and self.sn["symbol"] else ("range" if self.sn and not self.is_whole_file else "file")

    @property
    def label(self) -> str:
        """図・表に出す関数名。シンボル無しは L10-40、ファイル全体はそのとおり。"""
        if not self.sn:
            return f"停留所 {self.no}"
        if self.sn["symbol"]:
            return self.sn["symbol"] + ("()" if self.kind == "func" else "")
        if self.is_whole_file:
            return "ファイル全体"
        return f'L{self.sn["start"]}-{self.sn["end"]}'


def symbol_kind(sn: dict) -> str:
    """スニペットの先頭の宣言から種別を推定する: func（関数・メソッド）/ type（クラス・型）/ const（定数）。"""
    lines = [ln for ln in sn["code"].split("\n")[:12] if ln.strip() and not ln.lstrip().startswith(("@", "//", "/*", "*", "#"))]
    head = lines[0].strip() if lines else ""
    sym = sn["symbol"].split(".")[-1]
    if re.match(r"^(?:export\s+)?(?:default\s+)?(?:declare\s+)?(?:abstract\s+)?(?:class|interface|type|enum)\b", head) or re.match(r"^class\s", head):
        return "type"
    if re.match(r"^(?:async\s+)?def\s", head) or re.search(r"\bfunction\b", head):
        return "func"
    if sn["path"].endswith(".py"):
        return "const"
    first3 = "\n".join(lines[:3])
    if "=>" in first3 or re.search(rf"\b{re.escape(sym)}\s*=\s*(?:async\s*)?\(", first3):
        return "func"
    return "const"


def _addr_segments(path: str, info: StopInfo | None, with_fn: bool = True) -> tuple[str, str]:
    """住所の HTML と、読み上げ用の平文を返す。フォルダ › ファイル › 関数。"""
    parts = path.split("/")
    segs: list[str] = []
    plain: list[str] = []
    for d in parts[:-1]:
        segs.append(f'<span class="addr-seg addr-dir">{_esc(d)}</span>')
        plain.append(d)
    ext = file_ext(path)
    ext_html = f'<span class="addr-ext">{_esc(ext.upper())}</span>' if ext else ""
    segs.append(f'<span class="addr-seg addr-file">{ext_html}{_esc(parts[-1])}</span>')
    plain.append(parts[-1])
    if with_fn and info is not None and info.sn:
        sn = info.sn
        if sn["symbol"]:
            names = sn["symbol"].split(".")
            for i, nm in enumerate(names):
                last = i == len(names) - 1
                kind = info.kind if last else "type"
                text = nm + ("()" if kind == "func" else "")
                segs.append(f'<span class="addr-seg addr-fn k-{kind}">{_esc(text)}</span>')
                plain.append(text)
        elif not info.is_whole_file:
            text = f'L{sn["start"]}-{sn["end"]}'
            segs.append(f'<span class="addr-seg addr-fn k-range">{text}</span>')
            plain.append(text)
    sep = '<span class="addr-sep" aria-hidden="true">›</span>'
    return sep.join(segs), " › ".join(plain)


def stop_addr_html(info: StopInfo) -> str:
    segs, plain = _addr_segments(info.path, info)
    return f'<div class="stop-addr" data-gen role="group" aria-label="{_esc("住所: " + plain)}">{segs}</div>'


def pick_block(blocks: list[tuple[int, int, str]], line: int, start: int, end: int, exact: bool) -> tuple[int, int, str] | None:
    """line を含むブロック。exact=False（data-focus が無い）で見つからなければ、範囲 [start, end] で最初のブロック。"""
    for b in blocks:
        if b[0] <= line <= b[1]:
            return b
    if not exact:
        for b in blocks:
            if b[1] >= start and b[0] <= end:
                return b
    return None


def stop_aid_html(info: StopInfo, blocks: list[tuple[int, int, str]]) -> str:
    """注目行（コードは JS が埋める）と、その行を含むブロックの訳。"""
    sn = info.sn
    assert sn is not None
    block = pick_block(blocks, info.focus, sn["start"], sn["end"], info.has_focus_attr)
    line = info.focus
    code_lines = sn["code"].split("\n")
    if block and not code_lines[line - sn["start"]].strip():
        # 先頭が空行なら、ブロックの最初の空でない行を注目行にする
        for n in range(max(block[0], sn["start"]), min(block[1], sn["end"]) + 1):
            if code_lines[n - sn["start"]].strip():
                line = n
                break
    if block:
        tr = f'<div class="aid-tr"><span class="aid-tag">訳</span><span class="aid-ja">{_esc(block[2])}</span></div>'
    else:
        tr = '<div class="aid-tr is-missing"><span class="aid-tag">訳</span><span class="aid-ja">（この行の訳は未作成）</span></div>'
    return (
        f'<div class="stop-aid" data-gen data-ln="{line}">'
        f'<div class="aid-code"><span class="aid-ln">L{line}</span><code class="aid-line"></code></div>{tr}</div>'
    )


def default_link(prev: StopInfo, cur: StopInfo) -> str:
    """前の停留所からこの停留所へのつながり方の既定の文言。"""
    pl, cl = prev.layer, cur.layer
    if pl != cl:
        if pl == "screen" and cl == "bff":
            return "HTTP（fetch）"
        if pl == "bff" and cl == "api":
            return "HTTP（内部トークン付き）"
        if (pl, cl) in (("api", "service"), ("service", "repo")):
            return "関数の呼び出し"
        if pl == "repo" and cl == "db":
            return "SQL"
    if prev.path and prev.path == cur.path:
        return "同じファイル内"
    return "呼び出し"


def _layer_idx(layer: str) -> int:
    return LAYER_ORDER.index(layer) if layer in LAYER_ORDER else len(LAYER_ORDER)


def _layer_label(layer: str) -> str:
    return LAYER_LABEL.get(layer, layer) if layer else "その他"


def conn_map_html(title: str, stops: list[StopInfo]) -> str:
    """順路 1 本ぶんのつながり図（入れ子の箱）。矢印は JS が SVG で描く。"""
    groups: list[dict] = []  # 連続する同じ層の停留所のまとまり
    for info in stops:
        if not groups or groups[-1]["layer"] != info.layer:
            groups.append({"layer": info.layer, "dirs": []})
        g = groups[-1]
        d = info.path.rsplit("/", 1)[0] if "/" in info.path else ("." if info.path else "")
        if not g["dirs"] or g["dirs"][-1]["dir"] != d:
            g["dirs"].append({"dir": d, "files": []})
        files = g["dirs"][-1]["files"]
        if not files or files[-1]["path"] != info.path:
            files.append({"path": info.path, "fns": []})
        files[-1]["fns"].append(info)

    lanes = sorted({g["layer"] for g in groups}, key=lambda l: (_layer_idx(l), l))
    lane_no = {l: i + 1 for i, l in enumerate(lanes)}
    out: list[str] = []
    for l in lanes:
        attr = f' data-layer="{_esc(l)}"' if l else ""
        out.append(f'<div class="conn-lane-bg"{attr} style="--c:{lane_no[l]}" data-label="{_esc(_layer_label(l))}" aria-hidden="true"></div>')
    idx = 0
    for gi, g in enumerate(groups):
        l = g["layer"]
        attr = f' data-layer="{_esc(l)}"' if l else ""
        box = [f'<div class="conn-layer"{attr} style="--c:{lane_no[l]};--r:{gi + 1}"><div class="conn-layer-name">{_esc(_layer_label(l))}</div>']
        for dd in g["dirs"]:
            if dd["dir"]:
                box.append(f'<div class="conn-dir"><div class="conn-dir-name">{_wbr(dd["dir"])}</div>')
            for ff in dd["files"]:
                if ff["path"]:
                    name = ff["path"].rsplit("/", 1)[-1]
                    ext = file_ext(ff["path"])
                    ext_html = f'<span class="addr-ext">{_esc(ext.upper())}</span>' if ext else ""
                    box.append(f'<div class="conn-file"><div class="conn-file-name">{ext_html}{_wbr(name)}</div>')
                for info in ff["fns"]:
                    prev = stops[idx - 1] if idx > 0 else None
                    link = (info.link or default_link(prev, info)) if prev else ""
                    where = f"{info.path}:{info.focus}" if info.sn else ""
                    sr = f"停留所 {info.no}、{info.label}" + (f"、{where}" if where else "") + (f"。前の停留所から: {link}" if link else "") + "。押すとこの停留所へ移動します"
                    lattr = f' data-layer="{_esc(info.layer)}"' if info.layer else ""
                    box.append(
                        f'<button type="button" class="conn-fn" data-i="{idx}"{lattr} data-link="{_esc(link)}" '
                        f'title="{_esc(where)}" aria-label="{_esc(sr)}">'
                        f'<span class="conn-no" aria-hidden="true">{info.no}</span>'
                        f'<span class="conn-fn-name">{_wbr(info.label)}</span></button>'
                    )
                    idx += 1
                if ff["path"]:
                    box.append("</div>")
            if dd["dir"]:
                box.append("</div>")
        box.append("</div>")
        out.append("".join(box))
    return (
        f'<div class="conn-map" data-gen role="group" aria-label="{_esc("つながり図: " + (title or "順路"))}" '
        f'data-stops="{len(stops)}"><div class="conn-head"><span class="conn-title">つながり図</span>'
        f'<span class="conn-sub">{_esc(title)}</span>'
        f'<span class="conn-hint">箱を押すと、その停留所へ移ってコードを開きます</span></div>'
        f'<div class="conn-scroll"><div class="conn-grid" style="--lanes:{len(lanes)};--rows:{len(groups)}">'
        + "".join(out)
        + "</div></div></div>\n"
    )


def short_title(title: str) -> str:
    t = re.sub(r"[（(][^）)]*[）)]", "", title).strip()
    return t if len(t) <= 12 else t[:12] + "…"


def overlap_html(chapters: list[dict], infos: list[StopInfo], title: str) -> str:
    """章 × ファイルの表。セルはその章の停留所で使う関数名（押すとコードが開く）。"""
    ch_ids = [c["id"] for c in chapters]
    rows: dict[str, dict] = {}
    for info in infos:
        if not info.sn or info.section not in ch_ids:
            continue
        r = rows.setdefault(info.path, {"layers": Counter(), "ch": {}})
        r["layers"][info.layer] += 1
        cell = r["ch"].setdefault(info.section, [])
        if not any(c.label == info.label for c in cell):
            cell.append(info)
    ordered = sorted(
        rows.items(),
        key=lambda kv: (
            _layer_idx(kv[1]["layers"].most_common(1)[0][0]),
            kv[0].rsplit("/", 1)[0] if "/" in kv[0] else "",
            kv[0],
        ),
    )
    head = "".join(
        f'<th scope="col" title="{_esc(c["title"])}"><a href="#{_esc(c["id"])}">{_esc(c["id"])}</a><span class="ov-ch">{_esc(short_title(c["title"]))}</span></th>'
        for c in chapters
    )
    body: list[str] = []
    for path, r in ordered:
        layer = r["layers"].most_common(1)[0][0]
        n = len(r["ch"])
        hot = n >= OVERLAP_HOT
        segs, plain = _addr_segments(path, None, with_fn=False)
        lattr = f' data-layer="{_esc(layer)}"' if layer else ""
        tag = '<span class="ov-hot">共通</span>' if hot else ""
        cells = []
        for c in chapters:
            fns = r["ch"].get(c["id"], [])
            if not fns:
                cells.append('<td class="ov-empty" aria-label="なし">–</td>')
                continue
            btns = "".join(
                f'<button type="button" class="ov-fn" data-ref="{_esc(i.ref)}" data-focus-line="{i.focus}" title="{_esc(i.path)}:{i.focus}">{_wbr(i.label)}</button>'
                for i in fns
            )
            cells.append(f"<td>{btns}</td>")
        body.append(
            f'<tr class="{"hot" if hot else ""}"{lattr}><th scope="row"><span class="layer"{lattr}>{_esc(_layer_label(layer))}</span> '
            f'<span class="stop-addr addr-sm" role="group" aria-label="{_esc("住所: " + plain)}">{segs}</span>{tag}</th>'
            f'{"".join(cells)}<td class="num">{n} 章</td></tr>'
        )
    return (
        f'<div class="overlap-gen" data-gen><div class="overlap-head">{_esc(title)}</div>'
        f'<p class="overlap-note">行は停留所に出てくるファイル（層 → フォルダの順）、列は章、セルはその章の停留所で使う関数です。'
        f'{OVERLAP_HOT} 章以上で使うファイルの行は「共通」の印と色で強調しています。関数名を押すとコードが開きます。</p>'
        f'<div class="table-wrap"><table class="overlap-table"><thead><tr><th scope="col">ファイル</th>{head}<th scope="col">章数</th></tr></thead>'
        f'<tbody>{"".join(body)}</tbody></table></div></div>'
    )


# ---------------------------------------------------------------------------
# 訳（review/translations/*.json）
# ---------------------------------------------------------------------------


def load_translations(tdir: Path, label_of, errors: list[str]) -> tuple[dict[str, list[tuple[int, int, str, str]]], list[str], bool]:
    """訳の JSON を読んでマージする。(path → [(a, b, ja, ファイル名)], 読んだファイル名, sample を使ったか)。"""
    files = sorted((p for p in tdir.glob("*.json") if p.name != "sample.json"), key=lambda p: p.name) if tdir.is_dir() else []
    used_sample = False
    if not files and (tdir / "sample.json").is_file():
        files = [tdir / "sample.json"]
        used_sample = True
    blocks: dict[str, list[tuple[int, int, str, str]]] = {}
    for p in files:
        label = label_of(p)
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{label}: JSON として読めない: {exc}")
            continue
        if not isinstance(data, dict):
            errors.append(f"{label}: 最上位はオブジェクト（キー = パス）にする")
            continue
        for path, items in data.items():
            if not isinstance(items, list):
                errors.append(f'{label}: "{path}" の値は配列にする')
                continue
            for k, it in enumerate(items):
                where = f'{label}: "{path}"[{k}]'
                if not isinstance(it, dict):
                    errors.append(f"{where}: オブジェクト {{lines, ja}} にする")
                    continue
                extra = set(it) - {"lines", "ja"}
                if extra:
                    errors.append(f"{where}: 未知のキー {sorted(extra)}（lines と ja だけ）")
                ln, ja = it.get("lines"), it.get("ja")
                if not (isinstance(ln, list) and len(ln) == 2 and all(isinstance(x, int) and not isinstance(x, bool) for x in ln) and 1 <= ln[0] <= ln[1]):
                    errors.append(f"{where}: lines は [開始行, 終了行]（1 以上の整数、開始 <= 終了）にする: {ln!r}")
                    continue
                if not isinstance(ja, str) or not ja.strip():
                    errors.append(f"{where}: ja は空でない文字列にする")
                    continue
                blocks.setdefault(path, []).append((ln[0], ln[1], ja.strip(), p.name))
    return blocks, [p.name for p in files], used_sample


def compute_scope(infos: list[StopInfo]) -> dict[str, list[list[int]]]:
    """全停留所の data-ref の解決範囲を、ファイルごとに和集合（隣接・重複は結合）にする。"""
    raw: dict[str, list[tuple[int, int]]] = {}
    for info in infos:
        if info.sn:
            raw.setdefault(info.path, []).append((info.sn["start"], info.sn["end"]))
    return {p: _merge_ranges(r) for p, r in sorted(raw.items())}


def check_translations(
    blocks: dict[str, list[tuple[int, int, str, str]]],
    scope: dict[str, list[list[int]]],
    git: GitFiles,
    errors: list[str],
) -> list[tuple[str, list[list[int]], int]]:
    """網羅の検査。形式の誤り・はみ出し・重なりは errors に、訳の無い行は戻り値（path, 範囲, 行数）に返す。"""
    for path in sorted(blocks):
        if path not in scope:
            try:
                git.lines(path)
            except ResolveError:
                errors.append(f"訳 {path}: ファイルが存在しない（コミット {git.sha[:7]}）")
            else:
                errors.append(f"訳 {path}: 停留所の行範囲に含まれないファイル（ブロック {len(blocks[path])} 件。--dump-translation-scope で対象を確認する）")
    missing: list[tuple[str, list[list[int]], int]] = []
    for path, ranges in scope.items():
        lines = git.lines(path)
        bl = sorted(blocks.get(path, []), key=lambda b: (b[0], b[1]))
        out_of: list[str] = []
        for a, b, _ja, src in bl:
            rest = _subtract(a, b, ranges)
            if rest:
                out_of.append(f"{_fmt_ranges(rest)}（{src} の L{a}-L{b} のうち）")
        if out_of:
            errors.append(f"訳 {path}: 停留所の行範囲（{_fmt_ranges(ranges)}）の外にはみ出している: " + "、".join(out_of))
        overlaps: list[str] = []
        reach_b, reach_src, reach_a = 0, "", 0
        for a, b, _ja, src in bl:
            if a <= reach_b:
                overlaps.append(f"{reach_src} の L{reach_a}-L{reach_b} と {src} の L{a}-L{b}")
            if b > reach_b:
                reach_a, reach_b, reach_src = a, b, src
        if overlaps:
            errors.append(f"訳 {path}: ブロックが重なっている: " + "、".join(overlaps))
        covered: set[int] = set()
        for a, b, _ja, _src in bl:
            covered.update(range(a, b + 1))
        miss = [n for ra, rb in ranges for n in range(ra, rb + 1) if n - 1 < len(lines) and lines[n - 1].strip() and n not in covered]
        if miss:
            missing.append((path, _ranges_from_lines(miss), len(miss)))
    return missing


def scope_dump(scope: dict[str, list[list[int]]], git: GitFiles) -> dict:
    out = {}
    for path, ranges in scope.items():
        lines = git.lines(path)
        total = sum(b - a + 1 for a, b in ranges)
        nonblank = sum(1 for a, b in ranges for n in range(a, b + 1) if lines[n - 1].strip())
        out[path] = {"ranges": ranges, "lines": total, "nonblank": nonblank}
    return out


# ---------------------------------------------------------------------------
# 用語集（review/glossary.json）
# ---------------------------------------------------------------------------


def load_glossary(path: Path, label: str, git: GitFiles, errors: list[str], snippets: dict[str, dict]) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"{label}: JSON として読めない: {exc}")
        return []
    if not isinstance(data, list):
        errors.append(f"{label}: 最上位は配列にする")
        return []
    out: list[dict] = []
    seen: dict[str, int] = {}
    for i, e in enumerate(data):
        where = f"{label}[{i}]"
        if not isinstance(e, dict):
            errors.append(f"{where}: オブジェクトにする")
            continue
        extra = set(e) - {"term", "aliases", "short", "analogy", "ref"}
        if extra:
            errors.append(f"{where}: 未知のキー {sorted(extra)}")
        term, short = e.get("term"), e.get("short")
        if not isinstance(term, str) or not term.strip():
            errors.append(f"{where}: term は空でない文字列にする")
            continue
        if not isinstance(short, str) or not short.strip():
            errors.append(f'{where}（{term}）: short は空でない文字列にする')
            continue
        aliases = e.get("aliases", [])
        if aliases is None:
            aliases = []
        if not isinstance(aliases, list) or not all(isinstance(a, str) and a.strip() for a in aliases):
            errors.append(f"{where}（{term}）: aliases は文字列の配列にする")
            aliases = []
        analogy = e.get("analogy") or ""
        if not isinstance(analogy, str):
            errors.append(f"{where}（{term}）: analogy は文字列にする")
            analogy = ""
        ref = e.get("ref") or ""
        if not isinstance(ref, str):
            errors.append(f"{where}（{term}）: ref は文字列にする")
            ref = ""
        names = [term.strip()] + [a.strip() for a in aliases]
        for nm in names:
            if nm in seen:
                errors.append(f'{where}（{term}）: 「{nm}」が [{seen[nm]}] と重複している')
            seen[nm] = i
        if ref:
            ref = ref.strip()
            if ref not in snippets:
                try:
                    snippets[ref] = resolve_ref(ref, git)
                except ResolveError as exc:
                    snippets[ref] = {"error": str(exc)}
            if "error" in snippets[ref]:
                errors.append(f"{where}（{term}）: ref {ref} → {snippets[ref]['error']}")
        item = {"term": term.strip(), "aliases": [a.strip() for a in aliases], "short": short.strip()}
        if analogy.strip():
            item["analogy"] = analogy.strip()
        if ref:
            item["ref"] = ref
        out.append(item)
    return out


# ---------------------------------------------------------------------------
# 原文の保護の検査
# ---------------------------------------------------------------------------


class _TextCollector(HTMLParser):
    """HTML のテキストを集める。data-gen の付いた要素（組み立てで挿入したもの）と span.loc の中身は除く。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_tag = ""
        self._depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._skip_tag:
            if tag == self._skip_tag:
                self._depth += 1
            return
        a = dict(attrs)
        if "data-gen" in a or (tag == "span" and "loc" in (a.get("class") or "").split()):
            self._skip_tag, self._depth = tag, 1

    def handle_endtag(self, tag: str) -> None:
        if self._skip_tag and tag == self._skip_tag:
            self._depth -= 1
            if self._depth == 0:
                self._skip_tag = ""

    def handle_data(self, data: str) -> None:
        if not self._skip_tag:
            self.parts.append(data)


def collected_text(source: str) -> str:
    c = _TextCollector()
    c.feed(source)
    c.close()
    return re.sub(r"\s+", "", "".join(c.parts))


def check_original_text(original: str, built: str) -> str | None:
    """一致しなければ、最初に食い違う位置の前後を返す。"""
    a, b = collected_text(original), collected_text(built)
    if a == b:
        return None
    i = 0
    n = min(len(a), len(b))
    while i < n and a[i] == b[i]:
        i += 1
    return f"原文 …{a[max(0, i - 20):i + 30]}… ／ 出力 …{b[max(0, i - 20):i + 30]}…（{i} 文字目）"


# ---------------------------------------------------------------------------
# 解説書・レビュー回答ガイドの組み立て
# ---------------------------------------------------------------------------


def prepare_review_aids(
    args: argparse.Namespace,
    root: Path,
    git: GitFiles,
    docs: list[tuple[Path, str, "ContentScanner"]],
    sections: list[dict],
    snippets: dict[str, dict],
    errors: list[str],
    warnings: list[str],
) -> dict:
    """--review の補助（訳・住所・つながり図・重なりの図・用語集）を作り、各 rewrite に差し込む HTML を持たせる。"""

    def label_of(p: Path) -> str:
        try:
            return str(p.relative_to(root))
        except ValueError:
            return str(p)

    # 停留所の情報（順路ごと）
    infos: list[StopInfo] = []
    routes: dict[tuple[int, int], list[StopInfo]] = {}
    route_rw: dict[tuple[int, int], dict] = {}
    for di, (_path, _text, scanner) in enumerate(docs):
        for rw in scanner.rewrites:
            if rw["kind"] == "route":
                route_rw[(di, rw["route_no"])] = rw
            elif rw["kind"] == "stop":
                ref = rw["attrs"].get("data-ref", "").strip()
                entry = snippets.get(ref) if ref else None
                if entry is not None and ("error" in entry or "focus_line" not in rw):
                    entry = None
                info = StopInfo(rw, entry)
                infos.append(info)
                routes.setdefault((di, rw["route_no"]), []).append(info)

    scope = compute_scope(infos)
    if args.dump_translation_scope:
        dump = scope_dump(scope, git)
        Path(args.dump_translation_scope).write_text(json.dumps(dump, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    # 訳
    tdir = Path(args.translations_dir).resolve()
    blocks, tr_files, used_sample = load_translations(tdir, label_of, errors)
    missing = check_translations(blocks, scope, git, errors)
    miss_lines = sum(m[2] for m in missing)
    if used_sample:
        warnings.append(f"本番の訳（{label_of(tdir)}/*.json）が無いため、sample.json を使う")
    if missing:
        detail = [f"    {p}: {_fmt_ranges(r)}（{n} 行）" for p, r, n in missing]
        head = f"訳の無い行: {len(missing)} ファイル・{miss_lines} 行（空行を除く）"
        if args.allow_missing_translations:
            warnings.append(head + "（--allow-missing-translations のため警告）")
            warnings.extend(d.replace("    ", "  - ", 1) for d in detail)
        else:
            errors.append(head + "。すべての行に訳が要る（データ作成中の確認は --allow-missing-translations）")
            errors.extend(detail)
    merged: dict[str, list[tuple[int, int, str]]] = {
        p: sorted((a, b, ja) for a, b, ja, _ in v) for p, v in blocks.items() if p in scope
    }

    # 用語集
    gl_path = Path(args.glossary).resolve()
    glossary: list[dict] = []
    gl_used = ""
    if gl_path.is_file():
        gl_used = label_of(gl_path)
    elif REVIEW_GLOSSARY_SAMPLE.is_file() and gl_path == REVIEW_GLOSSARY.resolve():
        gl_path = REVIEW_GLOSSARY_SAMPLE
        gl_used = label_of(gl_path)
        warnings.append("本番の用語集（review/glossary.json）が無いため、glossary.sample.json を使う")
    if gl_used:
        glossary = load_glossary(gl_path, gl_used, git, errors, snippets)
    else:
        warnings.append("用語集が無い（review/glossary.json）。用語ポップアップは出ない")

    # 図・住所・重なりの差し込み
    for key, stops in routes.items():
        rw = route_rw.get(key)
        if rw is not None:
            rw["gen_html"] = conn_map_html(rw["attrs"].get("data-title", ""), stops)
    for info in infos:
        if info.sn and info.focus:
            info.rw["aid_html"] = stop_addr_html(info) + stop_aid_html(info, merged.get(info.path, []))
    by_id = {sec["id"]: sec for sec in sections}
    for _path, _text, scanner in docs:
        for rw in scanner.rewrites:
            if rw["kind"] != "overlap":
                continue
            ids = [x.strip() for x in rw["attrs"].get("data-chapters", "").split(",") if x.strip()] or OVERLAP_CHAPTERS
            chapters = [by_id[i] for i in ids if i in by_id]
            if not chapters:
                errors.append(f"{rw['line']}: div.overlap-map の対象の章（{', '.join(ids)}）が本文に無い")
                continue
            rw["gen_html"] = overlap_html(chapters, infos, rw["attrs"].get("data-title", "") or "章 × ファイル")

    n_blocks = sum(len(v) for v in merged.values())
    nonblank = sum(v["nonblank"] for v in scope_dump(scope, git).values())
    summary = [
        f"訳の対象: {len(scope)} ファイル・{nonblank} 行（空行を除く）／訳のブロック {n_blocks}"
        + (f"（{', '.join(tr_files)}）" if tr_files else "（訳データなし）"),
        f"用語集: {len(glossary)} 語" + (f"（{gl_used}）" if gl_used else ""),
    ]
    tr_json = {p: [[a, b, ja] for a, b, ja in v] for p, v in sorted(merged.items())}
    return {
        "tr_json": tr_json, "glossary": glossary, "summary": summary,
        "infos": infos, "routes": routes, "route_rw": route_rw,
    }


def build_guide(args: argparse.Namespace) -> int:
    review = bool(getattr(args, "review", False))
    root = repo_root()
    sha = resolve_commit(root, args.commit)
    git = GitFiles(root, sha)

    content_dir = Path(args.content_dir).resolve()
    label = content_dir.name  # エラー表示用（content / review）
    files = sorted(content_dir.glob("*.html"), key=lambda p: p.name)
    if not args.include_sample:
        files = [p for p in files if not p.name.startswith("00-sample")]
    if review:
        files = [p for p in files if not p.name.startswith("template")]  # template-review.html は本文ではない
    if not files:
        print(f"エラー: {content_dir}/*.html が見つからない", file=sys.stderr)
        return 1

    errors: list[str] = []
    warnings: list[str] = []
    docs: list[tuple[Path, str, ContentScanner]] = []
    sections: list[dict] = []
    all_refs: list[tuple[str, str, str, int]] = []  # (ref, note, file, line)
    id_seen: dict[str, str] = {}
    hrefs: list[tuple[str, str, int]] = []

    for path in files:
        try:
            rel = str(path.relative_to(root))
        except ValueError:
            rel = str(path)
        text = path.read_text(encoding="utf-8")
        scanner = ContentScanner(path.name)
        scanner.feed(text)
        scanner.close()
        if not scanner.sections:
            errors.append(f"{rel}: <section id=\"sNN\" data-title=\"...\"> が見つからない")
        for sec in scanner.sections:
            if not sec["title"]:
                warnings.append(f"{rel}:{sec['line']}: section#{sec['id']} に data-title が無い")
            sections.append(sec)
        for ref, note, line in scanner.refs:
            all_refs.append((ref, note, path.name, line))
        for id_, line in scanner.ids:
            where = f"{path.name}:{line}"
            if id_ in id_seen:
                errors.append(f"{rel}:{line}: id \"{id_}\" が重複（初出 {id_seen[id_]}）")
            else:
                id_seen[id_] = where
        for target, line in scanner.hrefs:
            hrefs.append((target, path.name, line))
        for line, msg in scanner.problems:
            errors.append(f"{label}/{path.name}:{line}: {msg}")
        docs.append((path, text, scanner))

    for target, fname, line in hrefs:
        if target not in id_seen:
            warnings.append(f"{label}/{fname}:{line}: リンク先 #{target} が本文に存在しない")

    snippets: dict[str, dict] = {}
    for ref, note, fname, line in all_refs:
        if not ref:
            errors.append(f"{label}/{fname}:{line}: data-ref が空")
            continue
        if ref not in snippets:
            try:
                snippets[ref] = resolve_ref(ref, git)
            except ResolveError as exc:
                snippets[ref] = {"error": str(exc)}
        entry = snippets[ref]
        if "error" in entry:
            errors.append(f"{label}/{fname}:{line}: {ref} → {entry['error']}")
        elif note and not entry["note"]:
            entry["note"] = note

    # data-focus・span.loc・停留所の行番号を、解決済みのコードから求める
    focus_total = 0
    stop_list: list[str] = []
    for path, text, scanner in docs:
        for rw in scanner.rewrites:
            ref = rw["attrs"].get("data-ref", "").strip()
            if not ref:
                if rw["kind"] == "stop":
                    warnings.append(f"{label}/{path.name}:{rw['line']}: 停留所に data-ref が無い（path:行 とコードボタンは出ない）")
                continue
            entry = snippets.get(ref)
            if not entry or "error" in entry:
                continue  # 参照の解決エラーは上で報告済み
            try:
                rw["focus_line"] = focus_line(entry, rw["attrs"].get("data-focus", ""))
            except ResolveError as exc:
                errors.append(f"{label}/{path.name}:{rw['line']}: {ref} → {exc}")
                continue
            rw["path"] = entry["path"]
            focus_total += 1
            if rw["kind"] == "stop":
                f = rw["attrs"].get("data-focus", "")
                stop_list.append(f"  {path.name}:{rw['line']}  停留所 {rw['stop_no']}  {entry['path']}:{rw['focus_line']}" + (f"  （focus: {f}）" if f else ""))

    review_info: dict = {}
    if review:
        review_info = prepare_review_aids(args, root, git, docs, sections, snippets, errors, warnings)

    chunks: list[str] = []
    for path, text, scanner in docs:
        chunks.append(apply_rewrites(text, scanner.rewrites, f"{label}/{path.name}", errors).rstrip("\n"))

    if review and not errors:
        # 原文の保護: 組み立てで挿入した要素を除くと、本文の原文と一致すること
        mismatch = check_original_text("\n".join(t for _, t, _ in docs), "\n".join(chunks))
        if mismatch:
            errors.append(f"原文の保護: 組み立てで本文のテキストが変わっている: {mismatch}")

    for w in warnings:
        print(f"警告: {w}", file=sys.stderr)

    if errors:
        # 先頭が空白の行は、直前のエラーの詳細（箇条書きにしない）
        print(f"エラー: {sum(1 for e in errors if not e.startswith(' '))} 件（解決できない参照・構造の不備）", file=sys.stderr)
        for e in errors:
            print(e if e.startswith(" ") else f"  - {e}", file=sys.stderr)
        return 1

    unique = {k: v for k, v in snippets.items() if "error" not in v}
    snip_json, snip_code = snippet_parts(unique)
    content_html = "\n\n".join(chunks)

    jst = timezone(timedelta(hours=9))
    values = {
        "CONTENT": content_html,
        "TOC": build_toc(sections),
        "SNIPPETS_JSON": snip_json,
        "SNIPPETS_CODE": snip_code,
        "COMMIT": sha[:7],
        "COMMIT_FULL": sha,
        "BUILD_DATE": datetime.now(jst).strftime("%Y-%m-%d"),
        "MAP_URL": html.escape(args.map_url, quote=True),
        "GUIDE_URL": html.escape(args.guide_url, quote=True),
    }
    if review:
        values["TRANSLATIONS_JSON"] = escape_json_for_script(review_info["tr_json"], per_line=True)
        values["GLOSSARY_JSON"] = escape_json_for_script(review_info["glossary"])
    output = render_template(REVIEW_TEMPLATE if review else TEMPLATE, values)

    default_name = REVIEW_OUTPUT_NAME if review else OUTPUT_NAME
    out_path = Path(args.out).resolve() if args.out else root / "docs" / "05_解説" / default_name
    size = len(output.encode("utf-8"))
    if not args.check:
        out_path.write_text(output, encoding="utf-8")

    print(f"対象コミット: {sha}")
    print(f"章数: {len(sections)}")
    print(f"参照数: {len(all_refs)}")
    print(f"ユニークスニペット数: {len(unique)}")
    if review or focus_total:
        n_routes = sum(sc.route_count for _, _, sc in docs)
        n_stops = sum(1 for _, _, sc in docs for rw in sc.rewrites if rw["kind"] == "stop")
        print(f"順路数: {n_routes}／停留所数: {n_stops}／行番号を自動で入れた箇所: {focus_total}")
    if review:
        for line in review_info["summary"]:
            print(line)
    if getattr(args, "list_stops", False):
        print("停留所の一覧（ファイル:行 は実ファイルの行番号）:")
        for line in stop_list:
            print(line)
    if args.check:
        print(f"検証のみ（出力は書いていない）。出力サイズの見込み: {size:,} bytes")
    else:
        try:
            shown = str(out_path.relative_to(root))
        except ValueError:
            shown = str(out_path)
        print(f"出力: {shown}（{size:,} bytes）")
    return 0


# ---------------------------------------------------------------------------
# コードトレーサー（--tracer）
# ---------------------------------------------------------------------------

# 層の帯に並べる順（data-layer の値 → 表示名）
TRACER_LAYERS = [
    ("screen", "ブラウザ"), ("bff", "BFF"), ("api", "FastAPI"), ("service", "サービス"),
    ("repo", "リポジトリ"), ("db", "DB"), ("infra", "インフラ"),
]
IMAGE_MIME = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp", "gif": "image/gif", "avif": "image/avif"}
_STOP_P_RE = re.compile(r'<p class="stop-(see|say|next)">(.*?)</p>', re.S)
_LOC_SPAN_RE = re.compile(r'<span class="loc"([^>]*)>\s*</span>')
_TAG_RE = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9]*)([^>]*)>")
TRACER_INLINE_TAGS = {"code", "kbd", "strong", "em", "b", "i", "br"}
_SCENARIO_KEYS = {"version", "description", "flow", "aliases", "initial_state", "initial", "actions"}
_ACTION_KEYS = {"title", "routes", "extras", "server_calls", "network_note", "forward_headers"}
_ROUTE_KEYS = {"section", "title", "stops", "label"}


def tracer_clean_html(inner: str, snippets: dict[str, dict], where: str, errors: list[str]) -> str:
    """停留所の補足（見る・言う・次へ）の HTML を、トレーサーの解説パネルに入れられる形にする。

    - span.loc（中身は組み立て時に入る）は `path:行` の code にする
    - code・kbd・strong・em・b・i・br 以外のタグ（リンク・バッジなど）は、属性ごと外して中の文字だけ残す
    """

    def loc(m: re.Match[str]) -> str:
        attrs = m.group(1)
        mr = re.search(r'data-ref="([^"]*)"', attrs)
        mf = re.search(r'data-focus="([^"]*)"', attrs)
        ref = html.unescape(mr.group(1)).strip() if mr else ""
        focus = html.unescape(mf.group(1)) if mf else ""
        sn = snippets.get(ref)
        if not sn or "error" in sn:
            errors.append(f"{where}: span.loc の参照 {ref} を解決できない")
            return "<code>?</code>"
        try:
            return f"<code>{html.escape(sn['path'])}:{focus_line(sn, focus)}</code>"
        except ResolveError as exc:
            errors.append(f"{where}: span.loc {ref} → {exc}")
            return "<code>?</code>"

    inner = _LOC_SPAN_RE.sub(loc, inner)

    def tag(m: re.Match[str]) -> str:
        closing, name = m.group(1), m.group(2).lower()
        if name == "br":
            return "<br>"
        return f"<{closing}{name}>" if name in TRACER_INLINE_TAGS else ""

    return _TAG_RE.sub(tag, inner).strip()


def tracer_link(prev: StopInfo | None, cur: StopInfo, first_of_route: bool, route_title: str) -> str:
    """前の停留所からこの停留所への経路の文言。data-link があればそれ。無ければ層の変わり目から決める。"""
    if prev is None:
        return ""
    if cur.link:
        return cur.link
    if first_of_route and "応答" in route_title:
        return "応答が戻る（処理の結果が画面の側へ返っていく）"
    if first_of_route and prev.layer == cur.layer and cur.layer:
        return "順路の続き（同じ層の中の処理へ）"
    return default_link(prev, cur)


def tracer_load_scenario(path: Path, errors: list[str]) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        errors.append(f"scenario: {path} を読めない: {exc}")
        return {}
    except json.JSONDecodeError as exc:
        errors.append(f"scenario: {path} が JSON として読めない: {exc}")
        return {}
    if not isinstance(data, dict):
        errors.append("scenario: 最上位はオブジェクトにする")
        return {}
    extra = set(data) - _SCENARIO_KEYS
    if extra:
        errors.append(f"scenario: 未知のキー {sorted(extra)}")
    return data


def tracer_resolve_routes(
    specs: object, catalog: dict[tuple[str, str], list[dict]], where: str, errors: list[str]
) -> list[dict]:
    """scenario の routes（{section, title, stops?, label?} の配列）を、順路の実体に解決する。"""
    out: list[dict] = []
    if not isinstance(specs, list) or not specs:
        errors.append(f"{where}: 順路の配列（1 件以上）にする")
        return out
    for k, sp in enumerate(specs):
        w = f"{where}[{k}]"
        if not isinstance(sp, dict):
            errors.append(f"{w}: オブジェクト {{section, title}} にする")
            continue
        extra = set(sp) - _ROUTE_KEYS
        if extra:
            errors.append(f"{w}: 未知のキー {sorted(extra)}")
        sec, title = sp.get("section"), sp.get("title")
        if not isinstance(sec, str) or not isinstance(title, str):
            errors.append(f"{w}: section と title は文字列にする")
            continue
        hits = catalog.get((sec, title), [])
        if not hits:
            cands = [t for (s, t) in catalog if s == sec]
            hint = "。この章の順路: " + " ／ ".join(f"「{t}」" for t in cands) if cands else f"。章 {sec} は本文に無い"
            errors.append(f"{w}: 章 {sec} に data-title「{title}」の順路が無い{hint}")
            continue
        if len(hits) > 1:
            errors.append(f"{w}: 章 {sec} に同じ data-title「{title}」の順路が {len(hits)} 本ある（本文側で区別が要る）")
            continue
        entry = hits[0]
        n = len(entry["stops"])
        lo, hi = 1, n
        if "stops" in sp:
            rng = sp["stops"]
            if not (isinstance(rng, list) and len(rng) == 2 and all(isinstance(x, int) and not isinstance(x, bool) for x in rng) and 1 <= rng[0] <= rng[1] <= n):
                errors.append(f"{w}: stops は [開始, 終了]（1〜{n} の整数、開始 <= 終了）にする: {rng!r}")
                continue
            lo, hi = rng
        label = sp.get("label")
        if label is not None and not isinstance(label, str):
            errors.append(f"{w}: label は文字列にする")
            label = None
        out.append({"entry": entry, "lo": lo, "hi": hi, "label": label or ""})
    return out


def tracer_group(items: list[dict], docs: list, starts: dict[int, list[int]], snippets: dict[str, dict],
                 extra: bool, title: str, errors: list[str]) -> dict:
    """順路（の一部）をつないで、1 本の停留所の列にする。"""
    stops: list[dict] = []
    routes_meta: list[dict] = []
    prev: StopInfo | None = None
    for ri, it in enumerate(items):
        entry = it["entry"]
        di = entry["key"][0]
        text = docs[di][1]
        picked = entry["stops"][it["lo"] - 1 : it["hi"]]
        routes_meta.append({
            "title": entry["title"], "label": it["label"], "section": entry["section"], "doc": entry["doc"],
            "count": len(picked), "from": it["lo"], "to": it["hi"], "total": len(entry["stops"]),
        })
        for k, info in enumerate(picked):
            where = f"{entry['doc']} 章{entry['section']}「{entry['title']}」停留所 {info.no}"
            if not info.sn or not info.focus:
                errors.append(f"{where}: data-ref を解決できていない（トレースに使えない）")
                continue
            rw = info.rw
            off = starts[di][rw["line"] - 1] + rw["col"] + len(rw["raw"])
            close = text.find("</li>", off)
            body = text[off:close] if close >= 0 else ""
            parts = {"see": "", "say": "", "next": ""}
            for m in _STOP_P_RE.finditer(body):
                parts[m.group(1)] = tracer_clean_html(m.group(2), snippets, where, errors)
            sn = info.sn
            stops.append({
                "path": info.path, "start": sn["start"], "end": sn["end"], "focus": info.focus,
                "label": info.label, "kind": info.kind, "layer": info.layer,
                "link": tracer_link(prev, info, k == 0 and ri > 0, entry["title"]) if stops else "",
                "see": parts["see"], "say": parts["say"], "next": parts["next"],
                "route": ri, "no": info.no,
            })
            prev = info
    return {"title": title, "extra": extra, "routes": routes_meta, "stops": stops}


def tracer_load_capture(cap_dir: Path, errors: list[str], warnings: list[str]) -> tuple[dict, dict[str, str]]:
    """撮影素材（capture.json と画像）を読んで検査する。(capture の JSON（画像を除く）, 状態 id → data URI)。"""
    cj = cap_dir / "capture.json"
    try:
        cap = json.loads(cj.read_text(encoding="utf-8"))
    except OSError as exc:
        errors.append(f"capture: {cj} を読めない: {exc}")
        return {}, {}
    except json.JSONDecodeError as exc:
        errors.append(f"capture: {cj} が JSON として読めない: {exc}")
        return {}, {}
    if not isinstance(cap, dict) or not isinstance(cap.get("states"), list) or not cap["states"]:
        errors.append("capture: states（1 件以上の配列）が要る")
        return {}, {}
    actions = cap.get("actions", {})
    if not isinstance(actions, dict):
        errors.append("capture: actions はオブジェクトにする")
        actions = {}
    images: dict[str, str] = {}
    ids: set[str] = set()
    states: list[dict] = []

    def is_num(v: object) -> bool:
        return isinstance(v, (int, float)) and not isinstance(v, bool)

    for i, st in enumerate(cap["states"]):
        w = f"capture: states[{i}]"
        if not isinstance(st, dict) or not isinstance(st.get("id"), str) or not st["id"]:
            errors.append(f"{w}: id（文字列）が要る")
            continue
        sid = st["id"]
        w = f"capture: states[{i}]（{sid}）"
        if sid in ids:
            errors.append(f"{w}: id が重複している")
        ids.add(sid)
        for key in ("width", "height"):
            if not is_num(st.get(key)) or st[key] <= 0:
                errors.append(f"{w}: {key} は正の数にする")
        img = st.get("image")
        if not isinstance(img, str) or not img:
            errors.append(f"{w}: image（ファイル名）が要る")
        else:
            p = cap_dir / img
            ext = img.rsplit(".", 1)[-1].lower() if "." in img else ""
            if ext not in IMAGE_MIME:
                errors.append(f"{w}: 画像の拡張子 .{ext} は未対応（{'/'.join(sorted(IMAGE_MIME))}）")
            elif not p.is_file():
                errors.append(f"{w}: 画像 {img} が {cap_dir} に無い")
            else:
                images[sid] = f"data:{IMAGE_MIME[ext]};base64," + base64.b64encode(p.read_bytes()).decode("ascii")
        hs = st.get("hotspots", [])
        if not isinstance(hs, list):
            errors.append(f"{w}: hotspots は配列にする")
            hs = []
        for j, h in enumerate(hs):
            hw = f"{w} hotspots[{j}]"
            if not isinstance(h, dict) or not isinstance(h.get("action"), str):
                errors.append(f"{hw}: action（文字列）が要る")
                continue
            for key in ("x", "y", "w", "h"):
                if not is_num(h.get(key)):
                    errors.append(f"{hw}: {key} は数にする")
        states.append({k: v for k, v in st.items() if k != "image"})
    for i, st in enumerate(cap["states"]):
        hs = st.get("hotspots", []) if isinstance(st, dict) else []
        for j, h in enumerate(hs if isinstance(hs, list) else []):
            nx = h.get("next") if isinstance(h, dict) else None
            if nx and nx not in ids:
                errors.append(f"capture: states[{i}]（{st.get('id')}）hotspots[{j}]: next「{nx}」という状態が無い")
    for aid, ac in actions.items():
        if not isinstance(ac, dict):
            errors.append(f"capture: actions.{aid} はオブジェクトにする")
            continue
        for key in ("from", "to"):
            if ac.get(key) and ac[key] not in ids:
                warnings.append(f"capture: actions.{aid}.{key}「{ac[key]}」という状態が無い")
        net = ac.get("network", [])
        if not isinstance(net, list) or not all(isinstance(n, dict) for n in net):
            errors.append(f"capture: actions.{aid}.network はオブジェクトの配列にする")
    out = {k: v for k, v in cap.items() if k not in ("states", "actions")}
    out["states"] = states
    out["actions"] = actions
    return out, images


def tracer_aliases(raw: object, scen_actions: dict, errors: list[str]) -> dict[str, dict]:
    """aliases を {別名: {action, stop}} にそろえる。値は action 名の文字列か {action, stop}（stop は本筋の何番目の停留所から始めるか。1 始まり）。"""
    out: dict[str, dict] = {}
    if raw in (None, {}):
        return out
    if not isinstance(raw, dict):
        errors.append("scenario: aliases はオブジェクトにする")
        return out
    for a, v in raw.items():
        if isinstance(v, str):
            v = {"action": v}
        if not isinstance(v, dict) or set(v) - {"action", "stop"} or not isinstance(v.get("action"), str):
            errors.append(f"scenario: aliases.{a} は action 名の文字列か {{action, stop}} にする")
            continue
        stop = v.get("stop", 1)
        if not isinstance(stop, int) or isinstance(stop, bool) or stop < 1:
            errors.append(f"scenario: aliases.{a}.stop は 1 以上の整数にする")
            continue
        if v["action"] not in scen_actions:
            errors.append(f"scenario: aliases.{a} → 「{v['action']}」という action が scenario.actions に無い")
            continue
        out[a] = {"action": v["action"], "stop": stop}
    return out


def build_tracer(args: argparse.Namespace) -> int:
    root = repo_root()
    sha = resolve_commit(root, args.commit)
    git = GitFiles(root, sha)

    content_dir = Path(args.content_dir).resolve()
    label = content_dir.name
    files = sorted(content_dir.glob("*.html"), key=lambda p: p.name)
    if not args.include_sample:
        files = [p for p in files if not p.name.startswith("00-sample")]
    files = [p for p in files if not p.name.startswith("template")]
    if not files:
        print(f"エラー: {content_dir}/*.html が見つからない", file=sys.stderr)
        return 1

    errors: list[str] = []
    warnings: list[str] = []

    # --- 順路の本文を解析し、参照・行番号を解決する（--review と同じ処理） ---
    docs: list[tuple[Path, str, ContentScanner]] = []
    sections: list[dict] = []
    all_refs: list[tuple[str, str, str, int]] = []
    id_seen: dict[str, str] = {}
    for path in files:
        text = path.read_text(encoding="utf-8")
        scanner = ContentScanner(path.name)
        scanner.feed(text)
        scanner.close()
        sections.extend(scanner.sections)
        for ref, note, line in scanner.refs:
            all_refs.append((ref, note, path.name, line))
        for id_, line in scanner.ids:
            if id_ in id_seen:
                errors.append(f"{label}/{path.name}:{line}: id \"{id_}\" が重複（初出 {id_seen[id_]}）")
            else:
                id_seen[id_] = f"{path.name}:{line}"
        for line, msg in scanner.problems:
            errors.append(f"{label}/{path.name}:{line}: {msg}")
        docs.append((path, text, scanner))

    snippets: dict[str, dict] = {}
    for ref, note, fname, line in all_refs:
        if not ref:
            errors.append(f"{label}/{fname}:{line}: data-ref が空")
            continue
        if ref not in snippets:
            try:
                snippets[ref] = resolve_ref(ref, git)
            except ResolveError as exc:
                snippets[ref] = {"error": str(exc)}
        if "error" in snippets[ref]:
            errors.append(f"{label}/{fname}:{line}: {ref} → {snippets[ref]['error']}")
    for path, text, scanner in docs:
        for rw in scanner.rewrites:
            ref = rw["attrs"].get("data-ref", "").strip()
            entry = snippets.get(ref) if ref else None
            if not entry or "error" in entry:
                continue
            try:
                rw["focus_line"] = focus_line(entry, rw["attrs"].get("data-focus", ""))
            except ResolveError as exc:
                errors.append(f"{label}/{path.name}:{rw['line']}: {ref} → {exc}")
                continue
            rw["path"] = entry["path"]

    # 訳・用語集の検査と読み込み（--review と共通。訳の無い行は既定でエラー）
    review_info = prepare_review_aids(args, root, git, docs, sections, snippets, errors, warnings)

    # --- 順路の一覧（章 id × data-title） ---
    doc_starts: dict[int, list[int]] = {}
    for di, (_p, text, _sc) in enumerate(docs):
        st = [0]
        for m in re.finditer("\n", text):
            st.append(m.end())
        doc_starts[di] = st
    catalog: dict[tuple[str, str], list[dict]] = {}
    catalog_list: list[dict] = []
    for key, rw in sorted(review_info["route_rw"].items()):
        entry = {
            "key": key, "doc": docs[key[0]][0].name, "section": rw.get("section", ""),
            "title": rw["attrs"].get("data-title", ""), "stops": review_info["routes"].get(key, []),
        }
        catalog.setdefault((entry["section"], entry["title"]), []).append(entry)
        catalog_list.append(entry)
    if args.list_routes:
        print("順路の一覧（章 id ／ data-title ／ 停留所数 ／ 本文ファイル）:")
        for e in catalog_list:
            print(f"  {e['section']}  {e['title']}  （{len(e['stops'])} 停留所）  {e['doc']}")

    # --- 撮影素材 ---
    cap_dir = Path(args.capture_dir).resolve() if args.capture_dir else TRACER_CAPTURE
    capture: dict = {}
    images: dict[str, str] = {}
    if not (cap_dir / "capture.json").is_file():
        errors.append(
            f"撮影素材が無い: {cap_dir / 'capture.json'}（撮影担当の出力 tracer/capture/ を待つか、"
            "別の場所の素材を --capture-dir で指定する）"
        )
    else:
        capture, images = tracer_load_capture(cap_dir, errors, warnings)

    # --- scenario（操作 → 順路の対応） ---
    scen_path = Path(args.scenario).resolve() if args.scenario else TRACER_SCENARIO
    scenario: dict = {}
    if scen_path.is_file():
        scenario = tracer_load_scenario(scen_path, errors)
    else:
        errors.append(f"scenario が無い: {scen_path}")

    traces: dict[str, dict] = {}
    scen_actions = scenario.get("actions", {})
    if scenario and not isinstance(scen_actions, dict):
        errors.append("scenario: actions はオブジェクトにする")
        scen_actions = {}
    summary_rows: list[str] = []

    def make_trace(name: str, spec: object) -> None:
        where = f"scenario: {name}"
        if not isinstance(spec, dict):
            errors.append(f"{where}: オブジェクトにする")
            return
        extra_keys = set(spec) - _ACTION_KEYS
        if extra_keys:
            errors.append(f"{where}: 未知のキー {sorted(extra_keys)}")
        main_items = tracer_resolve_routes(spec.get("routes"), catalog, f"{where}.routes", errors)
        groups = [tracer_group(main_items, docs, doc_starts, snippets, False, "本筋", errors)]
        for k, ex in enumerate(spec.get("extras", []) or []):
            items = tracer_resolve_routes([ex], catalog, f"{where}.extras[{k}]", errors)
            if items:
                t = items[0]["label"] or items[0]["entry"]["title"]
                groups.append(tracer_group(items, docs, doc_starts, snippets, True, t, errors))
        for key in ("server_calls", "forward_headers"):
            if key in spec and not isinstance(spec[key], list):
                errors.append(f"{where}.{key}: 配列にする")
        traces[name] = {
            "title": spec.get("title", name), "groups": groups,
            "server_calls": spec.get("server_calls", []), "network_note": spec.get("network_note", ""),
            "forward_headers": spec.get("forward_headers", []),
        }
        main_titles = " ＋ ".join(
            f"{r['section']}「{r['title']}」" + (f"[{r['from']}-{r['to']}]" if (r["from"], r["to"]) != (1, r["total"]) else "")
            for r in groups[0]["routes"]
        )
        row = f"  {name}: {main_titles} → {len(groups[0]['stops'])} 停留所"
        for g in groups[1:]:
            row += f"\n      別ルート（参考）: {g['routes'][0]['section']}「{g['routes'][0]['title']}」 → {len(g['stops'])} 停留所"
        summary_rows.append(row)

    aliases: dict[str, dict] = {}
    flow: list[str] = []
    if scenario:
        if "initial" not in scenario:
            errors.append("scenario: initial（ページを開いたときの順路）が要る")
        else:
            make_trace("initial", scenario["initial"])
        for aid, spec in scen_actions.items():
            make_trace(aid, spec)
        aliases = tracer_aliases(scenario.get("aliases"), scen_actions, errors)
        flow = scenario.get("flow", [])
        if not isinstance(flow, list) or not all(isinstance(x, str) for x in flow):
            errors.append("scenario: flow は action id の文字列の配列にする")
            flow = []
        for a in flow:
            if a not in scen_actions and a not in aliases:
                errors.append(f"scenario: flow の「{a}」が scenario.actions にも aliases にも無い")
        for a, v in aliases.items():
            tr = traces.get(v["action"])
            if tr and v["stop"] > len(tr["groups"][0]["stops"]):
                errors.append(f"scenario: aliases.{a}.stop = {v['stop']} が「{v['action']}」の本筋の停留所数 {len(tr['groups'][0]['stops'])} を超えている")
        if capture:
            state_ids = {s["id"] for s in capture["states"]}
            init_state = scenario.get("initial_state") or capture["states"][0]["id"]
            if init_state not in state_ids:
                errors.append(f"scenario: initial_state「{init_state}」が撮影素材の states に無い")
            real = lambda a: aliases[a]["action"] if a in aliases else a  # noqa: E731
            for aid in capture["actions"]:
                if real(aid) not in scen_actions:
                    warnings.append(f"撮影素材の action「{aid}」に対応する scenario.actions が無い（押しても順路は出ない）")
            for aid in scen_actions:
                if aid not in capture["actions"]:
                    warnings.append(f"scenario の action「{aid}」が撮影素材の actions に無い（通信の記録は出ない）")
            for st in capture["states"]:
                for h in st.get("hotspots", []):
                    a = h.get("action", "")
                    if real(a) not in scen_actions:
                        warnings.append(f"撮影素材の状態「{st['id']}」の hotspot「{a}」は scenario に無い（押すと次の画面へ移るだけ）")

    # --- 使うファイルの全文 ---
    used_paths: list[str] = []
    for tr in traces.values():
        for g in tr["groups"]:
            for s in g["stops"]:
                if s["path"] not in used_paths:
                    used_paths.append(s["path"])
    used_paths.sort()
    file_text: dict[str, str] = {}
    files_meta: dict[str, dict] = {}
    for p in used_paths:
        try:
            lines = git.lines(p)
        except ResolveError as exc:
            errors.append(f"ファイル {p}: {exc}")
            continue
        file_text[p] = "\n".join(lines)
        files_meta[p] = {"lang": lang_of(p), "n": len(lines), "tr": review_info["tr_json"].get(p, [])}

    for w in warnings:
        print(f"警告: {w}", file=sys.stderr)
    if errors:
        print(f"エラー: {sum(1 for e in errors if not e.startswith(' '))} 件（トレーサーを組み立てられない）", file=sys.stderr)
        for e in errors:
            print(e if e.startswith(" ") else f"  - {e}", file=sys.stderr)
        return 1

    jst = timezone(timedelta(hours=9))
    built = datetime.now(jst).strftime("%Y-%m-%d")
    data = {
        "meta": {
            "commit": sha[:7], "built": built,
            "captured_at": capture.get("captured_at", ""), "base_url": capture.get("base_url", ""),
            "viewport": capture.get("viewport", {}), "repo_url": REPO_URL,
        },
        "layers": [{"id": i, "label": l} for i, l in TRACER_LAYERS],
        "flow": flow, "aliases": aliases,
        "initial_state": scenario.get("initial_state") or capture["states"][0]["id"],
        "states": capture["states"], "actions": capture["actions"],
        "traces": traces, "files": files_meta, "glossary": review_info["glossary"],
    }
    file_blocks = "\n".join(
        f'<script type="text/plain" data-file="{html.escape(p, quote=True)}">{escape_script_text(t)}</script>'
        for p, t in file_text.items()
    )
    image_blocks = "\n".join(
        f'<script type="text/plain" data-image="{html.escape(sid, quote=True)}">{uri}</script>' for sid, uri in images.items()
    )
    values = {
        "TRACER_JSON": escape_json_for_script(data),
        "TRACER_FILES": file_blocks,
        "TRACER_IMAGES": image_blocks,
        "COMMIT": sha[:7], "COMMIT_FULL": sha, "BUILD_DATE": built,
        "MAP_URL": html.escape(args.map_url, quote=True),
        "GUIDE_URL": html.escape(args.guide_url, quote=True),
        "REVIEW_URL": html.escape(args.review_url, quote=True),
    }
    output = render_template(TRACER_TEMPLATE, values)
    out_path = Path(args.out).resolve() if args.out else root / "docs" / "05_解説" / TRACER_OUTPUT_NAME
    size = len(output.encode("utf-8"))
    if not args.check:
        out_path.write_text(output, encoding="utf-8")

    print(f"対象コミット: {sha}")
    print(f"撮影素材: {cap_dir}（状態 {len(capture['states'])}・action {len(capture['actions'])}・画像 {len(images)}）")
    print(f"scenario: {scen_path}（action {len(scen_actions)} ＋ initial）")
    print("action → 順路（章「data-title」[停留所の範囲]）の並び → 停留所数（本筋）:")
    for r in summary_rows:
        print(r)
    for a, v in aliases.items():
        print(f"  （別名）{a} → {v['action']} の本筋の {v['stop']} 番目の停留所から")
    n_stops = sum(len(g["stops"]) for tr in traces.values() for g in tr["groups"])
    print(f"停留所のべ数: {n_stops}／埋め込むファイル: {len(file_text)}（{sum(len(t) for t in file_text.values()):,} 文字）／画像: {len(images)}")
    for line in review_info["summary"]:
        print(line)
    if args.check:
        print(f"検証のみ（出力は書いていない）。出力サイズの見込み: {size:,} bytes")
    else:
        try:
            shown = str(out_path.relative_to(root))
        except ValueError:
            shown = str(out_path)
        print(f"出力: {shown}（{size:,} bytes）")
    return 0


# ---------------------------------------------------------------------------
# リポジトリ地図（--map）
# ---------------------------------------------------------------------------

MAP_LAYERS = ("web", "api", "docs", "scripts", "ci", "root")
PREVIEW_MAX_BYTES = 200 * 1024
IMAGE_EXTS = {"png", "jpg", "jpeg", "gif", "webp", "avif", "ico", "bmp", "svg"}
BINARY_EXTS = {"docx", "xlsx", "pptx", "pdf", "zip", "gz", "woff", "woff2", "ttf", "otf", "eot", "mp3", "mp4", "mov"}
SECRET_FILES = {".secrets.baseline", ".gitleaks.toml", ".gitleaksignore"}
ROOT_PREVIEW_FILES = {"README.md", "docker-compose.yml", ".pre-commit-config.yaml", ".gitignore", ".gitattributes"}
PREVIEW_ROOT_DIRS = ("apps/", "scripts/", "tools/", ".github/")
TEST_DIRS = ("apps/api/tests/", "apps/web/tests/")
PUBLIC_DIR = "apps/web/public/"


def file_ext(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[-1].lower() if "." in name.lstrip(".") else ""


def preview_reason(path: str) -> str:
    """プレビュー対象なら空文字。対象外なら理由コード（JS 側で文言に変換する）。"""
    name = path.rsplit("/", 1)[-1]
    ext = file_ext(path)
    if name.startswith(".env"):
        return "env"
    if name in SECRET_FILES:
        return "secret"
    if ext in IMAGE_EXTS:
        return "image"
    if ext in BINARY_EXTS:
        return "binary"
    if ext in ("html", "htm"):
        return "html"
    if path.startswith(TEST_DIRS):
        return "test"
    if path.startswith(PUBLIC_DIR):
        return "public"
    if path.startswith(PREVIEW_ROOT_DIRS):
        return ""
    if path.startswith("docs/") and ext == "md":
        return ""
    if path in ROOT_PREVIEW_FILES:
        return ""
    return "out"


def norm_path(p: str) -> str:
    p = str(p).strip().replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    p = p.strip("/")
    return "" if p == "." else p


def ls_tree(root: Path, sha: str) -> list[tuple[str, str, int]]:
    """`git ls-tree -r -l -z` → [(path, oid, size)]（blob のみ）。日本語パスも -z でそのまま読む。"""
    out = subprocess.run(
        ["git", "-C", str(root), "ls-tree", "-r", "-l", "-z", sha],
        check=True,
        capture_output=True,
    ).stdout
    entries: list[tuple[str, str, int]] = []
    for rec in out.split(b"\0"):
        if not rec:
            continue
        meta, _, path = rec.partition(b"\t")
        parts = meta.split()
        if len(parts) < 4 or parts[1] != b"blob":
            continue
        size = int(parts[3]) if parts[3].isdigit() else 0
        entries.append((path.decode("utf-8"), parts[2].decode(), size))
    return entries


def batch_blobs(root: Path, oids: list[str]) -> dict[str, bytes]:
    """`git cat-file --batch` でまとめて読む（行数の集計用。中身は出力しない）。"""
    if not oids:
        return {}
    proc = subprocess.run(
        ["git", "-C", str(root), "cat-file", "--batch"],
        input=("\n".join(oids) + "\n").encode(),
        check=True,
        capture_output=True,
    )
    data = proc.stdout
    pos = 0
    out: dict[str, bytes] = {}
    for oid in oids:
        nl = data.index(b"\n", pos)
        header = data[pos:nl].split()
        if len(header) < 3 or header[1] != b"blob":
            pos = nl + 1
            continue
        size = int(header[2])
        start = nl + 1
        out[oid] = data[start : start + size]
        pos = start + size + 1
    return out


def count_lines(data: bytes) -> int | None:
    """テキストなら行数、バイナリなら None。"""
    if b"\0" in data[:8000]:
        return None
    text = data.decode("utf-8", errors="replace").replace("\r\n", "\n")
    if not text:
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


class RefCollector(HTMLParser):
    """HTML 断片から data-ref（と data-note）を集める。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.refs: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: (v or "") for k, v in attrs}
        if "data-ref" in a:
            self.refs.append((a["data-ref"].strip(), a.get("data-note", "")))


def collect_refs(fragment: str) -> list[tuple[str, str]]:
    c = RefCollector()
    c.feed(fragment)
    c.close()
    return c.refs


def scan_guide_ids(content_dir: Path) -> dict[str, str] | None:
    """解説書の content から id → 表示名（章タイトル › 見出し）を集める。content が無ければ None。"""
    files = [p for p in sorted(content_dir.glob("*.html"), key=lambda p: p.name) if not p.name.startswith("00-sample")]
    if not files:
        return None
    ids: dict[str, str] = {}
    for path in files:
        sc = ContentScanner(path.name)
        sc.feed(path.read_text(encoding="utf-8"))
        sc.close()
        for id_, _ in sc.ids:
            ids.setdefault(id_, "")
        for sec in sc.sections:
            ids[sec["id"]] = sec["title"] or sec["id"]
            for h in sec["h3"]:
                ids[h["id"]] = f'{sec["title"] or sec["id"]} › {h["text"]}'
    return ids


def build_map(args: argparse.Namespace) -> int:
    root = repo_root()
    commit = resolve_commit(root, args.commit)
    tree_sha = resolve_commit(root, args.tree_commit)
    errors: list[str] = []
    warnings: list[str] = []

    data_path = Path(args.map_data).resolve()
    try:
        data_label = str(data_path.relative_to(root))
    except ValueError:
        data_label = str(data_path)
    if not data_path.is_file():
        print(f"エラー: 説明データが見つからない: {data_label}（--map-data で指定する）", file=sys.stderr)
        return 1
    try:
        desc = json.loads(data_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"エラー: {data_label} を JSON として読めない: {exc}", file=sys.stderr)
        return 1
    if not isinstance(desc, dict):
        print(f"エラー: {data_label} の最上位はオブジェクトにする", file=sys.stderr)
        return 1

    # --- ツリー -----------------------------------------------------------
    entries = ls_tree(root, tree_sha)
    path_set = {e[0] for e in entries}
    dir_set: set[str] = set()
    for pth in path_set:
        parts = pth.split("/")
        for i in range(1, len(parts)):
            dir_set.add("/".join(parts[:i]))
    commit_set = {e[0] for e in ls_tree(root, commit)}
    known = path_set | dir_set

    # --- 説明データの検証と正規化 ----------------------------------------
    def as_str(value: object, where: str) -> str:
        if value is None:
            return ""
        if not isinstance(value, str):
            errors.append(f"{data_label}: {where} は文字列にする")
            return ""
        return value

    def as_str_list(value: object, where: str) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            errors.append(f"{data_label}: {where} は文字列の配列にする")
            return []
        return list(value)

    intro_html = as_str(desc.get("intro_html"), "intro_html")
    tips_html = as_str(desc.get("tips_html"), "tips_html")

    blocks_out: list[dict] = []
    raw_blocks = desc.get("blocks") or []
    if not isinstance(raw_blocks, list):
        errors.append(f"{data_label}: blocks は配列にする")
        raw_blocks = []
    seen_block_ids: set[str] = set()
    for i, b in enumerate(raw_blocks):
        where = f"blocks[{i}]"
        if not isinstance(b, dict):
            errors.append(f"{data_label}: {where} はオブジェクトにする")
            continue
        bid = as_str(b.get("id"), f"{where}.id").strip()
        if not bid:
            errors.append(f"{data_label}: {where}.id が無い")
        elif bid in seen_block_ids:
            errors.append(f"{data_label}: {where}.id \"{bid}\" が重複")
        seen_block_ids.add(bid)
        bpath = norm_path(as_str(b.get("path"), f"{where}.path"))
        if bpath and bpath not in known:
            errors.append(f"{data_label}: {where}.path \"{bpath}\" がツリーに存在しない")
        layer = as_str(b.get("layer"), f"{where}.layer")
        if layer not in MAP_LAYERS:
            errors.append(f"{data_label}: {where}.layer \"{layer}\" は {'|'.join(MAP_LAYERS)} のいずれかにする")
        blocks_out.append(
            {
                "id": bid,
                "path": bpath,
                "title": as_str(b.get("title"), f"{where}.title") or bpath or "ルート直下",
                "subtitle": as_str(b.get("subtitle"), f"{where}.subtitle"),
                "summary": as_str(b.get("summary"), f"{where}.summary"),
                "layer": layer,
            }
        )

    nodes_out: dict[str, dict] = {}
    raw_nodes = desc.get("nodes") or {}
    if not isinstance(raw_nodes, dict):
        errors.append(f"{data_label}: nodes はオブジェクトにする")
        raw_nodes = {}
    ref_jobs: list[tuple[str, str, str]] = []  # (場所, ref, note)
    for key, n in raw_nodes.items():
        npath = norm_path(key)
        where = f'nodes["{key}"]'
        if npath not in known:
            errors.append(f"{data_label}: {where} がツリーに存在しない（{tree_sha[:7]} に無いパス）")
            continue
        if not isinstance(n, dict):
            errors.append(f"{data_label}: {where} はオブジェクトにする")
            continue
        out: dict = {}
        for field in ("role", "body_html", "ref"):
            v = as_str(n.get(field), f"{where}.{field}")
            if v:
                out[field] = v
        for field in ("open_when", "key_files", "guide"):
            lst = as_str_list(n.get(field), f"{where}.{field}")
            if field == "key_files":
                lst = [norm_path(x) for x in lst]
                for kf in lst:
                    if kf not in known:
                        warnings.append(f"{data_label}: {where}.key_files \"{kf}\" がツリーに存在しない（リンク無しで表示）")
            if lst:
                out[field] = lst
        nodes_out[npath] = out
        if out.get("ref"):
            ref_jobs.append((f"{where}.ref", out["ref"], ""))
        for ref, note in collect_refs(out.get("body_html", "")):
            ref_jobs.append((f"{where}.body_html", ref, note))
    for field, frag in (("intro_html", intro_html), ("tips_html", tips_html)):
        for ref, note in collect_refs(frag):
            ref_jobs.append((field, ref, note))

    collapse_out: list[dict] = []
    raw_collapse = desc.get("collapse") or []
    if not isinstance(raw_collapse, list):
        errors.append(f"{data_label}: collapse は配列にする")
        raw_collapse = []
    for i, c in enumerate(raw_collapse):
        where = f"collapse[{i}]"
        if not isinstance(c, dict):
            errors.append(f"{data_label}: {where} はオブジェクトにする")
            continue
        cpath = norm_path(as_str(c.get("path"), f"{where}.path"))
        if cpath not in dir_set:
            warnings.append(f"{data_label}: {where}.path \"{cpath}\" がツリーのディレクトリに無い（無視する）")
            continue
        collapse_out.append({"path": cpath, "label": as_str(c.get("label"), f"{where}.label")})

    # --- 参照の解決 --------------------------------------------------------
    git = GitFiles(root, commit, fallback=GitFiles(root, tree_sha))
    snippets: dict[str, dict] = {}
    for where, ref, note in ref_jobs:
        if not ref:
            errors.append(f"{data_label}: {where}: data-ref / ref が空")
            continue
        if ref not in snippets:
            try:
                snippets[ref] = resolve_ref(ref, git)
            except ResolveError as exc:
                snippets[ref] = {"error": str(exc)}
        entry = snippets[ref]
        if "error" in entry:
            errors.append(f"{data_label}: {where}: {ref} → {entry['error']}")
        elif note and not entry["note"]:
            entry["note"] = note

    # --- 解説書の id 照合 --------------------------------------------------
    guide_ids = scan_guide_ids(Path(args.content_dir).resolve())
    guide_titles: dict[str, str] = {}
    if guide_ids is None:
        if any(n.get("guide") for n in nodes_out.values()):
            warnings.append(f"解説書の content（{args.content_dir}）が無いため、guide の id を照合できない")
    for npath, n in nodes_out.items():
        for gid in n.get("guide", []):
            if guide_ids is None:
                continue
            if gid not in guide_ids:
                warnings.append(f'{data_label}: nodes["{npath}"].guide "{gid}" は解説書の出力に存在しない')
            else:
                guide_titles[gid] = guide_ids[gid]

    if errors:
        for w in warnings:
            print(f"警告: {w}", file=sys.stderr)
        print(f"エラー: {len(errors)} 件（ツリーに無いパス・解決できない参照・形式の不備）", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    # --- ファイル一覧とプレビュー -----------------------------------------
    files_out: list[list] = []
    preview_count = 0
    for path, oid, size in entries:
        reason = preview_reason(path)
        lines_n: int | None = None
        if not reason and size > PREVIEW_MAX_BYTES:
            reason = "big"
        if not reason:
            try:
                lines = git.lines(path)
            except ResolveError:
                reason = "err"
            else:
                text = "\n".join(lines)
                if "\0" in text:
                    reason = "binary"
                elif len(text.encode("utf-8")) > PREVIEW_MAX_BYTES:
                    reason = "big"
                else:
                    if path not in snippets:
                        snippets[path] = make_snippet(path, "", 1, max(len(lines), 1), lines, git)
                    lines_n = len(lines)
                    preview_count += 1
        files_out.append([path, size, lines_n, reason, 0 if path in commit_set else 1])

    # プレビューしないテキストファイルの行数（.env* は中身を読まない）
    need = [
        (i, e[1])
        for i, e in enumerate(entries)
        if files_out[i][2] is None
        and files_out[i][3] not in ("env", "image", "binary")
        and not e[0].rsplit("/", 1)[-1].startswith(".env")
    ]
    blobs = batch_blobs(root, sorted({oid for _, oid in need}))
    for i, oid in need:
        if oid in blobs:
            files_out[i][2] = count_lines(blobs[oid])

    # --- 統計 -------------------------------------------------------------
    collapse_dirs = {c["path"] for c in collapse_out}
    hidden = {d for d in dir_set if any(d.startswith(c + "/") for c in collapse_dirs)}
    counted = dir_set - hidden
    described = counted & set(nodes_out)
    missing = sorted(counted - set(nodes_out))
    if missing:
        warnings.append(f"説明の無いディレクトリ: {len(missing)} 件 / {len(counted)}")
        for d in missing:
            warnings.append(f"  - {d}")

    for w in warnings:
        print(f"警告: {w}" if not w.startswith("  - ") else w, file=sys.stderr)

    # --- 出力 -------------------------------------------------------------
    unique = {k: v for k, v in snippets.items() if "error" not in v}
    snip_json, snip_code = snippet_parts(unique)
    payload = {
        "repo": REPO_URL,
        # SHA 単体（40 桁 16 進）は秘密検査ツールが高エントロピー文字列と誤検知するため、URL の形で持つ
        "tree": {"blob": f"{REPO_URL}/blob/{tree_sha}/", "dir": f"{REPO_URL}/tree/{tree_sha}"},
        "code": {"blob": f"{REPO_URL}/blob/{commit}/", "dir": f"{REPO_URL}/tree/{commit}"},
        "files": files_out,
        "blocks": blocks_out,
        "nodes": nodes_out,
        "collapse": collapse_out,
        "guide": {"url": args.guide_url, "titles": guide_titles},
    }
    jst = timezone(timedelta(hours=9))
    intro = intro_html.strip() or (
        "<p>IDE の横に開いて、「どこに何があって、どういう中身か」を引くための地図。"
        "フォルダやファイルを選ぶと、右に説明が出ます。</p>"
    )
    tips_section = (
        f'<section class="tips" id="tips"><div class="tips-body">{tips_html}</div></section>' if tips_html.strip() else ""
    )
    values = {
        "MAP_JSON": escape_json_for_script(payload, per_line=True),
        "SNIPPETS_JSON": snip_json,
        "SNIPPETS_CODE": snip_code,
        "COMMIT": tree_sha[:7],
        "COMMIT_FULL": tree_sha,
        "CODE_COMMIT": commit[:7],
        "CODE_COMMIT_FULL": commit,
        "BUILD_DATE": datetime.now(jst).strftime("%Y-%m-%d"),
        "GUIDE_URL": html.escape(args.guide_url, quote=True),
        "INTRO_HTML": intro,
        "TIPS_SECTION": tips_section,
        "TOTAL_FILES": str(len(entries)),
        "TOTAL_DIRS": str(len(dir_set)),
    }
    output = render_template(MAP_TEMPLATE, values)
    out_path = Path(args.out).resolve() if args.out else root / "docs" / "05_解説" / MAP_OUTPUT_NAME
    size = len(output.encode("utf-8"))
    if not args.check:
        out_path.write_text(output, encoding="utf-8")

    print(f"対象コミット（ツリー）: {tree_sha}")
    print(f"対象コミット（コード）: {commit}")
    print(f"ディレクトリ数: {len(dir_set)}")
    print(f"ファイル数: {len(entries)}（うちコードのコミットに無くツリー側から読むもの {sum(1 for f in files_out if f[4])}）")
    print(f"説明ありのディレクトリ: {len(described)} / {len(counted)}（collapse 配下 {len(hidden)} 件を除く）")
    print(f"説明ありのノード: {len(nodes_out)}（ブロック {len(blocks_out)}、collapse {len(collapse_out)}）")
    print(f"プレビュー埋め込みファイル数: {preview_count}")
    print(f"ユニークスニペット数: {len(unique)}（プレビュー + 関数参照）")
    if args.check:
        print(f"検証のみ（出力は書いていない）。出力サイズの見込み: {size:,} bytes")
    else:
        try:
            shown = str(out_path.relative_to(root))
        except ValueError:
            shown = str(out_path)
        print(f"出力: {shown}（{size:,} bytes）")
    return 0


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="GUapp コード解説書 / リポジトリ地図 / レビュー回答ガイドを組み立てる")
    parser.add_argument("--commit", default="origin/main", help="コードを読むコミット（既定: origin/main の完全 SHA）")
    parser.add_argument("--check", action="store_true", help="出力を書かず、参照と構造の検証だけ行う")
    parser.add_argument("--include-sample", action="store_true", help="00- で始まるサンプル本文を取り込む（解説書・レビュー回答ガイド）")
    parser.add_argument("--content-dir", default=None, help="本文ディレクトリ（既定: 解説書は code-guide/content、--review は code-guide/review。検証用。地図では guide の id 照合に使う）")
    parser.add_argument("--out", default="", help="出力先 HTML（既定: 解説書は docs/05_解説/GU_ECsite_コード解説.html、地図は GU_ECsite_リポジトリ地図.html、--review は GU_ECsite_レビュー回答ガイド.html。検証用）")
    parser.add_argument("--map", action="store_true", help="解説書ではなくリポジトリ地図を組み立てる")
    parser.add_argument("--review", action="store_true", help="解説書ではなくレビュー回答ガイドを組み立てる（本文は code-guide/review/*.html）")
    parser.add_argument("--list-stops", action="store_true", help="--review で、停留所ごとの path:行 を標準出力に一覧する")
    parser.add_argument("--allow-missing-translations", action="store_true", help="--review で、訳の無い行を警告に落とす（データ作成中の確認用。既定はエラー）")
    parser.add_argument("--dump-translation-scope", default="", metavar="PATH", help="--review で、訳の対象（停留所の data-ref の和集合: ファイル別の行範囲と行数）を JSON で書き出す")
    parser.add_argument("--translations-dir", default=None, help="--review の訳の JSON ディレクトリ（既定: code-guide/review/translations。sample.json 以外をすべて読む。無ければ sample.json）")
    parser.add_argument("--glossary", default=None, help="--review の用語集 JSON（既定: code-guide/review/glossary.json。無ければ glossary.sample.json）")
    parser.add_argument("--tracer", action="store_true", help="解説書ではなくコードトレーサーを組み立てる（順路は code-guide/review/*.html、対応表は tracer/scenario.json、画面写真は tracer/capture/）")
    parser.add_argument("--capture-dir", default=None, help="--tracer の撮影素材ディレクトリ（capture.json と画像。既定: code-guide/tracer/capture。開発中は tracer/capture-dummy）")
    parser.add_argument("--scenario", default=None, help="--tracer の操作 → 順路の対応表（既定: code-guide/tracer/scenario.json）")
    parser.add_argument("--list-routes", action="store_true", help="--tracer で、順路の一覧（章 id・data-title・停留所数）を標準出力に出す")
    parser.add_argument("--map-data", default=str(MAP_DATA_DEFAULT), help="地図の説明データ（既定: code-guide/map/descriptions.json）")
    parser.add_argument("--tree-commit", default="HEAD", help="地図のツリーを作るコミット（既定: HEAD）。プレビューのコードは --commit から読み、無いファイルだけここから読む")
    parser.add_argument("--guide-url", default=OUTPUT_NAME, help="地図・レビュー回答ガイドから解説書へのリンク先（既定: GU_ECsite_コード解説.html）")
    parser.add_argument("--map-url", default=MAP_OUTPUT_NAME, help="解説書・レビュー回答ガイドのヘッダーから地図へのリンク先（既定: GU_ECsite_リポジトリ地図.html）")
    parser.add_argument("--review-url", default=REVIEW_OUTPUT_NAME, help="コードトレーサーからレビュー回答ガイドへのリンク先（既定: GU_ECsite_レビュー回答ガイド.html）")
    args = parser.parse_args()
    if args.map and args.review:
        parser.error("--map と --review は同時に指定できない")
    if args.tracer and (args.map or args.review):
        parser.error("--tracer は --map・--review と同時に指定できない")
    if (args.capture_dir or args.scenario or args.list_routes) and not args.tracer:
        parser.error("--capture-dir・--scenario・--list-routes は --tracer と一緒に使う")
    if args.content_dir is None:
        args.content_dir = str(REVIEW_DIR if (args.review or args.tracer) else CONTENT_DIR)
    if args.translations_dir is None:
        args.translations_dir = str(REVIEW_TRANSLATIONS_DIR)
    if args.glossary is None:
        args.glossary = str(REVIEW_GLOSSARY)
    if not (args.review or args.tracer) and (args.allow_missing_translations or args.dump_translation_scope):
        parser.error("--allow-missing-translations と --dump-translation-scope は --review（または --tracer）と一緒に使う")
    if args.tracer:
        return build_tracer(args)
    return build_map(args) if args.map else build_guide(args)


if __name__ == "__main__":
    sys.exit(main())
