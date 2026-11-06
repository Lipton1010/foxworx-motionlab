using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Net.Http;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media.Imaging;
using Microsoft.Win32;
using System.Runtime.InteropServices;
using System.Windows.Interop;

namespace ImageStudio;

public partial class MainWindow : Window
{
    [DllImport("dwmapi.dll")]
    private static extern int DwmSetWindowAttribute(IntPtr window, int attribute, ref int value, int size);

    protected override void OnSourceInitialized(EventArgs e)
    {
        base.OnSourceInitialized(e);
        ThemeManager.ApplyTitleBar(this);
    }

    private readonly StudioEngine engine = new();
    private readonly string settingsPath = Path.Combine(App.Root, "user", "desktop-settings.json");
    private readonly string jobPath = Path.Combine(App.Root, "user", "desktop-job.json");
    private string? sourcePath, previewPath, jobId;
    private bool busy, cancelled;
    private ImageRequest? currentRequest;
    private VideoRequest? currentVideoRequest;
    private record Settings(string Prompt, string Negative, string Seed, int Shape, int Size, int Quality, bool Transparent, bool Edit = false, string? Source = null, string? Preview = null, ReferenceImage[]? References = null, bool UseReferences = true, BuilderDraft? Builder = null);
    private record PendingJob(string Id, ImageRequest? Request, VideoRequest? Video = null);
    private record GalleryImage(string Path, string Name, BitmapSource Thumbnail);

    public MainWindow()
    {
        ThemeManager.Initialize();
        InitializeComponent();
        OutputLibrary.Films = FilmWorkspace;
        FilmWorkspace.KeyframeRequested += prompt => { PromptBox.Text = prompt; CreateMode.IsChecked = true; WorkspaceTabs.SelectedItem = StudioTab; SetStatus("Film keyframe prompt ready. Generate an image, then adopt it from Library into the selected film shot."); };
        UpdateBuilderMode();
        BuiltPrompt.TextChanged += (_, _) => { if (BuiltPrompt.IsKeyboardFocusWithin) BuilderDraftState.Text = builderVideo ? "Manual video draft · Apply to text or first-frame video below" : "Manual image draft · Apply to a new image or edit below"; };
        ReferenceList.ItemsSource = references;
        InitializeMediaWorkspace();
        PreviewKeyDown += (_, e) =>
        {
            if (e.Key == Key.Enter && Keyboard.Modifiers == ModifierKeys.Control)
            {
                if (VideoTab.IsSelected) { e.Handled = true; GenerateVideo(this, new RoutedEventArgs()); }
                else if (StudioTab.IsSelected) { e.Handled = true; Generate(this, new RoutedEventArgs()); }
            }
        };
    }

    private async void WindowLoaded(object sender, RoutedEventArgs e)
    {
        try
        {
            Directory.CreateDirectory(Path.Combine(App.Root, "user"));
            if (File.Exists(settingsPath))
            {
                var settings = JsonSerializer.Deserialize<Settings>(await File.ReadAllTextAsync(settingsPath));
                if (settings != null)
                {
                    PromptBox.Text = settings.Prompt; NegativeBox.Text = settings.Negative; SeedBox.Text = settings.Seed;
                    ShapeBox.SelectedIndex = Math.Clamp(settings.Shape, 0, 4); SizeBox.SelectedIndex = Math.Clamp(settings.Size, 0, 2);
                    QualityBox.SelectedIndex = Math.Clamp(settings.Quality, 0, 2); TransparentBox.IsChecked = settings.Transparent;
                    if (settings.References != null)
                    {
                        foreach (var reference in settings.References.Take(10))
                        {
                            try { references.Add(PrepareReference(reference)); }
                            catch (Exception) { references.Add(reference); }
                        }
                        RefreshReferences();
                    }
                    else if (settings.Source != null && File.Exists(settings.Source)) SetSource(settings.Source);
                    IncludeReferences.IsChecked = settings.UseReferences;
                    if (settings.Builder != null) RestoreBuilder(settings.Builder);
                    CreateMode.IsChecked = !settings.Edit;
                    EditMode.IsChecked = settings.Edit;
                    if (settings.Preview != null && File.Exists(settings.Preview)) ShowPreview(settings.Preview);
                }
            }
            LoadGallery();
            await LoadMediaWorkspace();
            if (File.Exists(jobPath))
            {
                var job = JsonSerializer.Deserialize<PendingJob>(await File.ReadAllTextAsync(jobPath));
                if (job != null)
                {
                    jobId = job.Id; currentRequest = job.Request; currentVideoRequest = job.Video; SetBusy(true);
                    if (job.Video != null) WorkspaceTabs.SelectedItem = VideoTab;
                    await engine.EnsureStarted(SetStatus);
                    CancelButton.IsEnabled = true;
                    await WatchJob();
                    SetBusy(false);
                }
            }
        }
        catch (OperationCanceledException ex) when (ex is not TaskCanceledException) { CompleteJob(); SetStatus("Generation cancelled. Ready for a new image."); SetBusy(false); }
        catch (Exception ex) { ShowError(ex); SetBusy(false); }
    }

