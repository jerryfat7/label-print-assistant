"""Install a checksummed upstream Noto CJK font for this user; no sudo needed."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
from urllib.request import urlopen

UPSTREAM = "https://raw.githubusercontent.com/notofonts/noto-cjk/f8d157532fbfaeda587e826d4cd5b21a49186f7c"
FILES = {
    "NotoSansCJKsc-Regular.otf": (
        "/Sans/OTF/SimplifiedChinese/NotoSansCJKsc-Regular.otf",
        "2c76254f6fc379fddfce0a7e84fb5385bb135d3e399294f6eeb6680d0365b74b"),
    "LICENSE": ("/Sans/LICENSE", "6a73f9541c2de74158c0e7cf6b0a58ef774f5a780bf191f2d7ec9cc53efe2bf2"),
}


def main():
    if not shutil.which("fc-cache"):
        raise SystemExit("fontconfig (fc-cache) is required")
    target = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "fonts/label-print-assistant"
    target.mkdir(parents=True, exist_ok=True)
    for name, (relative, expected) in FILES.items():
        path = target / name
        if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == expected:
            continue
        with urlopen(UPSTREAM + relative, timeout=60) as response:
            data = response.read(32 * 1024 * 1024)
        if hashlib.sha256(data).hexdigest() != expected:
            raise SystemExit(f"Font download checksum mismatch: {name}")
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(data)
        temporary.replace(path)
    subprocess.run(["fc-cache", "-f", str(target)], check=True)
    print("Installed Noto Sans CJK SC, with upstream SIL Open Font License:", target)


if __name__ == "__main__":
    main()
