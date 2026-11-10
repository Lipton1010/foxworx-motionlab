"""Independent Qwen3.5 adapter. An owned local process unloads before generation."""
import base64
import csv
import io
import hashlib
import json
import os
from pathlib import Path
import secrets
import re
import socket
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from prompt_profiles import profile_for

EXPECTED = {
    "4b": ("00fe7986ff5f6b463e62455821146049db6f9313603938a70800d1fb69ef11a4", "cd88edcf8d031894960bb0c9c5b9b7e1fea6ebee02b9f7ce925a00d12891f864"),
    "9b": ("03b74727a860a56338e042c4420bb3f04b2fec5734175f4cb9fa853daf52b7e8", "f70dc3509053962b0d0d3ee8a7eacebf5d60aa560cad78254ae8698516ae029f"),
}

def checked_asset(entry):
    path = (ROOT / entry["path"]).resolve()
    if not path.is_relative_to(ROOT.resolve()) or not path.is_file():
        raise ValueError("Refiner asset must be an existing local file inside this installation.")
    with path.open("rb") as handle:
        actual = hashlib.file_digest(handle, "sha256").hexdigest()
    if actual != entry["sha256"]:
        raise ValueError("Refiner asset checksum differs from the approved setup receipt.")
    return path

def configuration(tier, images):
    if tier not in ("4b", "9b"):
        raise ValueError("Choose Qwen3.5 4B or 9B.")
    path = ROOT / "models/prompt-refiner" / (tier + ".json")
    if not path.is_file():
        raise ValueError("The selected Qwen3.5 refiner is not configured. Manual prompts remain available. No model is downloaded automatically.")
    config = json.loads(path.read_text(encoding="utf-8-sig"))
    if config.get("family") != "qwen3.5" or config.get("tier") != tier or config.get("license") != "Apache-2.0":
        raise ValueError("Unsupported refiner receipt; restricted PE weights are not accepted.")
    if config.get("model", {}).get("sha256") != EXPECTED[tier][0]:
        raise ValueError("This model does not match the reviewed Qwen3.5 conversion.")
    assets = {key: checked_asset(config[key]) for key in ("model", "runtime")}
    if images:
        if "projector" not in config:
            raise ValueError("Image-conditioned refinement requires the matching vision projector; text-only fallback is not automatic.")
        if config["projector"].get("sha256") != EXPECTED[tier][1]:
            raise ValueError("The projector does not match the reviewed Qwen3.5 conversion.")
        assets["projector"] = checked_asset(config["projector"])
    return config, assets