    private void SetStatus(string text) => StatusText.Text = text;
    private void SetBusy(bool value)
    {
        busy = value;
        ControlsPanel.IsEnabled = !value;
        GenerateButton.IsEnabled = !value && workspaceReady && ImageModelBox.SelectedItem != null;
        VideoControls.IsEnabled = !value;
        GenerateVideoButton.IsEnabled = !value && workspaceReady && VideoModelBox.SelectedItem != null;
        ModelList.IsEnabled = RefreshModelsButton.IsEnabled = !value;
        DownloadModelsButton.IsEnabled = !value;
        ReferencesPanel.IsEnabled = BuilderPanel.IsEnabled = !value;
        UseButton.IsEnabled = !value && previewPath != null;
        AnimateButton.IsEnabled = !value && previewPath != null;
        DeleteButton.IsEnabled = !value && ImageLibrary.CanRecycle(Path.Combine(App.Root, "output"), previewPath);
        VideoDeleteButton.IsEnabled = !value && ImageLibrary.CanRecycle(Path.Combine(App.Root, "output"), videoPreview);
        CancelButton.Visibility = value ? Visibility.Visible : Visibility.Collapsed;
        CancelButton.IsEnabled = value && jobId != null;
        Progress.Visibility = value ? Visibility.Visible : Visibility.Collapsed;
    }

    private void ModeChanged(object sender, RoutedEventArgs e)
    {
        if (SourcePanel == null) return;
        bool edit = EditMode.IsChecked == true;
        SourcePanel.IsExpanded = edit;
        IncludeReferences.IsEnabled = !edit;
        if (edit) IncludeReferences.IsChecked = true;
        ShapePanel.Visibility = edit ? Visibility.Collapsed : Visibility.Visible;
        PromptLabel.Content = edit ? "_Describe the change" : "_Describe your image";
        PromptHint.Text = edit ? "Say what to change and what to keep. Original proportions are preserved." : "Describe the subject, setting, and style.";
        GenerateButton.Content = edit ? "_Generate edited image" : "_Generate image";
        SwitchImageWorkflow();
    }

    private static BitmapImage LoadBitmap(string path, int decodeWidth = 0)
    {
        var bitmap = new BitmapImage();
        bitmap.BeginInit(); bitmap.CacheOption = BitmapCacheOption.OnLoad;
        if (decodeWidth > 0) bitmap.DecodePixelWidth = decodeWidth;
        bitmap.UriSource = new Uri(path); bitmap.EndInit(); bitmap.Freeze();
        return bitmap;
    }

    private void SetSource(string path)
    {
        var source = PrepareReference(new ReferenceImage { Path = path });
        if (references.Count == 10) references.RemoveAt(0);
        references.Insert(0, source); RefreshReferences(); IncludeReferences.IsChecked = true;
        EditMode.IsChecked = true;
    }

