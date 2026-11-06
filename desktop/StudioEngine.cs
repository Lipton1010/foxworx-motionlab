using System.Diagnostics;
using System.IO;
using System.Net.Http;
using System.Net.Http.Json;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace ImageStudio;

public record ImageRequest(string Prompt, string Negative, long Seed, int Width, int Height, int Steps,
    bool Transparent, string? Source, int ReferenceSize, ReferenceImage[]? References = null,
    string Model = GenerationPipelines.QwenModel, LoraSelection[]? Loras = null);

public sealed class EngineJobFailedException(string message) : IOException(message);

public sealed class StudioEngine
{
    private readonly HttpClient http = new() { BaseAddress = new Uri("http://127.0.0.1:8193/"), Timeout = TimeSpan.FromSeconds(30) };
    private readonly ProductionClient production = new();

    public async Task EnsureStarted(Action<string> status)
    {
        status("Starting the local generation engine… The first start can take a little longer.");
        // A background engine inherits redirected launcher pipe handles on
        // Windows. Waiting for EOF blocks catalog loading until the engine exits.
        // The launcher already sends engine diagnostics to logs/server-*.
        var start = new ProcessStartInfo("powershell.exe") { CreateNoWindow = true, UseShellExecute = false };
        foreach (var arg in new[] { "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", Path.Combine(App.Root, "Start Image Studio.ps1"), "-NoBrowser" }) start.ArgumentList.Add(arg);
        using var process = Process.Start(start) ?? throw new IOException("Could not start the image engine.");
        await process.WaitForExitAsync();
        if (process.ExitCode != 0) throw new IOException("The image engine could not start. Check the newest server log in logs, then choose Refresh library in Models & LoRAs.");
    }

    public static object BuildGraph(ImageRequest request, IReadOnlyList<string>? sourceNames = null)
    {
        if (!Path.GetFileName(request.Model).StartsWith("qwen_image_2.1", StringComparison.OrdinalIgnoreCase))
            return GenerationPipelines.BuildImage(request);
        int referenceCount = sourceNames?.Count ?? 0;
        if (referenceCount > 10 || request.References?.Length > 10)
            throw new ArgumentException("Qwen supports up to 10 reference images.");
        if (request.Source != null && referenceCount == 0)
            throw new ArgumentException("Choose the main image before creating an edit.");
        if (request.References != null && request.References.Length != referenceCount)
            throw new ArgumentException("Every reference image must be uploaded before creating the image.");
        object Link(string id, int slot = 0) => new object[] { id, slot };
        object Node(string type, object inputs) => new { class_type = type, inputs };
        var prompt = request.Prompt;
        bool hasReferences = sourceNames?.Count > 0;
        bool edit = request.Source != null;
        if (edit && !prompt.Contains("<image1>")) prompt = "Edit <image1>: " + prompt;
        if (hasReferences && request.References != null)
            prompt += "\n\nReference guidance:\n" + string.Join("\n", request.References.Select((reference, index) => $"<image{index + 1}>: {reference.Role}. {reference.Notes}"));
        if (request.Transparent) prompt = "This is an RGBA image with transparency. " + prompt + " The image has alpha channel and the background is transparent.";
        var encode = new Dictionary<string, object> { ["clip"] = Link("2"), ["prompt"] = prompt, ["negative_prompt"] = request.Negative, ["resolution"] = hasReferences ? request.ReferenceSize : 0 };
        var graph = new Dictionary<string, object>
        {
            ["1"] = Node("UNETLoader", new { unet_name = request.Model, weight_dtype = "default" }),
            ["2"] = Node("CLIPLoader", new { clip_name = "qwen3vl_8b_int8_convrot.safetensors", type = "qwen_image", device = "default" }),
            ["3"] = Node("VAELoader", new { vae_name = "qwen_image_2.1_vae_bf16.safetensors" }),
            ["4"] = Node("TextEncodeQwenImage21", encode),
            ["5"] = Node("EmptyLatentImage", new { width = request.Width, height = request.Height, batch_size = 1 }),
            ["6"] = Node("KSampler", new { model = Link("1"), positive = Link("4"), negative = Link("4", 1), latent_image = edit ? Link("4", 2) : Link("5"), seed = request.Seed, steps = request.Steps, cfg = 1.0, sampler_name = "euler", scheduler = "simple", denoise = 1.0 }),
            ["7"] = Node("VAEDecode", new { samples = Link("6"), vae = Link("3") }),
            ["8"] = Node("SaveImage", new { images = Link("7"), filename_prefix = "desktop/" + DateTime.Now.ToString("yyyy-MM-dd") + "/Image" })
        };
        if (hasReferences)
        {
            for (int index = 0; index < sourceNames!.Count; index++)
            {
                string node = (9 + index).ToString();
                graph[node] = Node("LoadImage", new { image = sourceNames[index] });
                encode[$"images.image_{index + 1}"] = Link(node);
            }
            encode["vae"] = Link("3");
            if (edit) graph.Remove("5");
        }
        var result = JsonSerializer.SerializeToNode(graph)!.AsObject();
        GenerationPipelines.ApplyLoras(result, "1", "2", 0, request.Loras);
        return result;
    }

