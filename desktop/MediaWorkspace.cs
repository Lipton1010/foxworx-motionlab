using System.Diagnostics;
using System.IO;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Threading;
using Microsoft.Win32;

namespace ImageStudio;

public partial class MainWindow
{
    private readonly string workspacePath = Path.Combine(App.Root, "user", "workspace-settings.json");
    private WorkspaceSettings workspace = new();
    private IReadOnlyList<ModelChoice> models = [];
    private string[] loraFiles = [];
    private string imageWorkflow = "image:create", videoWorkflow = "video:text";
    private string? imageModel, videoModel, videoSource, videoPreview;
    private bool workspaceReady, applyingChoice, updatingSeek, videoPlaying;
    private readonly DispatcherTimer videoTimer = new() { Interval = TimeSpan.FromMilliseconds(250) };
    private record VideoItem(string Path, string Name, string Details, System.Windows.Media.ImageSource? Thumbnail);

    private void InitializeMediaWorkspace()
    {
        DownloadModelsButton.Visibility = File.Exists(Path.Combine(App.Root, "portable.json")) && File.Exists(Path.Combine(App.Root, "portable", "Setup.ps1")) ? Visibility.Visible : Visibility.Collapsed;
        ImageLoras.SelectionEdited += (_, _) => SaveWorkspaceSafely();
        VideoLoras.SelectionEdited += (_, _) => SaveWorkspaceSafely();
        VideoShapeBox.SelectionChanged += (_, _) => UpdateVideoHint();
        videoTimer.Tick += (_, _) =>
        {
            if (!VideoPlayer.NaturalDuration.HasTimeSpan || !VideoTab.IsSelected) return;
            updatingSeek = true;
            VideoSeek.Value = VideoPlayer.Position.TotalSeconds;
            updatingSeek = false;
            VideoInfo.Text = $"{VideoPlayer.Position:mm\\:ss} / {VideoPlayer.NaturalDuration.TimeSpan:mm\\:ss}";
        };
    }

    private async Task LoadMediaWorkspace()
    {
        workspace = WorkspaceSettings.Load(workspacePath);
        applyingChoice = true;
        VideoPromptBox.Text = workspace.VideoPrompt; VideoNegativeBox.Text = workspace.VideoNegative; VideoSeedBox.Text = workspace.VideoSeed;
        VideoShapeBox.SelectedIndex = Math.Clamp(workspace.VideoShape, 0, 2);
        VideoDurationBox.SelectedIndex = Math.Clamp(workspace.VideoDuration, 0, 2);
        VideoImageMode.IsChecked = workspace.AnimateImage;
        VideoTextMode.IsChecked = !workspace.AnimateImage;
        VideoSourcePanel.Visibility = workspace.AnimateImage ? Visibility.Visible : Visibility.Collapsed;
        if (workspace.VideoSource != null && File.Exists(workspace.VideoSource)) SetVideoSource(workspace.VideoSource);
        if (workspace.VideoPreview != null && File.Exists(workspace.VideoPreview)) ShowVideo(workspace.VideoPreview);
        imageWorkflow = EditMode.IsChecked == true ? "image:edit" : "image:create";
        videoWorkflow = workspace.AnimateImage ? "video:image" : "video:text";
        applyingChoice = false;
        LoadVideoGallery();
        GenerateButton.IsEnabled = GenerateVideoButton.IsEnabled = false;
        await RefreshModelLibrary();
        workspaceReady = true;
        GenerateButton.IsEnabled = ImageModelBox.SelectedItem != null;
        GenerateVideoButton.IsEnabled = VideoModelBox.SelectedItem != null;
        SetStatus("Ready · Models and LoRAs are remembered for each workflow.");
    }

    private async Task RefreshModelLibrary()
    {
        RefreshModelsButton.IsEnabled = false;
        try
        {
            await engine.EnsureStarted(SetStatus);
            var info = await engine.ObjectInfo();
            models = ModelCatalog.Read(info, File.Exists(Path.Combine(App.Root, "models", "moss-image-base", "install-manifest.json")));
            loraFiles = ModelCatalog.Options(info, "LoraLoader", "lora_name");
            ModelList.ItemsSource = models; LoraLibrary.ItemsSource = loraFiles.Length > 0 ? loraFiles : new[] { "No LoRAs installed yet." };
            ModelsSummary.Text = $"{models.Count(x => x.Ready && !x.Video)} image models · {models.Count(x => x.Ready && x.Video)} video models · {loraFiles.Length} LoRAs";
            RestoreImageChoice(); RestoreVideoChoice();
        }
        finally { RefreshModelsButton.IsEnabled = !busy; }
    }

