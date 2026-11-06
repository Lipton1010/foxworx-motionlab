# Desktop app verification

## Still images, videos, and model library — 2026-10-19

- Release 2.0.0 build passed without warnings or errors. All 96 GraphChecks
  passed, including graph wiring, multiple/disabled LoRAs, the modern ComfyUI
  COMBO schema, workflow/model preference round-trips, and existing prompt rules.
- Actual engine generation passed for Qwen, MOSS Base, Krea Raw with KreaMapv1
  at strength 0.6, LTX 2.5 text/image, and MiniMax H3 text/image. Evidence is in
  `logs/ui-generation-checks.log` and `output/desktop/verification-2026-10-19`.
  These used short smoke settings, not every supported quality/size combination.
- Clicking Generate video in the real WPF window completed an LTX text-to-video
  job in 34 seconds, displayed its playable 768 × 512 clip, wrote the JSON
  sidecar, and cleared the pending-job record. Output:
  `output/desktop/2026-10-19/video/LTX_00001_.mp4`.
- Real UI model choices restored independently for image creation (Krea), image
  editing (Qwen), text-to-video (LTX), and image-to-video (MiniMax). Krea's selected
  LoRA, disabled state, and 0.65 strength survived switching and relaunch. Test
  LoRAs were removed afterward; MOSS is now selected for new still images.
- Play, pause, and seek worked through native UI Automation. Still images,
  References, and Prompt Builder were visually checked at the minimum window
  size; the Models library was inspected at the default size. Original image
  prompts and reference settings were preserved. The temporary video prompt
  was cleared after testing.
- MOSS Base weights (27.22 GB) matched official Hugging Face SHA-256 metadata.
  The manifest pins model and plugin revisions. Live `/system_stats` confirmed
  ComfyUI 0.42.1, frontend 1.55.18, and matching required/installed packages.
- Previous app binaries are retained in `temp/ui-refresh/app-before-publish`;
  previous ComfyUI source and package directories are also retained.
- Final Release publish succeeded. Launching the actual Windows desktop shortcut
  opened `D:/Image Studio/app/Image Studio.exe`, file version 2.0.0.0. The published
  app reported ready, restored MOSS, and displayed the generated video; final
  captures are `temp/ui-refresh/published-models.png` and `published-video.png`.

Limits: image references/editing use Qwen; Krea/MOSS are text-to-image workflows.
LoRAs must match the selected model family. Other display scaling factors,
every codec, and every model/size/duration combination were not exercised.

## Original desktop verification — 2026-09-22

Built with the installed .NET 10 SDK; Release publish completed with no warnings
or errors. No NuGet packages or model downloads were needed.

Verified in the real WPF window using Windows Computer Use:

- Empty description shows a useful message and focuses the prompt.
- Standard 1024 × 1024 generation completed, displayed its PNG, and added it to
  recent images. Output: `output/desktop/2026-09-22/Image_00001_.png`.
- Edit this image selected the source, changed the controls to Edit mode, and
  generated a winter version from the autumn source. Output: `Image_00002_.png`.
- Save as opened the native Windows dialog and exported a PNG. SHA-256 matched
  the generated original exactly (`temp/desktop-save-test.png`).
- Cancel generation interrupted the app's specific active prompt. The server log
  recorded targeted interruption; the app returned to ready and the queue was empty.
- Relaunch restored editing mode and source. A persisted job record referencing
  the first completed generation recovered its actual output and removed the
  pending record. The final app is open in Create mode with the sample prompt.
- Generated PNGs and JSON sidecars exist. The preview, source thumbnail, and recent
  images were visually inspected. WPF exposes labeled controls to UI Automation.

Contrast checks: secondary text on the app background 5.97:1; primary button text
8.87:1; input border on white 4.08:1 (above the 3:1 non-text threshold).

Custom icon update: Release publish passed. The generated RGBA artwork was
packaged into an ICO with 16, 20, 24, 32, 40, 48, 64, 96, 128, and 256 pixel
variants. Windows successfully extracted the custom icon from the executable;
the running WPF window visibly displayed the same icon. Both the project and
Windows desktop shortcuts were verified to target the published executable and
use its icon at index 0. The WPF window Icon resource supplies its taskbar icon.