    public async Task<string> Submit(ImageRequest request)
    {
        var sourceNames = new List<string>();
        var references = request.References ?? (request.Source == null ? [] : new[] { new ReferenceImage { Path = request.Source } });
        foreach (var reference in references)
            sourceNames.Add(await UploadImage(reference.Path));
        return await SubmitGraph(BuildGraph(request, sourceNames), request);
    }

    private async Task<string> UploadImage(string path)
    {
        using var form = new MultipartFormDataContent();
        await using var stream = File.OpenRead(path);
        form.Add(new StreamContent(stream), "image", "studio-" + Guid.NewGuid().ToString("N") + Path.GetExtension(path));
        form.Add(new StringContent("desktop"), "subfolder");
        using var response = await http.PostAsync("upload/image", form);
        var uploaded = await ReadResponse(response);
        return uploaded["subfolder"] + "/" + uploaded["name"];
    }

    public async Task<string> SubmitVideo(VideoRequest request) =>
        await SubmitGraph(GenerationPipelines.BuildVideo(request, request.Source == null ? null : await UploadImage(request.Source),
            request.LastFrame == null ? null : await UploadImage(request.LastFrame),
            request.AudioGuide == null ? null : await UploadAudio(request.AudioGuide)), video: request);

    private async Task<string> UploadAudio(string path)
    {
        using var form = new MultipartFormDataContent();
        await using var stream = File.OpenRead(path);
        form.Add(new StreamContent(stream), "image", "studio-" + Guid.NewGuid().ToString("N") + Path.GetExtension(path));
        form.Add(new StringContent("desktop"), "subfolder");
        using var response = await http.PostAsync("upload/image", form);
        var uploaded = await ReadResponse(response);
        return uploaded["subfolder"] + "/" + uploaded["name"];
    }

    public async Task<JsonNode> ObjectInfo() => JsonNode.Parse(await http.GetStringAsync("object_info"))!;

    private async Task<string> SubmitGraph(object graph, ImageRequest? request = null, VideoRequest? video = null)
    {
        string id = Guid.NewGuid().ToString();
        string owner = "create_" + id.Replace("-", "");
        var payload = new { prompt = graph, prompt_id = id, client_id = owner };
        var admission = await production.Call("gpu-claim", new { owner, intent = id });
        if (admission["phase"]?.GetValue<string>() != "admitted") throw new IOException("GPU admission needs reconciliation before submission.");
        // Both the admission and legacy recovery record precede any possibly ambiguous POST.
        var persisted = await production.Call("gpu-submitting", new { owner, prompt_id = id, payload });
        if (persisted["phase"]?.GetValue<string>() != "unknown_submission") throw new IOException("The durable submission intent needs reconciliation; no POST was sent.");
        string job = Path.Combine(App.Root, "user", "desktop-job.json");
        string temporary = job + ".tmp";
        await File.WriteAllTextAsync(temporary, JsonSerializer.Serialize(new { Id = id, Request = request, Video = video }));
        File.Move(temporary, job, true);
        using var response = await http.PostAsJsonAsync("prompt", payload);
        var data = await ReadResponse(response);
        if (data["prompt_id"]?.GetValue<string>() != id) throw new IOException("The engine did not acknowledge the saved job UUID. Reconcile the durable job before new work.");
        return id;
    }

    private static async Task<JsonNode> ReadResponse(HttpResponseMessage response)
    {
        var text = await response.Content.ReadAsStringAsync();
        if (!response.IsSuccessStatusCode) throw new IOException("Image engine: " + text);
        return JsonNode.Parse(text) ?? throw new IOException("The engine returned an empty response.");
    }

    public async Task<JsonNode> Queue() => JsonNode.Parse(await http.GetStringAsync("queue"))!;

