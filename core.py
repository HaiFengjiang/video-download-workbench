#!/usr/bin/env python3
"""视频下载工具台核心：任务队列与下载引擎（仅使用 Python 标准库）。"""

from __future__ import annotations

import json
import locale
import os
import re
import shutil
import subprocess
import threading
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
CONFIG_FILE = DATA_DIR / "config.json"
STATE_FILE = DATA_DIR / "tasks.json"
DEFAULT_OUTPUT = BASE_DIR / "downloads"

# 界面设置可选项
LANGUAGES = ("zh", "en", "ja", "ko")
SOUNDS = ("chime", "bell", "pop", "coin")

# 界面预设：每一项对应一组 yt-dlp 参数
PRESETS = {
    "best": {
        "label": "最高画质",
        "hint": "最佳视频 + 最佳音频，合并为 MP4",
        "args": ["-f", "bv*+ba/b", "--merge-output-format", "mp4"],
    },
    "p1080": {
        "label": "1080P 以内",
        "hint": "优先不超过 1080P，兼顾体积与速度",
        "args": ["-S", "res:1080", "--merge-output-format", "mp4"],
    },
    "video": {
        "label": "仅视频",
        "hint": "只保留画面，不下载音轨（无纯视频流时回退到普通文件）",
        "args": ["-f", "bv/b"],
    },
    "audio": {
        "label": "仅音频",
        "hint": "提取音轨并转码为 MP3，音质最高",
        "args": ["-f", "ba/b", "-x", "--audio-format", "mp3", "--audio-quality", "0"],
    },
}

# 自定义进度行，便于稳定解析：百分比|已下载|总大小|速度|剩余时间
PROGRESS_PREFIX = "__PROG__"
PROGRESS_TPL = (
    "download:" + PROGRESS_PREFIX + " "
    "%(progress._percent_str)s|%(progress._downloaded_bytes_str)s|"
    "%(progress._total_bytes_estimate_str)s|%(progress._speed_str)s|%(progress._eta_str)s"
)

OUTPUT_TEMPLATE = "%(title).150B [%(id)s].%(ext)s"

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
POSTPROCESS_RE = re.compile(
    r"^\[(Merger|ExtractAudio|VideoConvertor|Fixup\w+|Metadata|EmbedSubtitle|EmbedThumbnail|MoveFiles)\]"
)
HISTORY_LIMIT = 300
LOG_LIMIT = 600
FINISH_LOG_KEEP = 80

# yt-dlp.exe 在 Windows 上按系统 ANSI 编码（中文系统为 GBK）输出，需据此解码。
# locale.getencoding() 不受 Python 的 UTF-8 模式影响，能拿到真正的 cp936。
def _system_output_encoding() -> str:
    try:
        return locale.getencoding()
    except AttributeError:
        pass
    if os.name == "nt":
        try:
            import ctypes

            return f"cp{ctypes.windll.kernel32.GetACP()}"
        except Exception:
            pass
    return locale.getpreferredencoding(False) or "utf-8"


