"""Refresh pinned, checksum-verified download metadata from official repositories."""
import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


def fetch(url):
    with urlopen(Request(url, headers={"User-Agent": "ImageStudio-PortableBuilder"}), timeout=60) as response:
        return response.read()


def model(repo, revision, names, target_prefix="models/"):
    info = json.loads(fetch(f"https://huggingface.co/api/models/{repo}/revision/{revision}?blobs=true"))
    result = []
    for name in names:
        entry = next(item for item in info["siblings"] if item["rfilename"] == name)
        url = f"https://huggingface.co/{repo}/resolve/{info['sha']}/{name}"
        size = entry.get("size")
        digest = entry.get("lfs", {}).get("sha256")
        if not digest:
            data = fetch(url)
            size, digest = len(data), hashlib.sha256(data).hexdigest()
        result.append({"path": target_prefix + name, "url": url, "bytes": size, "sha256": digest})
    return result


def bundle(key, title, description, ram, vram, files, license_url, recommended=False):
    return {"id": key, "title": title, "description": description, "minRamGB": ram,
            "minVramGB": vram, "recommended": recommended, "licenseUrl": license_url,
            "bytes": sum(entry["bytes"] for entry in files), "files": files}


def main():
    qwen = json.loads((ROOT / "models/qwen21-downloads.json").read_text())
    bundles = [bundle("qwen", "Qwen Image 2.1 â€” images, edits, references",
                      "Recommended starting point. Use 1 megapixel and one reference initially.", 32, 16,
                      model(qwen[0]["repo"], qwen[0]["revision"], [Path(e["path"]).relative_to(ROOT / "models").as_posix() for e in qwen]),
                      "https://huggingface.co/Qwen/Qwen-Image-2.1/blob/main/LICENSE", True)]
    bundles.append(bundle("krea", "Krea 2 Raw â€” text-to-image",
                          "Optional illustration and photography model. Start at 1 megapixel.", 32, 16,
                          model("Comfy-Org/Krea-2", "main", ["diffusion_models/krea2_raw_fp8_scaled.safetensors", "text_encoders/qwen3vl_4b_fp8_scaled.safetensors", "vae/qwen_image_vae.safetensors"]),
                          "https://huggingface.co/krea/Krea-2-Raw"))
    bundles.append(bundle("ltx", "LTX 2.5 â€” short videos with audio",
                          "More demanding. Start with 3 seconds at the default resolution. Laptop speed varies.", 32, 16,
                          model("Lightricks/LTX-2.5", "49b093a39c19169a8a81721dcc541e07e945232f", ["diffusion_models/ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors", "text_encoders/gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors", "vae/ltx-2.5-video-vae-bf16.safetensors", "vae/ltx-2.5-audio-vae-bf16.safetensors", "latent_upscale_models/ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors"]),
                          "https://huggingface.co/Lightricks/LTX-2.5"))
    mini = json.loads((ROOT / "output/video/ww1-comparison-20261018/model-downloads.json").read_text())
    mini = [e for e in mini if e["repo"] == "Comfy-Org/MiniMax-H3"]
    bundles.append(bundle("minimax", "MiniMax H3 â€” larger video model",
                          "Optional, memory-intensive video model. Start with 3 seconds and keep the Windows page file enabled.", 32, 16,
                          model(mini[0]["repo"], mini[0]["revision"], [e["source"] for e in mini]),
                          "https://huggingface.co/Comfy-Org/MiniMax-H3"))
    moss = json.loads((ROOT / "models/moss-image-base/install-manifest.json").read_text())
    bundles.append(bundle("moss", "MOSS Image Base â€” larger image model",
                          "Optional, larger image model. Start at 1 megapixel; SSD storage is recommended.", 32, 16,
                          [{"path": "models/moss-image-base/" + e["file"], "url": f"https://huggingface.co/{moss['repo']}/resolve/{moss['revision']}/{e['file']}", "bytes": e["bytes"], "sha256": e["sha256"]} for e in moss["files"]],
                          "https://huggingface.co/OpenMOSS-Team/MOSS-Image-Base"))
    reviewed = json.loads((ROOT / "portable/catalog.json").read_text(encoding="utf-8-sig"))
    # Refiner packs use immutable reviewed assets, never the retired PE package.
    bundles.extend(item for item in reviewed["bundles"] if item["id"].startswith("refiner-"))
    catalog = {"version": "2.2.0", "engine": {"path": "downloads/ComfyUI_windows_portable_nvidia.7z", "url": "https://github.com/Comfy-Org/ComfyUI/releases/download/v0.42.1/ComfyUI_windows_portable_nvidia.7z", "bytes": 2018444114, "sha256": "496afd18790ec685d99ebba2edf200d7371a29fbdd3a992bb0f4f52f244a6874"}, "bundles": bundles}
    # Refresh bytes, not release policy. Preserve reviewed terms and optional code
    # entries; otherwise regeneration would silently restore preselected Qwen.
    reviewed = json.loads((ROOT / "portable/catalog.json").read_text(encoding="utf-8-sig"))
    for item in bundles:
        previous = next(old for old in reviewed["bundles"] if old["id"] == item["id"])
        for key in ("validation", "licenseSummary", "minFreeVramGB"):
            if key in previous:
                item[key] = previous[key]
        item["recommended"] = False
        item["bytes"] = sum(entry["bytes"] for entry in item["files"])
    catalog["version"] = reviewed["version"]
    (ROOT / "portable/catalog.json").write_text(json.dumps(catalog, indent=2), encoding="utf-8")
    for item in bundles:
        print(f"{item['id']}: {item['bytes'] / 1e9:.2f} GB, {len(item['files'])} verified entries")


if __name__ == "__main__":
    main()
