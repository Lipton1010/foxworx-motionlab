using System.Collections.ObjectModel;
using System.IO;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media.Imaging;
using Microsoft.Win32;

namespace ImageStudio;

public sealed class ReferenceImage
{
    public string Path { get; set; } = "";
    public string Role { get; set; } = "General reference";
    public string Notes { get; set; } = "";
    [JsonIgnore] public int Number { get; set; }
    [JsonIgnore] public string Label => $"Image {Number}";
    [JsonIgnore] public string FileName => System.IO.Path.GetFileName(Path);
    [JsonIgnore] public BitmapSource? Thumbnail { get; set; }
    public ReferenceImage Snapshot() => new() { Path = Path, Role = Role, Notes = Notes };
}

public record BuilderDraft(int Type, string Subject, string Setting, string Style, string Composition, string Lighting, string Lettering, string Preserve, string Output,
    bool Video = false, string Motion = "", string Camera = "", string Pacing = "", string Audio = "", string VideoOutput = "");

public partial class MainWindow
{
    private readonly ObservableCollection<ReferenceImage> references = [];
    private record ReferenceSet(ReferenceImage[] Images, string Style);
    private const string ImageFilter = "Images|*.png;*.jpg;*.jpeg;*.bmp;*.tif;*.tiff";
    private bool builderVideo;
    private string imageBuilderOutput = "", videoBuilderOutput = "";

    private void RefreshReferences()
    {
        for (int index = 0; index < references.Count; index++) references[index].Number = index + 1;
        ReferenceList.Items.Refresh();
        ReferenceSummary.Text = references.Count == 0 ? "No reference images" : $"{references.Count} reference image{(references.Count == 1 ? "" : "s")}";
        ReferenceCount.Text = $"{references.Count} / 10 images";
        ReferencesEmpty.Visibility = references.Count == 0 ? Visibility.Visible : Visibility.Collapsed;
        AddReferencesButton.IsEnabled = references.Count < 10;
        sourcePath = references.FirstOrDefault()?.Path;
    }

    private ReferenceImage PrepareReference(ReferenceImage image)
    {
        if (string.IsNullOrWhiteSpace(image.Path)) throw new IOException("A reference has no image path.");
        image.Path = Path.GetFullPath(image.Path);
        if (image.Path.StartsWith(@"\\")) throw new IOException("Copy reference images to a local folder before adding them.");
        image.Thumbnail = LoadBitmap(image.Path, 160);
        return image;
    }

