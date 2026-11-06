using ImageStudio;
using System.IO;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

Console.InputEncoding = Console.OutputEncoding = new UTF8Encoding(false);
try
{
    var input = JsonNode.Parse(Console.In.ReadToEnd()) ?? throw new ArgumentException("Expected a graph request.");
    var root = input["root"]?.GetValue<string>() ?? throw new ArgumentException("Explicit application root required.");
    if (!Path.IsPathFullyQualified(root) || !File.Exists(Path.Combine(root, "launch.py"))) throw new ArgumentException("Application root must contain launch.py.");
    Environment.SetEnvironmentVariable("IMAGE_STUDIO_ROOT", root);
    object graph = input["kind"]?.GetValue<string>() switch
    {
        "image" => StudioEngine.BuildGraph(input["request"]!.Deserialize<ImageRequest>()!, input["source_names"]?.Deserialize<string[]>()),
        "video" => GenerationPipelines.BuildVideo(input["request"]!.Deserialize<VideoRequest>()!, input["source_name"]?.GetValue<string>(), input["last_frame"]?.GetValue<string>(), input["audio_guide"]?.GetValue<string>(), input["guide_video"]?.GetValue<string>()),
        _ => throw new ArgumentException("Unknown graph kind.")
    };
    Console.WriteLine(JsonSerializer.Serialize(new { version = 1, ok = true, graph }));
}
catch (Exception ex)
{
    Console.WriteLine(JsonSerializer.Serialize(new { version = 1, ok = false, code = "invalid-input", message = ex.Message }));
    Environment.ExitCode = 2;
}
