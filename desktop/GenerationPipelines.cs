using System.IO;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace ImageStudio;

public record VideoRequest(string Prompt, string Negative, long Seed, int Width, int Height, int Seconds,
    string Model, string? Source = null, LoraSelection[]? Loras = null,
    string Profile = "standard", string? LastFrame = null, string? AudioGuide = null,
    bool PersistAV = false, string? RuntimeIdentity = null, string? LatentFile = null,
    string? LatentSha256 = null, bool InterpolateFinish = false, string? LatentRuntimeIdentity = null,
    string? GuideVideo = null, bool GuideAudio = false, int? LastFrameAt = null);

public static class GenerationPipelines
{
    public const string QwenModel = "qwen_image_2.1_int8_convrot.safetensors";
    public static JsonArray Link(string id, int slot = 0) => new(id, slot);
    private static JsonNode Node(string type, object inputs) => JsonSerializer.SerializeToNode(new { class_type = type, inputs })!;
    private static JsonObject Template(string name)
    {
        using var stream = typeof(GenerationPipelines).Assembly.GetManifestResourceStream($"ImageStudio.Workflows.{name}.json")
            ?? throw new IOException("The application is missing its " + name + " workflow. Rebuild Image Studio.");
        return JsonNode.Parse(stream)!.AsObject();
    }

    public static JsonObject BuildImage(ImageRequest request)
    {
        if (request.Source != null || request.References?.Length > 0)
            throw new ArgumentException("Choose Qwen Image 2.1 to edit an image or use image references.");
        JsonObject graph;
        if (request.Model == "moss-image-base")
        {
            graph = Template("moss");
            graph["1"]!["inputs"]!["model_path"] = Path.Combine(App.Root, "models", "moss-image-base");
            graph["4"]!["inputs"]!["text"] = request.Prompt;
            graph["5"]!["inputs"]!["text"] = request.Negative;
            graph["6"]!["inputs"]!["width"] = request.Width;
            graph["6"]!["inputs"]!["height"] = request.Height;
            graph["16"]!["inputs"]!["seed"] = request.Seed;
            graph["16"]!["inputs"]!["steps"] = request.Steps;
            graph["18"]!["inputs"]!["filename_prefix"] = OutputPrefix("images/MOSS");
            ApplyLoras(graph, "1", "1", 1, request.Loras);
        }
        else if (Path.GetFileName(request.Model).StartsWith("krea2_", StringComparison.OrdinalIgnoreCase))
        {
            bool turbo = request.Model.Contains("turbo", StringComparison.OrdinalIgnoreCase);
            graph = new()
            {
                ["1"] = Node("UNETLoader", new { unet_name = request.Model, weight_dtype = "default" }),
                ["2"] = Node("CLIPLoader", new { clip_name = "qwen3vl_4b_fp8_scaled.safetensors", type = "krea2", device = "default" }),
                ["3"] = Node("VAELoader", new { vae_name = "qwen_image_vae.safetensors" }),
                ["4"] = Node("CLIPTextEncode", new { clip = Link("2"), text = request.Prompt }),
                ["negative"] = turbo ? Node("ConditioningZeroOut", new { conditioning = Link("4") }) : Node("CLIPTextEncode", new { clip = Link("2"), text = request.Negative }),
                ["5"] = Node("EmptyLatentImage", new { width = request.Width, height = request.Height, batch_size = 1 }),
                ["6"] = Node("KSampler", new { model = Link("1"), positive = Link("4"), negative = Link("negative"), latent_image = Link("5"), seed = request.Seed, steps = request.Steps, cfg = turbo ? 1.0 : 4.0, sampler_name = "euler", scheduler = "simple", denoise = 1.0 }),
                ["7"] = Node("VAEDecode", new { samples = Link("6"), vae = Link("3") }),
                ["8"] = Node("SaveImage", new { images = Link("7"), filename_prefix = OutputPrefix("images/Krea") })
            };
            ApplyLoras(graph, "1", "2", 0, request.Loras);
        }
        else throw new ArgumentException("This image model does not have a configured workflow.");
        return graph;
    }

