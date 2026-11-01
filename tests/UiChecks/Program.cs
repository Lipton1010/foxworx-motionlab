using ImageStudio;
using System.IO;
using System.Reflection;
using System.Windows;
using System.Windows.Controls;
using System.Runtime.InteropServices;
using System.Windows.Media;
using System.Windows.Media.Imaging;

internal static class Program
{
    [STAThread]
    static void Main()
    {
        // Exercise the real WPF controls and event handlers without starting an
        // engine, submitting requests, or reading/writing production settings.
        var root = AppContext.BaseDirectory;
        File.WriteAllText(Path.Combine(root, "launch.py"), "# isolated UI test root");
        Directory.CreateDirectory(Path.Combine(root, "user"));
        Directory.CreateDirectory(Path.Combine(root, "logs"));
        var app = new App(); app.InitializeComponent();
        var window = new MainWindow();
        int checks = 0;
        const BindingFlags flags = BindingFlags.Instance | BindingFlags.NonPublic;
        T Control<T>(string name) where T : FrameworkElement => (T)window.FindName(name);
        void Set(string name, object value) => typeof(MainWindow).GetField(name, flags)!.SetValue(window, value);
        object? Call(string name, params object[] args) => typeof(MainWindow).GetMethod(name, flags)!.Invoke(window, args);
        void Check(bool condition, string message)
        {
            if (!condition) throw new Exception("FAIL: " + message);
            checks++; Console.WriteLine("PASS: " + message);
        }
        var image = Control<ComboBox>("ImageModelBox");
        var video = Control<ComboBox>("VideoModelBox");
        var workspace = new WorkspaceSettings();
        Set("workspace", workspace); Set("workspaceReady", true);
        ModelChoice qwen = new(GenerationPipelines.QwenModel, "Qwen", "qwen", false, "References and editing", "Installed");
        ModelChoice krea = new("krea2_raw_fp8_scaled.safetensors", "Krea", "krea", false, "Text images", "Installed");
        ModelChoice ltx = new("ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors", "LTX", "ltx", true, "Video", "Installed");
        ModelChoice minimax = new("minimax_h3_fl2va_pruned_int8_convrot.safetensors", "MiniMax", "minimax", true, "Video", "Installed");

        Set("models", Array.Empty<ModelChoice>());
        Call("RestoreImageChoice"); Call("RestoreVideoChoice"); Call("SetBusy", false);
        Check(image.Items.Count == 0 && !image.IsEnabled && !Control<Button>("GenerateButton").IsEnabled, "Empty image catalog disables picker and generation");
        Check(video.Items.Count == 0 && !video.IsEnabled && !Control<Button>("GenerateVideoButton").IsEnabled, "Empty video catalog disables picker and generation");
        Check(Control<TextBlock>("ImageModelHint").Text.Contains("Refresh"), "Empty catalog explains how to recover");
        Set("models", new[] { qwen with { Status = "Missing: VAE" }, ltx with { Status = "Missing: encoder" } });
        Call("RestoreImageChoice"); Call("RestoreVideoChoice"); Call("SetBusy", false);
        Check(image.Items.Count == 0 && video.Items.Count == 0, "Incomplete model installations cannot be selected");
        Check(!Control<Button>("GenerateButton").IsEnabled && !Control<Button>("GenerateVideoButton").IsEnabled, "Returning from an error never enables generation without a model");

        Set("models", new[] { qwen, krea, ltx, minimax });
        workspace.Choice("image:create").Model = "missing-old-model";
        Call("RestoreImageChoice"); Call("RestoreVideoChoice");
        Check(Equals(image.SelectedItem, qwen) && image.IsEnabled, "Unavailable saved model falls back to a compatible installed model");
        image.SelectedItem = krea;
        Check(workspace.Choice("image:create").Model == krea.Id, "Image selector saves the actual selected model");
        Control<TextBox>("PromptBox").Text = "A quiet forest";
        var request = (ImageRequest)Call("ReadRequest")!;
        Check(request.Model == krea.Id, "Actual image request uses the model selected in the UI");
        var graph = System.Text.Json.JsonSerializer.Serialize(StudioEngine.BuildGraph(request));
        Check(graph.Contains(krea.Id), "Selected UI model reaches the generation graph");
        Control<RadioButton>("EditMode").IsChecked = true;
        Check(image.Items.Count == 1 && Equals(image.SelectedItem, qwen), "Edit mode only offers the compatible Qwen model");
        Control<RadioButton>("CreateMode").IsChecked = true;
        Check(Equals(image.SelectedItem, krea), "Switching back restores the create model");
        video.SelectedItem = minimax;
        Control<RadioButton>("VideoImageMode").IsChecked = true;
        video.SelectedItem = ltx;
        Control<RadioButton>("VideoTextMode").IsChecked = true;
        Check(Equals(video.SelectedItem, minimax), "Text-to-video choice remains independent");
        Control<RadioButton>("VideoImageMode").IsChecked = true;
        Check(Equals(video.SelectedItem, ltx), "Image-to-video choice remains independent");
        Call("SaveWorkspace");
        var restored = WorkspaceSettings.Load(Path.Combine(root, "user", "workspace-settings.json"));
        Check(restored.Choice("image:create").Model == krea.Id && restored.Choice("image:edit").Model == qwen.Id, "Image workflows survive disk round-trip");
        Check(restored.Choice("video:text").Model == minimax.Id && restored.Choice("video:image").Model == ltx.Id, "Video workflows survive disk round-trip");
        Call("SetBusy", true);
        Check(!Control<StackPanel>("ControlsPanel").IsEnabled && !Control<Button>("GenerateButton").IsEnabled, "Busy state prevents model changes and duplicate generation");
        Call("SetBusy", false);
        Check(Control<Button>("GenerateButton").IsEnabled, "Ready state restores generation with a compatible model");
        // Builder modes preserve written drafts and hand off without generating.
        var mediaType = Control<ComboBox>("BuilderMediaType");
        var built = Control<TextBox>("BuiltPrompt");
        built.Text = "Image draft edited by the user";
        mediaType.SelectedIndex = 1;
        Check(built.Text == "" && Control<StackPanel>("BuilderVideoFields").Visibility == Visibility.Visible, "Video mode opens its own draft and motion controls");
        Check(Control<StackPanel>("BuilderArtworkFields").Visibility == Visibility.Collapsed && Control<StackPanel>("ImageRefinementControls").Visibility == Visibility.Collapsed, "Video mode hides image presets and the image-only refiner");
        Control<TextBox>("BuilderSubject").Text = "A fox in a garden";
        Control<TextBox>("BuilderMotion").Text = "Turns toward the door";
        Control<TextBox>("BuilderCamera").Text = "Slow push-in";
        Control<TextBox>("BuilderAudio").Text = "Birdsong, no speech";
        Call("BuildPrompt", window, new RoutedEventArgs());
        Check(built.Text.Contains("Slow push-in") && built.Text.Contains("Birdsong"), "Build button composes the visible video fields");
        built.Text = "Video draft edited by the user";
        mediaType.SelectedIndex = 0;
        Check(built.Text == "Image draft edited by the user", "Switching to images restores the edited image prompt");
        mediaType.SelectedIndex = 1;
        Check(built.Text == "Video draft edited by the user", "Switching to video restores the edited video prompt");
        var savedBuilder = (BuilderDraft)Call("ReadBuilder")!;
        Call("RestoreBuilder", System.Text.Json.JsonSerializer.Deserialize<BuilderDraft>(System.Text.Json.JsonSerializer.Serialize(savedBuilder))!);
        Check(mediaType.SelectedIndex == 1 && built.Text == savedBuilder.VideoOutput && Control<TextBox>("BuilderCamera").Text == savedBuilder.Camera, "Restoring a saved video builder keeps its mode, controls, and output");
        Call("ApplyBuiltVideoPrompt", false);
        Check(Control<TabItem>("VideoTab").IsSelected && Control<RadioButton>("VideoTextMode").IsChecked == true && Control<TextBox>("VideoPromptBox").Text == built.Text, "Video builder hands the edited prompt to text-to-video");
        string imagePromptBeforeVideo = Control<TextBox>("PromptBox").Text;
        Call("ApplyBuiltVideoPrompt", true);
        Check(Control<RadioButton>("VideoImageMode").IsChecked == true && Control<TextBlock>("StatusText").Text.Contains("first frame"), "Image-to-video handoff asks for a missing first frame");
        Check(Control<TextBox>("PromptBox").Text == imagePromptBeforeVideo && typeof(MainWindow).GetField("jobId", flags)!.GetValue(window) == null, "Video handoff preserves the image prompt and does not generate");
        Call("SetBusy", true); Control<TextBox>("VideoPromptBox").Text = "Busy sentinel";
        Call("ApplyBuiltVideoPrompt", false);
        Check(Control<TextBox>("VideoPromptBox").Text == "Busy sentinel", "Busy state blocks video prompt transfer");
        Call("SetBusy", false); built.Text = "";
        Call("ApplyBuiltVideoPrompt", false);
        Check(Control<TextBox>("VideoPromptBox").Text == "Busy sentinel", "Empty builder prompt cannot overwrite the video workspace");
        // Drive the real deletion handler, including its confirmation and disk operation.
        var output = Path.Combine(root, "output");
        Directory.CreateDirectory(output);
        var disposable = Path.Combine(output, "delete-check.png");
        var encoder = new PngBitmapEncoder();
        encoder.Frames.Add(BitmapFrame.Create(BitmapSource.Create(1, 1, 96, 96, PixelFormats.Bgra32, null, new byte[] { 0, 0, 255, 255 }, 4)));
        using (var stream = File.Create(disposable)) encoder.Save(stream);
        File.WriteAllText(disposable + ".json", "{}");
        Call("ShowPreview", disposable);
        Call("SetVideoSource", disposable);
        var confirm = ConfirmDeletion("Delete image?");
        Call("DeleteImage", window, new RoutedEventArgs());
        confirm.GetAwaiter().GetResult();
        Check(!File.Exists(disposable) && !File.Exists(disposable + ".json"), "UI deletion removes the actual image and sidecar from their folder");
        Check(!Control<Button>("AnimateButton").IsEnabled, "Deleting the last image disables Animate");
        Check(typeof(MainWindow).GetField("videoSource", flags)!.GetValue(window) == null && Control<Image>("VideoSourcePreview").Source == null, "Deleting the selected first frame clears its video source and thumbnail");
        var disposableVideo = Path.Combine(output, "delete-check.mp4");
        File.WriteAllText(disposableVideo, "Disposable video deletion fixture");
        File.WriteAllText(disposableVideo + ".json", "{}");
        Set("videoPreview", disposableVideo);
        confirm = ConfirmDeletion("Delete video?");
        Call("DeleteVideo", window, new RoutedEventArgs());
        confirm.GetAwaiter().GetResult();
        Check(!File.Exists(disposableVideo) && !File.Exists(disposableVideo + ".json"), "UI video deletion removes the actual video and metadata");
        Check(!Control<Button>("VideoDeleteButton").IsEnabled && !Control<Button>("VideoPlayButton").IsEnabled, "Deleting the last video disables Delete and Play");
        Check(typeof(MainWindow).GetField("videoPreview", flags)!.GetValue(window) == null, "Deleting the last video clears its preview path");
        Console.WriteLine($"Passed {checks} real-control UI checks; no engine or generation requests were made.");
        app.Shutdown();
    }

    private static Task ConfirmDeletion(string title)
    {
        return Task.Run(() =>
        {
            for (int attempt = 0; attempt < 100; attempt++)
            {
                var dialog = FindWindow("#32770", title);
                GetWindowThreadProcessId(dialog, out var processId);
                if (dialog != IntPtr.Zero && processId == Environment.ProcessId)
                {
                    PostMessage(dialog, 0x0111, new IntPtr(6), IntPtr.Zero);
                    return;
                }
                Thread.Sleep(50);
            }
            throw new Exception("Deletion confirmation did not open for this test process.");
        });
    }
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern IntPtr FindWindow(string className, string windowName);
    [DllImport("user32.dll")]
    private static extern uint GetWindowThreadProcessId(IntPtr window, out int processId);
    [DllImport("user32.dll")]
    private static extern bool PostMessage(IntPtr window, uint message, IntPtr wParam, IntPtr lParam);
}
