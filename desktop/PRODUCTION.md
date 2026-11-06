# Local production checks and resumable jobs

The desktop app remains a single-clip editor/generator. These optional Python tools
support local production experiments using its existing Comfy engine and API graphs.
They do not implement a longform timeline UI, semantic reviewer or automatic scheduler.
No new Python packages are needed. Media checks use installed FFmpeg/ffprobe.

## Integrated film workflow

[FILM_PROCESS.md](FILM_PROCESS.md) is the current process. The completed Opus production's
`output/evie-blocked-2026-11-02/film.py` and `05-film/edit.py` now invoke the shared
acceptance/workflow controls. The single-clip desktop UI and general job runner keep
their existing interfaces. Historical films are preserved and have no new approval.

Each film project keeps `production/task/current-task.json`. Use the existing
`production_acceptance.py record` command to create/update it from a proposal, with
`--expected new` initially or the exact previous token on update. The current project
includes a proposal and an installed record with **no new production authorized**;
reconcile the next actual assignment before rendering. Do not remove an unresolved
requirement merely to make a command pass.

The proposal contains the normal task fields plus `production`:

- `inputs`: absolute-path/SHA-256 references for the current brief, blocking, prompts,
  adapter code and other common material inputs. All are checked before work.
- `pilot_jobs`: map of explicitly allowed job names to fingerprints of their exact
  `{name, kind, settings}` plan items. An empty map allows no initial pilot rendering.
  Use `production_acceptance.fingerprint(item)`; the pilot exception cannot admit
  arbitrary jobs merely because a plan is small.
- `repair_limits`: stable defect ID to total candidate allowance, e.g. `{"escape": 2}`.
  Reservations persist in `production/runs.json` across new seeds/plans/task revisions.
  Resuming the same take does not spend another candidate. An interrupted reservation
  is conservative; it is not automatically refunded.

Use `production_acceptance.film_requirements()` when constructing the proposal. The
validator requires the current full film profile, including action/body/listening
evidence. `production_plan_template.json` supports the review; its placeholder fields
are not machine-validated semantic facts. Supply the actual brief/plan/evidence and
record unavailable review honestly.

For expansion, place `pilot-candidate.json` and `pilot-review.json` under `production/`.
The candidate has purpose `pilot` and the exact connected pilot artifact/timeline.
Its dependencies must include every file returned by
`production_workflow.context(project, token)[2]`, plus its material media inputs.
The review uses the existing acceptance schema, with all required checks and cut
evidence. A missing/failed review blocks the batch; passing declarations are trusted
judgments, not proof that this code perceived a film.

From the project directory, using the existing interpreter:

```powershell
# TOKEN is the current task fingerprint returned by record (or ref on its canonical JSON).
python film.py plans/pilot.json --phase pilot --expected TOKEN
python film.py plans/next-batch.json --expected TOKEN
python film.py plans/repair.json --phase repair --defect escape --expected TOKEN
```

The default phase is `scale`, even for a one-job plan. A pending/unknown/failed job
stops the batch before later submissions. Completed results update `plans/results.json`
atomically; other entries survive. Rerun the same command to resume its recorded
revision. Job names are immutable. Historical names without the new ledger are never
silently regenerated: inspect their saved `selected-revision.json` and use the general
runner to reconcile pending IDs. Existing runner attempt limits/ambiguous-POST policy
still apply. Stale pending jobs can be reconciled through that runner; they cannot
become current approvals or silently authorize new work.

Assembly uses the current task's intended delivery path in a **new** folder:

```powershell
python 05-film/edit.py mix 05-film/picks-mix.json --destination 05-film/revision-new --expected TOKEN
python 05-film/review.py cuts mix --edit-dir 05-film/revision-new --destination 05-film/review-new
```

The editor checks actual source frame counts before encoding, snapshots selected
sources/dependencies, validates the master with a full decode, and writes `candidate.json`,
`timeline.json`, `edit-inputs.json` and `technical-validation.json`. Output is explicitly
an incomplete review cut. Review extraction uses that encoded candidate, exact cut
frames and a fresh evidence directory. Take-sheet clamping is recorded and short
sources are labeled; it does not satisfy edit duration. The existing ASR verifier now
requires `--edit-dir` and a fresh `--report`; it compares ordered normalized wording.
Running it still uses its existing model and applicable inventory/research procedure;
integration tests do not execute it or select a model.

