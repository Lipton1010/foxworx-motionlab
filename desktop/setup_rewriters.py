"""Install Q5_K_M rewriters and a pinned, private Windows llama.cpp runtime."""
import hashlib
import json
import shutil
from pathlib import Path
from urllib.request import urlopen
from zipfile import ZipFile
from huggingface_hub import HfApi, hf_hub_download

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "models/prompt-rewriters"
RELEASE = "b10964"
CORE_REVISION = "fb7ae1d1f9611cd91524d03c53c5246b36ac8577"
REVISIONS = {
    "T2I": ("e18d4a3e0830ab157770738b16830e6fcf5f57d4", "f3ed7985c788ad75b3ab7223e0c4c51e2a43545b"),
    "I2I": ("55b9c1a326599e142d59bcad8715d5601ccf8daa", "72927bc08afc99b7888ceb7d7d51a12db3700bbd"),
}
ARCHIVES = {
    "llama-b10964-bin-win-cuda-12.4-x64.zip": "264f20d7ee3860aecca9ec12418357a9f3e80349a2b186f66c63859ded1a9593",
    "cudart-llama-bin-win-cuda-12.4-x64.zip": "8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6",
}


def main():
    code = ROOT / "runtime/qwen-prompt-rewrite"
    code.mkdir(parents=True, exist_ok=True)
    with urlopen(f"https://raw.githubusercontent.com/QwenLM/Qwen-Image-2.1/{CORE_REVISION}/prompt_rewrite/pe_core.py") as response:
        (code / "pe_core.py").write_bytes(response.read())
    runtime = ROOT / "runtime/llama"
    runtime.mkdir(parents=True, exist_ok=True)
    for name, expected in ARCHIVES.items():
        archive = ROOT / "temp" / name
        print(f"Installing {name}", flush=True)
        valid = False
        if archive.exists():
            with archive.open("rb") as data:
                valid = hashlib.file_digest(data, "sha256").hexdigest() == expected
        if not valid:
            partial = archive.with_suffix(".zip.partial")
            with urlopen(f"https://github.com/ggml-org/llama.cpp/releases/download/{RELEASE}/{name}") as response, partial.open("wb") as output:
                shutil.copyfileobj(response, output)
            with partial.open("rb") as data:
                if hashlib.file_digest(data, "sha256").hexdigest() != expected:
                    raise ValueError(f"Checksum mismatch: {partial}")
            partial.replace(archive)
        with ZipFile(archive) as bundle:
            for entry in bundle.infolist():
                if not entry.is_dir():
                    with bundle.open(entry) as source, (runtime / Path(entry.filename).name).open("wb") as output:
                        shutil.copyfileobj(source, output)
    api = HfApi()
    manifest = {"runtime": RELEASE, "core_revision": CORE_REVISION, "quantization": "Q5_K_M", "models": []}
    for task, suffix in (("t2i", "T2I"), ("edit", "I2I")):
        name = f"Qwen-Image-2.1-PE-{suffix}"
        quant_revision, official_revision = REVISIONS[suffix]
        info = api.model_info(f"prithivMLmods/{name}-GGUF", revision=quant_revision, files_metadata=True)
        files = [f"{name}.Q5_K_M.gguf"]
        if task == "edit":
            files.append(f"{name}.mmproj-bf16.gguf")
        for filename in files:
            print(f"Downloading {filename}", flush=True)
            path = hf_hub_download(info.id, filename, revision=info.sha, local_dir=TARGET / "gguf")
            sibling = next(file for file in info.siblings if file.rfilename == filename)
            with open(path, "rb") as data:
                if hashlib.file_digest(data, "sha256").hexdigest() != sibling.lfs.sha256:
                    raise ValueError(f"Checksum mismatch: {filename}")
        official = api.model_info(f"Qwen/{name}", revision=official_revision)
        hf_hub_download(official.id, "system_prompt.txt", revision=official.sha, local_dir=TARGET / task)
        manifest["models"].append({"task": task, "repo": info.id, "revision": info.sha,
                                   "files": files, "system_prompt_revision": official.sha})
        print(f"Ready: {task}", flush=True)
    (TARGET / "gguf/manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("Q5 rewriters ready.", flush=True)


if __name__ == "__main__":
    main()