    private ImageRequest ReadRequest()
    {
        var prompt = PromptBox.Text.Trim();
        if (prompt.Length == 0) { PromptBox.Focus(); throw new ArgumentException("Describe the image you want before generating."); }
        long seed = Random.Shared.NextInt64(0, long.MaxValue);
        if (!string.IsNullOrWhiteSpace(SeedBox.Text) && (!long.TryParse(SeedBox.Text, out seed) || seed < 0))
            throw new ArgumentException("Use a whole number from 0 to 9223372036854775807 for the seed, or leave it blank.");
        bool edit = EditMode.IsChecked == true;
        var model = ImageModelBox.SelectedItem as ModelChoice ?? throw new ArgumentException("Choose an installed image model. Refresh the Models library if needed.");
        var selectedReferences = model.Family == "qwen" && IncludeReferences.IsChecked == true ? references.Select(r => r.Snapshot()).ToArray() : [];
        if (edit && selectedReferences.Length == 0) throw new ArgumentException("Add the image you want to edit in References. Image 1 will be the main image.");
        foreach (var reference in selectedReferences)
            if (!File.Exists(reference.Path)) throw new IOException("Reference image is missing: " + reference.Path + ". Remove it or load the saved reference set.");
        var ratio = new[] { 1.0, 1.5, 2.0 / 3, 16.0 / 9, 9.0 / 16 }[ShapeBox.SelectedIndex];
        var pixels = new[] { 1, 2, 4 }[SizeBox.SelectedIndex] * 1024 * 1024;
        int width = (int)Math.Round(Math.Sqrt(pixels * ratio) / 16) * 16;
        int height = (int)Math.Round(Math.Sqrt(pixels / ratio) / 16) * 16;
        int resolution = (int)Math.Round(Math.Sqrt(pixels) / 32) * 32;
        var steps = model.Family == "moss" ? new[] { 20, 50, 70 } : model.Family == "krea" ? (model.Id.Contains("turbo") ? new[] { 4, 8, 12 } : new[] { 20, 30, 50 }) : new[] { 12, 25, 40 };
        return new(prompt, NegativeBox.Text.Trim(), seed, width, height, steps[QualityBox.SelectedIndex], model.Family == "qwen" && TransparentBox.IsChecked == true, edit ? selectedReferences[0].Path : null, resolution, selectedReferences, model.Id, ImageLoras.Selection);
    }

    private async void Generate(object sender, RoutedEventArgs e)
    {
        if (busy) return;
        try
        {
            if (jobId != null)
            {
                SetBusy(true); CancelButton.IsEnabled = true;
                await engine.EnsureStarted(SetStatus);
                await WatchJob();
                return;
            }
            currentRequest = ReadRequest();
            currentVideoRequest = null;
            SaveSettings();
            cancelled = false; SetBusy(true);
            await engine.EnsureStarted(SetStatus);
            SetStatus(currentRequest.Source == null ? "Sending your description to the image engine…" : "Preparing your source image…");
            jobId = await engine.Submit(currentRequest);
            CancelButton.IsEnabled = true;
            await WatchJob();
        }
        catch (OperationCanceledException ex) when (ex is not TaskCanceledException) { CompleteJob(); SetStatus("Generation cancelled. You can change your settings and try again."); }
        catch (Exception ex) { ShowError(ex); }
        finally { SetBusy(false); }
    }