After actual review, completion is an explicit check of the existing bytes:

```powershell
python 05-film/edit.py mix --destination 05-film/revision-new --expected TOKEN --release-review path/to/review.json
```

This action renders nothing. It archives the review, applies the exact-artifact gate,
and writes a content-bound receipt in `production/deliveries/` only on success.
It uploads/sends nothing. A later change to task, inputs, criteria, media or review
requires a fresh check; a historical receipt is not continuing authorization.

CLI batch exit codes: 0 rendered/unreviewed, 2 pending/unknown submission, 1 blocked
or failed. Assembly exit 0 means a valid **review cut**; only the explicit release
action can emit `completion: true`. No helper can force an assistant's prose to be true.

## Run the checks

From `D:\Image Studio`:

```powershell
& 'D:\ComfyUI\python_embeded\python.exe' -B -m unittest discover -s tests -p 'test_production_*.py' -v
```

`production_media.py` accepts a JSON specification and writes a **new** report:

```json
{
  "shots": [{"id": "S01", "seconds": 5}, {"id": "S02", "seconds": 6}],
  "fps": 24,
  "sample_rate": 48000,
  "cues": [{"shot_id": "S02", "offset": "0.65", "seconds": "38/15"}],
  "word_checks": [{"intended": "That's better.", "transcript": "That's better."}],
  "media": "D:/Image Studio/output/my-project/review.mp4",
  "expected": {"duration": 11, "frames": 264, "fps": 24, "audio_rate": 48000, "channels": 2}
}
```

```powershell
& 'D:\ComfyUI\python_embeded\python.exe' desktop/production_media.py spec.json --report checks-new.json --full-decode
```

Video durations use exact frame counts. Audio cues use exact samples independently
of the video frame grid; use rational strings such as `60800/24000` from the actual
WAV sample count rather than rounded metadata. Cue positions reflow when earlier
shots change. Wording checks preserve intended and observed text separately.

For a music stem, add `"check_audio_gaps": true`, `"min_silence": 1` and explicit
`"allowed_quiet": [[0,1],[119,120]]` intervals appropriate to that asset. The detector
finds all-channel sample silence; it cannot decide whether a pause is artistic,
whether music is good, or whether speech is intelligible. Inspect the stem separately:
effects can hide a music gap in the final mix. These values are examples, not universal
delivery standards. Media reports include content hashes and refuse overwrite.

## Prepare and run a graph revision

Supply a Comfy **API graph**, not editor-layout JSON. The job specification contains:

```json
{
  "graph": {
    "1": {"class_type": "LoadImage", "inputs": {"image": "replaced-during-staging.png"}},
    "2": {"class_type": "SaveImage", "inputs": {"images": ["1",0], "filename_prefix": "replaced-for-isolation"}}
  },
  "inputs": [{"node": "1", "field": "image", "path": "D:/Image Studio/input/source.png"}],
  "dependencies": ["D:/Image Studio/output/my-project/approved-intent.json"],
  "environment": {"backend": "ComfyUI 0.42.1", "model": "none; this example copies an image"},
  "output": {"node": "2", "key": "images", "type": "output", "extension": ".png"}
}
```

```powershell
& 'D:\ComfyUI\python_embeded\python.exe' desktop/production_jobs.py prepare job.json --project-root 'D:\Image Studio\output\my-project' --engine-input 'D:\Image Studio\input' --engine-output 'D:\Image Studio\output'
# Use the revision path printed by prepare:
& 'D:\ComfyUI\python_embeded\python.exe' desktop/production_jobs.py run '<revision-path>' --timeout 30 --max-attempts 2
& 'D:\ComfyUI\python_embeded\python.exe' desktop/production_jobs.py status '<revision-path>'
```

