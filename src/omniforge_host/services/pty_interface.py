# src/omniforge_host/services/pty_interface.py
from __future__ import annotations

import os
import sys
import signal
import threading
import time
from typing import Callable
from omniforge_api.logger import get_logger

class PTYInterface:
    def __init__(self, on_exit: Callable[[int], None], on_data: Callable[[str, bytes], None], session_id: str) -> None:
        self._on_exit = on_exit
        self._on_data = on_data
        self._session_id = session_id
        self._closed = False
        self._exited = False
        self._lock = threading.Lock()
        self._log = get_logger("pty_interface")

    def write(self, data: bytes) -> None: ...
    def resize(self, rows: int, cols: int) -> None: ...
    def close(self) -> None: ...

class UnixPTY(PTYInterface):
    def __init__(self, shell: str | None, cwd: str | None, rows: int, cols: int, on_exit: Callable[[int], None], on_data: Callable[[str, bytes], None], session_id: str) -> None:
        super().__init__(on_exit, on_data, session_id)
        self._log = get_logger("unix_pty")
        
        import pty as _pty
        import fcntl
        
        shell_path = shell or os.environ.get('SHELL', '/bin/sh')
        cwd_path = cwd or os.path.expanduser('~')
        
        pid, master_fd = _pty.fork()
        if pid == 0:
            try:
                os.chdir(cwd_path)
                os.execvp(shell_path, [shell_path])
            except Exception as e:
                self._log.error("Failed to exec shell", exc_info=e)
                os._exit(1)
        else:
            self.pid = pid
            self.master_fd = master_fd
            flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
            fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
            self.resize(rows, cols)
            self._log.info("UnixPTY created", pid=self.pid)
            self._wait_thread = threading.Thread(target=self._wait_for_exit, daemon=True)
            self._wait_thread.start()

    def write(self, data: bytes) -> None:
        with self._lock:
            if self._closed: return
        try:
            os.write(self.master_fd, data)
        except OSError:
            pass

    def resize(self, rows: int, cols: int) -> None:
        with self._lock:
            if self._closed: return
        try:
            import struct, termios
            winsize = struct.pack("HHHH", rows, cols, 0, 0)
            fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, winsize)
        except Exception:
            pass

    def close(self) -> None:
        with self._lock:
            if self._closed: return
            self._closed = True
            
        try:
            os.close(self.master_fd)
        except OSError:
            pass
        try:
            os.kill(self.pid, signal.SIGHUP)
        except ProcessLookupError:
            pass

    def _wait_for_exit(self) -> None:
        try:
            _, status = os.waitpid(self.pid, 0)
            exit_code = os.WEXITSTATUS(status) if os.WIFEXITED(status) else -1
            self._log.info("Process exited", pid=self.pid, exit_code=exit_code)
        except ChildProcessError:
            exit_code = -1
            
        with self._lock:
            if self._exited: return
            self._exited = True
        self._on_exit(exit_code)


class WindowsPTY(PTYInterface):
    def __init__(self, shell: str | None, cwd: str | None, rows: int, cols: int, on_exit: Callable[[int], None], on_data: Callable[[str, bytes], None], session_id: str) -> None:
        super().__init__(on_exit, on_data, session_id)
        self._log = get_logger("windows_pty")
        
        try:
            import winpty
        except ImportError:
            raise RuntimeError("pywinpty is required on Windows")
            
        shell_path = shell or "cmd.exe"
        cwd_path = cwd or os.path.expanduser('~')
        
        self._pty = winpty.PTY(cols, rows)
        self._pty.spawn(shell_path, cwd=cwd_path)
        self.pid = self._pty.pid
        self._log.info("WindowsPTY created", pid=self.pid)
        
        self._exit_event = threading.Event()
        self._read_thread = threading.Thread(target=self._read_loop, daemon=True)
        self._read_thread.start()
        self._wait_thread = threading.Thread(target=self._wait_for_exit, daemon=True)
        self._wait_thread.start()

    def _read_loop(self) -> None:
        while not self._exit_event.is_set():
            try:
                data_str = self._pty.read(timeout=100)
                if data_str:
                    self._on_data(self._session_id, data_str.encode('utf-8', errors='replace'))
                elif not self._pty.isalive():
                    break
            except Exception:
                if not self._pty.isalive():
                    break
                time.sleep(0.01)

    def write(self, data: bytes) -> None:
        with self._lock:
            if self._closed: return
        self._pty.write(data.decode('utf-8', errors='replace'))

    def resize(self, rows: int, cols: int) -> None:
        with self._lock:
            if self._closed: return
        self._pty.set_size(cols, rows)

    def close(self) -> None:
        with self._lock:
            if self._closed: return
            self._closed = True
            
        self._exit_event.set()
        if self.pid:
            try:
                import subprocess
                subprocess.call(['taskkill', '/F', '/T', '/PID', str(self.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass

    def _wait_for_exit(self) -> None:
        # ИСПРАВЛЕНО: Цикл с таймаутом для проверки флага смерти процесса
        while self._pty.isalive():
            if self._exit_event.wait(0.1):
                break
                
        with self._lock:
            if self._exited: return
            self._exited = True
            
        exit_code = -1
        try:
            exit_code = self._pty.get_exit_status() or -1
        except Exception:
            pass
        self._on_exit(exit_code)

def create_pty(shell: str | None, cwd: str | None, rows: int, cols: int, on_exit: Callable[[int], None], on_data: Callable[[str, bytes], None], session_id: str) -> PTYInterface:
    if sys.platform == 'win32':
        return WindowsPTY(shell, cwd, rows, cols, on_exit, on_data, session_id)
    return UnixPTY(shell, cwd, rows, cols, on_exit, on_data, session_id)