    public static JsonObject BuildVideo(VideoRequest request, string? uploadedImage = null,
        string? uploadedLastFrame = null, string? uploadedAudio = null, string? uploadedGuide = null)
    {
        if (request.Profile == "standard" && request.Loras?.Any(l => l.Enabled && l.Strength != 0 && l.Name == "pika_h3_flex_fl2va_comfy_bf16.safetensors") == true)
            request = request with { Profile = "pika-flex" };
        if (string.IsNullOrWhiteSpace(request.Prompt)) throw new ArgumentException("Describe the video before generating.");
        if (request.Seconds is < 1 or > 10 || request.Width < 256 || request.Height < 256 || request.Width > 1920 || request.Height > 1920 || request.Width % 64 != 0 || request.Height % 64 != 0)
            throw new ArgumentException("Use a 1–10 second video with dimensions from 256 to 1920 in multiples of 64.");
        if (request.Source != null && string.IsNullOrEmpty(uploadedImage)) throw new ArgumentException("Upload the first frame before generating.");
        if (request.LastFrame != null && uploadedLastFrame == null) throw new ArgumentException("Stage the last frame before generating.");
        if (request.AudioGuide != null && uploadedAudio == null) throw new ArgumentException("Stage the audio guide before generating.");
        if (request.GuideVideo != null && uploadedGuide == null) throw new ArgumentException("Stage the exact guide interval before generating.");
        if (request.Profile is not ("standard" or "pika-flex" or "refine" or "decode-preview")) throw new ArgumentException("Unsupported sampling profile.");
        JsonObject graph;
        if (Path.GetFileName(request.Model).StartsWith("ltx-2.5-", StringComparison.OrdinalIgnoreCase))
        {
            if (request.Profile != "standard" || request.PersistAV || request.LastFrame != null || request.AudioGuide != null || request.LatentFile != null || request.GuideVideo != null || request.LastFrameAt != null)
                throw new ArgumentException("These film profiles currently require the H3 graph.");
            graph = Template("ltx");
            graph["398:384"]!["inputs"]!["unet_name"] = request.Model;
            graph["398:376"]!["inputs"]!["value"] = request.Prompt;
            graph["398:373"]!["inputs"]!["text"] = request.Negative;
            graph["398:372"]!["inputs"]!["value"] = request.Width;
            graph["398:360"]!["inputs"]!["value"] = request.Height;
            graph["398:362"]!["inputs"]!["value"] = request.Seconds;
            foreach (string id in new[] { "398:338", "398:339" }) graph[id]!["inputs"]!["noise_seed"] = request.Seed;
            if (uploadedImage != null) graph["395"]!["inputs"]!["image"] = uploadedImage;
            else
            {
                graph["398:377"]!["inputs"]!["video_latent"] = Link("398:356");
                graph["398:340"]!["inputs"]!["video_latent"] = Link("398:348");
                foreach (string id in new[] { "395", "398:357", "398:349", "398:350", "398:351", "398:363" }) graph.Remove(id);
            }
            graph["75"]!["inputs"]!["filename_prefix"] = OutputPrefix("video/LTX");
            ApplyLoras(graph, "398:384", "398:387", 0, request.Loras);
        }
        else if (Path.GetFileName(request.Model).StartsWith("minimax_h3_", StringComparison.OrdinalIgnoreCase))
        {
            int frames = request.Seconds * 24 + 1;
            frames += (5 - frames % 17 + 17) % 17;
            graph = new()
            {
                ["model"] = Node("UNETLoader", new { unet_name = request.Model, weight_dtype = "default" }),
                ["clip"] = Node("CLIPLoader", new { clip_name = "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors", type = "minimax", device = "default" }),
                ["vae"] = Node("VAELoader", new { vae_name = "minimax_h3_video_vae_fp16.safetensors" }),
                ["audio_vae"] = Node("VAELoader", new { vae_name = "minimax_h3_audio_vae_fp32.safetensors" }),
                ["conditioning"] = Node("MiniMaxH3ImageToVideo", new { clip = Link("clip"), vae = Link("vae"), prompt = request.Prompt, width = request.Width, height = request.Height, length = frames }),
                ["noise"] = Node("RandomNoise", new { noise_seed = request.Seed }),
                ["guider"] = Node("BasicGuider", new { model = Link("model"), conditioning = Link("conditioning") }),
                ["sampler"] = Node("KSamplerSelect", new { sampler_name = "res_multistep" }),
                ["sigmas"] = Node("BasicScheduler", new { model = Link("model"), scheduler = "simple", steps = 20, denoise = 1.0 }),
                ["sample"] = Node("SamplerCustomAdvanced", new { noise = Link("noise"), guider = Link("guider"), sampler = Link("sampler"), sigmas = Link("sigmas"), latent_image = Link("conditioning", 1) }),
                ["decode"] = Node("VAEDecodeTiled", new { samples = Link("sample"), vae = Link("vae"), tile_size = 512, overlap = 64, temporal_size = 64, temporal_overlap = 16 }),
                ["audio"] = Node("VAEDecodeAudio", new { samples = Link("sample"), vae = Link("audio_vae") }),
                ["video"] = Node("CreateVideo", new { images = Link("decode"), audio = Link("audio"), fps = 24 }),
                ["save"] = Node("SaveVideo", new { video = Link("video"), filename_prefix = OutputPrefix("video/MiniMax"), format = "mp4", codec = "auto" })
            };
            if (uploadedImage != null)
            {
                graph["image"] = Node("LoadImage", new { image = uploadedImage });
                graph["conditioning"]!["inputs"]!["first_frame"] = Link("image");
            }
            ApplyLoras(graph, "model", "clip", 0, request.Loras);
            string positive = "conditioning";
            if (request.LastFrameAt is int endFrame && (uploadedLastFrame == null || endFrame < 0 || endFrame >= frames))
                throw new ArgumentException("An explicit endpoint index needs a last-frame image and must be inside the generated frame range.");
            if (uploadedLastFrame != null)
            {
                graph["last_image"] = Node("LoadImage", new { image = uploadedLastFrame });
                if (request.LastFrameAt is int at)
                {
                    graph["last_guide"] = Node("MiniMaxH3AddGuide", new { positive = Link(positive), latent = Link("conditioning", 1), vae = Link("vae"), image = Link("last_image"), frame_idx = at });
                    positive = "last_guide";
                    graph["guider"]!["inputs"]!["conditioning"] = Link(positive);
                }
                else graph["conditioning"]!["inputs"]!["last_frame"] = Link("last_image");
            }
            if (uploadedAudio != null)
            {
                graph["guide_audio"] = Node("LoadAudio", new { audio = uploadedAudio });
                graph["guide"] = Node("MiniMaxH3AddGuide", new { positive = Link(positive), latent = Link("conditioning", 1), audio_vae = Link("audio_vae"), audio = Link("guide_audio"), frame_idx = 0 });
                positive = "guide";
                graph["guider"]!["inputs"]!["conditioning"] = Link("guide");
            }
            if (uploadedGuide != null)
            {
                graph["guide_video"] = Node("LoadVideo", new { file = uploadedGuide });
                graph["guide_parts"] = Node("GetVideoComponents", new { video = Link("guide_video") });
                var guideInputs = new JsonObject { ["positive"] = Link(positive), ["latent"] = Link("conditioning", 1), ["vae"] = Link("vae"), ["image"] = Link("guide_parts"), ["frame_idx"] = 0 };
                if (request.GuideAudio) { guideInputs["audio_vae"] = Link("audio_vae"); guideInputs["audio"] = Link("guide_parts", 1); }
                graph["tail_guide"] = Node("MiniMaxH3AddGuide", guideInputs);
                graph["guider"]!["inputs"]!["conditioning"] = Link("tail_guide");
            }
            if (request.Profile is "pika-flex" or "refine")
            {
                const string flex = "pika_h3_flex_fl2va_comfy_bf16.safetensors";
                var adapters = request.Loras?.Where(l => l.Enabled && l.Strength != 0).ToArray() ?? [];
                if (adapters.Length != 1 || adapters[0].Name != flex || adapters[0].Strength != 1)
                    throw new ArgumentException("This profile requires only the verified Pika Flex FL2VA adapter at strength 1.0.");
                graph["sampler"] = Node("KSamplerSelect", new { sampler_name = "lcm" });
                graph["sigmas"] = Node("ManualSigmas", new { sigmas = request.Profile == "refine" ? "0.571429, 0.333333, 0.0" : "1.0, 0.972973, 0.923077, 0.8, 0.571429, 0.333333, 0.0" });
            }
            if (request.LatentFile != null)
            {
                if (request.Profile is not ("refine" or "decode-preview") || string.IsNullOrWhiteSpace(request.RuntimeIdentity) || string.IsNullOrWhiteSpace(request.LatentSha256))
                    throw new ArgumentException("Finishing requires a selected AV companion, hash and exact runtime identity.");
                graph["saved_av"] = Node("LoadStudioAV", new { file = request.LatentFile, sha256 = request.LatentSha256, runtime_identity = request.LatentRuntimeIdentity ?? request.RuntimeIdentity });
                graph["sample"]!["inputs"]!["latent_image"] = Link("saved_av");
                if (request.InterpolateFinish)
                {
                    graph["resize_av"] = Node("ResizeStudioAV", new { samples = Link("saved_av"), width = request.Width, height = request.Height });
                    graph["sample"]!["inputs"]!["latent_image"] = Link("resize_av");
                }
            }
            else if (request.Profile == "refine") throw new ArgumentException("Select a persisted preview before finishing.");
            if (request.Profile == "decode-preview")
            {
                if (request.LatentFile == null || request.InterpolateFinish || request.PersistAV)
                    throw new ArgumentException("A decode-only round trip requires an unchanged persisted AV input.");
                foreach (var id in graph.Where(n => n.Key is not ("saved_av" or "vae" or "audio_vae" or "decode" or "audio" or "video" or "save")).Select(n => n.Key).ToArray()) graph.Remove(id);
                graph["decode"]!["inputs"]!["samples"] = Link("saved_av");
                graph["audio"]!["inputs"]!["samples"] = Link("saved_av");
            }
            if (request.PersistAV)
            {
                if (string.IsNullOrWhiteSpace(request.RuntimeIdentity)) throw new ArgumentException("AV persistence requires explicit runtime identity.");
                graph["save_av"] = Node("SaveStudioAV", new { samples = Link("sample"), filename_prefix = OutputPrefix("video/av"), runtime_identity = request.RuntimeIdentity });
            }
        }
        else throw new ArgumentException("This video model does not have a configured workflow.");
        return graph;
    }

