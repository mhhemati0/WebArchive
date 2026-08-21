# WebArchive

A GTK4 / libadwaita desktop app for browsing offline **ZIM archives** — the
format used to package entire websites (Wikipedia, Wiktionary, Stack
Exchange, TED talks, and more) for reading with no internet connection.

## Features

- **Browse and read ZIM archives** — open `.zim` files and view their pages
  rendered just like the original website, powered by WebKitGTK.
- **Full-text search inside an archive** using libzim's built-in search
  index.
- **Bookmarks** — save pages within an archive for quick access later.
- **History** — recently visited pages are tracked per archive.
- **Kiwix library browser** — search and browse the public
  [Kiwix library](https://library.kiwix.org) catalog from inside the app,
  filter by language and category, and download new archives straight to
  your ZIM folder.
- **No server required** — reads ZIM files directly via `libzim`, with no
  `kiwix-serve` process running in the background.

## Why

Most offline-Wikipedia readers either require running a local server or
lack a proper native GNOME interface. WebArchive aims for feature parity
with Kiwix's reading experience while feeling like a first-class GTK4/
libadwaita application.

## Installing

<!-- Once published on Flathub:
```
flatpak install flathub io.github.mhhemati0.WebArchive
```
-->

Not yet published — see [Building](#building) to run it from source.

## Getting ZIM files

Place `.zim` files in the folder you prefer, or download them directly from the
built-in Kiwix library browser inside the app. More archives are available
at [library.kiwix.org](https://library.kiwix.org).

## Building

Requires `flatpak` and `flatpak-builder`, plus the GNOME 50 platform/SDK:

```bash
flatpak install flathub org.gnome.Platform//50 org.gnome.Sdk//50
flatpak-builder --user --install --force-clean build-dir io.github.mhhemati0.WebArchive.json
flatpak run io.github.mhhemati0.WebArchive
```

## Tech stack

- Python 3 + PyGObject (GTK4, libadwaita)
- [`libzim`](https://pypi.org/project/libzim/) for reading ZIM archives and
  full-text search
- WebKitGTK for rendering, via a custom registered `zim://` URI scheme
- Meson build system, packaged as a Flatpak

## License

GPL-3.0-or-later — see [LICENSE](LICENSE).

## Contributing

Issues and pull requests are welcome at
[github.com/mhhemati0/WebArchive](https://github.com/mhhemati0/WebArchive).
