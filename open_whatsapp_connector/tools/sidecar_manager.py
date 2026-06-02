import logging
import os
import subprocess
import threading

import requests

_logger = logging.getLogger(__name__)

_sidecar_process = None
_lock = threading.Lock()


def start_sidecar(sidecar_path, port=3100, api_key='', sidecar_url=None):
    """Start the sidecar Node.js process. Returns True if started."""
    global _sidecar_process
    with _lock:
        # Check if already running via health endpoint (works across workers)
        url = sidecar_url or f'http://localhost:{port}'
        if is_sidecar_running(url):
            return True

        if _sidecar_process and _sidecar_process.poll() is None:
            return True  # Already running in this worker

        node_script = os.path.join(sidecar_path, 'dist', 'index.js')
        if not os.path.isfile(node_script):
            _logger.error("Sidecar script not found: %s", node_script)
            return False

        env = os.environ.copy()
        env['PORT'] = str(port)
        if api_key:
            env['API_KEY'] = api_key

        # Write sidecar output to a log file instead of PIPE
        # (PIPE buffers fill up and freeze the process)
        log_file = os.path.join(sidecar_path, 'sidecar.log')
        log_fh = open(log_file, 'a')

        kwargs = {
            'cwd': sidecar_path,
            'env': env,
            'stdout': log_fh,
            'stderr': log_fh,
        }
        # On Windows, hide the console window
        if os.name == 'nt':
            kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW

        try:
            _sidecar_process = subprocess.Popen(
                ['node', node_script],
                **kwargs,
            )
            _logger.info("Sidecar started (PID %s) on port %s", _sidecar_process.pid, port)
            return _sidecar_process.poll() is None
        except Exception:
            _logger.exception("Failed to start sidecar")
            return False
        finally:
            # The child has its own dup of the fd; close the parent-side
            # handle so we don't leak descriptors on retries.
            try:
                log_fh.close()
            except Exception:
                pass


def stop_sidecar():
    """Stop the sidecar process. Returns True if stopped."""
    global _sidecar_process
    with _lock:
        if not _sidecar_process or _sidecar_process.poll() is not None:
            _sidecar_process = None
            return False
        _sidecar_process.terminate()
        try:
            _sidecar_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _sidecar_process.kill()
            _sidecar_process.wait(timeout=3)
        pid = _sidecar_process.pid
        _sidecar_process = None
        _logger.info("Sidecar stopped (PID %s)", pid)
        return True


def is_sidecar_running(sidecar_url='http://localhost:3100'):
    """Check if sidecar is reachable via health endpoint."""
    try:
        resp = requests.get(f'{sidecar_url.rstrip("/")}/health', timeout=2)
        return resp.status_code == 200
    except Exception:
        return False


def get_sidecar_pid():
    """Return PID if sidecar process is managed and running."""
    global _sidecar_process
    if _sidecar_process and _sidecar_process.poll() is None:
        return _sidecar_process.pid
    return None