    public async Task ReleaseIdleModels(CancellationToken cancellationToken = default)
    {
        var queue = await Queue();
        var slot = await production.Call("gpu-status", cancellationToken: cancellationToken);
        if (slot["owner"]?.GetValue<string>()?.StartsWith("rewrite_", StringComparison.Ordinal) != true)
            throw new IOException("Prompt refinement must reserve GPU ownership before freeing models.");
        if (queue["queue_running"]!.AsArray().Count > 0 || queue["queue_pending"]!.AsArray().Count > 0)
            throw new IOException("Wait for the image engine's current jobs to finish before starting this task.");
        cancellationToken.ThrowIfCancellationRequested();
        using var response = await http.PostAsJsonAsync("free", new { unload_models = true, free_memory = true }, cancellationToken);
        response.EnsureSuccessStatusCode();
        for (int attempt = 0; attempt < 20; attempt++)
        {
            var stats = JsonNode.Parse(await http.GetStringAsync("system_stats", cancellationToken))!;
            if (stats["devices"]?[0]?["vram_free"]?.GetValue<long>() >= 10L * 1024 * 1024 * 1024) return;
            await Task.Delay(500, cancellationToken);
        }
        throw new IOException("Free at least 10 GB of GPU memory, then try again.");
    }

    public async Task<string?> Result(string id, bool video = false)
    {
        var data = JsonNode.Parse(await http.GetStringAsync("history/" + id))?[id];
        if (data == null) return null;
        var ownership = await production.Call("gpu-status");
        if (ownership["owner"]?.GetValue<string>() == "create_" + id.Replace("-", ""))
        {
            if (ownership["prompt_id"]?.GetValue<string>() != id || data["prompt"]?[1]?.GetValue<string>() != id ||
                !JsonNode.DeepEquals(ownership["payload"]?["prompt"], data["prompt"]?[2]))
                throw new IOException("Engine history differs from the saved Create UUID/graph. Ownership remains reserved for reconciliation.");
        }
        var status = data["status"];
        if (status?["status_str"]?.GetValue<string>() == "error")
        {
            await ReleaseCreate(id);
            var messages = status["messages"]?.AsArray();
            var error = messages?.LastOrDefault(m => m?[0]?.GetValue<string>() == "execution_error");
            if (error == null) throw new OperationCanceledException("Generation was cancelled.");
            throw new EngineJobFailedException(error[1]?["exception_message"]?.GetValue<string>() ?? "Generation failed. Inspect the saved request before retrying.");
        }
        var image = data["outputs"]?.AsObject().SelectMany(node => node.Value!.AsObject())
            .Where(value => value.Value is JsonArray).SelectMany(value => value.Value!.AsArray())
            .FirstOrDefault(value => value is JsonObject && value["type"]?.GetValue<string>() == "output" &&
                Path.GetExtension(value["filename"]?.GetValue<string>() ?? "").Equals(video ? ".mp4" : ".png", StringComparison.OrdinalIgnoreCase));
        if (image != null)
        {
            var output = Path.GetFullPath(Path.Combine(App.Root, "output")) + Path.DirectorySeparatorChar;
            var path = Path.GetFullPath(Path.Combine(output, image["subfolder"]!.GetValue<string>(), image["filename"]!.GetValue<string>()));
            if (!path.StartsWith(output, StringComparison.OrdinalIgnoreCase)) throw new IOException("The engine returned an invalid image path.");
            await ReleaseCreate(id);
            return path;
        }
        if (status?["completed"]?.GetValue<bool>() == true) throw new IOException("The job finished without a saved result. Try generating again.");
        return null;
    }

    public async Task Cancel(string id)
    {
        var pending = Path.Combine(App.Root, "user", "desktop-job.json");
        if (!File.Exists(pending) || JsonNode.Parse(await File.ReadAllTextAsync(pending))?["Id"]?.GetValue<string>() != id)
            throw new IOException("This job is not owned by the current Create recovery record.");
        using var response = await http.PostAsJsonAsync("api/jobs/" + Uri.EscapeDataString(id) + "/cancel", new { });
        if (response.StatusCode == System.Net.HttpStatusCode.NotFound)
            throw new IOException("This engine lacks atomic targeted cancellation. Running work continues; no global interrupt was sent.");
        var result = await ReadResponse(response);
        if (result["cancelled"]?.GetValue<bool>() != true)
            throw new IOException("The engine did not cancel this job. Reconcile its queue/history; it may already have finished.");
    }

    private async Task ReleaseCreate(string id)
    {
        var slot = await production.Call("gpu-status");
        if (slot["owner"]?.GetValue<string>() == "create_" + id.Replace("-", ""))
            await production.Call("gpu-release", new { owner = slot["owner"]!.GetValue<string>(), terminal = true });
    }
}
