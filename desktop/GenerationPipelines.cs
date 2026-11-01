using System.IO;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace ImageStudio;

public record VideoRequest(string Prompt, string Negative, long Seed, int Width, int Height, int Seconds,
    string Model, string? Source = null, LoraSelection[]? Loras = null);

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

    public static JsonObject BuildVideo(VideoRequest request, string? uploadedImage = null)
    {
        if (string.IsNullOrWhiteSpace(request.Prompt)) throw new ArgumentException("Describe the video before generating.");
        if (request.Seconds is < 1 or > 10 || request.Width < 256 || request.Height < 256 || request.Width > 1920 || request.Height > 1920 || request.Width % 64 != 0 || request.Height % 64 != 0)
            throw new ArgumentException("Use a 1–10 second video with dimensions from 256 to 1920 in multiples of 64.");
        if (request.Source != null && string.IsNullOrEmpty(uploadedImage)) throw new ArgumentException("Upload the first frame before generating.");
        JsonObject graph;
        if (Path.GetFileName(request.Model).StartsWith("ltx-2.5-", StringComparison.OrdinalIgnoreCase))
        {
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
