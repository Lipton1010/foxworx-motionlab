using ImageStudio;
using System.Text.Json;
using System.Text.Json.Nodes;

int checks = 0;
void Check(bool condition, string message)
{
    if (!condition) throw new Exception(message);
    checks++;
}
void Reject(Action action, string message)
{
    try { action(); }
    catch (ArgumentException) { checks++; return; }
    throw new Exception(message);
}
JsonNode Graph(ImageRequest request, string[]? images = null) => JsonSerializer.SerializeToNode(StudioEngine.BuildGraph(request, images))!;
void Link(JsonNode? value, string node, int slot, string label) => Check(value?[0]?.GetValue<string>() == node && value?[1]?.GetValue<int>() == slot, label);

var request = new ImageRequest("A dwarf archivist", "blur", 1234, 1536, 1024, 20, false, null, 1440);
var plain = Graph(request);
Check(plain.AsObject().Count == 8 && plain["4"]!["inputs"]!["resolution"]!.GetValue<int>() == 0, "A new image without references needs no image loading or reference scaling.");
Link(plain["6"]!["inputs"]!["latent_image"], "5", 0, "A new image must start from the requested empty latent.");
Check(plain["5"]!["inputs"]!["width"]!.GetValue<int>() == 1536 && plain["5"]!["inputs"]!["height"]!.GetValue<int>() == 1024, "New-image dimensions must preserve the selected shape.");

var refs = Enumerable.Range(1, 10).Select(i => new ReferenceImage { Path = $"local/reference-{i}.png", Role = "Character identity", Notes = $"Keep identity {i}" }).ToArray();
var uploads = Enumerable.Range(1, 10).Select(i => $"desktop/upload-{i}.png").ToArray();
var createWithRefs = Graph(request with { References = refs }, uploads);
var edit = Graph(request with { Source = refs[0].Path, References = refs }, uploads);
foreach (var graph in new[] { createWithRefs, edit })
{
    var encoding = graph["4"]!["inputs"]!;
    Check(encoding["resolution"]!.GetValue<int>() == 1440, "Reference resolution must use the request setting.");
    Link(encoding["vae"], "3", 0, "Reference encoding needs the VAE.");
    for (int i = 1; i <= 10; i++)
    {
        string node = (8 + i).ToString();
        Link(encoding[$"images.image_{i}"], node, 0, $"Reference {i} must retain its image slot.");
        Check(graph[node]!["inputs"]!["image"]!.GetValue<string>() == uploads[i - 1], $"Reference {i} must load the same ordered uploaded image.");
    }
    string prompt = encoding["prompt"]!.GetValue<string>();
    Check(prompt.Contains("<image1>: Character identity. Keep identity 1") && prompt.Contains("<image10>: Character identity. Keep identity 10"), "Role guidance must identify the first and tenth image correctly.");
}
Link(createWithRefs["6"]!["inputs"]!["latent_image"], "5", 0, "Reference-guided creation must retain independent output dimensions.");
Check(createWithRefs["5"]!["inputs"]!["width"]!.GetValue<int>() == 1536, "Reference images must not replace a new composition's selected width.");
Link(edit["6"]!["inputs"]!["latent_image"], "4", 2, "Editing must use the latent from the main reference image.");
Check(edit["5"] == null && edit["4"]!["inputs"]!["prompt"]!.GetValue<string>().StartsWith("Edit <image1>: "), "Editing must target image1 without an unused empty latent.");
var legacy = Graph(request with { Source = "legacy.png" }, ["desktop/legacy.png"]);
Link(legacy["6"]!["inputs"]!["latent_image"], "4", 2, "Saved requests from before reference sets must still edit their single source.");
Reject(() => StudioEngine.BuildGraph(request with { Source = "missing.png" }), "An edit without an uploaded source must fail before queueing.");
Reject(() => StudioEngine.BuildGraph(request, uploads.Concat(["extra.png"]).ToArray()), "An eleventh reference must fail.");
Reject(() => StudioEngine.BuildGraph(request with { References = refs }, uploads[..9]), "Incomplete uploads must not silently shift or drop references.");