    private static void Remember(WorkspaceSettings settings, string key, string? model, LoraPicker picker)
    {
        if (model == null) return;
        var choice = settings.Choice(key);
        choice.Model = model;
        choice.LorasByModel[model] = picker.Selection;
    }

    private void SaveWorkspace()
    {
        if (!workspaceReady || applyingChoice) return;
        Remember(workspace, imageWorkflow, imageModel, ImageLoras);
        Remember(workspace, videoWorkflow, videoModel, VideoLoras);
        workspace.VideoPrompt = VideoPromptBox.Text; workspace.VideoNegative = VideoNegativeBox.Text; workspace.VideoSeed = VideoSeedBox.Text;
        workspace.VideoSource = videoSource; workspace.VideoPreview = videoPreview;
        workspace.VideoShape = VideoShapeBox.SelectedIndex; workspace.VideoDuration = VideoDurationBox.SelectedIndex;
        workspace.AnimateImage = VideoImageMode.IsChecked == true;
        workspace.Save(workspacePath);
    }
    private void SaveWorkspaceSafely() { try { SaveWorkspace(); } catch (Exception ex) { ShowError(ex); } }

    private void RestoreImageChoice()
    {
        applyingChoice = true;
        var options = models.Where(x => x.Ready && !x.Video && (imageWorkflow != "image:edit" || x.Family == "qwen")).ToArray();
        var choice = workspace.Choice(imageWorkflow);
        ImageModelBox.ItemsSource = options;
        ImageModelBox.IsEnabled = options.Length > 0;
        ImageModelBox.SelectedItem = options.FirstOrDefault(x => x.Id == choice.Model) ?? options.FirstOrDefault(x => x.Family == "qwen") ?? options.FirstOrDefault();
        imageModel = (ImageModelBox.SelectedItem as ModelChoice)?.Id;
        ImageLoras.Restore(loraFiles, imageModel != null && choice.LorasByModel.TryGetValue(imageModel, out var selections) ? selections : []);
        applyingChoice = false;
        UpdateImageModelControls();
    }

    private void RestoreVideoChoice()
    {
        applyingChoice = true;
        var options = models.Where(x => x.Ready && x.Video).ToArray();
        var choice = workspace.Choice(videoWorkflow);
        VideoModelBox.ItemsSource = options;
        VideoModelBox.IsEnabled = options.Length > 0;
        VideoModelBox.SelectedItem = options.FirstOrDefault(x => x.Id == choice.Model) ?? options.FirstOrDefault(x => x.Family == "ltx") ?? options.FirstOrDefault();
        videoModel = (VideoModelBox.SelectedItem as ModelChoice)?.Id;
        VideoLoras.Restore(loraFiles, videoModel != null && choice.LorasByModel.TryGetValue(videoModel, out var selections) ? selections : []);
        applyingChoice = false;
        UpdateVideoHint();
    }

    private void SwitchImageWorkflow()
    {
        if (!workspaceReady || applyingChoice) return;
        Remember(workspace, imageWorkflow, imageModel, ImageLoras);
        imageWorkflow = EditMode.IsChecked == true ? "image:edit" : "image:create";
        RestoreImageChoice(); SaveWorkspaceSafely();
    }

    private void ImageModelChanged(object sender, SelectionChangedEventArgs e)
    {
        if (!workspaceReady || applyingChoice) return;
        Remember(workspace, imageWorkflow, imageModel, ImageLoras);
        imageModel = (ImageModelBox.SelectedItem as ModelChoice)?.Id;
        var choice = workspace.Choice(imageWorkflow);
        applyingChoice = true;
        ImageLoras.Restore(loraFiles, imageModel != null && choice.LorasByModel.TryGetValue(imageModel, out var selections) ? selections : []);
        applyingChoice = false;
        UpdateImageModelControls(); SaveWorkspaceSafely();
    }

    private void UpdateImageModelControls()
    {
        var model = ImageModelBox.SelectedItem as ModelChoice;
        ImageModelHint.Text = model?.Description ?? "No compatible model found. Refresh the Models library.";
        SourcePanel.Visibility = model?.Family == "qwen" ? Visibility.Visible : Visibility.Collapsed;
        SourcePanel.IsExpanded = EditMode.IsChecked == true;
        TransparentBox.IsEnabled = model?.Family == "qwen";
        var steps = model?.Family == "moss" ? new[] { 20, 50, 70 } : model?.Family == "krea" ? (model.Id.Contains("turbo") ? new[] { 4, 8, 12 } : new[] { 20, 30, 50 }) : new[] { 12, 25, 40 };
        for (int i = 0; i < QualityBox.Items.Count; i++) ((ComboBoxItem)QualityBox.Items[i]).ToolTip = $"{steps[i]} steps";
        GenerateButton.IsEnabled = !busy && model != null;
    }