def check_capacity(tier):
    if os.environ.get("CUDA_VISIBLE_DEVICES"):
        raise ValueError("Explicit CUDA device mapping must be verified before refinement.")
    query = subprocess.run(["nvidia-smi", "--query-gpu=index,memory.free", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=15)
    free = None
    if query.returncode == 0:
        for row in csv.reader(io.StringIO(query.stdout)):
            if len(row) == 2 and row[0].strip() == "0":
                try:
                    free = float(row[1]) / 1024
                except ValueError:
                    pass
    floor = 6 if tier == "4b" else 10
    if free is None or not __import__("math").isfinite(free) or free < floor:
        raise ValueError(f"Refinement admission needs {floor} GiB free VRAM on device 0 (conservative estimate, not a benchmark-certified minimum). No CPU fallback is used.")

def parse_result(response, target=None):
    choice = response["choices"][0]
    if choice.get("finish_reason") != "stop":
        raise ValueError("The refiner did not complete. Your draft is unchanged.")
    result = json.loads(choice["message"].get("content") or "")
    if set(result) != {"prompt", "warnings"} or not isinstance(result["prompt"], str) or not result["prompt"].strip() or len(result["prompt"]) > 24000 or not isinstance(result["warnings"], list) or not all(isinstance(x, str) for x in result["warnings"]):
        raise ValueError("The refiner returned an invalid draft; original input is unchanged.")
    if target == "minimax":
        labels = ["integrated_multimodal_description:", "overall_soundscape:", "non_diegetic_music:"]
        positions = [result["prompt"].find(label) for label in labels]
        if min(positions) < 0 or positions != sorted(positions):
            raise ValueError("H3 refinement omitted its required profile sections; the original draft is unchanged.")
        # A deterministic format marker, not invented scene content.
        result["prompt"] = re.sub(r"integrated_multimodal_description:\s*(?:\[Shot 1\]\s*)?",
                                  "integrated_multimodal_description: [Shot 1] ", result["prompt"], count=1)
    return result


def main():
    request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8-sig"))
    paths = request.get("images", [])
    if not isinstance(request.get("prompt"), str) or not request["prompt"].strip():
        raise ValueError("Write a prompt before refining it.")
    if not isinstance(paths, list) or len(paths) > 10:
        raise ValueError("Use up to 10 reference images.")
    if len(request["prompt"]) > 16000:
        raise ValueError("Shorten the draft to 16,000 characters before refinement.")
    profile = profile_for(request.get("target"), request.get("mode"), ROOT / "prompt-profiles")
    check_capacity(request.get("tier"))
    config, assets = configuration(request.get("tier"), paths)
    devices = subprocess.run([str(assets["runtime"]), "--list-devices"], capture_output=True,
                             text=True, timeout=20, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if devices.returncode or "CUDA0" not in devices.stdout + devices.stderr:
        raise RuntimeError("The verified runtime has no CUDA0 backend. CPU fallback is disabled.")
    images = []
    from PIL import Image
    for path in paths:
        local = Path(path)
        if str(local).startswith("\\\\") or not local.is_file():
            raise ValueError("References must be existing local image files.")
        with Image.open(local) as source:
            image = source.convert("RGB")
            image.thumbnail((1024, 1024))
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            images.append("data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii"))
    content = [{"type": "text", "text": request["prompt"]}]
    content += [{"type": "image_url", "image_url": {"url": image}} for image in images]
    messages = [{"role": "system", "content": profile["system"]}, {"role": "user", "content": content}]
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    key = secrets.token_urlsafe(32)
    base = f"http://127.0.0.1:{port}"
    opener = build_opener(ProxyHandler({}))

    def call(route, payload=None, timeout=5):
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = Request(base + route, data, {"Content-Type": "application/json", "Authorization": "Bearer " + key})
        with opener.open(req, timeout=timeout) as response:
            return json.load(response)

    command = [str(assets["runtime"]), "--model", str(assets["model"]),
               "--host", "127.0.0.1", "--port", str(port), "--ctx-size", "8192", "--parallel", "1",
               "--gpu-layers", "all", "--device", "CUDA0", "--split-mode", "none", "--main-gpu", "0", "--fit", "off", "--flash-attn", "on", "--no-webui", "--no-warmup", "--offline", "--reasoning", "off", "--verbosity", "4"]
    if paths:
        command += ["--mmproj", str(assets["projector"]), "--mmproj-device", "CUDA0"]
    env = os.environ.copy()
    env["LLAMA_API_KEY"] = key
    log_path = Path(sys.argv[2]).with_suffix(".runtime.log")
    print("Loading the selected local prompt rewriter.", flush=True)
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(command, stdout=log, stderr=log, env=env, creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            deadline = time.monotonic() + 180
            while True:
                if process.poll() is not None:
                    raise RuntimeError(f"Local runtime exited ({process.returncode}). See {log_path}")
                try:
                    if call("/health").get("status") == "ok":
                        break
                except (URLError, TimeoutError):
                    pass
                if time.monotonic() > deadline:
                    raise TimeoutError(f"The local rewriter did not load in time. See {log_path}")
                time.sleep(0.3)
            log.flush()
            placement = log_path.read_text(encoding="utf-8", errors="replace")
            offloads = re.findall(r"offloaded (\d+)/(\d+) layers to GPU", placement)
            if not any(int(a) == int(b) and int(a) > 0 for a, b in offloads):
                raise RuntimeError("Full language-model GPU layer placement was not confirmed; no refinement requested.")
            if re.search(r"fall(?:ing)? back to CPU|no usable GPU", placement, re.IGNORECASE):
                raise RuntimeError("The runtime reported CPU fallback; no refinement requested.")
            print("Refining the prompt.", flush=True)
            response = call("/v1/chat/completions", {
                "messages": messages, "temperature": 0.3, "top_p": 0.9,
                "max_tokens": 1536, "seed": 42, "response_format": {"type": "json_object"},
            }, timeout=180)
            log.flush()
            if re.search(r"fall(?:ing)? back to CPU|no usable GPU", log_path.read_text(encoding="utf-8", errors="replace"), re.IGNORECASE):
                raise RuntimeError("The runtime reported CPU fallback during inference; draft unchanged.")
            result = parse_result(response, request["target"])
            result.update(model="Qwen3.5 " + request["tier"], profile_target=request["target"],
                          profile_version=profile["version"], profile_sha256=profile["sha256"],
                          model_sha256=config["model"]["sha256"], ratio=None, follow=None)
            Path(sys.argv[2]).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
            print("Prompt refinement complete.", flush=True)
        except HTTPError as error:
            raise RuntimeError(f"Local rewriter request failed ({error.code}); response body omitted to protect private drafts.") from None
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == "__main__":
    main()
