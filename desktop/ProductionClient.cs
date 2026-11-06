using System.Diagnostics;
using System.IO;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace ImageStudio;

public sealed class ProductionClient
{
    public async Task<JsonNode> Call(string operation, object? payload = null, string? project = null,
        string? revision = null, CancellationToken cancellationToken = default, string? requestId = null,
        TimeSpan? timeout = null)
    {
        string stableId = requestId ?? Guid.NewGuid().ToString("N");
        var snapshot = JsonSerializer.SerializeToNode(payload ?? new { });
        var started = Stopwatch.StartNew();
        var budget = timeout ?? TimeSpan.FromSeconds(45);
        for (int attempt = 0; ; attempt++)
        {
            if (started.Elapsed >= budget) throw new IOException("Film helper wait budget expired before starting another process. Reconcile the saved request before retrying.");
            try { return await CallOnce(operation, snapshot, project, revision, cancellationToken, stableId, budget-started.Elapsed); }
            catch (IOException ex) when (attempt < 3 && ex.Message == "busy: Revision is locked by another runner" && started.Elapsed < budget)
            { await Task.Delay(50 * (attempt+1), cancellationToken); }
        }
    }
    private async Task<JsonNode> CallOnce(string operation, object? payload, string? project,
        string? revision, CancellationToken cancellationToken, string requestId, TimeSpan timeout)
    {
        var start = new ProcessStartInfo(App.ProductionPythonPath)
        {
            CreateNoWindow = true, UseShellExecute = false, RedirectStandardInput = true,
            RedirectStandardOutput = true, RedirectStandardError = true, WorkingDirectory = App.Root,
            StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8,
            StandardInputEncoding = new UTF8Encoding(false)
        };
        foreach (var arg in new[] { "-u", Path.Combine(App.Root, "desktop", "production_service.py"), App.Root }) start.ArgumentList.Add(arg);
        start.Environment["PYTHONIOENCODING"] = "utf-8";
        using var process = Process.Start(start) ?? throw new IOException("The film service could not start.");
        using var bounded = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        bounded.CancelAfter(timeout > TimeSpan.Zero ? timeout : TimeSpan.Zero);
        var stdout = process.StandardOutput.ReadToEndAsync();
        var stderr = process.StandardError.ReadToEndAsync();
        var request = new { version = 1, operation, request_id = requestId ?? Guid.NewGuid().ToString("N"), project_id = project, expected_revision = revision, payload = payload ?? new { } };
        try
        {
            await process.StandardInput.WriteAsync(JsonSerializer.Serialize(request));
            process.StandardInput.Close();
            await process.WaitForExitAsync(bounded.Token);
            var output = await stdout;
            var diagnostics = await stderr;
            var reply = JsonNode.Parse(output) ?? throw new IOException("The film service returned no result. " + diagnostics);
            if (reply["version"]?.GetValue<int>() != 1) throw new IOException("Unsupported film service protocol.");
            if (reply["request_id"]?.GetValue<string>() != request.request_id) throw new IOException("Film helper reply belongs to a different request.");
            if (reply["ok"]?.GetValue<bool>() != true)
                throw new IOException($"{reply["code"]}: {reply["message"]}");
            if (process.ExitCode != 0) throw new IOException("Film helper failed. " + diagnostics);
            return reply["result"]!;
        }
        catch (OperationCanceledException)
        {
            // Durable engine intents remain on disk. Killing this wait never cancels an engine job.
            if (!process.HasExited) process.Kill(entireProcessTree: true);
            await process.WaitForExitAsync();
            await Task.WhenAll(stdout, stderr);
            throw new IOException("Stopped waiting for the film service. Reopen to reconcile durable work before retrying.");
        }
    }
}
