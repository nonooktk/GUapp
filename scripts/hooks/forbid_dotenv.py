"""pre-commit ローカルフック: .env 系ファイルのステージを名前で拒否する（.env.example のみ許可）。

.gitignore と二重化した保険。設計仕様書 7.2（DS-DEC-13）。
"""

import sys
from pathlib import PurePosixPath


def main(paths: list[str]) -> int:
    bad = []
    for p in paths:
        name = PurePosixPath(p.replace("\\", "/")).name
        if name == ".env.example":
            continue
        if name == ".env" or name.startswith(".env."):
            bad.append(p)
    for p in bad:
        print(f"拒否: {p} は秘匿ファイルです。コミットできません（設計仕様書 7.2）")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
