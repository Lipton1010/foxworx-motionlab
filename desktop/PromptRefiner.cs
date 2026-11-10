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
    private record RewriteResult(string? prompt, string? ratio, string? follow, string[]? warnings, string? profile_version);

    private async void RefinePrompt(object sender, RoutedEventArgs e)
    {
        if (busy) return;
        string? gpuOwner = null;
        string? privateInput = null;
        string? privateOutput = null;
        try
        {
            if (string.IsNullOrWhiteSpace(BuiltPrompt.Text)) BuiltPrompt.Text = ComposePrompt(ReadBuilder());
            var target = (builderVideo ? VideoModelBox.SelectedItem : ImageModelBox.SelectedItem) as ModelChoice
                ?? throw new IOException("Select the generation model in Images or Videos before refining.");
            var selected = builderVideo
                ? (RefineWithReferences.IsChecked == true && VideoImageMode.IsChecked == true && videoSource != null
                    ? new[] { new ReferenceImage { Path = videoSource, Role = "First frame" } } : [])
                : (RefineWithReferences.IsChecked == true ? references.ToArray() : []);
            if (!builderVideo && selected.Length > 0 && target.Family != "qwen")
                throw new IOException("This generation workflow does not support reference-image edits. Uncheck reference images for text-only refinement, or choose Qwen Image for an edit.");
            if (builderVideo && VideoImageMode.IsChecked == true && selected.Length == 0)
                throw new IOException("First-frame refinement requires an existing first frame and Include my reference images. Otherwise choose text-to-video or keep your manual prompt.");
            string mode = builderVideo ? (selected.Length > 0 ? "i2v" : "t2v") : (selected.Length > 0 ? "edit" : "t2i");
            string tier = RefinerTier.SelectedIndex == 1 ? "9b" : "4b";
            if (!File.Exists(Path.Combine(App.Root, "models", "prompt-refiner", tier + ".json")))
                throw new IOException("Qwen3.5 " + tier + " is not configured. Use the optional refiner setup; manual prompts remain available. No download has started.");
            foreach (var reference in selected)
                if (!File.Exists(reference.Path)) throw new IOException("Reference image is missing: " + reference.Path);
            cancelled = false; rewriteCancellation = new CancellationTokenSource();
            var token = rewriteCancellation.Token;
            SetBusy(true); CancelButton.Content = "Cancel refinement"; CancelButton.IsEnabled = true;
            await engine.EnsureStarted(SetStatus);
            token.ThrowIfCancellationRequested();
            gpuOwner = "rewrite_" + Guid.NewGuid().ToString("N");
            var admission = await new ProductionClient().Call("gpu-claim", new { owner = gpuOwner, intent = "model-specific-prompt-refinement" }, cancellationToken: token);
            if (admission["phase"]?.GetValue<string>() != "admitted") throw new IOException("Prompt refinement admission needs reconciliation before starting.");
            SetStatus("Preparing memory for the local prompt rewriterâ€¦");
            await engine.ReleaseIdleModels(token);
            string input = Path.Combine(App.Root, "temp", "rewrite-" + Guid.NewGuid().ToString("N") + ".json");
            string output = input + ".result.json";
            privateInput = input; privateOutput = output;
            string draft = BuiltPrompt.Text;
            if (selected.Length > 0) draft += "\n\nReference guidance:\n" + string.Join("\n", selected.Select((r, i) => $"<image{i + 1}>: {r.Role}. {r.Notes}"));
            await File.WriteAllTextAsync(input, JsonSerializer.Serialize(new { prompt = draft, images = selected.Select(r => r.Path).ToArray(), target = target.Family, mode, tier }));
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
            BuilderDraftState.Text = "AI-refined draft Â· review or edit before applying";
            RewriteInfo.Text = "Draft only; no media generated. Profile " + target.Name + " v" + result.profile_version + ". Model notes: " + string.Join(" ", result.warnings ?? []) + " " + (!string.IsNullOrWhiteSpace(result.ratio) ? "Suggested aspect ratio: " + result.ratio + ". " : "") + (!string.IsNullOrWhiteSpace(result.follow) ? "Suggested framing reference: " + result.follow + ". " : "") + "Review the prompt; your generation settings have not been changed.";
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
            // Requests and verbose runtime logs can contain private drafts. Keep no raw copies.
            foreach (var privatePath in new[] { privateInput, privateOutput, privateOutput == null ? null : Path.ChangeExtension(privateOutput, ".runtime.log") })
            {
                if (privatePath == null) continue;
                try { File.Delete(privatePath); }
                catch (IOException) { SetStatus("A temporary refinement file could not be removed. Review the temp folder."); }
                catch (UnauthorizedAccessException) { SetStatus("A temporary refinement file could not be removed. Review the temp folder."); }
            }
            rewriteCancellation?.Dispose(); rewriteCancellation = null;
        }
    }
    private void UndoRefinement(object sender, RoutedEventArgs e)
    {
        if (beforeRefinement == null) return;
        BuiltPrompt.Text = beforeRefinement; beforeRefinement = null; UndoRefinementButton.IsEnabled = false;
        BuilderDraftState.Text = "Previous draft restored Â· review before applying";
        RewriteInfo.Text = "Previous draft restored.";
    }
}
