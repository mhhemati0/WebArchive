import json,os,sys,threading,time,uuid,urllib.error,urllib.parse,urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from libzim.reader import Archive
from libzim.search import Query, Searcher
from .webarchive.setup import *
from .webarchive.kiwix_lib import KiwixLibraryDialog
from .webarchive.functions import *
from .webarchive.app import *
from gi.repository import Gtk, Adw, GLib,Gio
icon_theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
icon_theme.add_resource_path("/io/github/mhhemati0/WebArchive")
def main(version=None):
    app = WebArchivesApp()
    sys.argv[0] = str(Path(sys.argv[0]).resolve())
    return app.run(sys.argv)
if __name__ == "__main__":
    sys.exit(main())