    private void ManageReferences(object sender, RoutedEventArgs e) => WorkspaceTabs.SelectedItem = ReferencesTab;
    private void UseReferences(object sender, RoutedEventArgs e)
    {
        IncludeReferences.IsChecked = true;
        ImageModelBox.SelectedItem = ImageModelBox.Items.Cast<ModelChoice>().FirstOrDefault(x => x.Family == "qwen");
        SourcePanel.IsExpanded = true;
        WorkspaceTabs.SelectedItem = StudioTab;
    }
    private void AddReferences(object sender, RoutedEventArgs e)
    {
        var dialog = new OpenFileDialog { Title = "Add campaign reference images", Filter = ImageFilter, Multiselect = true };
        if (dialog.ShowDialog(this) != true) return;
        try
        {
            if (references.Count + dialog.FileNames.Length > 10) throw new ArgumentException("You can use up to 10 references. Remove a reference or select fewer images.");
            var additions = dialog.FileNames.Select(path => PrepareReference(new ReferenceImage { Path = path })).ToArray();
            foreach (var image in additions) references.Add(image);
            IncludeReferences.IsChecked = true; RefreshReferences();
        }
        catch (Exception ex) { ShowError(ex); }
    }
    private void RemoveReference(object sender, RoutedEventArgs e)
    {
        if ((sender as FrameworkElement)?.DataContext is ReferenceImage image) { references.Remove(image); RefreshReferences(); }
    }
    private void MoveReferenceUp(object sender, RoutedEventArgs e) => MoveReference(sender, -1);
    private void MoveReferenceDown(object sender, RoutedEventArgs e) => MoveReference(sender, 1);
    private void MoveReference(object sender, int direction)
    {
        if ((sender as FrameworkElement)?.DataContext is not ReferenceImage image) return;
        int from = references.IndexOf(image), to = from + direction;
        if (to >= 0 && to < references.Count) { references.Move(from, to); RefreshReferences(); }
    }
    private void SaveReferenceSet(object sender, RoutedEventArgs e)
    {
        if (references.Count == 0) { SetStatus("Add at least one image before saving a reference set."); return; }
        string library = Path.Combine(App.Root, "user", "reference-sets");
        Directory.CreateDirectory(library);
        var dialog = new SaveFileDialog { Title = "Save reference set", InitialDirectory = library, FileName = "Campaign references.json", Filter = "Reference set|*.json", DefaultExt = ".json" };
        if (dialog.ShowDialog(this) != true) return;
        try
        {
            string directory = Path.GetDirectoryName(dialog.FileName)!;
            string assets = Path.Combine(directory, Path.GetFileNameWithoutExtension(dialog.FileName) + ".images");
            Directory.CreateDirectory(assets);
            var saved = new List<ReferenceImage>();
            foreach (var image in references)
            {
                using var input = File.OpenRead(image.Path);
                string hash = Convert.ToHexString(SHA256.HashData(input));
                string target = Path.Combine(assets, hash + Path.GetExtension(image.Path).ToLowerInvariant());
                if (!File.Exists(target)) File.Copy(image.Path, target);
                var copy = image.Snapshot(); copy.Path = Path.GetRelativePath(directory, target); saved.Add(copy);
            }
            File.WriteAllText(dialog.FileName, JsonSerializer.Serialize(new ReferenceSet(saved.ToArray(), BuilderStyle.Text), new JsonSerializerOptions { WriteIndented = true }));
            SetStatus("Reference set saved with its own image copies, roles, notes, and campaign style.");
        }
        catch (Exception ex) { ShowError(ex); }
    }
    private void LoadReferenceSet(object sender, RoutedEventArgs e)
    {
        var dialog = new OpenFileDialog { Title = "Load campaign reference set", InitialDirectory = Path.Combine(App.Root, "user", "reference-sets"), Filter = "Reference set|*.json" };
        if (dialog.ShowDialog(this) != true) return;
        try
        {
            var set = JsonSerializer.Deserialize<ReferenceSet>(File.ReadAllText(dialog.FileName)) ?? throw new IOException("This reference set is empty.");
            if (set.Images == null || set.Images.Length > 10) throw new IOException("Reference sets must contain no more than 10 images.");
            var images = set.Images.Select(image => { image.Path = Path.GetFullPath(image.Path, Path.GetDirectoryName(dialog.FileName)!); return PrepareReference(image); }).ToArray();
            references.Clear(); foreach (var image in images) references.Add(image);
            BuilderStyle.Text = set.Style; IncludeReferences.IsChecked = true; RefreshReferences();
            SetStatus("Loaded " + Path.GetFileNameWithoutExtension(dialog.FileName));
        }
        catch (Exception ex) { ShowError(ex); }
    }

