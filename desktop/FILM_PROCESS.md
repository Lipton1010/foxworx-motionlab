# Current local filmmaking process

Revision: 3 November 2026. Use this when planning, resuming, repairing, reviewing or handing off a narrative-film production. This is the current process integrated with the film batch and assembly/delivery entry points; earlier reports remain evidence, not competing instructions. Start from the production's current accepted brief, never from the historical Evie plot.

## 1. Establish the assignment

Maintain one current-task record with accepted story, observable viewer outcomes, scope, decisions and sources, superseded directions, unresolved requirements and intended delivery. Capture consequential changes before dependent work. On resume, status, handoff and delivery, reconcile the latest relevant user decisions with that record; an older completed artifact is not the current assignment. Use the existing `record` operation and expected token so stale writers fail.

Define success in viewer terms: what causes the action, what changes, why the response makes sense, and what the viewer should understand or feel. Carry accepted dialogue and lyrics separately from transcripts. Decide any unresolved creative direction with Paul; routine execution and bounded repair within accepted direction need no new approval ceremony.

**Done:** the current record agrees with the decision sequence, and uncertain requirements are explicit. Unresolved creative intent blocks dependent production, not unrelated checks.

## 2. Prove the action in inexpensive blocking

Use one spatial plan with camera views, character/prop states and motivated cuts. In each shot record the trigger, response, visible path, timing, destination, occlusion/reappearance and body mechanics. Inspect the connected low-detail sequence at its intended speed. Correct endpoints do not establish a readable escape, sustained swimming or believable reaction.

Record what the reviewer understands from picture alone, then from picture with intended dialogue/sound. Dialogue may clarify motivation or emotion; an action contradicted or absent on screen requires a staging repair. This is not a requirement for a wholly silent film to explain every detail.

Mark objects in each control pass: geometry to include, effects to exclude or render separately, and deliberate occluders. Inspect silhouettes, depth and thin/flat proxy shapes for unintended forms. Compare styled first/end frames with the camera projection for framing, scale, cast count and identity. References declare their role, preserved properties and allowed changes; a styling reference must not silently replace the camera plan.

Inspect critical path crossings in depth or with distinguishable preview colours: characters should not pass through each other or become unintentionally buried in a crowd. Establish a prop/effect's visible origin before its consequence. Re-evaluate a corrective prompt when the pose changes; its earlier success is conditional on that staging.

**Done:** a capable reviewer can follow the required action, timing and body mechanics in the preview, and the actual control inputs support the intended constraints. Missing playback or ambiguous action remains unverified/failed in `blocking`; extra stills cannot turn it into a pass.

## 3. Test the difficult connected sequence before expansion

Choose a representative interaction with incoming and outgoing cuts (at least three connected shots), appropriate voice/sound and the proposed finishing/export path. Use the existing narrative-film checks plus [production_requirements.json](production_requirements.json). Complete the applicable fields in [production_plan_template.json](production_plan_template.json); this is a review input, not a schema validator or an approval.

The pilot should expose the production's real risk: occlusion, shared space, expressive acting, sustained locomotion, distant faces or another consequential capability. Record why it is representative. Give the reviewer the actual artifact and brief, and use a separate capable reviewer where available. If neither the agent nor another available reviewer can inspect required motion/audio, request that specific viewing/listening from Paul or stop at a labeled incomplete review cut.

**Done:** current pilot and finishing evidence satisfy `scale`, with genuine motion/audio observations. Synthetic fixtures, successful rendering and sampled-frame approval do not establish this. Reuse the same accepted plan/reviews at delivery only while their evidence and dependencies remain current; no duplicate ceremony is needed.

## 4. Generate, select and repair within a budget

Retain immutable takes, saved graphs, exact input/output hashes, voice lineage, separate stems and durable job IDs. Pass scene state and reference roles between shots. Use continuation or endpoint guidance where the action needs it and the supported path has been tested; chaining every last frame can propagate errors.

Select exact usable source ranges, with source frame count/rate, in/out frames, reason, and entry/exit state. Require `0 <= in < out <= actual frame count`; flag inadequate duration or missing action. Clamping review samples prevents out-of-range access but does not make a short take adequate. Review the assembled neighbors after trims, model mixing or grading for scale, identity, colour, expression, action and audio changes. Prefer the take that meets the shot's requirements; model assignments remain local observations, not a universal rule.

For a defect, record the observed failure, smallest likely owner (blocking, control pass, reference, take, edit or mix), one bounded change, evaluation criterion and total repair budget. Start with at most two generated repair candidates for that defect unless the current task specifies another limit. Carry the budget across prompt/seed revisions; making a new revision does not reset it. After exhaustion, stop that repair and present the evidence and specific alternatives. Other independent work may continue. The batch adapter enforces the recorded total repair budget by stable defect ID across seeds, plans and task revisions, reserving each candidate before submission. The existing runner separately enforces its per-revision execution-attempt cap. A changed defect ID is a new declared problem and still requires honest scope review.

Reconcile ambiguous submissions by their durable IDs before doing anything that could duplicate them. A reported load failure clearing on retry does not authorize replay of an unknown submission. Re-review the repaired output and affected adjacent cuts; preserve unrelated accepted work and all rejected evidence.

**Done:** selected ranges meet current requirements, material dependencies are declared, required repairs pass on their new bytes, and unresolved failures remain visible.

## 5. Reconcile sound with the current story and edit

Set intended dialogue timing and story/lyric fit before final music selection. Keep approved song structure and complete phrases; justify and listen to any join, fade, ducking or edit. An intact song is an option, not a blanket prohibition on editing. Check stem coverage separately from the final mix; intentional silence is recorded, and effects must not conceal an unintended score gap.

