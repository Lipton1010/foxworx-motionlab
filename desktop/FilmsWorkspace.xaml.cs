using System.IO;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media.Imaging;
using Microsoft.Win32;
using System.Windows.Threading;

namespace ImageStudio;

public partial class FilmsWorkspace : UserControl
{
    private readonly ProductionClient client = new();
    private JsonNode? document;
    private bool refreshing, loading;
    private readonly HashSet<string> commands = [];
    private readonly HashSet<string> dirty = [];
    private Dictionary<string, Dictionary<string, string>> drafts = [];
    private static readonly string[] PlanFields = ["FilmTitle", "Brief", "Decisions", "Unresolved"];
    private static readonly string[] ShotFields = ["ShotName", "Purpose", "ActionText", "CameraText", "StartState", "EndState", "Dialogue", "ShotPrompt", "EditFrames", "GenerationFrames"];
    private readonly string draftsPath = Path.Combine(App.Root, "user", "film-editor-drafts.json");
    private readonly DispatcherTimer draftTimer = new() { Interval = TimeSpan.FromMilliseconds(500) };
    private readonly DispatcherTimer playbackTimer = new() { Interval = TimeSpan.FromMilliseconds(100) };
    private bool updatingFilmSeek;
    private long previewSerial;
    private long comparisonSerial;
    private long? previewFrames;
    private string? previewRate;
    private double? previewSeconds;
    private readonly Dictionary<string, JsonNode> previewMetadata = [];
    private string? selectedShot;
    private JsonNode? proposed;
    private JsonNode? reviewState;
    private bool driving;
    private CancellationTokenSource? renderWait;
    private readonly DispatcherTimer queueTimer = new() { Interval = TimeSpan.FromSeconds(3) };
    public event Action<string>? KeyframeRequested;
    private readonly string viewPath = Path.Combine(App.Root, "user", "film-view.json");
    private record Row(string Id, string Label, JsonNode Node);
    private record ProjectRow(string Id, string Title);
    public FilmsWorkspace()
    {
        InitializeComponent();
        SizeChanged += (_, _) => ReflowInspector();
        Loaded += (_, _) => ReflowInspector();
        try { if (File.Exists(draftsPath)) drafts = JsonSerializer.Deserialize<Dictionary<string, Dictionary<string, string>>>(File.ReadAllText(draftsPath)) ?? []; }
        catch (Exception ex) when (ex is IOException or JsonException) { Status.Text = "Editor drafts could not load: " + ex.Message; }
        foreach (var name in PlanFields.Concat(ShotFields))
            ((TextBox)FindName(name)).TextChanged += (_, _) => { if (!refreshing) { dirty.Add(name); draftTimer.Stop(); draftTimer.Start(); } };
        draftTimer.Tick += (_, _) => { draftTimer.Stop(); CaptureDraft(); };
        playbackTimer.Tick += (_, _) =>
        {
            if (!Player.NaturalDuration.HasTimeSpan || !TryFrameRate(out double rate)) return;
            updatingFilmSeek = true;
            FilmSeek.Maximum = LastPreviewFrame(rate);
            FilmSeek.Value = Player.Position.TotalSeconds * rate; updatingFilmSeek = false;
            Playhead.Text = "Frame " + Math.Round(FilmSeek.Value) + " / " + Math.Round(FilmSeek.Maximum);
        };
        Player.MediaOpened += (_, _) => { if (Player.NaturalDuration.HasTimeSpan && TryFrameRate(out double rate)) { FilmSeek.Maximum = LastPreviewFrame(rate); FilmSeek.IsEnabled = FilmSeek.Maximum > 0; playbackTimer.Start(); } };
        Player.MediaFailed += (_, e) => Status.Text = "Preview could not open this media: " + e.ErrorException.Message;
        ComparePlayer.MediaFailed += (_, e) => Status.Text = "Comparison could not open this media: " + e.ErrorException.Message;
        queueTimer.Tick += async (_, _) => await DriveQueue();
        Loaded += (_, _) => queueTimer.Start();
        Loaded += async (_, _) =>
        {
            if (document != null || loading) return;
            loading = true;
            try
            {
                await ListProjects();
                if (File.Exists(viewPath))
                {
                    var saved = JsonNode.Parse(await File.ReadAllTextAsync(viewPath));
                    if (Projects.Items.OfType<ProjectRow>().FirstOrDefault(p => p.Id == (string?)saved?["project"]) is { } row)
                    {
                        document = await client.Call("open", project: row.Id);
                        selectedShot = (string?)saved?["shot"];
                        Refresh();
                        Stages.SelectedIndex = Math.Clamp((int?)saved?["stage"] ?? 0, 0, 5);
                    }
                }
                var required = await client.Call("requirements", project: document?["id"]?.GetValue<string>());
                ReviewDetails.Text = string.Join("\n\n", required.AsObject().Select(r => r.Key + ": " + Text(r.Value?["outcome"]) + "\nInspect: " + string.Join(", ", r.Value!["modalities"]!.AsArray().Select(Text)) + "\nStatus: unverified"));
            }
            catch (Exception ex) { Status.Text = ex.Message; }
            finally { loading = false; }
        };
        Unloaded += (_, _) => { previewSerial++; comparisonSerial++; CaptureDraft(); draftTimer.Stop(); queueTimer.Stop(); playbackTimer.Stop(); Player.Stop(); Player.Close(); ComparePlayer.Close(); };
    }
    private async Task Run(Func<Task> action, [System.Runtime.CompilerServices.CallerMemberName] string command = "")
    {
        if (!commands.Add(command)) { Status.Text = "This action is already in progress. Other planning actions remain available."; return; }
        try { await action(); }
        catch (Exception ex) { Status.Text = ex.Message; }
        finally { commands.Remove(command); }
    }
    private void ReflowInspector()
    {
        bool wide = ActualWidth >= 1100;
        if (wide && WideInspectorHost.Content == null)
        {
            PlanInspectorHost.Content = null; WideInspectorHost.Content = ShotEditor;
        }
        else if (!wide && PlanInspectorHost.Content == null)
        {
            WideInspectorHost.Content = null; PlanInspectorHost.Content = ShotEditor;
        }
        InspectorBorder.Visibility = wide ? Visibility.Visible : Visibility.Collapsed;
        InspectorGap.Width = new GridLength(wide ? 12 : 0); InspectorColumn.Width = new GridLength(wide ? 300 : 0);
    }
    private string ProjectId => document?["id"]?.GetValue<string>() ?? throw new IOException("Create or open a film first.");
    private string Revision => document?["revision"]?.GetValue<string>() ?? throw new IOException("Open a film first.");
    private string ShotId => selectedShot ?? throw new IOException("Select a shot first.");
    private static string Text(JsonNode? value) => value?.ToString() ?? "";
    private static int Number(TextBox box) => int.TryParse(box.Text, out int value) ? value : throw new IOException("Enter a whole number in " + box.Name + ".");
    private static string Choice(ComboBox box) => (box.SelectedItem as ComboBoxItem)?.Content?.ToString() ?? "";
    private JsonNode? Shot => document?["shots"]?.AsArray().FirstOrDefault(s => Text(s?["id"]) == selectedShot);
    private static Row[] Rows(JsonNode? nodes, Func<JsonNode, string> label) => nodes?.AsArray().Where(n => n != null).Select(n => new Row(Text(n!["id"]), label(n!), n!)).ToArray() ?? [];

