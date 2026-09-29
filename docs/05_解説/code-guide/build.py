#!/usr/bin/env python3
"""GUapp コード解説書の組み立てスクリプト（Python 3 標準ライブラリのみ）。

使い方（どのディレクトリから実行しても動く）:
    python3 docs/05_解説/code-guide/build.py [--commit SHA] [--check] [--include-sample]

- content/*.html をファイル名順に連結して template.html に差し込む
- 本文中の data-ref を `git show <sha>:<path>` で読んだコードに解決し、JSON として埋め込む
- 解決できない参照が 1 つでもあれば一覧を出して exit 1

data-ref の構文は README.md を参照。
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
OUTPUT_NAME = "GU_ECsite_コード解説.html"
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
    """`git show <sha>:<path>` の結果を行配列でキャッシュする。"""

    def __init__(self, root: Path, sha: str) -> None:
        self.root = root
        self.sha = sha
        self._cache: dict[str, list[str] | None] = {}

    def lines(self, path: str) -> list[str]:
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
        cached = self._cache[path]
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

    code = "\n".join(lines[start - 1 : end])
    url = f"{REPO_URL}/blob/{git.sha}/{quote(path, safe='/')}#L{start}-L{end}"
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


def escape_json_for_script(data: object) -> str:
    """`<` を \\u003c にして `</script>` や `<!--` が現れないようにする。"""
    s = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return s.replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="GUapp コード解説書を組み立てる")
    parser.add_argument("--commit", default="origin/main", help="対象コミット（既定: origin/main の完全 SHA）")
    parser.add_argument("--check", action="store_true", help="出力を書かず、参照と構造の検証だけ行う")
    parser.add_argument("--include-sample", action="store_true", help="00- で始まるサンプル本文を取り込む")
    parser.add_argument("--content-dir", default=str(CONTENT_DIR), help="本文ディレクトリ（既定: code-guide/content。検証用）")
    parser.add_argument("--out", default="", help="出力先 HTML（既定: docs/05_解説/GU_ECsite_コード解説.html。検証用）")
    args = parser.parse_args()

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
    content_html = "\n\n".join(chunks)

    jst = timezone(timedelta(hours=9))
    values = {
        "CONTENT": content_html,
        "TOC": build_toc(sections),
        "SNIPPETS_JSON": escape_json_for_script(unique),
        "COMMIT": sha[:7],
        "COMMIT_FULL": sha,
        "BUILD_DATE": datetime.now(jst).strftime("%Y-%m-%d"),
    }
    template = TEMPLATE.read_text(encoding="utf-8")
    # 1 回の走査で置換する（コード中の {{...}} を再置換しないため）
    output = re.sub(r"\{\{([A-Z_]+)\}\}", lambda m: values.get(m.group(1), m.group(0)), template)

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


if __name__ == "__main__":
    sys.exit(main())