Anchor sound events to shots/actions so edits reflow them. State whether music enters on a picture cut, prelaps it or follows it, using actual frame/sample timing. ASR checks wording; listening checks delivery, intelligibility, transitions, masking, musical endings and emotional fit. Measure loudness and peak separately on the final encode against the production's chosen targets; historical gain/ducking/stroke settings are not defaults.

Check voice timing and internal pauses against the selected take's visible mouth movement and occlusion. Conditioning inputs and recognized words do not prove lip sync. A timing repair needs review with the final picture and sound regardless of which generator supplied the take.

**Done:** `story`, `motion_audio` and `performance` evidence addresses the actual current picture and sound. Wording matches and numerical levels alone cannot approve them.

## 6. Assemble, review and hand off the exact result

Use fresh assembly outputs or a separately proven content-aware reuse path. The current editor requires a fresh output directory; the original stale-output defect has been reproduced, but was not proven to cause the historical wrong-film delivery. After assembly, decode/measure the master, inspect both sides of every declared cut and surrounding playback, and watch/listen to the connected film. Judge intentional viewpoint/time changes against the scene plan, not identical screen coordinates.

Keep technical, identity, story, motion/audio and performance results distinct. Every required failed/unverified result blocks a completion claim unless Paul explicitly authorizes a scoped exception; preserve the original status. An incomplete review cut can be shown with its explicit label. Bind the task, candidate, timeline, dependencies, evidence and reviews to exact hashes, then run `deliver` immediately before claiming completion. Reports and handoffs identify the inspected artifact, current direction, outstanding gaps and actual review methods.

**Done:** the current encoded master satisfies the recorded requirements, or is accurately labeled incomplete. External sending/publishing still requires the user's authorization. A process-test pass never approves a film or demonstrates 10–15-minute readiness.

## Adoption and enforcement

For an authorized production, use `production_acceptance.film_requirements()` for that task's requirements and save it with `record`; the live validator requires all base and planning IDs/modalities. Reconcile the production/task/current-task.json record first. See [PRODUCTION.md](PRODUCTION.md) for the actual commands and record fields. Bind the plan **and each material referenced file** separately in `candidate.dependencies`. The gate does not follow nested references automatically. Changed criteria require new task/candidate/review bindings; old passes remain historical.

The gate enforces supplied statuses, required modalities, declared cut coverage and record/hash consistency. It does not understand films, validate all planning fields, authenticate review claims, discover hidden dependencies, or intercept an agent bypassing it. The refined criteria guide capable judgment; they are not an automatic semantic detector.

The current `output/evie-blocked-2026-11-02/film.py` calls the shared workflow before each generation job. An exact, declared pilot allowlist permits initial pilot work; expansion/repair requires the current pilot review. Pending/uncertain results stop the batch and preserve earlier selections. The editor in that project's `05-film/edit.py` reserves a new directory, verifies sufficient source ranges, snapshots inputs and validates the resulting encode. It emits an incomplete review cut. Its explicit `--release-review` action checks the actual candidate before writing a completion receipt, without rendering again. The review/extraction tools accept the new edit directory and use the encoded candidate.

Shared implementation: `production_acceptance.py`, `production_workflow.py`, `production_requirements.json` and `production_plan_template.json` beside this document. The batch and editor enforce these checks on their public paths. Direct low-level job calls and unrelated scripts remain general tools, not a security boundary. Original completed films are preserved; integration does not retrospectively approve them. The desktop UI remains a single-clip tool.

## Evidence and decisions

| Evidence | Retained or changed | Why / limits |
|---|---|---|
| [Audit synthesis](../audits/evie-workflow/synthesis__20261101-221603/synthesis.md), SYN-01/04/05/06/10 | Retain immutable jobs, state/evidence binding, exact timing, wording separation and stem checks | Supported failures already have useful controls. No new scheduler, model replacement or generic quality score is justified. |
| [Reconciled postmortems](../output/process-review-2026-11-01/combined-findings.md) and [safeguard tests](../output/process-review-2026-11-01/safeguards-2026-11-02/verification-04/results.json) | Retain current-task reconciliation, meaningful failure states, connected pilot, every-cut and exact-delivery review | Address observed wrong-task delivery and insufficient acceptance. Internal cause and broad counterfactuals remain unproven. |
| [Tutorial reconciliation](../output/process-review-2026-11-01/safeguards-2026-11-02/video-learning-97lwtJ8NESs/README.md) | Retain common spatial plan, reference roles, source ranges, early finishing and total resource accounting | Methods to evaluate locally, not proof of universal savings or tool superiority. |
| [Opus reconciliation](../output/process-review-2026-11-01/safeguards-2026-11-02/opus-findings-follow-the-warm-2026-11-02/README.md) | Strengthen existing criteria for action timing, occlusion, locomotion, control-pass contents, mixed-shot review and story/music fit | His reported staging fixes explain what the pilot should expose. No fresh audiovisual validation is claimed. |
| [Negative score trial](../audits/evie-workflow/synthesis__20261101-221603/implementation-log.md) | Carry a defect-level repair budget across revisions; change the hypothesis after exhaustion | Two seed-only candidates failed the declared signal criterion. This is not proof all seeds or models fail. |

The captured mixed-cut records contain 15 H3 / 13 LTX selections, not 16/12. They place music at 16.5s and the nearest picture boundary at 17.0s. These are record corrections, not evidence of an audible defect; intentional prelap remains possible. The claimed 27 passing cuts is Opus's reported inspection, not this update's new observation.

No model is selected or recommended by this process update. Future selection/reuse follows Paul's current web-research and canonical inventory procedure, including exact variant, runtime, hardware, licence and project compatibility. One production's timings, recipes or private-viewing assertion cannot substitute for those checks.
