"""Launch the extracted Windows release and close its actual Qt main window."""

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import zipfile


def find_main_window(pid: int) -> int | None:
    user32 = ctypes.windll.user32
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    handles = []

    @callback_type
    def inspect(hwnd, _):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(owner))
        if owner.value == pid:
            title = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(wintypes.HWND(hwnd), title, len(title))
            if title.value == "K922 NTRIP Client":
                handles.append(hwnd)
        return True

    user32.EnumWindows(inspect, 0)
    return handles[0] if handles else None


def check_archive(archive: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="k922-release-") as directory:
        root = Path(directory)
        with zipfile.ZipFile(archive) as package:
            package.extractall(root)
        exe = root / "K922 NTRIP Client" / "K922 NTRIP Client.exe"
        env = os.environ.copy()
        windows = Path(os.environ["SystemRoot"])
        env["PATH"] = os.pathsep.join(map(str, (windows / "System32", windows)))
        env["APPDATA"] = str(root / "profile")
        for key in ("QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH", "QT_QPA_PLATFORM"):
            env.pop(key, None)
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = subprocess.SW_HIDE
        with subprocess.Popen([str(exe)], cwd=root, env=env, startupinfo=startup) as app:
            try:
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    if app.poll() is not None:
                        raise RuntimeError(f"Client exited before opening its window ({app.returncode})")
                    window = find_main_window(app.pid)
                    if window:
                        ctypes.windll.user32.PostMessageW(wintypes.HWND(window), 0x0010, 0, 0)  # WM_CLOSE
                        if app.wait(timeout=10) != 0:
                            raise RuntimeError(f"Client returned exit code {app.returncode}")
                        return
                    time.sleep(0.1)
                raise TimeoutError("Packaged client did not create its main window within 30 seconds")
            finally:
                if app.poll() is None:
                    app.kill()


if __name__ == "__main__":
    check_archive(Path(sys.argv[1]))
    print("Packaged Qt main window opened and closed successfully.")
