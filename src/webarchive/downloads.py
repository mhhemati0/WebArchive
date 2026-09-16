import json
import os
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from gi.repository import GLib, GObject

from libzim.reader import Archive

from .state import APP_DATA_DIR, describe_download_error

DOWNLOADS_FILE = APP_DATA_DIR / "downloads.json"

STATUS_QUEUED = "queued"
STATUS_DOWNLOADING = "downloading"
STATUS_PAUSED = "paused"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"

_ACTIVE_STATUSES = (STATUS_QUEUED, STATUS_DOWNLOADING)

_BLOCK_SIZE = 262144
_UI_UPDATE_INTERVAL = 0.2
_SAVE_INTERVAL = 1.0


class DownloadManager(GObject.Object):
    """Singleton. Access it with DownloadManager.get()."""

    __gsignals__ = {
        "download-changed": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "download-removed": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    _instance = None

    def __init__(self):
        super().__init__()
        self._downloads = {}
        self._completed_zim_ids = {}
        self._pause_events = {}
        self._cancel_flags = set()
        self._save_scheduled = False

    @classmethod
    def get(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    def load(self):
        if not DOWNLOADS_FILE.exists():
            return
        try:
            payload = json.loads(DOWNLOADS_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            print(f"Could not load downloads state: {e}")
            return
        self._downloads = payload.get("downloads", {}) or {}
        self._completed_zim_ids = payload.get("completed_zim_ids", {}) or {}
        for zid, path in list(self._completed_zim_ids.items()):
            if not path or not Path(path).exists():
                del self._completed_zim_ids[zid]
        stale_ids = []
        for did, rec in list(self._downloads.items()):
            if rec.get("status") == STATUS_COMPLETED:
                if not Path(rec.get("target_path", "")).exists():
                    stale_ids.append(did)
                continue
            if rec.get("status") in (STATUS_DOWNLOADING, STATUS_QUEUED):
                rec["status"] = STATUS_QUEUED

        for did in stale_ids:
            del self._downloads[did]

    def auto_resume_all(self):
        for rec in list(self._downloads.values()):
            if rec.get("status") == STATUS_QUEUED:
                self._launch_worker(rec["id"])

    def shutdown(self):
        active_ids = [
            did for did, rec in self._downloads.items()
            if rec.get("status") in _ACTIVE_STATUSES
        ]
        for did in active_ids:
            ev = self._pause_events.get(did)
            if ev is not None:
                ev.set()

        if active_ids:
            time.sleep(0.3)

        for did in active_ids:
            rec = self._downloads.get(did)
            if rec and rec.get("status") != STATUS_COMPLETED:
                rec["status"] = STATUS_QUEUED

        self._save_now()

    def _schedule_save(self):
        if self._save_scheduled:
            return
        self._save_scheduled = True

        def _do_save():
            self._save_scheduled = False
            self._save_now()
            return False

        GLib.timeout_add(int(_SAVE_INTERVAL * 1000), _do_save)

    def _save_now(self):
        try:
            payload = {
                "downloads": self._downloads,
                "completed_zim_ids": self._completed_zim_ids,
            }
            tmp_path = DOWNLOADS_FILE.with_suffix(".json.tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f)
            os.replace(tmp_path, DOWNLOADS_FILE)
        except OSError as e:
            print(f"Could not save downloads state: {e}")
    def list_downloads(self):
        return list(self._downloads.values())

    def get_download(self, download_id):
        return self._downloads.get(download_id)

    def find_by_zim_id(self, zim_id):
        if not zim_id:
            return None
        for rec in self._downloads.values():
            if rec.get("zim_id") == zim_id and rec.get("status") != STATUS_COMPLETED:
                return rec
        return None

    def completed_path_for(self, zim_id):
        if not zim_id:
            return None
        path = self._completed_zim_ids.get(zim_id)
        if path and Path(path).exists():
            return path
        return None

    def register_local_zim(self, zim_id, path):
        if not zim_id or not path:
            return
        if self._completed_zim_ids.get(zim_id) != str(path):
            self._completed_zim_ids[zim_id] = str(path)
            self._schedule_save()
    def start_download(self, zim_id, title, url, target_path, total_bytes=None):
        target_path = Path(target_path)

        existing_path = self.completed_path_for(zim_id)
        if existing_path:
            return {"status": "already_downloaded", "path": existing_path}

        existing = self.find_by_zim_id(zim_id)
        if existing:
            if existing["status"] == STATUS_PAUSED:
                self.resume_download(existing["id"])
            return {"status": "in_progress", "id": existing["id"]}

        download_id = uuid.uuid4().hex
        record = {
            "id": download_id,
            "zim_id": zim_id,
            "title": title or target_path.name,
            "url": url,
            "target_path": str(target_path),
            "tmp_path": str(target_path.with_name(target_path.name + ".part")),
            "total_bytes": total_bytes,
            "downloaded_bytes": 0,
            "status": STATUS_QUEUED,
            "error": None,
        }
        self._downloads[download_id] = record
        self._schedule_save()
        self._emit_changed(download_id)
        self._launch_worker(download_id)
        return {"status": "started", "id": download_id}

    def resume_download(self, download_id):
        rec = self._downloads.get(download_id)
        if not rec or rec["status"] not in (STATUS_PAUSED, STATUS_FAILED):
            return
        rec["status"] = STATUS_QUEUED
        rec["error"] = None
        self._schedule_save()
        self._emit_changed(download_id)
        self._launch_worker(download_id)

    def pause_download(self, download_id):
        rec = self._downloads.get(download_id)
        if not rec or rec["status"] not in _ACTIVE_STATUSES:
            return
        ev = self._pause_events.get(download_id)
        if ev is not None:
            ev.set()
        else:
            rec["status"] = STATUS_PAUSED
            self._schedule_save()
            self._emit_changed(download_id)

    def cancel_download(self, download_id):
        """Stop the download (if running) and remove it, deleting any
        partially-downloaded data. Also used to clear finished/failed
        entries from the downloads list."""
        rec = self._downloads.get(download_id)
        if not rec:
            return
        self._cancel_flags.add(download_id)
        ev = self._pause_events.get(download_id)
        if ev is not None:
            ev.set()
        if rec["status"] not in _ACTIVE_STATUSES:
            self._finalize_removal(download_id)

    def _finalize_removal(self, download_id):
        rec = self._downloads.pop(download_id, None)
        self._pause_events.pop(download_id, None)
        self._cancel_flags.discard(download_id)
        if rec and rec.get("status") != STATUS_COMPLETED:
            try:
                Path(rec["tmp_path"]).unlink(missing_ok=True)
            except OSError:
                pass
        self._schedule_save()
        self.emit("download-removed", download_id)
        return False
    def _emit_changed(self, download_id):
        GLib.idle_add(self.emit, "download-changed", download_id)

    def _launch_worker(self, download_id):
        event = threading.Event()
        self._pause_events[download_id] = event
        threading.Thread(
            target=self._download_worker, args=(download_id, event), daemon=True
        ).start()

    def _download_worker(self, download_id, pause_event):
        rec = self._downloads.get(download_id)
        if rec is None:
            return

        target_path = Path(rec["target_path"])
        tmp_path = Path(rec["tmp_path"])
        url = rec["url"]

        rec["status"] = STATUS_DOWNLOADING
        rec["error"] = None
        self._emit_changed(download_id)

        resume_offset = tmp_path.stat().st_size if tmp_path.exists() else 0
        headers = {"User-Agent": "WebArchivesGtk/1.0"}
        if resume_offset:
            headers["Range"] = f"bytes={resume_offset}-"

        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=30) as response:
                server_supports_resume = resume_offset and getattr(response, "status", 200) == 206
                if server_supports_resume:
                    mode = "ab"
                    downloaded = resume_offset
                    total = rec.get("total_bytes")
                    content_range = response.headers.get("Content-Range", "")
                    if "/" in content_range:
                        try:
                            total = int(content_range.rsplit("/", 1)[-1])
                        except ValueError:
                            pass
                else:
                    mode = "wb"
                    downloaded = 0
                    content_length = response.headers.get("Content-Length")
                    total = int(content_length) if content_length else rec.get("total_bytes")

                rec["total_bytes"] = total
                rec["downloaded_bytes"] = downloaded

                last_ui_update = 0.0
                with open(tmp_path, mode) as f:
                    while True:
                        if pause_event.is_set():
                            rec["downloaded_bytes"] = downloaded
                            self._pause_events.pop(download_id, None)
                            if download_id in self._cancel_flags:
                                GLib.idle_add(self._finalize_removal, download_id)
                            else:
                                rec["status"] = STATUS_PAUSED
                                self._schedule_save()
                                self._emit_changed(download_id)
                            return

                        chunk = response.read(_BLOCK_SIZE)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        rec["downloaded_bytes"] = downloaded

                        now = time.monotonic()
                        if now - last_ui_update > _UI_UPDATE_INTERVAL:
                            last_ui_update = now
                            self._emit_changed(download_id)

            if downloaded == 0:
                raise IOError("Downloaded file is empty.")
            if rec.get("total_bytes") and downloaded < rec["total_bytes"]:
                raise IOError(
                    f"Incomplete download: got {downloaded} of {rec['total_bytes']} bytes"
                )

            os.replace(tmp_path, target_path)
            rec["downloaded_bytes"] = downloaded
            rec["status"] = STATUS_COMPLETED
            rec["error"] = None

            zim_id = rec.get("zim_id")
            if zim_id:
                self._completed_zim_ids[zim_id] = str(target_path)
            try:
                real_id = str(Archive(str(target_path)).uuid)
                if real_id:
                    self._completed_zim_ids[real_id] = str(target_path)
            except Exception:
                pass

            self._pause_events.pop(download_id, None)
            self._schedule_save()
            self._emit_changed(download_id)

        except Exception as exc:
            self._pause_events.pop(download_id, None)
            if download_id in self._cancel_flags:
                GLib.idle_add(self._finalize_removal, download_id)
                return
            rec["status"] = STATUS_FAILED
            rec["error"] = describe_download_error(exc)
            self._schedule_save()
            self._emit_changed(download_id)