    private void VideoModeChanged(object sender, RoutedEventArgs e)
    {
        if (VideoSourcePanel == null) return;
        VideoSourcePanel.Visibility = VideoImageMode.IsChecked == true ? Visibility.Visible : Visibility.Collapsed;
        if (!workspaceReady || applyingChoice) return;
        Remember(workspace, videoWorkflow, videoModel, VideoLoras);
        videoWorkflow = VideoImageMode.IsChecked == true ? "video:image" : "video:text";
        RestoreVideoChoice(); SaveWorkspaceSafely();
    }

    private void VideoModelChanged(object sender, SelectionChangedEventArgs e)
    {
        if (!workspaceReady || applyingChoice) return;
        Remember(workspace, videoWorkflow, videoModel, VideoLoras);
        videoModel = (VideoModelBox.SelectedItem as ModelChoice)?.Id;
        var choice = workspace.Choice(videoWorkflow);
        applyingChoice = true;
        VideoLoras.Restore(loraFiles, videoModel != null && choice.LorasByModel.TryGetValue(videoModel, out var selections) ? selections : []);
        applyingChoice = false;
        UpdateVideoHint(); SaveWorkspaceSafely();
    }

    private (int Width, int Height) VideoDimensions() => VideoShapeBox.SelectedIndex switch { 1 => (512, 768), 2 => (640, 640), _ => (768, 512) };
    private void UpdateVideoHint()
    {
        if (VideoFormatHint == null) return;
        var model = VideoModelBox.SelectedItem as ModelChoice;
        VideoModelHint.Text = model?.Description ?? "No compatible model found. Refresh the Models library.";
        VideoNegativePanel.Visibility = model?.Family == "minimax" ? Visibility.Collapsed : Visibility.Visible;
        var (width, height) = VideoDimensions();
        VideoFormatHint.Text = $"{width} × {height} · 24 fps · MP4 with audio" + (model?.Family == "minimax" ? "\nDuration rounds up to MiniMax’s frame grid." : "");
        GenerateVideoButton.IsEnabled = !busy && model != null;
    }

    private async void RefreshModels(object sender, RoutedEventArgs e)
    {
        if (busy) return;
        try { SaveWorkspace(); await RefreshModelLibrary(); workspaceReady = true; SetStatus("Model and LoRA library refreshed."); }
        catch (Exception ex) { ShowError(ex); }
    }
    private void OpenLoraFolder(object sender, RoutedEventArgs e)
    {
        string path = Path.Combine(App.Root, "models", "loras"); Directory.CreateDirectory(path); OpenPath(path);
    }
    private void OpenModelSetup(object sender, RoutedEventArgs e)
    {
        if (busy) return;
        try
        {
            var start = new ProcessStartInfo("powershell.exe") { UseShellExecute = false, CreateNoWindow = true, WorkingDirectory = App.Root };
            foreach (var arg in new[] { "-NoProfile", "-ExecutionPolicy", "Bypass", "-STA", "-File", Path.Combine(App.Root, "portable", "Setup.ps1") }) start.ArgumentList.Add(arg);
            Process.Start(start)?.Dispose();
            SetStatus("Choose downloads in Setup, then refresh this library when installation finishes.");
        }
        catch (Exception ex) { ShowError(ex); }
    }
    private void UseCatalogModel(object sender, RoutedEventArgs e)
    {
        if (busy || ((FrameworkElement)sender).DataContext is not ModelChoice model) return;
        if (model.Video) { WorkspaceTabs.SelectedItem = VideoTab; VideoModelBox.SelectedItem = model; }
        else { WorkspaceTabs.SelectedItem = StudioTab; CreateMode.IsChecked = true; ImageModelBox.SelectedItem = model; }
    }

