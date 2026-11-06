# Image Studio

Local still-image and video generation with a native Windows desktop app.

For local multi-shot production experiments, see [production checks and resumable
jobs](desktop/PRODUCTION.md). These optional tools add dependency-aware reuse,
conservative recovery and media checks; they do not add a longform desktop editor.

## Desktop 2.1.0 — October 24, 2026

The desktop interface now uses a light workspace, clearer setup panels, larger
prompt fields, and a simpler layered-canvas icon. Cold-start model selection is
fixed: the app no longer waits on output pipes inherited by the background engine.
Unavailable model choices and Generate stay disabled when no compatible model exists.
Existing models, outputs, prompts, references, and preferences are retained.

## Open and generate

1. Double-click **Image Studio.lnk** (or **Start Image Studio.cmd**) in this folder.
2. Choose **Still images**, pick a model, describe your image, then click **Generate image**.
3. The result appears in the preview and saves automatically in `output\desktop`.
   Use **Save as** for another copy, or **Open full size** to inspect it.

The **Image Studio** shortcut on your Windows desktop opens the same app. Its
custom icon is embedded in the executable and used by the window and taskbar.
Run `Create Desktop Shortcut.ps1` to recreate the desktop shortcut if needed.

For edits, add the source on the **References** tab, put it first, select
**Edit an image**, and describe the change.
The app keeps the source proportions. **Edit this image** uses the current preview
as your source. The original file stays intact.

The app starts the local engine automatically. **Recent images** includes existing
images in the output library. **More options** contains a repeatable seed and a
negative prompt. Prompt/settings metadata is saved beside each new PNG as JSON.
Your last prompt, settings, editing source, and preview are remembered.
Ctrl+Enter generates in the active image or video workspace.

## Models, LoRAs, and video

**Still images** offers Qwen Image 2.1, Krea 2 Raw, and MOSS Image Base.
Qwen supports editing and reference images; Krea and MOSS currently generate from
text. **Videos** offers LTX 2.5 and MiniMax H3, with separate **From text** and
**From image** modes. Choose a first frame for image-to-video, or use **Animate**
beneath an image preview. Video controls include shape, duration, seed, playback,
seeking, and Save as. Generated MP4s and settings JSON save automatically; imported
videos are copied into the library without moving the originals.

Each model picker has an optional LoRA list: add one or more, set their strengths,
and toggle them on or off. Use LoRAs trained for that model family. The app remembers
the selected model and each model's LoRAs independently for image creation, image
editing, text-to-video, and image-to-video, including after restarting. These choices
live in `user/workspace-settings.json`. **Models & LoRAs** shows the installed library;
use Refresh after adding files. Unsupported model families are marked unavailable.

