"""Run Image Studio with isolated ComfyUI packages and shared Python/PyTorch."""
import os
from pathlib import Path
import runpy
import sys

ROOT = Path(__file__).resolve().parent
PORTABLE = ROOT / 'runtime/ComfyUI_windows_portable/ComfyUI'
SOURCE = PORTABLE if PORTABLE.is_dir() else ROOT / 'runtime/backend-0.42.1/Comfy-Org-ComfyUI-63be2f9'
sys.path.insert(0, str(SOURCE))
if SOURCE != PORTABLE:
    sys.path[1:1] = [str(ROOT / 'runtime/packages-0.42.1'), str(ROOT / 'runtime/packages')]
os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', PYTHONDONTWRITEBYTECODE='1')
os.chdir(SOURCE)
sys.argv = [str(SOURCE / 'main.py'), '--listen', '127.0.0.1', '--port', '8193',
            '--output-directory', str(ROOT / 'output'), '--input-directory', str(ROOT / 'input'),
            '--temp-directory', str(ROOT / 'temp'), '--user-directory', str(ROOT / 'user'),
            '--database-url', 'sqlite:///' + (ROOT / 'user/studio.db').as_posix(),
            '--extra-model-paths-config', str(ROOT / 'extra_model_paths.yaml'),
            '--disable-all-custom-nodes', '--whitelist-custom-nodes', 'moss-image', '--disable-api-nodes', '--preview-method', 'none',
            '--vram-headroom', '2', '--cache-none'] + sys.argv[1:]
runpy.run_path(str(SOURCE / 'main.py'), run_name='__main__')