var draft = new BuilderDraft(3, "Dwarf archivist", "", "Watercolor", "", "Soft light", "", "Copper beard clasp and blue left eye", "");
string token = MainWindow.ComposePrompt(draft);
Check(token.Contains("RGBA image with transparency") && token.Contains("background is transparent"), "Token prompts must request alpha transparency.");
Check(token.Contains("entirely within the frame") && token.Contains("no border, base, or surrounding scenery"), "Token prompts must preserve a usable isolated silhouette.");
Check(token.Contains("Preserve these details: Copper beard clasp and blue left eye."), "Campaign identity requirements must survive composition.");
Check(token.Contains("No lettering or watermark."), "Unspecified lettering must not add accidental labels.");
string handout = MainWindow.ComposePrompt(draft with { Type = 2, Lettering = "Wanted: Captain O'Malley!\nReward: 500 gold" });
Check(handout.Contains("Include exactly this lettering: \"Wanted: Captain O'Malley!\nReward: 500 gold\"."), "Exact handout lettering must preserve punctuation and line breaks.");
Check(!handout.Contains("RGBA") && handout.Contains("player handout"), "Handouts must not inherit token transparency framing.");
Check(MainWindow.ComposePrompt(draft with { Type = 1 }).Contains("wide scene"), "Backdrop preset must use wide composition.");
Check(MainWindow.ComposePrompt(draft with { Type = 0 }).Contains("readable face"), "Portrait preset must prioritize a readable face.");
Reject(() => MainWindow.ComposePrompt(draft with { Subject = " " }), "An empty subject must be rejected.");
var videoDraft = draft with { Video = true, Motion = "The fox turns its head", Camera = "Slow push-in", Pacing = "Pause, then look toward the door", Audio = "Birdsong; no speech", VideoOutput = "My edited video prompt" };
string videoPrompt = MainWindow.ComposePrompt(videoDraft);
Check(videoPrompt.StartsWith("Create a video clip."), "Video prompts explicitly request a clip.");
Check(videoPrompt.Contains("Subject and scene movement: The fox turns its head.") && videoPrompt.Contains("Camera movement: Slow push-in."), "Video composition preserves subject and camera motion.");
Check(videoPrompt.Contains("Timing and pacing: Pause, then look toward the door.") && videoPrompt.Contains("Sound and dialogue: Birdsong; no speech."), "Video composition preserves pacing and audio.");
Check(!videoPrompt.Contains("RGBA") && !videoPrompt.Contains("isolated subject"), "Video prompts must not inherit a selected image token preset.");
Check(!MainWindow.ComposePrompt(videoDraft with { Type = 0 }).Contains("Portrait framing"), "Video prompts must not inherit default image portrait framing.");
Check(MainWindow.ComposePrompt(videoDraft with { Composition = "Wide shot of the garden" }).Contains("Composition: Wide shot of the garden."), "Video prompts preserve explicit framing.");
Check(!MainWindow.ComposePrompt(videoDraft with { Video = false }).Contains("Camera movement:"), "Hidden video fields must not leak into image prompts.");
Check(JsonSerializer.Deserialize<BuilderDraft>(JsonSerializer.Serialize(videoDraft)) == videoDraft, "Video builder fields and separate drafts survive JSON persistence.");
var legacyDraft = JsonSerializer.Deserialize<BuilderDraft>("""{"Type":0,"Subject":"Fox","Setting":"","Style":"","Composition":"","Lighting":"","Lettering":"","Preserve":"","Output":"Saved image draft"}""")!;
Check(!legacyDraft.Video && legacyDraft.Output == "Saved image draft" && string.IsNullOrEmpty(legacyDraft.VideoOutput), "Existing saved builders open as images without losing their prompt.");
Reject(() => MainWindow.ComposePrompt(videoDraft with { Subject = " " }), "An empty video subject must be rejected.");
var loras = new[] { new LoraSelection("first.safetensors", 0.65), new LoraSelection("disabled.safetensors", 1.0, false), new LoraSelection("second.safetensors", -0.25) };
var catalogSchema = JsonNode.Parse("""{"Legacy":{"input":{"required":{"model":[["legacy.safetensors"],{}]}}},"Modern":{"input":{"required":{"model":["COMBO",{"options":["modern.safetensors"]}]}}}}""")!;
Check(ModelCatalog.Options(catalogSchema, "Legacy", "model").SequenceEqual(new[] { "legacy.safetensors" }), "Legacy ComfyUI model pickers must remain readable.");
Check(ModelCatalog.Options(catalogSchema, "Modern", "model").SequenceEqual(new[] { "modern.safetensors" }), "Modern ComfyUI COMBO schemas must expose installed models too.");
var withLoras = Graph(request with { Loras = loras });
Link(withLoras["6"]!["inputs"]!["model"], "studio_lora_1", 0, "Image sampling must use the complete enabled LoRA chain.");
Link(withLoras["4"]!["inputs"]!["clip"], "studio_lora_1", 1, "Text encoding must use the LoRA's CLIP output.");
Link(withLoras["studio_lora_0"]!["inputs"]!["model"], "1", 0, "The first LoRA must start from the original model.");
Link(withLoras["studio_lora_1"]!["inputs"]!["model"], "studio_lora_0", 0, "LoRAs must preserve their selected order.");
Check(withLoras["studio_lora_0"]!["inputs"]!["strength_model"]!.GetValue<double>() == 0.65, "LoRA strength must be preserved.");
Check(!withLoras.ToJsonString().Contains("disabled.safetensors"), "Disabled LoRAs must not be sent to the engine.");
Reject(() => Graph(request with { Loras = [new("invalid", double.NaN)] }), "Invalid LoRA strength must fail before submission.");
var moss = Graph(request with { Model = "moss-image-base", Loras = loras, Steps = 50 });
Link(moss["15"]!["inputs"]!["model"], "studio_lora_1", 0, "MOSS scheduling must use the selected LoRAs.");
Link(moss["4"]!["inputs"]!["clip"], "studio_lora_1", 1, "MOSS must patch the HF loader's CLIP output.");
Link(moss["17"]!["inputs"]!["vae"], "1", 2, "LoRA routing must leave the HF VAE output untouched.");
Check(moss["16"]!["inputs"]!["steps"]!.GetValue<int>() == 50, "MOSS must retain its own sampler settings.");
Reject(() => Graph(request with { Model = "moss-image-base", Source = "source.png" }), "MOSS must not silently ignore an edit source.");
var krea = Graph(request with { Model = "krea2_raw_fp8_scaled.safetensors", Loras = loras });
Check(krea["1"]!["inputs"]!["unet_name"]!.GetValue<string>() == "krea2_raw_fp8_scaled.safetensors", "The chosen Krea model must reach its loader.");
Link(krea["6"]!["inputs"]!["model"], "studio_lora_1", 0, "Krea must use its LoRAs.");
var videoRequest = new VideoRequest("Leaves move in the breeze", "", 42, 768, 512, 3, "ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors", Loras: loras);
var ltxText = GenerationPipelines.BuildVideo(videoRequest);
Check(ltxText.All(x => x.Value!["class_type"]!.GetValue<string>() != "LoadImage"), "Text-to-video must not load a hidden example image.");
Link(ltxText["398:377"]!["inputs"]!["video_latent"], "398:356", 0, "LTX text-to-video must start from an empty latent.");
Link(ltxText["398:388"]!["inputs"]!["model"], "studio_lora_1", 0, "LTX's first sampling stage must use LoRAs.");
Link(ltxText["398:391"]!["inputs"]!["model"], "studio_lora_1", 0, "LTX's second sampling stage must use LoRAs too.");
var ltxImage = GenerationPipelines.BuildVideo(videoRequest with { Source = "frame.png" }, "desktop/upload.png");
Check(ltxImage["395"]!["inputs"]!["image"]!.GetValue<string>() == "desktop/upload.png", "Image-to-video must use the chosen first frame.");
Reject(() => GenerationPipelines.BuildVideo(videoRequest with { Source = "frame.png" }), "A missing uploaded first frame must fail.");
Reject(() => GenerationPipelines.BuildVideo(videoRequest with { Seconds = 0 }), "Invalid video duration must fail.");
var minimax = GenerationPipelines.BuildVideo(videoRequest with { Model = "minimax_h3_fl2va_pruned_int8_convrot.safetensors", Source = "frame.png" }, "desktop/upload.png");
Link(minimax["conditioning"]!["inputs"]!["first_frame"], "image", 0, "MiniMax must connect the actual first_frame input.");
Check(minimax["conditioning"]!["inputs"]!["length"]!.GetValue<int>() % 17 == 5, "MiniMax frame counts must fit its native grid.");