    private async Task WatchJob()
    {
        var elapsed = Stopwatch.StartNew();
        int missing = 0, failures = 0;
        while (jobId != null)
        {
            string? path;
            JsonNode queue;
            try { path = await engine.Result(jobId, currentVideoRequest != null); queue = await engine.Queue(); failures = 0; }
            catch (HttpRequestException) when (++failures < 5) { SetStatus("Reconnecting to the image engine…"); await Task.Delay(2000); continue; }
            catch (TaskCanceledException) when (++failures < 5) { SetStatus("The image engine is taking longer to respond. Reconnecting…"); await Task.Delay(2000); continue; }
            catch (EngineJobFailedException) { CompleteJob(); throw; }
            if (path != null)
            {
                await File.WriteAllTextAsync(path + ".json", JsonSerializer.Serialize((object?)currentVideoRequest ?? currentRequest, new JsonSerializerOptions { WriteIndented = true }));
                if (currentVideoRequest != null) { ShowVideo(path); LoadVideoGallery(); }
                else { ShowPreview(path); LoadGallery(); }
                var seed = currentVideoRequest?.Seed ?? currentRequest?.Seed;
                string media = currentVideoRequest == null ? "Image" : "Video";
                CompleteJob(); SetStatus($"{media} saved · Seed {seed} · {elapsed.Elapsed:m\\:ss} elapsed");
                return;
            }
            var running = queue["queue_running"]!.AsArray().Any(x => x?[1]?.GetValue<string>() == jobId);
            var waiting = queue["queue_pending"]!.AsArray().Any(x => x?[1]?.GetValue<string>() == jobId);
            if (!running && !waiting)
            {
                if (++missing >= 3)
                {
                    if (cancelled) { CompleteJob(); throw new OperationCanceledException(); }
                    throw new IOException("The saved job is absent from queue/history. Its submission remains unknown; it will not be automatically resubmitted. Reconcile it with the originating engine.");
                }
            }
            else missing = 0;
            string kind = currentVideoRequest == null ? "image" : "video";
            SetStatus(cancelled ? $"Cancelling your {kind}…" : waiting ? $"Your {kind} is queued. Waiting for the current job to finish…" : $"Creating your {kind} · {elapsed.Elapsed:m\\:ss} elapsed. Loading the model can take a few minutes.");
            await Task.Delay(1200);
        }
    }

    private void CompleteJob()
    {
        jobId = null;
        if (File.Exists(jobPath)) File.Delete(jobPath);
    }

    private async void CancelGeneration(object sender, RoutedEventArgs e)
    {
        if (rewriteCancellation != null)
        {
            cancelled = true; CancelButton.IsEnabled = false;
            rewriteCancellation.Cancel(); SetStatus("Cancelling prompt refinement…");
            try { if (rewriteProcess != null && !rewriteProcess.HasExited) rewriteProcess.Kill(entireProcessTree: true); }
            catch (InvalidOperationException) { }
            catch (System.ComponentModel.Win32Exception ex) { ShowError(ex); CancelButton.IsEnabled = true; }
            return;
        }
        if (jobId == null) return;
        CancelButton.IsEnabled = false;
        try { await engine.Cancel(jobId); cancelled = true; SetStatus("Cancelling generation…"); }
        catch (Exception ex) { ShowError(ex); CancelButton.IsEnabled = true; }
    }

    private void ShowPreview(string path)
    {
        var bitmap = LoadBitmap(path);
        previewPath = path; Preview.Source = bitmap; EmptyPreview.Visibility = Visibility.Collapsed;
        ImageInfo.Text = $"{bitmap.PixelWidth} × {bitmap.PixelHeight} · PNG";
        OpenButton.IsEnabled = SaveButton.IsEnabled = true; UseButton.IsEnabled = !busy;
        AnimateButton.IsEnabled = !busy;
        DeleteButton.IsEnabled = !busy && ImageLibrary.CanRecycle(Path.Combine(App.Root, "output"), path);
    }