    private BuilderDraft ReadBuilder() => new(ArtworkType.SelectedIndex, BuilderSubject.Text, BuilderSetting.Text, BuilderStyle.Text, BuilderComposition.Text, BuilderLighting.Text, BuilderLettering.Text, BuilderPreserve.Text,
        builderVideo ? imageBuilderOutput : BuiltPrompt.Text, builderVideo, BuilderMotion.Text, BuilderCamera.Text, BuilderPacing.Text, BuilderAudio.Text,
        builderVideo ? BuiltPrompt.Text : videoBuilderOutput);
    private void RestoreBuilder(BuilderDraft draft)
    {
        ArtworkType.SelectedIndex = Math.Clamp(draft.Type, 0, 4);
        BuilderSubject.Text = draft.Subject; BuilderSetting.Text = draft.Setting; BuilderStyle.Text = draft.Style;
        BuilderComposition.Text = draft.Composition; BuilderLighting.Text = draft.Lighting; BuilderLettering.Text = draft.Lettering;
        BuilderPreserve.Text = draft.Preserve;
        BuilderMotion.Text = draft.Motion; BuilderCamera.Text = draft.Camera; BuilderPacing.Text = draft.Pacing; BuilderAudio.Text = draft.Audio;
        imageBuilderOutput = draft.Output; videoBuilderOutput = draft.VideoOutput;
        builderVideo = draft.Video; BuiltPrompt.Text = builderVideo ? videoBuilderOutput : imageBuilderOutput;
        BuilderMediaType.SelectedIndex = builderVideo ? 1 : 0;
        beforeRefinement = null; UndoRefinementButton.IsEnabled = false;
        UpdateBuilderMode();
    }

    private void BuilderMediaChanged(object sender, SelectionChangedEventArgs e)
    {
        if (BuiltPrompt == null) return;
        bool video = BuilderMediaType.SelectedIndex == 1;
        if (video != builderVideo)
        {
            if (builderVideo) videoBuilderOutput = BuiltPrompt.Text; else imageBuilderOutput = BuiltPrompt.Text;
            builderVideo = video; BuiltPrompt.Text = video ? videoBuilderOutput : imageBuilderOutput;
            beforeRefinement = null; UndoRefinementButton.IsEnabled = false;
        }
        UpdateBuilderMode();
    }

    private void UpdateBuilderMode()
    {
        BuilderArtworkFields.Visibility = ImagePromptActions.Visibility = builderVideo ? Visibility.Collapsed : Visibility.Visible;
        ImageRefinementControls.Visibility = Visibility.Visible;
        BuilderVideoFields.Visibility = VideoPromptActions.Visibility = builderVideo ? Visibility.Visible : Visibility.Collapsed;
        BuilderIntro.Text = builderVideo ? "Describe the scene, movement, and sound." : "Set the subject, look, and details that matter.";
        BuilderOutputHint.Text = builderVideo ? "Edit freely, then send your prompt to Videos." : "Edit freely. Refine when you're ready.";
        BuilderDraftState.Text = builderVideo ? "Video draft · editable · apply to text or first-frame video below" : "Image draft · editable · apply to a new image or edit below";
        BuilderPreserveLabel.Content = builderVideo ? "Details to keep consistent throughout" : "For edits: what should stay unchanged?";
        RewriteInfo.Text = builderVideo
            ? "Refinement uses the selected video model profile and optional first frame. Choose the model, duration and first frame in Videos."
            : "AI refinement runs on your computer. Review its changes before generating.";
    }

