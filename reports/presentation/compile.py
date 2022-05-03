#!/usr/bin/env python
import os
import shutil
import subprocess
import time
from pathlib import Path


def revealjs(source: Path) -> None:
    revealjs_path = source / "reveal.js"
    revealjs_url = "https://github.com/hakimel/reveal.js.git"
    if not revealjs_path.exists():
        subprocess.run(["git", "clone", revealjs_url, str(revealjs_path)], check=True)
        subprocess.run(["npm", "-C", str(revealjs_path), "install"], check=True)
    if (revealjs_path / "index.html").exists():
        (revealjs_path / "index.html").unlink()
    os.link("index.html", revealjs_path / "index.html")
    if (revealjs_path / "assets").exists():
        shutil.rmtree(revealjs_path / "assets")
    (revealjs_path / "assets").mkdir()
    for path in Path("assets").iterdir():
        os.link(path, revealjs_path / "assets" / path.name)
    proc = subprocess.Popen(["npm", "-C", str(revealjs_path), "start"])
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        proc.terminate()


if __name__ == "__main__":
    os.chdir(Path(__file__).parent)
    revealjs(Path())