    public static void ApplyLoras(JsonObject graph, string modelNode, string clipNode, int clipSlot, LoraSelection[]? selections)
    {
        var enabled = selections?.Where(x => x.Enabled && x.Strength != 0).ToArray() ?? [];
        if (enabled.Length == 0) return;
        var originalNodes = graph.ToArray();
        var model = Link(modelNode);
        var clip = Link(clipNode, clipSlot);
        for (int i = 0; i < enabled.Length; i++)
        {
            var lora = enabled[i];
            if (string.IsNullOrWhiteSpace(lora.Name) || !double.IsFinite(lora.Strength) || Math.Abs(lora.Strength) > 2)
                throw new ArgumentException("Choose a LoRA and a strength between -2 and 2.");
            string id = "studio_lora_" + i;
            graph[id] = Node("LoraLoader", new { model, clip, lora_name = lora.Name, strength_model = lora.Strength, strength_clip = lora.Strength });
            model = Link(id); clip = Link(id, 1);
        }
        foreach (var (_, node) in originalNodes)
        {
            foreach (var (key, value) in node!["inputs"]!.AsObject().ToArray())
            {
                if (value is not JsonArray link || link.Count != 2 || link[0] is not JsonValue id || !id.TryGetValue<string>(out var target)) continue;
                int slot = link[1]!.GetValue<int>();
                if (target == modelNode && slot == 0) node["inputs"]![key] = model.DeepClone();
                else if (target == clipNode && slot == clipSlot) node["inputs"]![key] = clip.DeepClone();
            }
        }
    }

    private static string OutputPrefix(string name) => "desktop/" + DateTime.Now.ToString("yyyy-MM-dd") + "/" + name;
}