Not exercised: a cold model/server start, an actual server disconnect during a
job, high-DPI configurations other than this desktop, and every size/quality
combination. The startup path reuses the existing server launcher; HTTP monitoring
retries connection failures and preserves a pending job for recovery.

## Prompt Builder and Q5 refinement — 2026-09-22

- Installed both Q5_K_M rewriters plus the matching I2I vision projector. All three
  model SHA-256 values matched Hugging Face metadata. Both pinned llama.cpp CUDA
  runtime archive SHA-256 values matched the official release metadata.
- Text-only worker smoke test completed in about 20 seconds including loading;
  returned a valid detailed portrait prompt and 2:3 ratio.
- Two distinct images (watercolor fox/cottage and the app's graphic icon) produced
  a valid edit rewrite in about 40 seconds. The rewrite correctly distinguished
  the cottage/fox from the icon's frame, mountains, sun, and brush, and retained
  `<image1>` as framing reference.
- The real desktop Refine button built a form draft, ran T2I Q5_K_M, displayed the
  result, and enabled Undo. Undo restored the draft. Cancel stopped an active
  refinement and returned to editable state without changing its draft.
- Loaded a saved reference fixture through the native file chooser: ten populated
  slots, Add disabled at the limit, and the saved art style restored. The fixture
  deliberately repeats the same sample image to test capacity, not visual quality
  across ten distinct characters. Image-aware refinement received all ten images
  (14,981 input tokens) and returned a valid prompt and `<image1>` framing.
- The app's own llama-server exited after each completed/cancelled request. An
  unrelated StockResearchLab llama-server remained running.
- `dotnet run --project tests/GraphChecks/GraphChecks.csproj -c Release` passed
  66 checks for reference ordering, create/edit framing, invalid requests,
  prompt presets, exact lettering, transparency, and preserved details.
- Python compilation passed for setup and rewrite workers. A code review found
  and fixed interrupted-runtime-download recovery and a late cancellation race.

No comparison against full-precision rewrite quality was performed. Real campaign
identity consistency depends on the references, instructions, and image model;
passing these tests does not guarantee exact reproduction.

Final end-to-end checks:
- Used the ten-reference AI result with Use for edit, generated at Standard/Draft,
  and displayed/saved `output/desktop/2026-09-22/Image_00008_.png` in 2:14. Visual
  inspection showed the requested spring setting with the cottage and sleeping
  fox retained. Original reference images were not modified.
- Native spellcheck underlined `beutiful`; the right-click menu offered `beautiful`.
- Final app publishing includes explicit UTF-8 worker output decoding and a
  cancellation check immediately before applying the completed result.
`Build Desktop.ps1` final Release publish passed. Original user settings were restored byte-for-byte (SHA-256 matched), the pending test job was cleared, and the rebuilt app was reopened.

## Modern desktop UI and image deletion — 2026-09-22

- Replaced the theme and layout with a dark graphite workspace, blue accents,
  dark native title bar, larger canvas, and separate guided/draft prompt panels.
  Generate and Build prompt remain fixed beneath their scrolling forms.
- Verified Create & Edit, empty References, Prompt Builder, dark shape dropdown,
  and guided prompt building in the running WPF app. Control names and event
  bindings remain connected; native TextBox spellchecking remains enabled.
- Delete image acts on the previewed output PNG and its `.png.json` sidecar.
  Confirmation defaults to No; the real dialog was inspected and cancelled,
  leaving the selected existing user image intact.
- The Windows recycle operation requests undo and a native warning before any
  permanent-delete fallback. Current references are removed only after the
  corresponding image is actually gone. The prompt is preserved.
- `tests/RecycleChecks` passed all 12 checks with newly created temporary files,
  covering paired recycling, missing images, non-PNG files, outside paths,
  sibling-prefix paths, and parent traversal. Existing user files were untouched.
- Release build and publish passed with no warnings or errors.
- Final published app was reopened and visually checked. Original user settings
  were restored byte-for-byte; their selected image remained present. Display
  scaling and layouts on other monitors were not exercised in this pass.

## Video Prompt Builder — 2026-11-01

- Added Image/Video selection, motion, camera, pacing, and sound/dialogue fields.
- Video prompts omit image preset framing and transparency. Image prompts retain
  existing presets; the image-trained local refiner is labeled and hidden in video mode.
- Separate written prompts survive mode changes and settings persistence; older
  image-only settings load without losing their draft. Shared scene/style inputs remain shared.
- Text-to-video and image-to-video actions transfer the edited prompt to Videos
  without generating, replacing the image prompt, or replacing a selected first frame.
- 106 graph/persistence/builder checks and 34 real-control UI checks passed.
- Native UI verification passed for composition, both handoff buttons, saved video
  mode/fields/output on close, and visual layout at default and smaller window sizes.
- Published the tested self-contained build to app; previous binaries retained in temp.

## Film implementation verification — 2026-11-05

Evidence for the current implementation is under `temp/film-implementation/evidence`.
Use isolated build state and project roots; do not use historical creative projects as fixtures.

```powershell
dotnet run --project tests/GraphChecks --artifacts-path temp/film-checks
dotnet run --project tests/UiChecks --artifacts-path temp/film-checks
dotnet run --project tests/FilmUiChecks --artifacts-path temp/film-checks -- 'D:\Image Studio'
dotnet run --project tests/RecycleChecks --artifacts-path temp/film-checks
dotnet run --project tests/StartupChecks --artifacts-path temp/film-checks
& D:/ComfyUI/python_embeded/python.exe -m unittest discover -s tests -p 'test_production_*.py'
```

The source-independent production tests cover persistence/replay/conflicts, adopted
and collected media, exact edit ranges and repair placement, AV tensors, immutable
promotion, retained failed judgments and concurrent delivery-state changes. Synthetic
review judgments are explicitly test data, never evidence of viewed/listened approval.

`measure_film_edit.py` measures a 100-occurrence, 14,400-frame synthetic H.264/AAC
edit, with budgets declared before export. The measured 640×360 run exported in
36.42 seconds and fully decoded; its largest measured child working set was 619.68 MiB.
Actual-client cancellation was about 1.02 seconds against a five-second budget.
These numbers are workload-specific; export memory excludes the parent UI/driver.
The original paused WPF player run presented a changed stable visible frame in 60.26 ms
against a 250 ms budget on this ten-minute cut. The owned-window pixel check does
not establish target-frame identity or sound synchronization; see `ui/seek.json`.

`verify_film_package.ps1` archives/extracts a portable package, checks every manifest
entry, and runs film persistence and the graph host with no engine installed.
`PublishedUiChecks` launches that actual self-contained executable and exercises
film creation, the appearance popup and native title-bar attributes through UI Automation. `FilmUiChecks`
renders all old/new workspaces in Dark/Light/System and checks actual Save shot,
draft preservation, title preference persistence, contrast and a 960×540 logical window.
The follow-up `--accessibility` mode adds actual keyboard tasks, a live Windows
high-contrast transition/restoration and foreground checks on actual Films text.
Physical 100/150/200% scale runs use `--physical-dpi=<percent>` after setting that
scale through Windows' standard UI; `physical-scale-restoration.json` verifies the
original 150% was restored. No registry or undocumented DPI mutation is used.

The current Film UI suite also uses an 8-bit frame ID encoded in H.264 source pixels
to verify exact paused frames, including the last frame and a rational 25/1 fps edit
reloaded through the shared interface. It waits for real MediaOpened events. Native
duration may be rounded; managed metadata and cut projections supply frame bounds.

`live_film_modes.py` / `finish_film_validation.py` retain a resumable, isolated ten-job
follow-up fixture. They exercise the same packaged JSON interface, exact ownership,
source/range bindings and real sound assembly. `transcribe_film_trial.py` is an offline
CPU diagnostic using an independently verified existing runtime/model, never a required
bundled dependency. Its failed wording check must not be relabelled as a pass.

The explicit temporary process coexistence approval is scoped to ten exact admission
owners and two exact PID/executable/start-time identities, with expiry and immutable
permission snapshots. The normal app has no automatic coexistence permission. Missing,
expired, changed-byte or different-owner approval keeps strict waiting in force.

`live_film_preview.py` and `live_av_restart.py` are opt-in bounded GPU diagnostics,
not ordinary unit tests. Read current model inventory/research and existing reservations
before running them. Their evidence records the selected UUIDs and full graphs; never
delete a receipt or automatically replay an ambiguous submission. Only the tested
preview/finish/decode modes receive execution evidence; semantic/listening review
and untested conditioning modes remain unverified.