The official [MOSS-Image-Base](https://huggingface.co/OpenMOSS-Team/MOSS-Image-Base)
weights are installed in `models/moss-image-base` (27.22 GB), pinned to revision
`32edbc8a53ff3117ed52af34ce27a031129f2d0e`. Weight SHA-256 values were checked against
Hugging Face metadata; the local manifest records every downloaded file. Run
`desktop/setup_moss.py` with the shared Python to download or verify those weights
again. The bundled official plugin in `runtime/custom_nodes/moss-image` is pinned
to OpenMOSS/MOSS-Image revision `95559c93ce9f85967de70435deefc1153a1a2fab`.

**Cancel generation** targets only this app's current job. Closing during generation
leaves the job running; reopening reconnects to it. If the engine connection drops,
select Generate again to reconnect. New jobs wait for other work using this engine.

The executable is `app\Image Studio.exe`. It uses the installed .NET 10 Windows
Desktop runtime, with no additional app packages. Rebuild from `desktop` source by
running `Build Desktop.ps1`. App error details are in `logs\desktop-errors.log`.

## Advanced node interface

Double-click **Open ComfyUI.cmd** if you want the node editor. In its left sidebar,
select **Workflows → Qwen 2.1 → Generate Image** or **Edit Image**.

The interface is at http://127.0.0.1:8193 while the server is running. Closing the
browser leaves the server running. Reopening the launcher reuses that server.
Double-click **Stop Image Studio.cmd** to stop an idle server and release its
memory. It refuses to stop while images are running or queued.
The first model load takes longer. Start with one image at 1 megapixel; the local
pilot also tests 2048 × 2048. The 25-step Euler/simple, CFG 1 settings come from
the official ComfyUI template. Larger images and more references need more memory.

Use **Qwen 2.1 → Edit Image** for editing: upload your source image into the
Load Image node and describe the change using `<image1>` in the prompt. The
included example starts with the pilot map. The underlying official workflow
also has inputs for additional references, addressed as `<image2>`, and so on.

For transparent images, Qwen recommends this prompt format:
“This is an RGBA image with transparency. [Describe your image.] The image has
alpha channel and the background is transparent.” Save as PNG to retain alpha.

## One model library, separate projects

| Folder | Purpose |
|---|---|
| `models` | Local model weights, MOSS Base, prompt rewriters, and LoRAs |
| `output` | Image and video results, including verification subfolders |
| `input` | Images supplied for editing |
| `user\default\workflows` | Your saved workflows |
| `logs` | Startup/runtime logs and the owned server PID |
| `runtime` | Pinned ComfyUI source and isolated updated packages |

`extra_model_paths.yaml` tells ComfyUI where models live. Image Studio also reads
the existing models in `D:\ComfyUI\ComfyUI\models`; those are not copied.
Another project can point at this same Qwen library using:

```yaml
image_studio:
  base_path: D:/Image Studio/models
  diffusion_models: diffusion_models
  text_encoders: text_encoders
  vae: vae
```

Pass that YAML to a Qwen-2.1-capable ComfyUI with `--extra-model-paths-config`.
Each project can set its own `--input-directory`, `--output-directory`, and
`--user-directory`. A custom UI can also use this running server's local API;
it needs no copy of the weights. Serialize generation jobs through one server
when possible to avoid loading duplicate models into GPU memory.

The original battlemap ComfyUI installation and production defaults are unchanged.
Its older runtime cannot execute the new Qwen 2.1 nodes merely by seeing the files.
The battlemap evaluation used Image Studio's server and saved its evidence under
`D:\Battlemap Pipeline\output\evaluations\qwen21-pilot-2026-09-22`.

## Runtime

Image Studio uses ComfyUI **0.42.1**, with frontend **1.55.18**,
comfy-kitchen **0.2.39** and comfy-aimdo **0.5.6** (updated October 19, 2026).
The source is in `runtime/backend-0.42.1`; updated packages are isolated in
`runtime/packages-0.42.1`. Exact package versions are in `runtime-requirements.txt`.
The prior backend and packages remain available for rollback. It reuses the existing
`D:\ComfyUI\python_embeded\python.exe` and its PyTorch installation. Keep that
Python folder available; this avoids duplicating the large CUDA/PyTorch libraries.

The server listens on localhost only. API/cloud nodes are disabled. Custom nodes
are disabled except for the official MOSS plugin. Generation runs locally.
Dynamic VRAM management has 2 GB extra
headroom; the server accounts for memory occupied by other applications.
Changing the shared Python environment can affect this workspace, even though
its ComfyUI source and updated packages are separate.

Qwen image weights are pinned to Hugging Face revision
`ace0edeb3791a594ddfa36ed5f41a178a394e921`; hashes and sizes are recorded in
`models\qwen21-downloads.json`.

The Qwen research license permits research/evaluation; commercial use requires
a separate license. See https://huggingface.co/Qwen/Qwen-Image-2.1/raw/main/LICENSE.

Official workflows: https://huggingface.co/Comfy-Org/Qwen-Image-2.1.

## Campaign references and Prompt Builder

The desktop app has a light workspace with separate Still images, Videos, References,
Prompt Builder, and Models & LoRAs sections. Select a thumbnail in Recent images to preview it.
Choose Delete image beneath the preview to remove it after confirmation. The
PNG and its saved prompt/settings JSON go to the Windows Recycle Bin; Windows
warns if recycling is unavailable. Deleting an image used by the current
reference list also removes those entries, with a warning in the confirmation.
The image prompt is kept when browsing or deleting recent images.

The References tab accepts up to 10 images. Assign roles and notes, then reorder
images if needed. In Edit mode, image 1 is the main image and determines framing.
In Create mode, references guide a new composition at the selected shape.
Save reference set stores copies alongside the JSON, including roles, notes, and
campaign art style. Keep the JSON and its `.images` folder together when moving it.

Prompt Builder supports Image and Video modes and remembers a separate written
prompt for each. Video mode adds subject/scene movement, camera movement, pacing,
and sound/dialogue. Build or write a prompt, then use the text-to-video or
image-to-video action to send it to Videos. Choose duration and a first frame there;
transferring the prompt never starts generation or replaces your image prompt.

Image mode includes portrait, backdrop, handout, transparent token, and general
artwork presets. Fill in the form and build a draft, or write directly in the draft
field. Refine with local AI optionally expands it. With reference images checked
and added, it uses the image-aware model; otherwise it uses the text model.
Review the result, Undo refinement if needed, then use it for a new image or edit.
Local AI refinement is available for image prompts only. Refining never generates
an image automatically. Suggested ratios are displayed
for review; they do not silently change your selected dimensions.

English spellcheck is enabled in prompts, reference notes, and builder fields.
Right-click a misspelled word for Windows spelling suggestions.

## Local 5-bit prompt refinement

Installed: community Q5_K_M conversions of Qwen's official T2I and I2I prompt
rewriters, with the matching BF16 vision projector (about 13.9 GB combined).
The app uses Qwen's official system prompts and sampling profiles through a
private llama.cpp b10964 CUDA 12.4 runtime under `runtime/llama`.
The checkpoint revisions are in `models/prompt-rewriters/gguf/manifest.json`.
No account or cloud service is needed for refinement; references stay local.

Refinement waits for the image engine to be idle, unloads its models, and checks
for 10 GiB of free GPU memory. One rewriter runs at a time, on a temporary loopback
port with a random session key. Its process exits and releases memory after the
request. Cancel refinement stops only that request's worker and runtime.
The next image generation reloads the image models as needed.

To reinstall the rewriters, run `desktop/setup_rewriters.py` with the existing
`D:/ComfyUI/python_embeded/python.exe`. This downloads models and the checksum-
verified Windows runtime; the shared Python installation is not modified.
The earlier full-precision model downloads are retained under `t2i` and `edit`
but are no longer loaded by the app. Only their system prompt files are used.
