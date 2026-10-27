#!/usr/bin/env python3
import sys
from pathlib import Path
from bs4 import BeautifulSoup

PAGES = ["congresos/2018.html","congresos/2019.html","congresos/2020.html","congresos/2021.html"]
KEYWORDS = ["laconeu","summer-school","summer_school","january-2027","january_2027"]

def is_wrong(img):
    for attr in ("src","alt","data-original-src","data-src","title"):
        if any(kw in img.get(attr,"").lower() for kw in KEYWORDS):
            return True
    return False

def remove_with_wrapper(img):
    node = img
    while node.parent and node.parent.name in ("figure","a","p","div","span"):
        parent = node.parent
        real = [c for c in parent.children if not (isinstance(c,str) and not c.strip())]
        if len(real)==1: node = parent
        else: break
    node.decompose()

def scan():
    import glob
    for f in sorted(glob.glob("congresos/*.html")):
        soup = BeautifulSoup(Path(f).read_text("utf-8"),"html.parser")
        imgs = soup.find_all("img")
        if imgs:
            print(f"\n{f}:")
            for img in imgs:
                print(f"  src={img.get('src',img.get('data-original-src','?'))[:100]!r}")

if "--scan" in sys.argv:
    scan()
else:
    for path_str in PAGES:
        p = Path(path_str)
        if not p.exists():
            print(f"○  no encontrado: {path_str}"); continue
        soup = BeautifulSoup(p.read_text("utf-8"),"html.parser")
        n = 0
        for img in soup.find_all("img"):
            if is_wrong(img):
                print(f"   {img.get('src',img.get('data-original-src','?'))[:80]}")
                remove_with_wrapper(img); n+=1
        if n:
            p.write_text(str(soup),"utf-8")
            print(f"✔  {path_str} — {n} imagen(es) eliminada(s)")
        else:
            print(f"⚠  {path_str} — no encontrada (ejecuta --scan)")
