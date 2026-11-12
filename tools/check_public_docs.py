"""Reject unmasked contact examples in public text documentation."""
import argparse
from pathlib import Path
import re
import subprocess

PATTERNS = {
    "unmasked mobile number": re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    "unmasked street and house number": re.compile(r"[\u4e00-\u9fff]{2,}(?:路|街|巷)\s*\d+\s*(?:号|弄)"),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged", action="store_true", help="Check the exact staged documentation")
    args = parser.parse_args()
    root = Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"]).decode().strip())
    command = ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"] if args.staged else ["git", "ls-files", "-z"]
    names = subprocess.check_output(command, cwd=root).decode().split("\0")
    failures = []
    for name in filter(None, names):
        if Path(name).suffix.lower() not in (".md", ".txt"):
            continue
        content = subprocess.check_output(["git", "show", ":" + name], cwd=root).decode("utf-8-sig") if args.staged else (root / name).read_text(encoding="utf-8-sig")
        for number, line in enumerate(content.splitlines(), 1):
            for label, pattern in PATTERNS.items():
                if pattern.search(line):
                    failures.append(f"{name}:{number}: {label}")
    if failures:
        # Never echo the actual personal values into public CI logs.
        raise SystemExit("\n".join(failures))
    print("Public documentation contact-format check passed.")


if __name__ == "__main__":
    main()
