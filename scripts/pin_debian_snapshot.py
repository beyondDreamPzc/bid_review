"""Image-local apt source pin, never changes the host machine."""
from pathlib import Path

path=Path("/etc/apt/sources.list.d/debian.sources")
text=path.read_text()
for scheme in ("http","https"):
    text=text.replace(f"{scheme}://deb.debian.org/debian-security",
        "https://snapshot.debian.org/archive/debian-security/20261021T000000Z/")
    text=text.replace(f"{scheme}://deb.debian.org/debian",
        "https://snapshot.debian.org/archive/debian/20261021T000000Z/")
path.write_text(text)