    private async Task ListProjects()
    {
        var rows = await client.Call("list");
        refreshing = true;
        Projects.ItemsSource = rows.AsArray().Select(n => new ProjectRow(Text(n?["id"]), Text(n?["title"]))).ToArray();
        refreshing = false;
    }
    private async Task Apply(string operation, object? payload = null, TimeSpan? timeout = null)
    {
        var result = await client.Call(operation, payload, ProjectId, Revision, timeout: timeout);
        if (operation == "plan") { drafts.Remove(ProjectId + ":plan"); foreach (var name in PlanFields) dirty.Remove(name); }
        if (operation == "shot-update") { drafts.Remove(ProjectId + ":" + selectedShot); foreach (var name in ShotFields) dirty.Remove(name); }
        if (result["project"] is { } updated && ((int?)document?["serial"] ?? -1) <= ((int?)updated["serial"] ?? 0)) document = updated;
        Refresh();
        Status.Text = result["status"] != null ? Text(result["status"]) : operation.StartsWith("render-") ? "Encoded draft saved and fully decoded. Creative review remains required." : "Saved · " + operation;
    }
    private void Refresh()
    {
        if (document == null) return;
        CaptureDraft();
        refreshing = true;
        FilmTitle.Text = Text(document["title"]); Brief.Text = Text(document["brief"]);
        Decisions.Text = string.Join(Environment.NewLine, document["decisions"]!.AsArray().Select(Text));
        Unresolved.Text = string.Join(Environment.NewLine, document["unresolved"]!.AsArray().Select(Text));
        RestoreDraft("plan");
        selectedShot ??= (string?)document["selected_shot"];
        Shots.ItemsSource = Rows(document["shots"], n => Text(n["name"]) + " · " + Text(n["edit_frames"]) + "f");
        Shots.SelectedItem = Shots.Items.OfType<Row>().FirstOrDefault(r => r.Id == selectedShot);
        SceneBox.ItemsSource = document["scenes"]!.AsArray().Select(s => new ProjectRow(Text(s?["id"]), Text(s?["name"]))).ToArray();
        var assets = Rows(document["assets"], n => Text(n["role"]) + " · " + Text(n["name"]));
        Assets.ItemsSource = assets;
        TakeBox.ItemsSource = assets.Where(r => Text(r.Node["role"]) == "take").ToArray();
        CompareTake.ItemsSource = assets.Where(r => Text(r.Node["role"]) == "take").ToArray();
        AudioAsset.ItemsSource = assets.Where(r => new[] { "dialogue", "music", "effects" }.Contains(Text(r.Node["role"]))).ToArray();
        TranscriptAudio.ItemsSource = assets.Where(r => new[] { "dialogue", "music", "effects", "take" }.Contains(Text(r.Node["role"]))).ToArray();
        Timeline.ItemsSource = Rows(document["edit"]?["segments"], n => (n["asset"] == null ? "GAP" : AssetName(Text(n["asset"]))) + " [" + Text(n["in_frame"]) + ", " + Text(n["out_frame"]) + ")");
        AudioCues.ItemsSource = Rows(document["edit"]?["audio"], n => Text(n["track"]) + " · " + AssetName(Text(n["asset"])) + " @ sample " + Text(n["start_sample"]));
        Markers.ItemsSource = Rows(document["edit"]?["markers"], n => Text(n["text"]) + " @ frame " + Text(n["frame"]));
        Cuts.ItemsSource = document["cuts"]!.AsArray().Select((n, i) => new Row(i.ToString(), Text(n?["label"]) + " · " + Path.GetFileName(Text(n?["path"])), n!)).ToArray();
        QueueItems.ItemsSource = Rows(document["queue"], n => Text(n["item"]?["name"]) + " · " + Text(n["status"]));
        StoryboardStatus.Text = document["animatic_current"]!.GetValue<bool>() ? "Current plan / animatic approval recorded." : "Animatic approval is missing or outdated.";
        Capabilities.Text = "Text / first frame use the shared graph builder. Motion pilot, conditioning modes and persistent AV finishing require runtime validation before production admission.";
        var queue = document["queue"]!.AsArray();
        Status.Text = (document["paused"]!.GetValue<bool>() ? "Queue paused" : "Queue ready") + " · " + queue.Count + " durable items · " + document["outdated_shots"]!.AsArray().Count + " outdated selections";
        refreshing = false;
        FillShot();
    }
    private string AssetName(string id) => Text(document?["assets"]?.AsArray().FirstOrDefault(a => Text(a?["id"]) == id)?["name"]);
    private string AssetPath(JsonNode asset) => Path.Combine(App.Root, "user", "films", ProjectId, Text(asset["path"]));
    private void FillShot()
    {
        if (Shot is not { } shot) return;
        bool previousRefresh = refreshing;
        refreshing = true;
        try
        {
        ShotName.Text = Text(shot["name"]); Purpose.Text = Text(shot["purpose"]); ActionText.Text = Text(shot["action"]);
        CameraText.Text = Text(shot["camera"]); StartState.Text = Text(shot["start_state"]); EndState.Text = Text(shot["end_state"]);
        Dialogue.Text = Text(shot["dialogue"]); ShotPrompt.Text = Text(shot["prompt"]); EditFrames.Text = Text(shot["edit_frames"]);
        GenerationFrames.Text = Text(shot["generation_frames"]); SceneBox.SelectedValue = Text(shot["scene"]);
        GenerationMode.SelectedItem = GenerationMode.Items.OfType<ComboBoxItem>().FirstOrDefault(i => Text(shot["mode"]) == Text(JsonValue.Create(i.Content.ToString())));
        Keyframe.Source = null;
        var key = shot["references"]!.AsArray().FirstOrDefault(r => Text(r?["role"]) == "keyframe");
        var asset = document?["assets"]?.AsArray().FirstOrDefault(a => Text(a?["id"]) == Text(key?["asset"]));
        if (asset != null)
        {
            try
            {
                var image = new BitmapImage(); image.BeginInit(); image.CacheOption = BitmapCacheOption.OnLoad;
                image.DecodePixelWidth = 700; image.UriSource = new Uri(AssetPath(asset)); image.EndInit(); image.Freeze();
                Keyframe.Source = image;
            }
            catch (Exception ex) { StoryboardStatus.Text = "Keyframe unavailable: " + ex.Message; }
        }
        RestoreDraft(ShotId);
        }
        finally { refreshing = previousRefresh; }
    }
    private async void NewProject(object sender, RoutedEventArgs e) => await Run(async () =>
    {
        CaptureDraft();
        document = await client.Call("create", new { title = NewTitle.Text }); selectedShot = null; dirty.Clear();
        await ListProjects(); Refresh(); PersistView();
    });
    private async void OpenProject(object sender, SelectionChangedEventArgs e)
    {
        if (refreshing || Projects.SelectedItem is not ProjectRow row) return;
        try
        {
            var opened = await client.Call("open", project: row.Id);
            if ((Projects.SelectedItem as ProjectRow)?.Id != row.Id) return;
            CaptureDraft(); document = opened; dirty.Clear(); selectedShot = (string?)document["selected_shot"]; Refresh(); PersistView();
        }
        catch (Exception ex) { Status.Text = ex.Message; }
    }
    private async void ReloadProject(object sender, RoutedEventArgs e) => await Run(async () =>
    {
        string? id = (string?)document?["id"];
        await ListProjects();
        if (id != null) { document = await client.Call("open", project: id); Refresh(); }
    });
    private async void AddShot(object sender, RoutedEventArgs e) => await Run(async () => { await Apply("shot-add"); CaptureDraft(); foreach (var name in ShotFields) dirty.Remove(name); selectedShot = (string?)document?["selected_shot"]; Refresh(); });
    private async void AddScene(object sender, RoutedEventArgs e) => await Run(() => Apply("scene-add", new { name = "Scene " + ((document?["scenes"]?.AsArray().Count ?? 0) + 1) }));
    private async void DuplicateShot(object sender, RoutedEventArgs e) => await Run(async () => { await Apply("shot-duplicate", new { shot = ShotId }); CaptureDraft(); foreach (var name in ShotFields) dirty.Remove(name); selectedShot = (string?)document?["selected_shot"]; Refresh(); });
    private void SelectShot(object sender, SelectionChangedEventArgs e)
    {
        if (refreshing || Shots.SelectedItem is not Row row) return;
        CaptureDraft(); foreach (var name in ShotFields) dirty.Remove(name);
        selectedShot = row.Id; FillShot(); PersistView();
    }
    private void StageChanged(object sender, SelectionChangedEventArgs e) { if (!refreshing && e.Source == Stages && document != null) PersistView(); }
    private void PersistView()
    {
        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(viewPath)!);
            File.WriteAllText(viewPath, JsonSerializer.Serialize(new { project = ProjectId, stage = Stages.SelectedIndex, shot = selectedShot }));
        }
        catch (IOException ex) { Status.Text = "View preference could not be saved: " + ex.Message; }
    }
    private void CaptureDraft()
    {
        if (document == null || refreshing) return;
        foreach (var (key, fields) in new[] { ("plan", PlanFields), (selectedShot ?? "none", ShotFields) })
        {
            var changed = fields.Where(dirty.Contains).ToArray();
            if (changed.Length == 0) continue;
            var name = ProjectId + ":" + key;
            if (!drafts.TryGetValue(name, out var saved)) drafts[name] = saved = [];
            foreach (var field in changed) saved[field] = ((TextBox)FindName(field)).Text;
        }
        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(draftsPath)!);
            File.WriteAllText(draftsPath + ".tmp", JsonSerializer.Serialize(drafts)); File.Move(draftsPath + ".tmp", draftsPath, true);
        }
        catch (IOException ex) { Status.Text = "Local draft could not save: " + ex.Message; }
    }
    private void RestoreDraft(string key)
    {
        if (!drafts.TryGetValue(ProjectId + ":" + key, out var saved)) return;
        foreach (var (name, text) in saved)
            if (PlanFields.Contains(name) || ShotFields.Contains(name)) { ((TextBox)FindName(name)).Text = text; dirty.Add(name); }
    }
    private async Task ReorderShot(int delta)
    {
        var ids = document!["shots"]!.AsArray().Select(s => Text(s?["id"])).ToList();
        int index = ids.IndexOf(ShotId), target = Math.Clamp(index + delta, 0, ids.Count - 1);
        (ids[index], ids[target]) = (ids[target], ids[index]); await Apply("shots-reorder", new { ids });
    }
    private async void ShotUp(object s, RoutedEventArgs e) => await Run(() => ReorderShot(-1));
    private async void ShotDown(object s, RoutedEventArgs e) => await Run(() => ReorderShot(1));
    private async void SavePlan(object s, RoutedEventArgs e) => await Run(() => Apply("plan", new { title = FilmTitle.Text, brief = Brief.Text, decisions = Decisions.Text.Split('\n', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries), unresolved = Unresolved.Text.Split('\n', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries) }));
    private async void SaveShot(object s, RoutedEventArgs e) => await Run(() => Apply("shot-update", new { shot = ShotId, changes = new { name = ShotName.Text, scene = (string?)SceneBox.SelectedValue ?? Text(Shot?["scene"]), purpose = Purpose.Text, action = ActionText.Text, camera = CameraText.Text, start_state = StartState.Text, end_state = EndState.Text, dialogue = Dialogue.Text, prompt = ShotPrompt.Text, edit_frames = Number(EditFrames), generation_frames = Number(GenerationFrames), mode = Choice(GenerationMode) } }));
    public async Task<string> Import(string path, string role)
    {
        await Run(() => Apply("asset-import", new { path, role, shot = selectedShot }));
        return Status.Text;
    }
    private async Task PickAsset(string role)
    {
        _ = ProjectId;
        var dialog = new OpenFileDialog { Title = "Import " + role + " into this film", Filter = "Media|*.png;*.jpg;*.jpeg;*.webp;*.mp4;*.mov;*.mkv;*.wav;*.mp3;*.flac;*.m4a|All files|*.*" };
        if (dialog.ShowDialog(Window.GetWindow(this)) == true) await Apply("asset-import", new { path = dialog.FileName, role, shot = selectedShot });
    }
    private async void ImportAsset(object s, RoutedEventArgs e) => await Run(() => PickAsset(Choice(AssetRole)));
    private async void ImportKeyframe(object s, RoutedEventArgs e) => await Run(() => PickAsset("keyframe"));
    private async void ImportTake(object s, RoutedEventArgs e) => await Run(() => PickAsset("take"));
    private void AssetSelected(object s, SelectionChangedEventArgs e)
    {
        if (Assets.SelectedItem is Row row) AssetDetails.Text = row.Node.ToJsonString(new JsonSerializerOptions { WriteIndented = true });
    }
    private async void PreviewAsset(object s, RoutedEventArgs e)
    {
        if (Assets.SelectedItem is Row row) await PreviewPath(AssetPath(row.Node));
    }
    private async Task PreviewPath(string path)
    {
        long serial = ++previewSerial;
        ComparePlayer.Close(); ComparePlayer.Visibility = Visibility.Collapsed; Grid.SetColumnSpan(Player, 2);
        Player.Close(); playbackTimer.Stop(); Player.Visibility = Visibility.Collapsed; FilmSeek.IsEnabled = false;
        updatingFilmSeek = true; FilmSeek.Value = 0; FilmSeek.Maximum = 0; updatingFilmSeek = false;
        previewFrames = null; previewRate = null; previewSeconds = null;
        try
        {
            string fullPath = Path.GetFullPath(path);
            var cut = document?["cuts"]?.AsArray().FirstOrDefault(c => string.Equals(Path.GetFullPath(Text(c?["path"])), fullPath, StringComparison.OrdinalIgnoreCase));
            if (cut == null)
            {
                var candidate = new[] { document?["candidate"], document?["pilot_candidate"] }.FirstOrDefault(c => !string.IsNullOrEmpty(Text(c?["artifact"]?["path"])) && string.Equals(Path.GetFullPath(Text(c?["artifact"]?["path"])), fullPath, StringComparison.OrdinalIgnoreCase));
                if (candidate != null) cut = document?["cuts"]?.AsArray().FirstOrDefault(c => Text(c?["sha256"]) == Text(candidate["artifact"]?["sha256"]));
            }
            if (cut != null) { previewFrames = (long?)cut["timeline"]?["frames"]; previewRate = Text(cut["timeline"]?["fps"]); }
            var asset = document?["assets"]?.AsArray().FirstOrDefault(a => string.Equals(Path.GetFullPath(AssetPath(a!)), fullPath, StringComparison.OrdinalIgnoreCase));
            if (asset != null)
            {
                string hash = Text(asset["sha256"]);
                if (!previewMetadata.TryGetValue(hash, out var metadata))
                {
                    metadata = await client.Call("media-inspect", new { asset = Text(asset["id"]), metadata_only = true }, ProjectId);
                    previewMetadata[hash] = metadata;
                }
                if (serial != previewSerial) return;
                previewFrames = (long?)metadata["frames"]; previewRate = (string?)metadata["frame_rate"]; previewSeconds = (double?)metadata["duration"];
            }
            if (serial != previewSerial) return;
            Player.Source = new Uri(fullPath); Player.Position = TimeSpan.Zero; Player.Visibility = Visibility.Visible; Player.Play();
        }
        catch (Exception ex) when (ex is IOException or ArgumentException or JsonException or InvalidOperationException)
        { if (serial == previewSerial) Status.Text = "Preview could not open: " + ex.Message; }
    }
    private double LastPreviewFrame(double rate) => previewFrames is long frames ? Math.Max(0, frames - 1) : Math.Max(0, Math.Round((previewSeconds ?? Player.NaturalDuration.TimeSpan.TotalSeconds) * rate)-1);
    private void Play(object s, RoutedEventArgs e) { Player.Play(); if (ComparePlayer.Visibility == Visibility.Visible) ComparePlayer.Play(); }
    private void PausePlayer(object s, RoutedEventArgs e) { Player.Pause(); ComparePlayer.Pause(); }
    private void StopPlayer(object s, RoutedEventArgs e) { Player.Stop(); ComparePlayer.Stop(); }
    private void SeekFilm(object s, RoutedPropertyChangedEventArgs<double> e)
    {
        if (updatingFilmSeek || !TryFrameRate(out double rate)) return;
        var position = TimeSpan.FromSeconds(Math.Round(e.NewValue) / rate);
        Player.Position = position;
        if (ComparePlayer.Visibility == Visibility.Visible) ComparePlayer.Position = position;
    }
    private bool TryFrameRate(out double rate)
    {
        var parts = (previewRate ?? (document == null ? "24" : Text(document["edit"]?["fps"]))).Split('/');
        var culture = System.Globalization.CultureInfo.InvariantCulture;
        double denominator = 1; rate = 0;
        if (parts.Length is < 1 or > 2 || !double.TryParse(parts[0], culture, out double numerator)
            || parts.Length == 2 && !double.TryParse(parts[1], culture, out denominator)
            || denominator <= 0 || !double.IsFinite(rate = numerator / denominator) || rate <= 0 || rate > 120)
        { Status.Text = "The saved edit has an invalid frame rate. Reload a valid project before frame seeking."; return false; }
        return true;
    }
    private async void CompareTakes(object s, RoutedEventArgs e)
    {
        if (TakeBox.SelectedItem is not Row first || CompareTake.SelectedItem is not Row second) { Status.Text = "Choose two explicit takes to compare."; return; }
        long comparison = ++comparisonSerial, expectedPreview = previewSerial + 1;
        await PreviewPath(AssetPath(first.Node));
        if (comparison != comparisonSerial || previewSerial != expectedPreview || Player.Visibility != Visibility.Visible) return;
        Grid.SetColumnSpan(Player, 1);
        ComparePlayer.Source = new Uri(AssetPath(second.Node)); ComparePlayer.Position = TimeSpan.Zero; ComparePlayer.Volume = 0;
        ComparePlayer.Visibility = Visibility.Visible; ComparePlayer.Play();
        Status.Text = "Two selected takes share the scrub position. Comparison B is muted; inspect each take's sound separately. Playback synchronization is approximate.";
    }
    private void CloseComparison(object s, RoutedEventArgs e) { comparisonSerial++; ComparePlayer.Close(); ComparePlayer.Visibility = Visibility.Collapsed; Grid.SetColumnSpan(Player, 2); }
    private async Task Render(string operation)
    {
        if (renderWait != null) { Status.Text = "A draft render is already running."; return; }
        renderWait = new CancellationTokenSource();
        try
        {
            Status.Text = "Rendering an immutable draft. You can continue editing; changed edits will require a new cut.";
            var result = await client.Call(operation, project: ProjectId, revision: Revision, timeout: TimeSpan.FromMinutes(65), cancellationToken: renderWait.Token);
            var updated = result["project"];
            if ((int?)updated?["serial"] >= (int?)document?["serial"]) document = updated;
            Cuts.ItemsSource = document!["cuts"]!.AsArray().Select((n, i) => new Row(i.ToString(), Text(n?["label"]) + " · " + Path.GetFileName(Text(n?["path"])), n!)).ToArray();
            Status.Text = "Draft encoded and fully decoded. No delivery approval was issued.";
        }
        catch (Exception ex) { Status.Text = ex.Message; }
        finally { renderWait.Dispose(); renderWait = null; }
    }
    private void CancelDraft(object s, RoutedEventArgs e) => renderWait?.Cancel();
    private async void RenderAnimatic(object s, RoutedEventArgs e) => await Render("render-animatic");
    private async void RenderDraft(object s, RoutedEventArgs e) => await Render("render-draft");
    private async void ApproveAnimatic(object s, RoutedEventArgs e) => await Run(async () =>
    {
        if (dirty.Count > 0) throw new IOException("Save the film and shot drafts before approving the current animatic revision.");
        await Apply("approve-animatic", new { reviewer = Reviewer.Text, finding = AnimaticFinding.Text });
    });
    private async void SelectTake(object s, RoutedEventArgs e) => await Run(() => Apply("select", new { shot = ShotId, asset = (TakeBox.SelectedItem as Row)?.Id ?? throw new IOException("Choose a take."), in_frame = Number(TakeIn), out_frame = Number(TakeOut), reason = TakeReason.Text }));
    private async void AddTakeToEdit(object s, RoutedEventArgs e) => await Run(async () =>
    {
        var selection = document?["selections"]?[ShotId] ?? throw new IOException("Select a take and range first.");
        await Apply("segment-insert", new { segment = new { shot = ShotId, asset = Text(selection["asset"]), in_frame = selection["in_frame"]!.GetValue<int>(), out_frame = selection["out_frame"]!.GetValue<int>() } });
    });
    private string SegmentId => (Timeline.SelectedItem as Row)?.Id ?? throw new IOException("Select a picture segment.");
    private void SelectSegment(object s, SelectionChangedEventArgs e)
    {
        if (Timeline.SelectedItem is not Row row) return;
        TrimIn.Text = Text(row.Node["in_frame"]); TrimOut.Text = Text(row.Node["out_frame"]);
        FadeIn.Text = Text(row.Node["fade_in"] ?? JsonValue.Create(0)); FadeOut.Text = Text(row.Node["fade_out"] ?? JsonValue.Create(0));
    }
    private async void TrimSegment(object s, RoutedEventArgs e) => await Run(() => Apply("segment-update", new { segment = SegmentId, changes = new { in_frame = Number(TrimIn), out_frame = Number(TrimOut), fade_in = Number(FadeIn), fade_out = Number(FadeOut) } }));
    private async void SplitSegment(object s, RoutedEventArgs e) => await Run(() => Apply("segment-split", new { segment = SegmentId, source_frame = Number(SplitFrame) }));
    private async void RemoveSegment(object s, RoutedEventArgs e) => await Run(() => Apply("segment-remove", new { segment = SegmentId, ripple = true }));
    private async void GapSegment(object s, RoutedEventArgs e) => await Run(() => Apply("segment-remove", new { segment = SegmentId, ripple = false }));
    private async void SegmentUp(object s, RoutedEventArgs e) => await Run(() => Apply("segment-move", new { segment = SegmentId, index = Math.Max(0, Timeline.SelectedIndex - 1) }));
    private async void SegmentDown(object s, RoutedEventArgs e) => await Run(() => Apply("segment-move", new { segment = SegmentId, index = Timeline.SelectedIndex + 1 }));
    private async void Undo(object s, RoutedEventArgs e) => await Run(() => Apply("undo"));
    private async void Redo(object s, RoutedEventArgs e) => await Run(() => Apply("redo"));
    private async void AddAudio(object s, RoutedEventArgs e) => await Run(() => Apply("audio-add", new { item = new { asset = (AudioAsset.SelectedItem as Row)?.Id ?? throw new IOException("Import and select audio first."), track = Choice(AudioTrack), start_sample = Number(CueStart), in_sample = Number(CueIn), samples = Number(CueSamples), volume = double.Parse(CueVolume.Text, System.Globalization.CultureInfo.InvariantCulture), mute = CueMute.IsChecked == true } }));
    private async void AddTitle(object s, RoutedEventArgs e) => await Run(() => Apply("title-add", new { item = new { text = TitleText.Text, start_frame = Number(TrimIn), end_frame = Number(TrimOut) } }));
    private async void AddMarker(object s, RoutedEventArgs e) => await Run(() => Apply("marker-add", new { item = new { text = TitleText.Text, frame = Number(SplitFrame) } }));
    private async void CutSelected(object s, SelectionChangedEventArgs e)
    {
        if (Cuts.SelectedItem is not Row row) return;
        CutDetails.Text = Text(row.Node["label"]) + "\nSHA-256 " + Text(row.Node["sha256"]);
        await PreviewPath(Text(row.Node["path"]));
    }
    private async void PauseQueue(object s, RoutedEventArgs e) => await Run(() => Apply("pause", new { paused = true }));
    private async void ResumeQueue(object s, RoutedEventArgs e) => await Run(() => Apply("pause", new { paused = false }));
    private async void DriveOne(object s, RoutedEventArgs e) => await DriveQueue(force: true);
    private async Task DriveQueue(bool force = false)
    {
        if (driving || document == null || !IsLoaded) return;
        var queue = document["queue"]!.AsArray();
        bool pending = queue.Any(q => Text(q?["status"]) is "admitted" or "pending" or "unknown_submission" or "lost");
        if (!force && !pending && (document["paused"]!.GetValue<bool>() || !queue.Any(q => Text(q?["status"]) == "queued"))) return;
        driving = true;
        try
        {
            var result = await client.Call("drive-one", project: ProjectId, revision: Revision, timeout: TimeSpan.FromMinutes(5));
            if (result["project"] is { } updated && (int?)updated["serial"] >= (int?)document["serial"])
            {
                document = updated;
                QueueItems.ItemsSource = Rows(updated["queue"], n => Text(n["item"]?["name"]) + " · " + Text(n["status"]));
            }
            Status.Text = "Queue · " + Text(result["state"]?["status"] ?? result["status"]);
        }
        catch (Exception ex) { Status.Text = ex.Message; }
        finally { driving = false; }
    }
    private async void RecordAuthority(object s, RoutedEventArgs e) => await Run(async () =>
    {
        _ = ProjectId;
        if (dirty.Count > 0) throw new IOException("Save the film and shot drafts before recording their production authority.");
        var dialog = new OpenFileDialog { Title = "Select the approved direction source", Filter = "Documents|*.md;*.txt;*.json;*.pdf|All files|*.*" };
        if (dialog.ShowDialog(Window.GetWindow(this)) == true) await Apply("direction-record", new { authority = dialog.FileName });
    });
    private async void CollectProject(object s, RoutedEventArgs e) => await Run(async () =>
    {
        var dialog = new OpenFolderDialog { Title = "Select parent for a new collected project folder" };
        if (dialog.ShowDialog(Window.GetWindow(this)) != true) return;
        var destination = Path.Combine(dialog.FolderName, "Film-" + ProjectId + "-" + DateTime.Now.ToString("yyyyMMdd-HHmmss"));
        var result = await client.Call("collect", new { destination }, ProjectId, Revision, timeout: TimeSpan.FromMinutes(65));
        Status.Text = "Hash-verified collection saved: " + Text(result["path"]) + ". Historical approvals need current-context validation after relocation.";
    });
    private async void ImportCollection(object s, RoutedEventArgs e) => await Run(async () =>
    {
        var dialog = new OpenFileDialog { Title = "Import a hash-verified collected film", Filter = "Collection manifest|collection.json" };
        if (dialog.ShowDialog(Window.GetWindow(this)) != true) return;
        CaptureDraft();
        document = await client.Call("import-collection", new { manifest = dialog.FileName }, timeout: TimeSpan.FromMinutes(65));
        dirty.Clear(); selectedShot = (string?)document["selected_shot"]; await ListProjects(); Refresh(); PersistView();
        Status.Text = "Managed project imported with its stable identity. Historical receipts and failed judgments were retained; record current authority before new production.";
    });
    private async void PromoteCut(object s, RoutedEventArgs e) => await Run(async () =>
    {
        if (dirty.Count > 0) throw new IOException("Save the film and shot drafts before promoting the current intended final.");
        if (Cuts.SelectedItem is not Row row) throw new IOException("Select a complete current draft cut.");
        var task = await client.Call("task-open", project: ProjectId);
        await Apply("promote", new { sha256 = Text(row.Node["sha256"]), task_sha256 = Text(task["task_sha256"]) });
    });
    public void SetModels(IEnumerable<ModelChoice> models) => FilmModel.ItemsSource = models.Where(m => m.Ready && m.Family == "minimax").ToArray();
    private void CreateKeyframe(object s, RoutedEventArgs e)
    {
        if (Shot != null) KeyframeRequested?.Invoke(Text(Shot["prompt"]));
    }
    private async void PreparePreview(object s, RoutedEventArgs e) => await Run(async () =>
    {
        var model = FilmModel.SelectedItem as ModelChoice ?? throw new IOException("Refresh Models & LoRAs, then choose the verified installed H3 model.");
        if (dirty.Overlaps(ShotFields)) throw new IOException("Save the shot edits before preparing an exact production item. Your local draft is preserved.");
        var first = Shot?["references"]?.AsArray().FirstOrDefault(r => Text(r?["role"]) == "keyframe");
        var asset = document?["assets"]?.AsArray().FirstOrDefault(a => Text(a?["id"]) == Text(first?["asset"]));
        string mode = Choice(GenerationMode);
        if (mode is not ("text" or "first-frame" or "last-frame" or "first-last-frame" or "voice")) throw new IOException("Use Edit → Extend for an exact tail guide. Control and Ref2VA need a separately verified compatible route.");
        string? source = mode is "first-frame" or "first-last-frame" or "voice" && asset != null ? AssetPath(asset!) : null;
        JsonNode? Bound(string role)
        {
            var binding = Shot?["references"]?.AsArray().FirstOrDefault(r => Text(r?["role"]) == role);
            return document?["assets"]?.AsArray().FirstOrDefault(a => Text(a?["id"]) == Text(binding?["asset"]));
        }
        var last = Bound("last-frame"); var speech = Bound("dialogue");
        if (mode is "first-frame" or "first-last-frame" && source == null) throw new IOException("Attach the explicit keyframe before using this conditioning mode.");
        if (mode is "last-frame" or "first-last-frame" && last == null) throw new IOException("Attach a reference with the last-frame role before using this mode.");
        if (mode == "voice" && speech == null) throw new IOException("Attach the exact dialogue recording before voice-conditioned pilot generation.");
        bool flex = Choice(FilmProfile) == "pika-flex";
        long seed = long.TryParse(FilmSeed.Text, out long chosenSeed) ? chosenSeed : Random.Shared.NextInt64(1, long.MaxValue);
        var request = new VideoRequest(ShotPrompt.Text, "", seed, 768, 448, 5, model.Id, source,
            flex ? [new("pika_h3_flex_fl2va_comfy_bf16.safetensors", 1)] : [], flex ? "pika-flex" : "standard",
            LastFrame: mode is "last-frame" or "first-last-frame" ? AssetPath(last!) : null,
            AudioGuide: mode == "voice" ? AssetPath(speech!) : null);
        proposed = await client.Call("propose-take", new { kind = "video", name = "preview-" + Guid.NewGuid().ToString("N"), shot = ShotId, phase = "pilot", request }, ProjectId, Revision, timeout: TimeSpan.FromMinutes(5));
        Proposal.Text = proposed.ToJsonString(new JsonSerializerOptions { WriteIndented = true });
        Status.Text = "Exact pilot item prepared. Inspect graph and inputs, then authorize this bounded item against current direction.";
    });
    private async void AuthorizeItem(object s, RoutedEventArgs e) => await Run(async () =>
    {
        if (proposed == null) throw new IOException("Prepare an exact pilot item first.");
        var task = await client.Call("task-open", project: ProjectId);
        await Apply("authorize-pilot-item", new { item = proposed["item"]!.DeepClone(), reviewer = Reviewer.Text, source = Text(task["task"]?["authority"]?["path"]), task_sha256 = Text(task["task_sha256"]) });
    });
    private async void PrepareFinish(object s, RoutedEventArgs e) => await Run(async () =>
    {
        if (QueueItems.SelectedItem is not Row row) throw new IOException("Choose a completed persisted preview.");
        proposed = await client.Call("propose-finish", new { preview = row.Id, width = 1280, height = 768, interpolate = true }, ProjectId, Revision, timeout: TimeSpan.FromMinutes(5));
        Proposal.Text = proposed.ToJsonString(new JsonSerializerOptions { WriteIndented = true });
        Status.Text = "Selected AV companion bound to an interpolated latent resize and two-step refinement. This is not a learned upscaler; inspect finished performance.";
    });
    private async void EnqueueItem(object s, RoutedEventArgs e) => await Run(async () =>
    {
        if (proposed == null) throw new IOException("Prepare and authorize an exact pilot item first.");
        var task = await client.Call("task-open", project: ProjectId);
        await Apply("enqueue", new { item = proposed["item"]!.DeepClone(), spec = proposed["spec"]!.DeepClone(), task_sha256 = Text(task["task_sha256"]), engine_input = Path.Combine(App.Root, "input"), engine_output = Path.Combine(App.Root, "output") });
    });
    private async void CancelItem(object s, RoutedEventArgs e) => await Run(() => Apply("cancel", new { item_id = (QueueItems.SelectedItem as Row)?.Id ?? throw new IOException("Select the owned queue item to cancel.") }));
    private async void RebindTake(object s, RoutedEventArgs e) => await Run(async () =>
    {
        if (QueueItems.SelectedItem is not Row row) throw new IOException("Select a completed historical take.");
        var task = await client.Call("task-open", project: ProjectId);
        await Apply("rebind-take", new { item_id = row.Id, reviewer = Reviewer.Text, finding = RebindFinding.Text,
            task_sha256 = Text(task["task_sha256"]), source = Text(task["task"]?["authority"]?["path"]) }, TimeSpan.FromMinutes(5));
    });
    private async void AdoptCompleted(object s, RoutedEventArgs e) => await Run(async () =>
    {
        if (QueueItems.SelectedItem is not Row row || Text(row.Node["status"]) != "completed") throw new IOException("Select a completed queue item.");
        var path = Text(row.Node["state"]?["result"]?["outputs"]?[0]?["path"]);
        await Apply("asset-import", new { path, role = "take", shot = Text(row.Node["item"]?["shot"]), metadata = row.Node.DeepClone() });
    });
    private async void LoadReview(object s, RoutedEventArgs e) => await Run(async () =>
    {
        reviewState = await client.Call("review-state", new { purpose = Choice(ReviewPurpose) }, project: ProjectId);
        ReviewCheck.ItemsSource = reviewState["requirements"]!.AsObject().Select(r => new Row(r.Key, r.Key + " · " + Text(r.Value?["outcome"]), r.Value!)).ToArray();
        var candidate = reviewState["candidate"]!;
        await PreviewPath(Text(candidate["artifact"]?["path"]));
        CutDetails.Text = "Intended final · SHA-256 " + Text(candidate["artifact"]?["sha256"]);
    });
    private void SelectReviewCheck(object s, SelectionChangedEventArgs e)
    {
        if (ReviewCheck.SelectedItem is Row row) ReviewModalities.ItemsSource = row.Node["modalities"]!.AsArray().Select(Text).ToArray();
        if (ReviewCheck.SelectedItem is Row selected && selected.Id.StartsWith("cut:") && int.TryParse(selected.Id[4..], out int frame)) FilmSeek.Value = Math.Max(0, frame-12);
    }
    private void CutBefore(object s, RoutedEventArgs e) => SeekCut(-1);
    private void CutAfter(object s, RoutedEventArgs e) => SeekCut(0);
    private void SeekCut(int offset)
    {
        if (ReviewCheck.SelectedItem is Row row && row.Id.StartsWith("cut:") && int.TryParse(row.Id[4..], out int frame))
        { Player.Pause(); FilmSeek.Value = frame+offset; }
    }
    private async void RecordJudgment(object s, RoutedEventArgs e) => await Run(() => Apply("review-row", new
    {
        check = (ReviewCheck.SelectedItem as Row)?.Id ?? throw new IOException("Choose a required review check."),
        purpose = Choice(ReviewPurpose),
        reviewer = ReviewPerson.Text, staging = ReviewStaging.Text,
        row = new { status = Choice(Judgment), finding = ReviewFinding.Text, method = ReviewMethod.Text,
                    inspected = ReviewModalities.SelectedItems.Cast<string>().ToArray() }
    }));
    private async void DeliverFilm(object s, RoutedEventArgs e) => await Run(async () =>
    {
        if (dirty.Count > 0) throw new IOException("Save the film and shot drafts before committing delivery of the current film.");
        var review = document?["review"] ?? throw new IOException("Record the required current candidate judgments first.");
        var dialog = new SaveFileDialog { Title = "Copy reviewed final bytes and commit delivery", Filter = "MP4 film|*.mp4", FileName = Text(document?["title"]) + ".mp4", OverwritePrompt = true };
        if (dialog.ShowDialog(Window.GetWindow(this)) == true)
        {
            if (File.Exists(dialog.FileName)) throw new IOException("Choose a new destination; existing exports are preserved.");
            await Apply("deliver", new { review = review.DeepClone(), destination = dialog.FileName }, TimeSpan.FromMinutes(10));
        }
    });
    private async void PilotCandidate(object s, RoutedEventArgs e) => await Run(() => Apply("pilot-candidate", new { sha256 = (Cuts.SelectedItem as Row)?.Node["sha256"]?.ToString() ?? throw new IOException("Select a current connected motion cut.") }));
    private async void InspectTimelineMedia(object s, RoutedEventArgs e) => await Run(async () =>
    {
        var segment = (Timeline.SelectedItem as Row)?.Node ?? throw new IOException("Select a picture segment.");
        if (segment["asset"] == null) throw new IOException("This occurrence is a gap, with no source media.");
        var result = await client.Call("media-inspect", new { asset = Text(segment["asset"]) }, ProjectId, Revision, timeout: TimeSpan.FromMinutes(2));
        BitmapImage? Read(string key)
        {
            if (result[key] == null) return null;
            var image = new BitmapImage(); image.BeginInit(); image.CacheOption = BitmapCacheOption.OnLoad;
            image.UriSource = new Uri(Text(result[key])); image.EndInit(); image.Freeze(); return image;
        }
        Filmstrip.Source = Read("filmstrip"); Waveform.Source = Read("waveform");
    });
    private async void ImportTranscript(object s, RoutedEventArgs e) => await Run(() => Apply("transcript-import", new
    {
        path = AssetPath((TranscriptAudio.SelectedItem as Row)?.Node ?? throw new IOException("Select the exact recording or encoded take.")),
        expected = Text(Shot?["dialogue"]),
        observed = ObservedWords.Text, method = TranscriptMethod.Text, reviewer = ReviewPerson.Text,
        status = Choice(TranscriptStatus), start_sample = Number(TranscriptStart), end_sample = Number(TranscriptEnd)
    }));
    private void SelectAudioCue(object s, SelectionChangedEventArgs e)
    {
        if (AudioCues.SelectedItem is not Row row) return;
        CueStart.Text = Text(row.Node["start_sample"]); CueIn.Text = Text(row.Node["in_sample"]);
        CueSamples.Text = Text(row.Node["samples"]); CueVolume.Text = Text(row.Node["volume"] ?? JsonValue.Create(1));
        CueMute.IsChecked = (bool?)row.Node["mute"] ?? false;
    }
    private async void UpdateAudioCue(object s, RoutedEventArgs e) => await Run(() => Apply("audio-update", new
    {
        cue = (AudioCues.SelectedItem as Row)?.Id ?? throw new IOException("Select an audio cue."),
        changes = new { start_sample = Number(CueStart), in_sample = Number(CueIn), samples = Number(CueSamples), volume = double.Parse(CueVolume.Text, System.Globalization.CultureInfo.InvariantCulture), mute = CueMute.IsChecked == true,
                        fade_in = Number(AudioFadeIn), fade_out = Number(AudioFadeOut) }
    }));
    private async void RemoveAudioCue(object s, RoutedEventArgs e) => await Run(() => Apply("audio-remove", new { id = (AudioCues.SelectedItem as Row)?.Id ?? throw new IOException("Select an audio cue.") }));
    private async void BindAsset(object s, RoutedEventArgs e) => await Run(() => Apply("asset-bind", new
    {
        shot = ShotId, asset = (Assets.SelectedItem as Row)?.Id ?? throw new IOException("Select an asset."), role = Choice(AssetRole), precedence = Number(Precedence)
    }));
    private async void PrepareRepair(object s, RoutedEventArgs e) => await Run(async () =>
    {
        if (dirty.Count > 0) throw new IOException("Save the film and shot drafts before preparing exact repair dependencies.");
        var model = FilmModel.SelectedItem as ModelChoice ?? throw new IOException("Choose the installed H3 model in Takes.");
        long seed = long.TryParse(FilmSeed.Text, out long supplied) ? supplied : Random.Shared.NextInt64(1, long.MaxValue);
        var request = new VideoRequest(ShotPrompt.Text, "", seed, 768, 448, 5, model.Id, Loras: [new("pika_h3_flex_fl2va_comfy_bf16.safetensors", 1)], Profile: "pika-flex");
        proposed = await client.Call("propose-repair", new { repair = Choice(RepairKind), modality = Choice(RepairModality),
            segment = SegmentId, shot = ShotId, frames = Number(RepairFrames), in_frame = Number(TrimIn), out_frame = Number(TrimOut),
            prompt = RepairPrompt.Text, defect = RepairDefect.Text, request, phase = Choice(RepairPhase) }, ProjectId, Revision, timeout: TimeSpan.FromMinutes(5));
        Proposal.Text = proposed.ToJsonString(new JsonSerializerOptions { WriteIndented = true });
        Stages.SelectedIndex = 3;
        Status.Text = "Repair anchors and exact source ranges prepared. Conditioning and seam stay unverified; inspect and authorize the bounded item in Takes.";
    });
    private async void PlaceRepair(object s, RoutedEventArgs e) => await Run(() => Apply("place-repair", new { item_id = (QueueItems.SelectedItem as Row)?.Id ?? throw new IOException("Select the completed repair take in Takes.") }));
    private async void SetRepairBudget(object s, RoutedEventArgs e) => await Run(async () =>
    {
        var task = await client.Call("task-open", project: ProjectId);
        await Apply("repair-budget", new { defect = RepairDefect.Text, limit = Number(RepairBudget), reviewer = Reviewer.Text,
            source = Text(task["task"]?["authority"]?["path"]) });
    });
}