string statePath = System.IO.Path.Combine(App.Root, "temp", "workflow-settings-test-" + Guid.NewGuid() + ".json");
var settings = new WorkspaceSettings();
settings.Choice("image:create").Model = "moss-image-base";
settings.Choice("image:create").LorasByModel["moss-image-base"] = loras;
settings.Choice("image:edit").Model = GenerationPipelines.QwenModel;
settings.Choice("image:edit").LorasByModel[GenerationPipelines.QwenModel] = [];
settings.Choice("video:text").Model = videoRequest.Model;
settings.Choice("video:image").Model = "minimax_h3_fl2va_pruned_int8_convrot.safetensors";
settings.Save(statePath);
var restored = WorkspaceSettings.Load(statePath);
Check(restored.Choice("image:create").Model == "moss-image-base", "Create model must survive restart.");
Check(restored.Choice("image:edit").Model == GenerationPipelines.QwenModel, "Edit must retain a separate model.");
Check(restored.Choice("video:text").Model != restored.Choice("video:image").Model, "Text and image video workflows must retain separate models.");
Check(restored.Choice("image:create").LorasByModel["moss-image-base"].SequenceEqual(loras), "All LoRA strengths and disabled states must survive restart.");
Check(restored.Choice("image:edit").LorasByModel[GenerationPipelines.QwenModel].Length == 0, "An empty LoRA choice must stay empty.");
System.IO.File.Delete(statePath);
if (args.Length > 0)
{
    System.IO.Directory.CreateDirectory(args[0]);
    foreach (var (name, graph) in new[] { ("moss", moss), ("krea", krea), ("ltx-text", (JsonNode)ltxText), ("ltx-image", ltxImage), ("minimax", minimax), ("qwen", withLoras) })
        System.IO.File.WriteAllText(System.IO.Path.Combine(args[0], name + ".json"), graph.ToJsonString(new JsonSerializerOptions { WriteIndented = true }));
}
Check(JsonNode.DeepEquals(JsonNode.Parse("{\"n\":1}"), JsonNode.Parse("{\"n\":1.0}")), "Create history matching tolerates equivalent engine numeric normalization.");
var flexRequest = new VideoRequest("Synthetic graph check", "", 1, 768, 448, 5, "minimax_h3_fl2va_pruned_int8_convrot.safetensors", Loras: [new("pika_h3_flex_fl2va_comfy_bf16.safetensors", 1)]);
var flexGraph = GenerationPipelines.BuildVideo(flexRequest);
Check(flexGraph["sampler"]!["inputs"]!["sampler_name"]!.GetValue<string>() == "lcm", "Selecting the installed Pika adapter uses its calibrated sampler in Create as well as Films.");
Check(flexGraph["sigmas"]!["class_type"]!.GetValue<string>() == "ManualSigmas", "Pika uses its full manual sigma schedule rather than a generic step count.");
var guided = GenerationPipelines.BuildVideo(flexRequest with { GuideVideo = "tail.mkv" }, uploadedGuide: "staged-tail.mkv");
Check(guided["guide_video"]!["inputs"]!["file"]!.GetValue<string>() == "staged-tail.mkv" && guided["tail_guide"]!["class_type"]!.GetValue<string>() == "MiniMaxH3AddGuide", "Exact continuation guides enter the same shared C# graph authority.");
var shortRepair = GenerationPipelines.BuildVideo(flexRequest with { LastFrame = "end.png", LastFrameAt = 23 }, uploadedLastFrame: "staged-end.png");
Check(shortRepair["last_guide"]!["inputs"]!["frame_idx"]!.GetValue<int>() == 23 && shortRepair["conditioning"]!["inputs"]!["last_frame"] == null,
    "Short repair endpoint is anchored inside the retained 24-frame interval, not at the end of the longer generation.");
var layeredRepair = GenerationPipelines.BuildVideo(flexRequest with { LastFrame = "end.png", LastFrameAt = 23, AudioGuide = "voice.wav", GuideVideo = "tail.mkv" },
    uploadedLastFrame: "staged-end.png", uploadedAudio: "staged-voice.wav", uploadedGuide: "staged-tail.mkv");
Check(layeredRepair["guide"]!["inputs"]!["positive"]![0]!.GetValue<string>() == "last_guide" && layeredRepair["tail_guide"]!["inputs"]!["positive"]![0]!.GetValue<string>() == "guide",
    "Audio and continuation conditioning preserve the explicit retained-range endpoint guide.");
try { GenerationPipelines.BuildVideo(flexRequest with { LastFrameAt = 500 }, uploadedLastFrame: "end.png"); Check(false, "Out-of-range endpoint must fail."); }
catch (ArgumentException) { Check(true, "Out-of-range retained endpoint fails before submission."); }
Console.WriteLine($"Passed {checks} graph, workflow persistence, and prompt-builder checks.");