Only loopback HTTP is allowed. The installed backend must support caller-supplied
UUID prompt IDs. The runner starts/stops/cancels no engine. Graphs and explicit
dependencies are trusted local input; this is not a sandbox for arbitrary custom nodes.

Input bytes, graph, selection, environment declaration, runner implementation and
dependency hashes define a revision. Input files are staged under digest-based names;
saver prefixes are isolated by revision and attempt. The exact selected saver collection
must return one nonempty file of the specified type/extension. Original and preserved
copy hashes must still match for reuse/review. Media decode/creative checks are separate:
`completed` means validated job provenance and bytes, not approved audiovisual quality.

Declare **all relevant dependencies**, including model files or a verified immutable
model catalog, workflow/code versions, creative intent, and upstream selection manifests.
Checkpoint names alone do not identify model bytes. Actual model files are hashed with
bounded memory but can cost disk I/O. Caller-supplied environment metadata is not
automatically verified. Unsupported custom loaders must have their files explicitly
declared; arbitrary ambient reads are outside this cache contract.

Downstream specs must declare the relevant shared/transitive dependencies themselves.
Changing a declared selection/intent manifest makes its consumers stale; unrelated
revisions stay current. There is no hidden DAG discovery or automatic regeneration.
Prepare a new revision after changes. Existing results/reviews survive, but stale
approval cannot authorize new content. During generation, a stale revision can still
reconcile its existing attempt read-only; it cannot submit another attempt or be approved.

## Resume, retry and review

The runner persists a UUID and payload **before** submission. After a timeout or lost
response, rerun the same revision: it reconciles history/queue using that UUID and graph.
It never repeats an ambiguous POST. A missing job/history is `lost` or
`unknown_submission`, not permission to retry. Preserve its state and inspect that ID
and engine logs; resolve ambiguity before deliberately preparing a new candidate.

Automatic retries require an explicitly allowlisted `retry_errors` exception type
and a definitive engine execution failure. The attempt cap is durable and cannot
increase on resume. Validation rejection, cancellation, missing history and uncertain
submission never trigger blind retries. Polling is bounded; the persisted pending ID
survives timeout. CLI exit codes: 0 for current completed/prepared state, 2 for
pending/unknown state, 1 for failed/rejected/invalid/lost or stale state and errors.

After checking the actual candidate with the required criteria, record a review:

```powershell
& 'D:\ComfyUI\python_embeded\python.exe' desktop/production_jobs.py review '<revision-path>' --criteria 'my-review-v1' --evidence 'path to checks and actual review notes'
# Add --reject for a failed or not-yet-approved candidate.
```

This is a caller-recorded judgment, not an automated semantic check. Review records
bind the revision and selected-result hashes and retain previous decisions. Revalidate
when inputs, outputs, implementation or criteria change. Before release, measure and
watch/listen to the exact encoded master and write its report with the final hash.

## Evie evidence

The reversible synthesis, preflight, bounded score experiments and model-audit
comparison are under `audits/evie-workflow/synthesis__20261101-221603`. Original film,
scripts, assets and independent audits are unchanged. Run `preflight.py --report <new-path>`
there for the preserved production: it intentionally flags wording and score defects.
No complete revised film or 10–15-minute quality claim follows from passing code tests.

## Native Films interface — 2026-11-05

Image Studio 2.3 adds Plan → References → Storyboard → Takes → Edit → Review.
The GUI and scripts use `production_service.py`; no web server or historical film
adapter is required. Send one UTF-8 JSON object on stdin and receive one JSON reply:

```json
{"version":1,"operation":"create","request_id":"a-unique-stable-id","payload":{"title":"My film"}}
```

Run `runtime/production-python/python.exe desktop/production_service.py <studio-root>`
in an extracted package. `open` and `list` are reads. Writers supply `project_id`,
`expected_revision`, and a fresh request ID; replaying the same ID/content returns
its receipt. A changed payload with the same ID conflicts. Exit 0 means success;
exit 2 carries a structured error. Keep stdout for the result and stderr for diagnostics.