    private void LoadGallery()
    {
        string output = Path.Combine(App.Root, "output");
        Directory.CreateDirectory(output);
        var images = new List<GalleryImage>();
        foreach (var file in new DirectoryInfo(output).EnumerateFiles("*.png", SearchOption.AllDirectories).Where(f => ImageLibrary.CanRecycle(output, f.FullName)).OrderByDescending(f => f.LastWriteTimeUtc).Take(30))
            try { images.Add(new(file.FullName, file.Name, LoadBitmap(file.FullName, 160))); } catch (Exception ex) when (ex is IOException or NotSupportedException or FileFormatException) { /* An in-progress output will appear on the next refresh. */ }
        Gallery.ItemsSource = images;
        EmptyGallery.Visibility = images.Count == 0 ? Visibility.Visible : Visibility.Collapsed;
    }

    private void GallerySelected(object sender, SelectionChangedEventArgs e)
    {
        if (Gallery.SelectedItem is GalleryImage image)
            try { ShowPreview(image.Path); } catch (Exception ex) { ShowError(ex); }
    }
    private void RefreshGallery(object sender, RoutedEventArgs e) { try { LoadGallery(); } catch (Exception ex) { ShowError(ex); } }
    private void UseAsSource(object sender, RoutedEventArgs e) { if (previewPath != null) { try { SetSource(previewPath); PromptBox.Focus(); } catch (Exception ex) { ShowError(ex); } } }
    private void OpenFolder(object sender, RoutedEventArgs e) => OpenPath(Path.Combine(App.Root, "output"));
    private void OpenImage(object sender, RoutedEventArgs e) { if (previewPath != null) OpenPath(previewPath); }
    private void OpenPath(string path) { try { Process.Start(new ProcessStartInfo(path) { UseShellExecute = true }); } catch (Exception ex) { ShowError(ex); } }

    private void SaveAs(object sender, RoutedEventArgs e)
    {
        if (previewPath == null) return;
        var dialog = new SaveFileDialog { Title = "Save image as", Filter = "PNG image|*.png", FileName = Path.GetFileName(previewPath), DefaultExt = ".png" };
        if (dialog.ShowDialog(this) != true) return;
        try
        {
            if (!string.Equals(Path.GetFullPath(dialog.FileName), Path.GetFullPath(previewPath), StringComparison.OrdinalIgnoreCase)) File.Copy(previewPath, dialog.FileName, true);
            SetStatus("Saved to " + dialog.FileName);
        }
        catch (Exception ex) { ShowError(ex); }
    }

    private void ShowError(Exception ex)
    {
        var message = ex is HttpRequestException or TaskCanceledException ? "Connection to the generation engine was lost. Select Generate to reconnect to your job, or reopen the app." : ex.Message;
        SetStatus(message.Length > 280 ? message[..280] + "… See logs/desktop-errors.log for details." : message);
        try { File.AppendAllText(Path.Combine(App.Root, "logs", "desktop-errors.log"), DateTime.Now + " " + ex + Environment.NewLine); } catch (IOException) { }
    }
    private void SaveSettings()
    {
        File.WriteAllText(settingsPath, JsonSerializer.Serialize(new Settings(PromptBox.Text, NegativeBox.Text, SeedBox.Text, ShapeBox.SelectedIndex, SizeBox.SelectedIndex, QualityBox.SelectedIndex, TransparentBox.IsChecked == true, EditMode.IsChecked == true, sourcePath, previewPath, references.Select(r => r.Snapshot()).ToArray(), IncludeReferences.IsChecked == true, ReadBuilder())));
        SaveWorkspace();
    }
    private void WindowClosing(object? sender, CancelEventArgs e)
    {
        if (rewriteCancellation != null) { e.Cancel = true; SetStatus("Cancel prompt refinement before closing this window."); return; }
        if (busy && jobId == null) { e.Cancel = true; SetStatus("Please wait until the engine has accepted the image before closing."); return; }
        if (busy && !StudioDialog.Confirm(this, "Your generation will keep running in the background. Reopen Image Studio to see the result. Close this window?", "Still generating")) { e.Cancel = true; return; }
        try { SaveSettings(); } catch (Exception ex) { ShowError(ex); }
        videoTimer.Stop(); VideoPlayer.Close();
    }
}
