"""Download and verify MOSS-Image-Base weights for the bundled official plugin."""
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL_REVISION = "32edbc8a53ff3117ed52af34ce27a031129f2d0e"
CODE_REVISION = "95559c93ce9f85967de70435deefc1153a1a2fab"
os.environ["HF_XET_CACHE"] = str(ROOT / "runtime/huggingface/xet")
os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
os.environ["HF_XET_NUM_CONCURRENT_RANGE_GETS"] = "4"

def main():
    from huggingface_hub import HfApi, snapshot_download
    repo = "OpenMOSS-Team/MOSS-Image-Base"
    target = ROOT / "models/moss-image-base"
    info = HfApi().model_info(repo, revision=MODEL_REVISION, files_metadata=True)
    files = [f for f in info.siblings if f.rfilename.endswith((".json", ".safetensors", ".txt", ".model", ".jinja"))]
    print(f"Downloading official MOSS-Image-Base: {sum(f.size or 0 for f in files) / 1e9:.2f} GB", flush=True)
    snapshot_download(repo, revision=MODEL_REVISION, allow_patterns=[f.rfilename for f in files], local_dir=target, max_workers=2)
    manifest = []
    for entry in files:
        path = target / entry.rfilename
        if path.stat().st_size != entry.size:
            raise RuntimeError(f"Incomplete model file: {entry.rfilename}")
        digest = hashlib.file_digest(path.open("rb"), "sha256").hexdigest()
        expected = entry.lfs.sha256 if entry.lfs else None
        if expected and expected != digest:
            raise RuntimeError(f"Checksum mismatch: {entry.rfilename}")
        manifest.append({"file": entry.rfilename, "bytes": entry.size, "sha256": digest})
        print(f"Verified {entry.rfilename}", flush=True)
    (target / "install-manifest.json").write_text(json.dumps({"repo": repo, "revision": MODEL_REVISION, "plugin_revision": CODE_REVISION, "files": manifest}, indent=2))
    print("MOSS-Image-Base download and verification complete.", flush=True)

if __name__ == "__main__":
    main()
