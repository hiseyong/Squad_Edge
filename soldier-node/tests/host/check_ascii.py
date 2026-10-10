"""펌웨어 소스의 문자열 리터럴이 ASCII인지 검사(LOG는 ASCII 전용, 프로토콜 §5.3). 주석은 검사하지 않는다.
사용: python3 check_ascii.py <펌웨어 폴더>
"""
import pathlib
import sys


def literals(src):
    """(줄 번호, 문자열 리터럴) — 주석·문자 리터럴을 건너뛰는 단순 토크나이저."""
    i, n, line = 0, len(src), 1
    while i < n:
        c = src[i]
        if c == "\n":
            line += 1
        if src.startswith("//", i):
            j = src.find("\n", i)
            i = n if j < 0 else j
            continue
        if src.startswith("/*", i):
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            line += src.count("\n", i, j)
            i = j
            continue
        if c in "\"'":
            j = i + 1
            while j < n and src[j] != c:
                j += 2 if src[j] == "\\" else 1
            if c == '"':
                yield line, src[i + 1:j]
            i = j + 1
            continue
        i += 1


def main(root):
    bad = 0
    for p in sorted(pathlib.Path(root).rglob("*")):
        if p.suffix not in (".c", ".cpp", ".h", ".ino") or "assets" in p.parts:
            continue
        for line, lit in literals(p.read_text(encoding="utf-8")):
            if any(ord(ch) > 127 for ch in lit):
                print(f"{p}:{line}: non-ASCII string literal: \"{lit}\"")
                bad += 1
    print("firmware string literals ASCII check OK" if bad == 0 else f"{bad} non-ASCII literal(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