    private void SetVideoSource(string path)
    {
        VideoSourcePreview.Source = LoadBitmap(path, 200);
        videoSource = path; VideoSourceName.Text = Path.GetFileName(path); VideoSourceName.ToolTip = path;
    }
    private void ChooseVideoSource(object sender, RoutedEventArgs e)
    {
        var dialog = new OpenFileDialog { Title = "Choose the first frame", Filter = ImageFilter };
        if (dialog.ShowDialog(this) != true) return;
        try { SetVideoSource(dialog.FileName); SaveWorkspace(); } catch (Exception ex) { ShowError(ex); }
    }
    private void AnimatePreview(object sender, RoutedEventArgs e)
    {
        if (previewPath == null || busy) return;
        try { SetVideoSource(previewPath); VideoImageMode.IsChecked = true; WorkspaceTabs.SelectedItem = VideoTab; VideoPromptBox.Focus(); SaveWorkspace(); }
        catch (Exception ex) { ShowError(ex); }
    }

    private async void GenerateVideo(object sender, RoutedEventArgs e)
    {
        if (busy) return;
        try
        {
            if (jobId != null) { SetBusy(true); await engine.EnsureStarted(SetStatus); CancelButton.IsEnabled = true; await WatchJob(); return; }
            string prompt = VideoPromptBox.Text.Trim();
            if (prompt.Length == 0) { VideoPromptBox.Focus(); throw new ArgumentException("Describe the video you want before generating."); }
            var model = VideoModelBox.SelectedItem as ModelChoice ?? throw new ArgumentException("Choose an installed video model first.");
            bool animate = VideoImageMode.IsChecked == true;
            if (animate && (videoSource == null || !File.Exists(videoSource))) throw new ArgumentException("Choose an image for the first frame.");
            long seed = Random.Shared.NextInt64(0, long.MaxValue);
            if (!string.IsNullOrWhiteSpace(VideoSeedBox.Text) && (!long.TryParse(VideoSeedBox.Text, out seed) || seed < 0)) throw new ArgumentException("Use a positive whole-number seed, or leave it blank.");
            var (width, height) = VideoDimensions();
            currentVideoRequest = new(prompt, model.Family == "minimax" ? "" : VideoNegativeBox.Text.Trim(), seed, width, height, new[] { 3, 5, 10 }[VideoDurationBox.SelectedIndex], model.Id, animate ? videoSource : null, VideoLoras.Selection);
            currentRequest = null;
            SaveSettings(); cancelled = false; SetBusy(true);
            await engine.EnsureStarted(SetStatus);
            SetStatus("Preparing your video…");
            jobId = await engine.SubmitVideo(currentVideoRequest);
            await File.WriteAllTextAsync(jobPath, JsonSerializer.Serialize(new PendingJob(jobId, null, currentVideoRequest)));
            CancelButton.IsEnabled = true;
            await WatchJob();
        }
        catch (OperationCanceledException ex) when (ex is not TaskCanceledException) { CompleteJob(); SetStatus("Video generation cancelled."); }
        catch (Exception ex) { ShowError(ex); }
        finally { SetBusy(false); }
    }

    private void LoadVideoGallery()
    {
        string output = Path.Combine(App.Root, "output");
        VideoGallery.ItemsSource = new DirectoryInfo(output).EnumerateFiles("*", SearchOption.AllDirectories)
            .Where(f => ImageLibrary.IsVideo(f.FullName)).OrderByDescending(f => f.LastWriteTimeUtc).Take(40)
            .Select(f => new VideoItem(f.FullName, f.Name, $"{f.Extension.TrimStart('.').ToUpperInvariant()} · {f.Length / 1048576.0:F1} MB", MediaThumbnail.Load(f.FullName))).ToArray();
        EmptyVideoLibrary.Visibility = VideoGallery.Items.Count == 0 ? Visibility.Visible : Visibility.Collapsed;
    }
    private void VideoSelected(object sender, SelectionChangedEventArgs e)
    {
        if (VideoGallery.SelectedItem is VideoItem item) try { ShowVideo(item.Path); } catch (Exception ex) { ShowError(ex); }
    }
    private void RefreshVideos(object sender, RoutedEventArgs e) { try { LoadVideoGallery(); } catch (Exception ex) { ShowError(ex); } }
    private async void ImportVideos(object sender, RoutedEventArgs e)
    {
        var dialog = new OpenFileDialog { Title = "Import videos", Filter = "Videos|*.mp4;*.mov;*.webm;*.mkv;*.wmv", Multiselect = true };
        if (dialog.ShowDialog(this) != true) return;
        try
        {
            string folder = Path.Combine(App.Root, "output", "video", "imported"); Directory.CreateDirectory(folder);
            string? last = null;
            foreach (var source in dialog.FileNames)
            {
                string destination = Path.Combine(folder, Path.GetFileName(source));
                if (File.Exists(destination)) destination = Path.Combine(folder, Path.GetFileNameWithoutExtension(source) + "-" + Guid.NewGuid().ToString("N")[..8] + Path.GetExtension(source));
                await using var input = File.OpenRead(source);
                await using var output = new FileStream(destination, FileMode.CreateNew, FileAccess.Write);
                await input.CopyToAsync(output);
                last = destination;
            }
            LoadVideoGallery(); if (last != null) ShowVideo(last);
            SetStatus($"Imported {dialog.FileNames.Length} video(s). Original files kept.");
        }
        catch (Exception ex) { ShowError(ex); }
    }

