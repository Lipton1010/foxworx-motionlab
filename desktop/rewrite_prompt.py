"""Refine once with a private Q5 llama.cpp server, then release its GPU memory."""
import base64
import io
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "runtime/qwen-prompt-rewrite"))
import pe_core as core


def main():
    request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8-sig"))
    paths = request.get("images", [])
    if not isinstance(request.get("prompt"), str) or not request["prompt"].strip():
        raise ValueError("Write a prompt before refining it.")
    if not isinstance(paths, list) or len(paths) > 10:
        raise ValueError("Use up to 10 reference images.")
    task, suffix = ("edit", "I2I") if paths else ("t2i", "T2I")
    profile = core.get_profile(task)
    images = []
    for path in paths:
        with core.load_image(Path(path), profile.image_max_pixels) as image:
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            images.append("data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii"))
    messages = core.build_messages(core.load_system_prompt(None, str(ROOT / "models/prompt-rewriters" / task)), request["prompt"], images)
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

    model_root = ROOT / "models/prompt-rewriters/gguf"
    command = [str(ROOT / "runtime/llama/llama-server.exe"), "--model", str(model_root / f"Qwen-Image-2.1-PE-{suffix}.Q5_K_M.gguf"),
               "--host", "127.0.0.1", "--port", str(port), "--ctx-size", "65536", "--parallel", "1",
               "--gpu-layers", "all", "--flash-attn", "on", "--no-webui", "--no-warmup", "--reasoning-format", "deepseek"]
    if paths:
        command += ["--mmproj", str(model_root / "Qwen-Image-2.1-PE-I2I.mmproj-bf16.gguf")]
    env = os.environ.copy()
    env["LLAMA_API_KEY"] = key
    log_path = Path(sys.argv[2]).with_suffix(".runtime.log")
    print("Loading the 5-bit local prompt rewriter…", flush=True)
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
            print("Refining the prompt…", flush=True)
            response = call("/v1/chat/completions", {
                "messages": messages, "temperature": profile.temperature, "top_p": profile.top_p,
                "top_k": profile.top_k, "min_p": profile.min_p, "presence_penalty": profile.presence_penalty,
                "repeat_penalty": 1.0, "max_tokens": profile.max_new_tokens, "seed": 42,
                "chat_template_kwargs": {"enable_thinking": True},
            }, timeout=900)
            choice = response["choices"][0]
            parsed = core.parse_answer(choice["message"].get("content") or "", profile)
            if choice.get("finish_reason") == "length" or not parsed["parse_ok"]:
                raise ValueError("The rewriter did not finish a valid prompt. Your draft is unchanged; try a shorter request.")
            result = {"prompt": parsed["positive_prompt"], "ratio": parsed["wh_ratio"], "follow": parsed["ratio_follow"],
                      "model": f"{suffix} Q5_K_M", "usage": response.get("usage", {}), "timings": response.get("timings", {})}
            Path(sys.argv[2]).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
            print("Prompt refinement complete.", flush=True)
        except HTTPError as error:
            raise RuntimeError(f"Local rewriter request failed ({error.code}): {error.read().decode('utf-8', errors='replace')}") from error
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
