using System.IO;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace ImageStudio;

public record LoraSelection(string Name, double Strength = 0.8, bool Enabled = true);
public sealed record ModelChoice(string Id, string Name, string Family, bool Video, string Description, string Status)
{
    public bool Ready => Status == "Installed";
    public override string ToString() => Name;
}

public sealed class WorkflowChoice
{
    public string? Model { get; set; }
    public Dictionary<string, LoraSelection[]> LorasByModel { get; set; } = [];
}

public sealed class WorkspaceSettings
{
    public Dictionary<string, WorkflowChoice> Workflows { get; set; } = [];
    public string VideoPrompt { get; set; } = "";
    public string VideoNegative { get; set; } = "";
    public string VideoSeed { get; set; } = "";
    public string? VideoSource { get; set; }
    public string? VideoPreview { get; set; }
    public int VideoShape { get; set; }
    public int VideoDuration { get; set; }
    public bool AnimateImage { get; set; }

    public WorkflowChoice Choice(string workflow)
    {
        if (!Workflows.TryGetValue(workflow, out var choice)) Workflows[workflow] = choice = new();
        return choice;
    }

    public static WorkspaceSettings Load(string path) => File.Exists(path)
        ? JsonSerializer.Deserialize<WorkspaceSettings>(File.ReadAllText(path)) ?? new() : new();

    public void Save(string path)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        File.WriteAllText(path + ".tmp", JsonSerializer.Serialize(this, new JsonSerializerOptions { WriteIndented = true }));
        File.Move(path + ".tmp", path, true);
    }
}

public static class ModelCatalog
{
    public static string[] Options(JsonNode info, string node, string input)
    {
        var definition = info[node]?["input"]?["required"]?[input];
        var values = definition?[0] as JsonArray ?? definition?[1]?["options"] as JsonArray;
        return values?.Select(x => x!.GetValue<string>()).ToArray() ?? [];
    }

    public static IReadOnlyList<ModelChoice> Read(JsonNode info, bool mossInstalled)
    {
        var encoders = Options(info, "CLIPLoader", "clip_name");
        var vaes = Options(info, "VAELoader", "vae_name");
        var upscalers = Options(info, "LatentUpscaleModelLoader", "model_name");
        var result = new List<ModelChoice>();
        foreach (var file in Options(info, "UNETLoader", "unet_name"))
        {
            var name = Path.GetFileName(file).ToLowerInvariant();
            var (family, title, video, description, required) = name switch
            {
                var n when n.StartsWith("qwen_image_2.1") => ("qwen", "Qwen Image 2.1", false, "Create, edit, and combine image references.", new[] { "qwen3vl_8b_int8_convrot.safetensors", "qwen_image_2.1_vae_bf16.safetensors" }),
                var n when n.StartsWith("krea2_") => ("krea", n.Contains("turbo") ? "Krea 2 Turbo" : "Krea 2 Raw", false, "Illustration, photography, and custom LoRA styles.", new[] { "qwen3vl_4b_fp8_scaled.safetensors", "qwen_image_vae.safetensors" }),
                var n when n.StartsWith("ltx-2.5-") => ("ltx", "LTX 2.5", true, "Text or image to video, with generated audio.", new[] { "gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors", "ltx-2.5-video-vae-bf16.safetensors", "ltx-2.5-audio-vae-bf16.safetensors", "ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors" }),
                var n when n.StartsWith("minimax_h3_") => ("minimax", "MiniMax H3", true, "Cinematic video and audio from text or a first frame.", new[] { "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors", "minimax_h3_video_vae_fp16.safetensors", "minimax_h3_audio_vae_fp32.safetensors" }),
                _ => ("unknown", Path.GetFileNameWithoutExtension(file), false, "This model needs a compatible generation workflow.", Array.Empty<string>())
            };
            var missing = required.Except(encoders.Concat(vaes).Concat(upscalers)).ToArray();
            var status = family == "unknown" ? "Workflow unavailable" : missing.Length > 0 ? "Missing: " + string.Join(", ", missing) : "Installed";
            result.Add(new(file, title, family, video, description, status));
        }
        result.Add(new("moss-image-base", "MOSS Image Base", "moss", false, "Detailed text, illustration, and structured layouts.",
            !mossInstalled ? "Model download incomplete" : info["MOSSImageHFLoader"] == null ? "Restart engine to load MOSS" : "Installed"));
        return result.OrderBy(x => x.Video).ThenBy(x => x.Name).ToArray();
    }
}
