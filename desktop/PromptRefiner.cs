using System.Diagnostics;
using System.IO;
using System.Text.Json;
using System.Windows;

namespace ImageStudio;

public partial class MainWindow
{
    private Process? rewriteProcess;
    private CancellationTokenSource? rewriteCancellation;
    private string? beforeRefinement;
    private record RewriteResult(string? prompt, string? ratio, string? follow);

    private async void RefinePrompt(object sender, RoutedEventArgs e)
    {
        if (busy) return;
        string? gpuOwner = null;
        if (builderVideo) { SetStatus("Local AI refinement is available for image prompts only. You can build and edit video prompts directly."); return; }
        try
        {
            if (string.IsNullOrWhiteSpace(BuiltPrompt.Text)) BuiltPrompt.Text = ComposePrompt(ReadBuilder());
            var selected = RefineWithReferences.IsChecked == true ? references.ToArray() : [];
            string task = selected.Length > 0 ? "edit" : "t2i";
            string modelRoot = Path.Combine(App.Root, "models", "prompt-rewriters");
            string modelName = selected.Length > 0 ? "I2I" : "T2I";
            var required = new List<string>
            {
                Path.Combine(modelRoot, "gguf", $"Qwen-Image-2.1-PE-{modelName}.Q5_K_M.gguf"),
                Path.Combine(modelRoot, task, "system_prompt.txt"),
                Path.Combine(App.Root, "runtime", "llama", "llama-server.exe")
            };
            if (selected.Length > 0) required.Add(Path.Combine(modelRoot, "gguf", "Qwen-Image-2.1-PE-I2I.mmproj-bf16.gguf"));
            if (required.FirstOrDefault(path => !File.Exists(path)) is { } missing)
                throw new IOException("The 5-bit prompt rewriter is not fully installed. Missing: " + Path.GetFileName(missing));
            foreach (var reference in selected)
                if (!File.Exists(reference.Path)) throw new IOException("Reference image is missing: " + reference.Path);
            cancelled = false; rewriteCancellation = new CancellationTokenSource();
            var token = rewriteCancellation.Token;
            SetBusy(true); CancelButton.Content = "Cancel refinement"; CancelButton.IsEnabled = true;
            await engine.EnsureStarted(SetStatus);
            token.ThrowIfCancellationRequested();
            gpuOwner = "rewrite_" + Guid.NewGuid().ToString("N");
            var admission = await new ProductionClient().Call("gpu-claim", new { owner = gpuOwner, intent = "image-prompt-refinement" }, cancellationToken: token);
            if (admission["phase"]?.GetValue<string>() != "admitted") throw new IOException("Prompt refinement admission needs reconciliation before starting.");
            SetStatus("Preparing memory for the local prompt rewriter…");
            await engine.ReleaseIdleModels(token);
            string input = Path.Combine(App.Root, "temp", "rewrite-" + Guid.NewGuid().ToString("N") + ".json");
            string output = input + ".result.json";
            string draft = BuiltPrompt.Text;
            if (selected.Length > 0) draft += "\n\nReference guidance:\n" + string.Join("\n", selected.Select((r, i) => $"<image{i + 1}>: {r.Role}. {r.Notes}"));
            await File.WriteAllTextAsync(input, JsonSerializer.Serialize(new { prompt = draft, images = selected.Select(r => r.Path).ToArray() }));
            token.ThrowIfCancellationRequested();
            var start = new ProcessStartInfo(App.PythonPath) { CreateNoWindow = true, UseShellExecute = false, RedirectStandardOutput = true, RedirectStandardError = true, WorkingDirectory = App.Root };
            start.StandardOutputEncoding = start.StandardErrorEncoding = System.Text.Encoding.UTF8;
            foreach (string arg in new[] { "-u", Path.Combine(App.Root, "desktop", "rewrite_prompt.py"), input, output }) start.ArgumentList.Add(arg);
            start.Environment["PYTHONIOENCODING"] = "utf-8";
            rewriteProcess = Process.Start(start) ?? throw new IOException("The prompt rewriter could not start.");
            var errors = rewriteProcess.StandardError.ReadToEndAsync();
            while (await rewriteProcess.StandardOutput.ReadLineAsync() is { } line)
                if (!cancelled && (line.Contains("local prompt rewriter") || line.Contains("Refining the prompt"))) SetStatus(line + " This may take a few minutes.");
            await rewriteProcess.WaitForExitAsync();
            string detail = await errors;
            if (cancelled) { SetStatus("Prompt refinement cancelled. Your draft is ready to edit."); return; }
            if (rewriteProcess.ExitCode != 0)
            {
                await File.WriteAllTextAsync(Path.Combine(App.Root, "logs", "prompt-rewriter-error.log"), detail);
                throw new IOException("AI refinement could not finish. Your draft is unchanged. See logs/prompt-rewriter-error.log for details.");
            }
            var result = JsonSerializer.Deserialize<RewriteResult>(await File.ReadAllTextAsync(output)) ?? throw new IOException("The rewriter returned an empty result.");
            token.ThrowIfCancellationRequested();
            if (string.IsNullOrWhiteSpace(result.prompt)) throw new IOException("The rewriter returned an empty prompt.");
            beforeRefinement = BuiltPrompt.Text; BuiltPrompt.Text = result.prompt; UndoRefinementButton.IsEnabled = true;
            BuilderDraftState.Text = "AI-refined image draft · review or edit before applying";
            RewriteInfo.Text = "AI refinement ready. " + (!string.IsNullOrWhiteSpace(result.ratio) ? "Suggested aspect ratio: " + result.ratio + ". " : "") + (!string.IsNullOrWhiteSpace(result.follow) ? "Suggested framing reference: " + result.follow + ". " : "") + "Review the prompt; your image settings have not been changed.";
            SetStatus("Prompt refined locally. Review the result before using it.");
        }
        catch (OperationCanceledException) when (cancelled) { SetStatus("Prompt refinement cancelled. Your draft is ready to edit."); }
        catch (Exception ex) { ShowError(ex); }
        finally
        {
            if (rewriteProcess != null)
            {
                try { if (!rewriteProcess.HasExited) { rewriteProcess.Kill(entireProcessTree: true); await rewriteProcess.WaitForExitAsync(); } }
                catch (InvalidOperationException) { }
                catch (System.ComponentModel.Win32Exception ex) { ShowError(ex); }
            }
            rewriteProcess?.Dispose(); rewriteProcess = null; SetBusy(false); CancelButton.Content = "Cancel generation";
            if (gpuOwner != null)
            {
                try { await new ProductionClient().Call("gpu-release", new { owner = gpuOwner }); }
                catch (Exception ex) { SetStatus("GPU reservation needs reconciliation: " + ex.Message); }
            }
            rewriteCancellation?.Dispose(); rewriteCancellation = null;
        }
    }
    private void UndoRefinement(object sender, RoutedEventArgs e)
    {
        if (beforeRefinement == null) return;
        BuiltPrompt.Text = beforeRefinement; beforeRefinement = null; UndoRefinementButton.IsEnabled = false;
        BuilderDraftState.Text = "Previous image draft restored · review before applying";
        RewriteInfo.Text = "Previous draft restored.";
    }
}