Project records, immutable history, adopted references/sidecars/material bindings,
cuts, reviews and transcripts live in `user/films/<stable-id>`. Collection verifies
a manifest and supports importing into another installation with the original root
unavailable. Existing stable-ID collisions are refused. Relocation preserves historical
receipts and failed judgments; it does not silently preserve current-final approval.
Unknown/pending jobs cannot be collected or retargeted. Ordinary galleries and the
actual recycle boundary protect `output/films` and `output/production-jobs`.

The editor stores half-open source-frame ranges and independent 48 kHz sample cues.
Repeated/split sources have separate occurrence IDs. Imported video must have the
edit's constant frame rate; VFR/different-rate sources are rejected pending explicit
normalization. Drafts can contain visibly labelled missing-shot placeholders. Draft
rendering does not acquire the editor lock while encoding and never issues delivery.
Timeline Undo/Redo, gaps, trims, fades, volume/mute, titles, markers, lazy inspection
and exact-anchor repair placement use the same Python owner as scripts.

GPU admission is shared by Films, Create and prompt refinement. Pause blocks the
next persisted admission. Closing a view stops new ticks; an admitted engine job is
reconciled by UUID/full graph rather than replayed. Targeted cancellation requires
an owned item and a supported atomic backend route; `cancelled:false` is not success.
Ambiguous submissions retain their reservation. Unrelated GPU work is left alone.

H3 preview/finish graphs come from the same C# builder as Create, via the packaged
graph host. Typed SafeTensors AV companions preserve both tensor branches and
supported metadata/masks. Loader files, exact source ranges, model/runtime identities,
full executed graphs and selected-companion lineage are bound to receipts. The tested
finish is interpolated latent resizing plus two-step refinement, **not learned upscaling**.

The reference configuration completed a 124-frame 768×448 Pika Flex preview and a
1280×768 finish; both fully decode. After a real engine restart, decode-only reloading
produced identical decoded video and audio hashes. Reference details and limits are
in `production_capabilities.json`. Other conditioning/repair paths have explicit pilot
graphs and range contracts, but their seam/performance quality remains unverified.
Ref2VA/control cannot be presented as verified conditioning without compatible
runtime/weight evidence. No new synthesis/ASR model is required for manual imports.

Review records bind the exact candidate/audio interval and retain failures by byte hash.
Independent observed transcripts are stored separately from intended dialogue and
hashed against decoded audio. Failed/unavailable recognition remains unverified.
Promotion copies exact scratch bytes to a fresh intended-final path and updates task
authority. Delivery rechecks the active edit, task and retained review set at its final
commit. A passing integrity check does not itself perceive film quality.

Follow-up verification completed ten bounded real H3 jobs: three connected generated
shots, first/last/last-only/voice conditioning, selected-AV finish and all four repair
operations. Short Bridge/Fill/Retake endpoints are anchored inside the retained frame
range, with versioned immutable bindings. A multi-scene 15-second cut preserves three
independent sound cues and three linked source tracks; its 720,000-sample review
interval fully decodes. None of this grants perceptual or listening approval.

Independent CPU Whisper recognition of the voice-guided output found the intended
sentence plus additional words; the ordered-word diagnostic failed. Expected words
were not supplied to recognition. The exact audio-bound transcript and failure remain
inspectable. A short guide only conditions its covered interval; unconditioned tail
audio is not promised to preserve dialogue or silence.

Actual keyboard tasks across all workspaces, live Windows high contrast and physical
100/150/200% scaling were exercised; original OS appearance/scale were restored. Exact
paused source-frame identity was measured using encoded pixel IDs. The viewer uses
managed-source/cut frame metadata and rational rates, since Windows duration alone
can be rounded. Comparison playback remains approximate; scrubbing shares time.

Full-speed perceptual motion/seam, story/identity and by-ear performance approval remain
open. Control/Ref2VA have no verified Film graph route, picture overlaps are rejected,
VFR/different-fps imports require explicit normalization or rejection, and audio-only
Extend still has no picture-hold policy. Native playback is codec-dependent; the exact
seek test uses standard H.264 Main; the initial lossless 4:4:4 fixture showed black
frames in this native path and did not prove seeking. Do not
describe a generated film as approved without actual-artifact review.
