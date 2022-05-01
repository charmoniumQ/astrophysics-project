#!/usr/bin/env python
import time
import shutil
import subprocess
from pathlib import Path

def revealjs(index: Path) -> None:
    revealjs_path = Path(".cache/reveal.js")
    revealjs_url = "https://github.com/hakimel/reveal.js.git"
    if not revealjs_path.exists():
        subprocess.run(["git", "clone", revealjs_url, str(revealjs_path)], check=True)
        subprocess.run(["npm", "-C", str(revealjs_path), "install"], check=True)
    shutil.copy(index, revealjs_path / "index.html")
    proc = subprocess.Popen(["npm", "-C", str(revealjs_path), "start"])
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        proc.terminate()


if __name__ == "__main__":
    revealjs(Path("index.html"))
