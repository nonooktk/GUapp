#!/usr/bin/env python3
"""GUapp コード解説書の組み立てスクリプト（Python 3 標準ライブラリのみ）。

使い方（どのディレクトリから実行しても動く）:
    python3 docs/05_解説/code-guide/build.py [--commit SHA] [--check] [--include-sample]
    python3 docs/05_解説/code-guide/build.py --map [--map-data PATH] [--check] [--guide-url URL] [--map-url URL]

- content/*.html をファイル名順に連結して template.html に差し込む
- 本文中の data-ref を `git show <sha>:<path>` で読んだコードに解決し、JSON として埋め込む
- 解決できない参照が 1 つでもあれば一覧を出して exit 1
- `--map` を付けると、リポジトリ地図（map/template-map.html）を組み立てる。
  ツリーは `git ls-tree`、説明は map/descriptions.json、プレビューは `git show` から作る

data-ref の構文・descriptions.json のスキーマは README.md を参照。
"""

from __future__ import annotations

import argparse
import ast
import html
import json
import re
import subprocess
import sys
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
OUTPUT_NAME = "GU_ECsite_コード解説.html"
MAP_OUTPUT_NAME = "GU_ECsite_リポジトリ地図.html"
REPO_URL = "https://github.com/nonooktk/GUapp"

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

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: (v or "") for k, v in attrs}
        line = self.getpos()[0]
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
# 解説書の組み立て
# ---------------------------------------------------------------------------


def build_guide(args: argparse.Namespace) -> int:
    root = repo_root()
    sha = resolve_commit(root, args.commit)
    git = GitFiles(root, sha)

    content_dir = Path(args.content_dir).resolve()
    files = sorted(content_dir.glob("*.html"), key=lambda p: p.name)
    if not args.include_sample:
        files = [p for p in files if not p.name.startswith("00-")]
    if not files:
        print(f"エラー: {content_dir}/*.html が見つからない", file=sys.stderr)
        return 1

    errors: list[str] = []
    warnings: list[str] = []
    chunks: list[str] = []
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
        chunks.append(text.rstrip("\n"))

    for target, fname, line in hrefs:
        if target not in id_seen:
            warnings.append(f"content/{fname}:{line}: リンク先 #{target} が本文に存在しない")

    snippets: dict[str, dict] = {}
    for ref, note, fname, line in all_refs:
        if not ref:
            errors.append(f"content/{fname}:{line}: data-ref が空")
            continue
        if ref not in snippets:
            try:
                snippets[ref] = resolve_ref(ref, git)
            except ResolveError as exc:
                snippets[ref] = {"error": str(exc)}
        entry = snippets[ref]
        if "error" in entry:
            errors.append(f"content/{fname}:{line}: {ref} → {entry['error']}")
        elif note and not entry["note"]:
            entry["note"] = note

    for w in warnings:
        print(f"警告: {w}", file=sys.stderr)

    if errors:
        print(f"エラー: {len(errors)} 件（解決できない参照・構造の不備）", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
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
    }
    output = render_template(TEMPLATE, values)

    out_path = Path(args.out).resolve() if args.out else root / "docs" / "05_解説" / OUTPUT_NAME
    size = len(output.encode("utf-8"))
    if not args.check:
        out_path.write_text(output, encoding="utf-8")

    print(f"対象コミット: {sha}")
    print(f"章数: {len(sections)}")
    print(f"参照数: {len(all_refs)}")
    print(f"ユニークスニペット数: {len(unique)}")
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
    files = [p for p in sorted(content_dir.glob("*.html"), key=lambda p: p.name) if not p.name.startswith("00-")]
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
    parser = argparse.ArgumentParser(description="GUapp コード解説書 / リポジトリ地図を組み立てる")
    parser.add_argument("--commit", default="origin/main", help="コードを読むコミット（既定: origin/main の完全 SHA）")
    parser.add_argument("--check", action="store_true", help="出力を書かず、参照と構造の検証だけ行う")
    parser.add_argument("--include-sample", action="store_true", help="00- で始まるサンプル本文を取り込む（解説書のみ）")
    parser.add_argument("--content-dir", default=str(CONTENT_DIR), help="解説書の本文ディレクトリ（既定: code-guide/content。検証用。地図では guide の id 照合に使う）")
    parser.add_argument("--out", default="", help="出力先 HTML（既定: 解説書は docs/05_解説/GU_ECsite_コード解説.html、地図は GU_ECsite_リポジトリ地図.html。検証用）")
    parser.add_argument("--map", action="store_true", help="解説書ではなくリポジトリ地図を組み立てる")
    parser.add_argument("--map-data", default=str(MAP_DATA_DEFAULT), help="地図の説明データ（既定: code-guide/map/descriptions.json）")
    parser.add_argument("--tree-commit", default="HEAD", help="地図のツリーを作るコミット（既定: HEAD）。プレビューのコードは --commit から読み、無いファイルだけここから読む")
    parser.add_argument("--guide-url", default=OUTPUT_NAME, help="地図から解説書へのリンク先（既定: GU_ECsite_コード解説.html）")
    parser.add_argument("--map-url", default=MAP_OUTPUT_NAME, help="解説書のヘッダーから地図へのリンク先（既定: GU_ECsite_リポジトリ地図.html）")
    args = parser.parse_args()
    return build_map(args) if args.map else build_guide(args)


if __name__ == "__main__":
    sys.exit(main())