    public static string ComposePrompt(BuilderDraft draft)
    {
        if (string.IsNullOrWhiteSpace(draft.Subject)) throw new ArgumentException("Describe the subject or the change you want first.");
        var text = new List<string> { draft.Subject.Trim().TrimEnd('.') + "." };
        if (draft.Video) text.Insert(0, "Create a video clip.");
        void Add(string label, string value) { if (!string.IsNullOrWhiteSpace(value)) text.Add(label + value.Trim().TrimEnd('.') + "."); }
        Add("Setting and details: ", draft.Setting);
        Add("Art direction: ", draft.Style);
        string framing = draft.Composition.Trim();
        if (framing.Length == 0 && !draft.Video) framing = draft.Type switch
        {
            0 => "Portrait framing with a clear, readable face and distinctive features",
            1 => "A wide scene suitable as a tabletop roleplaying backdrop, with a readable focal point and a coherent environment",
            2 => "A clearly composed player handout with important visual clues easy to see",
            3 => "A single isolated subject, entirely within the frame, with clear edges and padding around it; no border, base, or surrounding scenery",
            _ => ""
        };
        Add("Composition: ", framing);
        Add("Lighting and mood: ", draft.Lighting);
        if (draft.Video)
        {
            Add("Subject and scene movement: ", draft.Motion);
            Add("Camera movement: ", draft.Camera);
            Add("Timing and pacing: ", draft.Pacing);
            Add("Sound and dialogue: ", draft.Audio);
        }
        if (!string.IsNullOrWhiteSpace(draft.Lettering)) text.Add("Include exactly this lettering: \"" + draft.Lettering.Trim() + "\". Make it legible.");
        else text.Add("No lettering or watermark.");
        Add("Preserve these details: ", draft.Preserve);
        if (!draft.Video && draft.Type == 3) text.Add("This is an RGBA image with transparency. The image has alpha channel and the background is transparent.");
        return string.Join("\n\n", text);
    }
    private void BuildPrompt(object sender, RoutedEventArgs e)
    {
        try
        {
            BuiltPrompt.Text = ComposePrompt(ReadBuilder()); beforeRefinement = null; UndoRefinementButton.IsEnabled = false;
            BuilderDraftState.Text = builderVideo ? "Built from video fields · editable draft · choose an Apply destination" : "Built from image fields · editable draft · choose an Apply destination";
            SetStatus(builderVideo ? "Video prompt built. Review it, then choose text-to-video or image-to-video." : "Prompt built. Review it, then choose new image or edit.");
        }
        catch (Exception ex) { ShowError(ex); }
    }
    private void UseBuiltPromptCreate(object sender, RoutedEventArgs e) => ApplyBuiltPrompt(false);
    private void UseBuiltPromptEdit(object sender, RoutedEventArgs e) => ApplyBuiltPrompt(true);
    private void ApplyBuiltPrompt(bool edit)
    {
        if (busy || builderVideo) return;
        if (string.IsNullOrWhiteSpace(BuiltPrompt.Text)) { SetStatus("Build or write a prompt first."); return; }
        if (edit && references.Count == 0) { SetStatus("Add the image you want to edit in References first."); WorkspaceTabs.SelectedItem = ReferencesTab; return; }
        PromptBox.Text = BuiltPrompt.Text; EditMode.IsChecked = edit; CreateMode.IsChecked = !edit;
        if (edit) IncludeReferences.IsChecked = true;
        TransparentBox.IsChecked = ArtworkType.SelectedIndex == 3;
        if (!edit) ShapeBox.SelectedIndex = ArtworkType.SelectedIndex switch { 0 => 2, 1 => 3, _ => 0 };
        WorkspaceTabs.SelectedItem = StudioTab; PromptBox.Focus();
        SetStatus("Prompt ready. Check references and settings, then generate.");
    }
    private void UseBuiltPromptVideoText(object sender, RoutedEventArgs e) => ApplyBuiltVideoPrompt(false);
    private void UseBuiltPromptVideoImage(object sender, RoutedEventArgs e) => ApplyBuiltVideoPrompt(true);
    private void ApplyBuiltVideoPrompt(bool fromImage)
    {
        if (busy || !builderVideo) return;
        if (string.IsNullOrWhiteSpace(BuiltPrompt.Text)) { SetStatus("Build or write a video prompt first."); return; }
        VideoPromptBox.Text = BuiltPrompt.Text;
        VideoImageMode.IsChecked = fromImage; VideoTextMode.IsChecked = !fromImage;
        WorkspaceTabs.SelectedItem = VideoTab; VideoPromptBox.Focus(); SaveWorkspaceSafely();
        SetStatus(fromImage && (videoSource == null || !File.Exists(videoSource))
            ? "Video prompt ready. Choose an image for the first frame, then review settings and generate."
            : "Video prompt ready. Check the model, duration, and settings, then generate.");
    }
    private void CopyBuiltPrompt(object sender, RoutedEventArgs e)
    {
        try { if (!string.IsNullOrWhiteSpace(BuiltPrompt.Text)) { Clipboard.SetText(BuiltPrompt.Text); SetStatus("Prompt copied."); } }
        catch (Exception ex) { ShowError(ex); }
    }
}