    private void ShowVideo(string path)
    {
        if (!File.Exists(path)) throw new FileNotFoundException("This video no longer exists.", path);
        videoPreview = path; videoPlaying = false; VideoPlayButton.Content = "Play";
        VideoPlayer.Stop(); VideoPlayer.Source = new Uri(path); VideoPlayer.Play();
        VideoPlayButton.IsEnabled = VideoSeek.IsEnabled = false;
        VideoOpenButton.IsEnabled = VideoSaveButton.IsEnabled = true;
        VideoDeleteButton.IsEnabled = !busy && ImageLibrary.CanRecycle(Path.Combine(App.Root, "output"), path);
        EmptyVideo.Visibility = Visibility.Collapsed;
        VideoInfo.Text = "Loading clip…";
    }
    private void VideoOpened(object sender, RoutedEventArgs e)
    {
        VideoPlayer.Pause(); videoPlaying = false;
        VideoPlayButton.IsEnabled = true;
        if (VideoPlayer.NaturalDuration.HasTimeSpan)
        {
            updatingSeek = true; VideoSeek.Maximum = VideoPlayer.NaturalDuration.TimeSpan.TotalSeconds; VideoSeek.Value = 0; updatingSeek = false;
            VideoSeek.IsEnabled = true; VideoInfo.Text = $"{VideoPlayer.NaturalVideoWidth} × {VideoPlayer.NaturalVideoHeight} · {VideoPlayer.NaturalDuration.TimeSpan:mm\\:ss}";
        }
    }
    private void ToggleVideo(object sender, RoutedEventArgs e)
    {
        if (videoPlaying) { VideoPlayer.Pause(); videoTimer.Stop(); }
        else { VideoPlayer.Play(); videoTimer.Start(); }
        videoPlaying = !videoPlaying; VideoPlayButton.Content = videoPlaying ? "Pause" : "Play";
    }
    private void VideoEnded(object sender, RoutedEventArgs e)
    {
        VideoPlayer.Pause(); VideoPlayer.Position = TimeSpan.Zero; videoPlaying = false; VideoPlayButton.Content = "Play"; videoTimer.Stop();
    }
    private void VideoFailed(object sender, ExceptionRoutedEventArgs e)
    {
        videoPlaying = false; videoTimer.Stop(); VideoPlayButton.IsEnabled = VideoSeek.IsEnabled = false;
        VideoInfo.Text = "Preview unavailable · Use Open to play externally";
        SetStatus("Windows could not preview this codec. Use Open to play the clip in your default video player.");
    }
    private void SeekVideo(object sender, RoutedPropertyChangedEventArgs<double> e)
    {
        if (!updatingSeek && VideoPlayer.NaturalDuration.HasTimeSpan) VideoPlayer.Position = TimeSpan.FromSeconds(e.NewValue);
    }
    private void WorkspaceChanged(object sender, SelectionChangedEventArgs e)
    {
        if (e.Source != WorkspaceTabs || VideoPlayer == null) return;
        if (!VideoTab.IsSelected) { VideoPlayer.Pause(); videoTimer.Stop(); videoPlaying = false; VideoPlayButton.Content = "Play"; }
    }
    private void OpenVideo(object sender, RoutedEventArgs e) { if (videoPreview != null) OpenPath(videoPreview); }
    private void SaveVideoAs(object sender, RoutedEventArgs e)
    {
        if (videoPreview == null) return;
        string extension = Path.GetExtension(videoPreview);
        var dialog = new SaveFileDialog { Title = "Save video as", FileName = Path.GetFileName(videoPreview), Filter = $"Video|*{extension}", DefaultExt = extension };
        if (dialog.ShowDialog(this) != true) return;
        try { if (!Path.GetFullPath(dialog.FileName).Equals(Path.GetFullPath(videoPreview), StringComparison.OrdinalIgnoreCase)) File.Copy(videoPreview, dialog.FileName, true); SetStatus("Saved to " + dialog.FileName); }
        catch (Exception ex) { ShowError(ex); }
    }
}