OUTPUT_ENCODING = _system_output_encoding()


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_json(path: Path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def find_ytdlp() -> str:
    env = os.environ.get("YTDLP_PATH", "").strip()
    if env and Path(env).is_file():
        return env
    for candidate in (BASE_DIR / "yt-dlp.exe", BASE_DIR.parent / "yt-dlp.exe", BASE_DIR / "yt-dlp"):
        if candidate.is_file():
            return str(candidate)
    found = shutil.which("yt-dlp")
    return found or "yt-dlp"


LOCAL_TOOLS = ("yt-dlp.exe", "yt-dlp", "ffmpeg.exe", "ffmpeg")


def ensure_local_bin_path() -> None:
    """把含 yt-dlp / ffmpeg 的程序目录加入当前进程 PATH，无需修改系统环境变量。"""
    path = os.environ.get("PATH", "")
    parts = path.split(os.pathsep)
    for directory in (BASE_DIR, BASE_DIR.parent):
        try:
            if not any((directory / name).is_file() for name in LOCAL_TOOLS):
                continue
        except OSError:
            continue
        if str(directory) not in parts:
            parts.insert(0, str(directory))
    os.environ["PATH"] = os.pathsep.join(parts)


def build_args(output_dir: str, preset: str, playlist: bool) -> list[str]:
    args = [
        "--newline",
        "--progress-template", PROGRESS_TPL,
        "-P", output_dir,
        "-o", OUTPUT_TEMPLATE,
    ]
    if not playlist:
        args.append("--no-playlist")
    args.extend(PRESETS[preset]["args"])
    return args


def title_from_path(path: str) -> str:
    if not path:
        return ""
    stem = Path(path).stem
    cleaned = re.sub(r"\s*\[[A-Za-z0-9_-]{6,}\]$", "", stem)
    return cleaned or stem


def to_float(value: str):
    try:
        return float(value.replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def clean_field(value: str) -> str:
    value = (value or "").strip()
    if value.upper() in ("NA", "N/A", "NONE") or value.lower().startswith("unknown"):
        return ""
    return value


def probe_version(executable: str) -> str:
    try:
        proc = subprocess.run(
            [executable, "--version"],
            capture_output=True, text=True, encoding=OUTPUT_ENCODING, errors="replace", timeout=20,
        )
        return (proc.stdout or "").strip().splitlines()[0] if proc.stdout else ""
    except Exception:
        return ""


def terminate_tree(proc: subprocess.Popen) -> None:
    """Windows 上 yt-dlp.exe 会派生子进程，必须按进程树结束。"""
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=15,
            )
            return
        except Exception:
            pass
    try:
        proc.kill()
    except Exception:
        pass


class Manager:
    def __init__(self):
        self.lock = threading.RLock()
        self.cond = threading.Condition(self.lock)
        self.tasks: dict[str, dict] = {}
        self.order: list[str] = []
        self.version = 0
        self.history_version = 0
        self.procs: dict[str, subprocess.Popen] = {}
        ensure_local_bin_path()
        self.ytdlp = find_ytdlp()
        self.ytdlp_version = probe_version(self.ytdlp)
        self.ffmpeg = bool(shutil.which("ffmpeg"))
        self._last_persist = 0.0
        self.config = self._load_config()
        self._load_tasks()
        threading.Thread(target=self._schedule_loop, daemon=True, name="scheduler").start()

    # ---------- 配置与持久化 ----------

    def _load_config(self) -> dict:
        cfg = {
            "output_dir": str(DEFAULT_OUTPUT),
            "concurrency": 2,
            "theme": "dark",
            "language": "zh",
            "animations": True,
            "sound_enabled": True,
            "sound_name": "chime",
        }
        raw = load_json(CONFIG_FILE, {})
        if isinstance(raw, dict):
            if isinstance(raw.get("output_dir"), str) and raw["output_dir"].strip():
                cfg["output_dir"] = raw["output_dir"].strip()
            if isinstance(raw.get("concurrency"), int):
                cfg["concurrency"] = max(1, min(4, raw["concurrency"]))
            if raw.get("theme") in ("dark", "light"):
                cfg["theme"] = raw["theme"]
            if raw.get("language") in LANGUAGES:
                cfg["language"] = raw["language"]
            if isinstance(raw.get("animations"), bool):
                cfg["animations"] = raw["animations"]
            if isinstance(raw.get("sound_enabled"), bool):
                cfg["sound_enabled"] = raw["sound_enabled"]
            if raw.get("sound_name") in SOUNDS:
                cfg["sound_name"] = raw["sound_name"]
        path = Path(cfg["output_dir"]).expanduser()
        if not path.is_absolute():
            path = (BASE_DIR / path).resolve()
        try:
            path.mkdir(parents=True, exist_ok=True)
            cfg["output_dir"] = str(path)
        except Exception:
            cfg["output_dir"] = str(DEFAULT_OUTPUT)
            DEFAULT_OUTPUT.mkdir(parents=True, exist_ok=True)
        return cfg

    def _load_tasks(self) -> None:
        raw = load_json(STATE_FILE, {})
        tasks = raw.get("tasks") if isinstance(raw, dict) else []
        if not isinstance(tasks, list):
            tasks = []
        interrupted = 0
        for task in tasks:
            if not isinstance(task, dict) or not task.get("id"):
                continue
            for legacy in ("tokens", "display", "log_tail"):
                task.pop(legacy, None)
            if task.get("preset") not in PRESETS:
                task["preset"] = "best"
            task.setdefault("title", "")
            task.setdefault("phase", None)
            task.setdefault("error", "")
            task.setdefault("output_file", "")
            task.setdefault("playlist", False)
            task.setdefault("command", [])
            task.setdefault("cancel_requested", False)
            task.setdefault("created_at", now_str())
            task.setdefault("started_at", "")
            task.setdefault("finished_at", "")
            if not isinstance(task.get("progress"), dict):
                task["progress"] = {}
            for key in ("percent", "downloaded", "total", "speed", "eta"):
                task["progress"].setdefault(
                    key, 0.0 if key == "percent" else ""
                )
            if not isinstance(task.get("log"), list):
                task["log"] = []
            if task.get("status") in ("pending", "running"):
                task["status"] = "error"
                task["phase"] = None
                task["error"] = "程序上次退出时任务未完成"
                task["finished_at"] = task.get("finished_at") or now_str()
                interrupted += 1
            self.tasks[task["id"]] = task
            self.order.append(task["id"])
        if tasks:
            self.save_state()
        if interrupted:
            self.history_version += 1

    def save_state(self) -> None:
        try:
            save_json(STATE_FILE, {"version": 1, "tasks": [self.tasks[i] for i in self.order]})
        except Exception:
            pass

    def _bump(self) -> None:
        self.version += 1
        self.cond.notify_all()

    def _maybe_persist(self) -> None:
        now = datetime.now().timestamp()
        if now - self._last_persist >= 4:
            self._last_persist = now
            self.save_state()

    # ---------- 任务生命周期 ----------

    def _new_task(self, url: str, preset: str, playlist: bool) -> dict:
        args = build_args(self.config["output_dir"], preset, playlist)
        task = {
            "id": uuid.uuid4().hex[:8],
            "url": url,
            "preset": preset,
            "playlist": playlist,
            "status": "pending",
            "phase": None,
            "progress": {"percent": 0.0, "downloaded": "", "total": "", "speed": "", "eta": ""},
            "title": "",
            "command": [self.ytdlp] + args + [url],
            "output_file": "",
            "error": "",
            "log": [],
            "cancel_requested": False,
            "created_at": now_str(),
            "started_at": "",
            "finished_at": "",
        }
        self.tasks[task["id"]] = task
        self.order.append(task["id"])
        return task

    def add_tasks(self, urls: list[str], preset: str, playlist: bool) -> dict:
        preset = preset if preset in PRESETS else "best"
        created, invalid, duplicates = [], [], []
        with self.lock:
            active_urls = {
                t["url"] for t in self.tasks.values() if t["status"] in ("pending", "running")
            }
            for raw in urls:
                url = str(raw).strip()
                if not url:
                    continue
                parsed = urlparse(url)
                if parsed.scheme not in ("http", "https") or not parsed.netloc:
                    invalid.append(url)
                    continue
                if url in active_urls:
                    duplicates.append(url)
                    continue
                active_urls.add(url)
                created.append(self._new_task(url, preset, playlist)["id"])
            if created:
                self._bump()
                self.save_state()
        return {"created": created, "invalid": invalid, "duplicates": duplicates}

    def cancel_task(self, task_id: str):
        with self.lock:
            task = self.tasks.get(task_id)
            if not task:
                return False, "任务不存在"
            if task["status"] == "pending":
                task["cancel_requested"] = True
                self._finish(task, "canceled", "")
                return True, ""
            if task["status"] == "running":
                task["cancel_requested"] = True
                task["phase"] = "canceling"
                proc = self.procs.get(task_id)
                if proc:
                    terminate_tree(proc)
                self._bump()
                self.save_state()
                return True, ""
            return False, "任务已经结束"

    def retry_task(self, task_id: str):
        with self.lock:
            old = self.tasks.get(task_id)
            if not old:
                return None, "任务不存在"
            if old["status"] in ("pending", "running"):
                return None, "任务正在进行中"
            new = self._new_task(old["url"], old["preset"], old["playlist"])
            self._bump()
            self.save_state()
            return new["id"], ""

    def delete_task(self, task_id: str):
        with self.lock:
            task = self.tasks.get(task_id)
            if not task:
                return False, "任务不存在"
            if task["status"] in ("pending", "running"):
                return False, "请先取消任务"
            self.tasks.pop(task_id, None)
            if task_id in self.order:
                self.order.remove(task_id)
            self.history_version += 1
            self._bump()
            self.save_state()
            return True, ""

    def clear_history(self) -> int:
        with self.lock:
            removed = 0
            for task_id in list(self.order):
                if self.tasks[task_id]["status"] in ("done", "error", "canceled"):
                    self.tasks.pop(task_id, None)
                    self.order.remove(task_id)
                    removed += 1
            if removed:
                self.history_version += 1
                self._bump()
                self.save_state()
            return removed

    def update_config(self, payload: dict):
        with self.lock:
            output = payload.get("output_dir")
            if isinstance(output, str) and output.strip():
                path = Path(output.strip()).expanduser()
                if not path.is_absolute():
                    path = (BASE_DIR / path).resolve()
                try:
                    path.mkdir(parents=True, exist_ok=True)
                    probe = path / ".video-download-workbench-test"
                    probe.write_text("ok", encoding="utf-8")
                    probe.unlink(missing_ok=True)
                except Exception as exc:
                    return False, f"目录不可写：{exc}"
                self.config["output_dir"] = str(path)
            concurrency = payload.get("concurrency")
            if concurrency is not None:
                try:
                    self.config["concurrency"] = max(1, min(4, int(concurrency)))
                except (TypeError, ValueError):
                    pass
            if payload.get("theme") in ("dark", "light"):
                self.config["theme"] = payload["theme"]
            if payload.get("language") in LANGUAGES:
                self.config["language"] = payload["language"]
            for key in ("animations", "sound_enabled"):
                if isinstance(payload.get(key), bool):
                    self.config[key] = payload[key]
            if payload.get("sound_name") in SOUNDS:
                self.config["sound_name"] = payload["sound_name"]
            try:
                save_json(CONFIG_FILE, self.config)
            except Exception as exc:
                return False, f"保存配置失败：{exc}"
            self._bump()
            return True, ""

    def open_path(self, path: str = "", task_id: str = ""):
        """打开下载目录或历史任务的文件位置。"""
        if task_id:
            with self.lock:
                task = self.tasks.get(task_id)
                if not task:
                    return False, "任务不存在"
                target_str = task.get("output_file") or ""
            if not target_str:
                return False, "该任务没有生成文件"
            target = Path(target_str).expanduser()
            try:
                target = target.resolve()
            except Exception:
                return False, "路径无效"
            if not target.exists():
                parent = target.parent
                if parent.exists():
                    target = parent
                else:
                    return False, "文件已被移动或删除"
        else:
            if not path:
                return False, "缺少路径"
            target = Path(path).expanduser()
            try:
                target = target.resolve()
            except Exception:
                return False, "路径无效"
            if not target.exists():
                return False, "路径不存在"
            root = Path(self.config["output_dir"]).resolve()
            if target != root and root not in target.parents:
                return False, "只能打开下载目录内的路径"
        try:
            if target.is_dir():
                subprocess.Popen(["explorer", str(target)])
            else:
                subprocess.Popen(["explorer", "/select,", str(target)])
            return True, ""
        except Exception as exc:
            return False, f"无法打开资源管理器：{exc}"

    def shutdown(self) -> None:
        """退出程序时结束仍在进行的任务，避免遗留 yt-dlp 子进程。"""
        with self.lock:
            ids = [
                task_id for task_id, task in self.tasks.items()
                if task["status"] in ("pending", "running")
            ]
        for task_id in ids:
            self.cancel_task(task_id)

    def _finish(self, task: dict, status: str, error: str) -> None:
        task["status"] = status
        task["phase"] = None
        task["error"] = error
        task["finished_at"] = now_str()
        if len(task["log"]) > FINISH_LOG_KEEP:
            del task["log"][: len(task["log"]) - FINISH_LOG_KEEP]
        if status == "done":
            task["progress"]["percent"] = 100.0
            task["progress"]["speed"] = ""
            task["progress"]["eta"] = ""
            if not task["title"] and task["output_file"]:
                task["title"] = title_from_path(task["output_file"])
        self.history_version += 1
        self._trim_history()
        self._bump()
        self.save_state()

    def _trim_history(self) -> None:
        finished = [
            i for i in self.order
            if self.tasks[i]["status"] in ("done", "error", "canceled")
        ]
        for task_id in finished[:-HISTORY_LIMIT]:
            self.tasks.pop(task_id, None)
            self.order.remove(task_id)

    def _schedule_loop(self) -> None:
        while True:
            with self.cond:
                limit = max(1, int(self.config.get("concurrency", 2)))
                running = sum(
                    1 for t in self.tasks.values() if t["status"] == "running"
                )
                if running >= limit:
                    self.cond.wait(timeout=1.0)
                    continue
                nxt = next(
                    (self.tasks[i] for i in self.order if self.tasks[i]["status"] == "pending"),
                    None,
                )
                if nxt is None:
                    self.cond.wait(timeout=1.0)
                    continue
                nxt["status"] = "running"
                nxt["phase"] = "downloading"
                nxt["started_at"] = now_str()
                self._bump()
                self.save_state()
                task_id = nxt["id"]
            threading.Thread(
                target=self._run_task, args=(task_id,), daemon=True, name=f"task-{task_id}"
            ).start()

    def _run_task(self, task_id: str) -> None:
        task = self.tasks.get(task_id)
        if not task:
            return
        with self.lock:
            if task.get("cancel_requested"):
                self._finish(task, "canceled", "")
                return
        env = os.environ.copy()
        env.setdefault("PYTHONIOENCODING", "utf-8")
        env.setdefault("PYTHONUTF8", "1")
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        error_line = ""
        proc = None
        try:
            proc = subprocess.Popen(
                task["command"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding=OUTPUT_ENCODING,
                errors="replace",
                bufsize=1,
                cwd=str(BASE_DIR),
                env=env,
                creationflags=creationflags,
            )
            with self.lock:
                self.procs[task_id] = proc
                if task.get("cancel_requested"):
                    terminate_tree(proc)
            assert proc.stdout is not None
            for raw in proc.stdout:
                line = ANSI_RE.sub("", raw).rstrip("\r\n")
                if line.strip():
                    error_line = self._consume_line(task, line) or error_line
            code = proc.wait()
        except Exception as exc:
            code = -1
            error_line = f"无法运行 yt-dlp：{exc}"
        finally:
            with self.lock:
                self.procs.pop(task_id, None)
        with self.lock:
            if task.get("cancel_requested"):
                self._finish(task, "canceled", "")
            elif code == 0:
                self._finish(task, "done", "")
            else:
                self._finish(task, "error", task.get("error") or error_line or f"yt-dlp 退出码 {code}")

    def _consume_line(self, task: dict, line: str) -> str:
        """处理一行输出，返回可能是错误摘要的文本。"""
        with self.lock:
            log = task["log"]
            log.append(line)
            if len(log) > LOG_LIMIT:
                del log[: len(log) - LOG_LIMIT]
            if line.startswith(PROGRESS_PREFIX):
                parts = [p.strip() for p in line[len(PROGRESS_PREFIX):].strip().split("|")]
                parts += [""] * (5 - len(parts))
                progress = task["progress"]
                percent = to_float(parts[0])
                if percent is not None:
                    progress["percent"] = round(percent, 1)
                progress["downloaded"] = clean_field(parts[1])
                progress["total"] = clean_field(parts[2])
                progress["speed"] = clean_field(parts[3])
                progress["eta"] = clean_field(parts[4])
                if task["status"] == "running" and not task.get("cancel_requested"):
                    task["phase"] = "downloading"
            elif line.startswith("[download] Destination: "):
                task["output_file"] = line.split("Destination: ", 1)[1].strip().strip('"')
            elif line.startswith("[Merger] Merging formats into "):
                task["output_file"] = line.split("into ", 1)[1].strip().strip('"')
                task["phase"] = "processing"
            elif line.startswith("[ExtractAudio] Destination: "):
                task["output_file"] = line.split("Destination: ", 1)[1].strip().strip('"')
                task["phase"] = "processing"
            elif line.startswith("[download] ") and " has already been downloaded" in line:
                path = line[len("[download] "):].split(" has already been downloaded")[0]
                task["output_file"] = path.strip().strip('"')
            elif POSTPROCESS_RE.match(line):
                task["phase"] = "processing"
            elif "ERROR:" in line:
                task["error"] = line.strip()
                self._bump()
                self.save_state()
                return task["error"]
            self._bump()
            self._maybe_persist()
        return ""

    # ---------- 视图数据 ----------

    def _active_view(self, task: dict) -> dict:
        return {
            "id": task["id"],
            "url": task["url"],
            "title": task["title"],
            "preset": task["preset"],
            "playlist": task["playlist"],
            "status": task["status"],
            "phase": task["phase"],
            "progress": dict(task["progress"]),
            "output_file": task["output_file"],
            "error": task["error"],
            "created_at": task["created_at"],
            "started_at": task["started_at"],
        }

    def _history_view(self, task: dict) -> dict:
        return {
            "id": task["id"],
            "url": task["url"],
            "title": task["title"],
            "preset": task["preset"],
            "playlist": task["playlist"],
            "status": task["status"],
            "progress": dict(task["progress"]),
            "output_file": task["output_file"],
            "error": task["error"],
            "created_at": task["created_at"],
            "started_at": task["started_at"],
            "finished_at": task["finished_at"],
        }

    def stats(self) -> dict:
        counts = {"pending": 0, "running": 0, "done": 0, "error": 0, "canceled": 0}
        for task in self.tasks.values():
            status = task.get("status", "")
            if status in counts:
                counts[status] += 1
        return counts

    def snapshot(self) -> dict:
        with self.lock:
            active = [
                self._active_view(self.tasks[i])
                for i in self.order
                if self.tasks[i]["status"] in ("pending", "running")
            ]
            return {
                "version": self.version,
                "history_version": self.history_version,
                "active": active,
                "stats": self.stats(),
            }

    def history(self) -> dict:
        with self.lock:
            history = [
                self._history_view(self.tasks[i])
                for i in reversed(self.order)
                if self.tasks[i]["status"] in ("done", "error", "canceled")
            ]
            return {"history": history, "history_version": self.history_version}

    def task_detail(self, task_id: str):
        with self.lock:
            task = self.tasks.get(task_id)
            if not task:
                return None
            return {
                "id": task["id"],
                "title": task["title"],
                "url": task["url"],
                "status": task["status"],
                "phase": task["phase"],
                "error": task["error"],
                "output_file": task["output_file"],
                "log": list(task["log"]),
            }
