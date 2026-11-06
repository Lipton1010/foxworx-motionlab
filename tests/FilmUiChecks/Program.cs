using ImageStudio;
using System.Diagnostics;
using System.IO;
using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Threading;
using System.Runtime.InteropServices;
using System.Windows.Interop;
using System.Security.Cryptography;

internal static class Program
{
    [STAThread]
    static void Main(string[] args)
    {
        var repository = args[0];
        var evidence = Path.Combine(repository, "temp", "film-implementation", "evidence", args.Contains("--accessibility") ? "followup-ui" : "ui");
        Directory.CreateDirectory(evidence);
        var root = AppContext.BaseDirectory;
        File.WriteAllText(Path.Combine(root, "launch.py"), "# Isolated real-control fixture");
        File.WriteAllText(Path.Combine(root, "Start Image Studio.ps1"), "exit 0");
        Directory.CreateDirectory(Path.Combine(root, "desktop"));
        Directory.CreateDirectory(Path.Combine(root, "user"));
        Directory.CreateDirectory(Path.Combine(root, "logs"));
        foreach (var file in Directory.GetFiles(Path.Combine(repository, "desktop"), "production_*"))
            File.Copy(file, Path.Combine(root, "desktop", Path.GetFileName(file)), true);
        var app = new App(); app.InitializeComponent();
        var window = new MainWindow();
        var failures = new List<string>();
        int checks = 0;
        void Check(bool condition, string message)
        {
            checks++; if (!condition) failures.Add(message);
            Console.WriteLine((condition ? "PASS: " : "FAIL: ") + message);
        }
        window.Loaded += async (_, _) =>
        {
            try
            {
                if (args.Contains("--accessibility"))
                {
                    var physical = args.FirstOrDefault(a => a.StartsWith("--physical-dpi="));
                    await AcceptanceChecks.Run(window, app, evidence, physical == null ? null : int.Parse(physical.Split('=')[1])); return;
                }
                var client = new ProductionClient();
                var project = await client.Call("create", new { title = "UI synthetic fixture" });
                string id = project["id"]!.GetValue<string>();
                var saved = await client.Call("shot-add", project: id, revision: project["revision"]!.GetValue<string>());
                Check(saved["project"]?["shots"]?.AsArray().Count == 1, "Actual WPF client creates a persisted film shot through the public interface");
                var scalePath = Path.Combine(repository, "temp/film-implementation/evidence/scale-result.json");
                if (File.Exists(scalePath))
                {
                    var scale = JsonNode.Parse(File.ReadAllText(scalePath))!;
                    string source = scale["source"]?.GetValue<string>() ?? Path.Combine(Directory.GetParent(Directory.GetParent(Directory.GetParent(Directory.GetParent(scale["artifact"]!.GetValue<string>())!.FullName)!.FullName)!.FullName)!.FullName, "six-seconds.mp4");
                    if (File.Exists(source))
                    {
                        var imported = await client.Call("asset-import", new { path = source, role = "take" }, id, saved["project"]!["revision"]!.GetValue<string>());
                        var doc = imported["project"]!;
                        string asset = doc["assets"]![0]!["id"]!.GetValue<string>();
                        var edit = doc["edit"]!.DeepClone();
                        var segments = new JsonArray();
                        for (int i = 0; i < 100; i++) segments.Add(new JsonObject { ["id"] = Guid.NewGuid().ToString("N"), ["asset"] = asset, ["in_frame"] = 0, ["out_frame"] = 144 });
                        edit["segments"] = segments;
                        var edited = await client.Call("edit-replace", new { edit }, id, doc["revision"]!.GetValue<string>());
                        using var cancellation = new CancellationTokenSource(1000);
                        var watch = Stopwatch.StartNew();
                        try { await client.Call("render-draft", new { width = 640, height = 360 }, id, edited["project"]!["revision"]!.GetValue<string>(), cancellation.Token); Check(false, "Draft render cancels before completion"); }
                        catch (IOException ex) { Check(ex.Message.Contains("Stopped waiting"), "Cancelling the actual client wait terminates its media process tree"); }
                        Check(watch.Elapsed.TotalSeconds < 5, "Draft cancellation returns within five seconds");
                        File.WriteAllText(Path.Combine(evidence, "cancellation.json"), System.Text.Json.JsonSerializer.Serialize(new { elapsed_seconds = watch.Elapsed.TotalSeconds, limit_seconds = 5 }));
                    }
                }
                var tabs = (TabControl)window.FindName("WorkspaceTabs");
                foreach (string palette in new[] { "Dark", "Light", "System" })
                {
                    ThemeManager.Select(palette);
                    Check(ThemeManager.Preference == palette, palette + " preference applies live");
                    var text = ((SolidColorBrush)app.Resources["TextBrush"]).Color;
                    var panel = ((SolidColorBrush)app.Resources["PanelBrush"]).Color;
                    double luminance(Color c) { double Channel(byte v) { double n = v / 255d; return n <= .04045 ? n / 12.92 : Math.Pow((n + .055) / 1.055, 2.4); } return .2126 * Channel(c.R) + .7152 * Channel(c.G) + .0722 * Channel(c.B); }
                    Check((Math.Max(luminance(text), luminance(panel)) + .05) / (Math.Min(luminance(text), luminance(panel)) + .05) >= 4.5, palette + " normal text exceeds 4.5:1 contrast");
                    var previewGrid = (Grid)((StackPanel)window.FindName("EmptyPreview")).Parent;
                    var checker = (DrawingBrush)((Border)previewGrid.Parent).Background;
                    Check(((SolidColorBrush)((GeometryDrawing)((DrawingGroup)checker.Drawing).Children[0]).Brush).Color == ((SolidColorBrush)app.Resources["CheckerABrush"]).Color, palette + " actual checkerboard drawing follows the live palette");
                    foreach (var (foreground, background, minimum) in new[] { ("Muted", "Panel", 4.5), ("Muted", "CheckerA", 4.5), ("Muted", "CheckerB", 4.5), ("Muted", "Preview", 4.5), ("InputBorder", "Input", 3d), ("Border", "Panel", 3d), ("SelectedText", "Selected", 4.5), ("AccentText", "Accent", 4.5) })
                    {
                        var a = ((SolidColorBrush)app.Resources[foreground + "Brush"]).Color;
                        var b = ((SolidColorBrush)app.Resources[background + "Brush"]).Color;
                        Check((Math.Max(luminance(a), luminance(b)) + .05) / (Math.Min(luminance(a), luminance(b)) + .05) >= minimum, palette + " " + foreground + "/" + background + " meets contrast target");
                    }
                    for (int i = 0; i < tabs.Items.Count; i++)
                    {
                        tabs.SelectedIndex = i;
                        await window.Dispatcher.InvokeAsync(() => { }, DispatcherPriority.ApplicationIdle);
                        await Task.Delay(100);
                        window.UpdateLayout();
                        var image = new RenderTargetBitmap((int)window.ActualWidth, (int)window.ActualHeight, 96, 96, PixelFormats.Pbgra32);
                        image.Render(window);
                        var encoder = new PngBitmapEncoder(); encoder.Frames.Add(BitmapFrame.Create(image));
                        using var stream = File.Create(Path.Combine(evidence, palette + "-workspace-" + i + ".png")); encoder.Save(stream);
                        Check(window.ActualWidth > 0 && window.ActualHeight > 0, palette + " workspace " + i + " renders real WPF controls");
                    }
                }
                ThemeManager.Select("Dark");
                Check(File.ReadAllText(Path.Combine(root, "user", "appearance.json")).Contains("Dark"), "Appearance preference persists in isolated user data");
                var film = (FilmsWorkspace)window.FindName("FilmWorkspace");
                var stages = (TabControl)film.FindName("Stages");
                Check(stages.Items.Count == 6, "Films exposes all six native stages");
                for (int i = 0; i < 6; i++)
                {
                    tabs.SelectedItem = window.FindName("FilmsTab"); stages.SelectedIndex = i;
                    await window.Dispatcher.InvokeAsync(() => { }, DispatcherPriority.ApplicationIdle);
                    window.UpdateLayout();
                    var image = new RenderTargetBitmap((int)window.ActualWidth, (int)window.ActualHeight, 96, 96, PixelFormats.Pbgra32); image.Render(window);
                    var encoder = new PngBitmapEncoder(); encoder.Frames.Add(BitmapFrame.Create(image));
                    using var stream = File.Create(Path.Combine(evidence, "Dark-film-stage-" + i + ".png")); encoder.Save(stream);
                }
                var projects = (ComboBox)film.FindName("Projects");
                Check(projects.Items.Count > 0, "Film browser discovers the actual shared-interface fixture");
                if (projects.Items.Count > 0)
                {
                    var toolbar = ((Grid)film.Content).Children.OfType<WrapPanel>().First();
                    toolbar.Children.OfType<Button>().First(b => b.Content?.ToString() == "Reload").RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
                    await Task.Delay(600);
                    projects.SelectedIndex = -1;
                    await Task.Delay(300);
                    projects.SelectedItem = projects.Items.Cast<object>().First(p => p.GetType().GetProperty("Id")?.GetValue(p)?.ToString() == id);
                    for (int attempt = 0; attempt < 20 && ((ListBox)film.FindName("Shots")).Items.Count == 0; attempt++) await Task.Delay(200);
                    Check(((ListBox)film.FindName("Shots")).Items.Count > 0, "Selecting a film loads its persisted shots into the real WPF list");
                    stages.SelectedIndex = 0;
                    var prompt = (TextBox)film.FindName("ShotPrompt");
                    prompt.Text = "Synthetic UI draft — keep while switching stages";
                    stages.SelectedIndex = 3; stages.SelectedIndex = 0;
                    Check(prompt.Text.Contains("keep while switching"), "Shot draft survives native stage navigation");
                    var editor = (StackPanel)film.FindName("ShotEditor");
                    var save = editor.Children.OfType<Button>().First(b => b.Content?.ToString() == "Save shot");
                    save.RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
                    JsonNode? opened = null;
                    for (int attempt = 0; attempt < 30; attempt++)
                    {
                        opened = await client.Call("open", project: id);
                        if (opened["shots"]?[0]?["prompt"]?.ToString() == prompt.Text) break;
                        await Task.Delay(100);
                    }
                    Check(opened?["shots"]?[0]?["prompt"]?.ToString() == prompt.Text, "Actual Save shot control commits its edited prompt to the shared project");
                }
                var scaleMedia = JsonNode.Parse(File.ReadAllText(Path.Combine(repository, "temp/film-implementation/evidence/scale-result.json")))!;
                tabs.SelectedItem = window.FindName("FilmsTab"); stages.SelectedIndex = 4;
                var player = (MediaElement)film.FindName("Player"); player.Volume = 0;
                async Task OpenPlayer(string path)
                {
                    var ready = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
                    RoutedEventHandler openedHandler = (_, _) => { ready.TrySetResult(true); };
                    player.MediaOpened += openedHandler;
                    try
                    {
                        await (Task)typeof(FilmsWorkspace).GetMethod("PreviewPath", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!.Invoke(film, [path])!;
                        await ready.Task.WaitAsync(TimeSpan.FromSeconds(10));
                    }
                    finally { player.MediaOpened -= openedHandler; }
                }
                await OpenPlayer(scaleMedia["artifact"]!.GetValue<string>());
                Check(player.NaturalDuration.HasTimeSpan && player.NaturalDuration.TimeSpan.TotalSeconds >= 599, "Real WPF player opens the ten-minute encoded synthetic cut");
                player.Pause();
                var seek = (Slider)film.FindName("FilmSeek"); seek.Value = 24;
                window.Activate(); await Task.Delay(300);
                var handle = new WindowInteropHelper(window).Handle;
                string before = Capture(player, handle);
                if (before == "BLACK") throw new IOException("The video baseline is not visibly decoded; seek latency remains unverified.");
                var seekWatch = Stopwatch.StartNew(); seek.Value = 497 * 24;
                string? decoded = null; double? seekMs = null;
                for (int i = 0; i < 100; i++)
                {
                    await Task.Delay(10);
                    string current = Capture(player, handle);
                    if (current != "BLACK" && current != before && current == decoded) { seekMs = seekWatch.Elapsed.TotalMilliseconds; break; }
                    decoded = current;
                }
                Check(seekMs is > 0 and <= 250, "Paused WPF seek presents a changed stable frame within the 250 ms budget");
                File.WriteAllText(Path.Combine(evidence, "seek.json"), System.Text.Json.JsonSerializer.Serialize(new { seconds = 600, target_seconds = 497, visible_frame_seek_ms = seekMs, budget_ms = 250, active_players = 1, process_peak_working_set_mib = Process.GetCurrentProcess().PeakWorkingSet64 / 1048576d, method = "Owned foreground video-region pixel hash changed and stabilized after paused scrub; not a frame-identity or sound judgment" }));
                player.Stop(); player.Close();
                string coded = Path.Combine(evidence, "frame-code-main.mp4");
                if (!File.Exists(coded))
                {
                    var encode = new ProcessStartInfo(Path.Combine(repository, "runtime/media/ffmpeg.exe")) { UseShellExecute = false, CreateNoWindow = true, RedirectStandardInput = true, RedirectStandardError = true };
                    foreach (string arg in new[] { "-nostdin", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "320x180", "-r", "24", "-i", "pipe:0", "-an", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18", "-profile:v", "main", "-pix_fmt", "yuv420p", "-g", "24", coded }) encode.ArgumentList.Add(arg);
                    using var encoder = Process.Start(encode)!; var errors = encoder.StandardError.ReadToEndAsync();
                    for (int frame = 0; frame < 120; frame++)
                    {
                        var pixels = new byte[320 * 180 * 3];
                        for (int y = 0; y < 180; y++) for (int x = 0; x < 320; x++)
                        {
                            byte value = (byte)(((frame >> (x / 40)) & 1) * 255);
                            int offset = (y * 320 + x) * 3; pixels[offset] = pixels[offset + 1] = pixels[offset + 2] = value;
                        }
                        await encoder.StandardInput.BaseStream.WriteAsync(pixels);
                    }
                    encoder.StandardInput.Close(); await encoder.WaitForExitAsync();
                    if (encoder.ExitCode != 0) throw new IOException(await errors);
                }
                await OpenPlayer(coded);
                Check(player.NaturalDuration.HasTimeSpan && player.NaturalVideoWidth == 320, "Exact-frame fixture opens in the actual WPF player");
                player.Pause(); window.Activate(); await Task.Delay(200);
                var frameResults = new List<object>();
                foreach (int target in new[] { 7, 37, 73, 119 })
                {
                    var clock = Stopwatch.StartNew(); seek.Value = target; int shown = -1;
                    while (clock.ElapsedMilliseconds < 1000)
                    {
                        await Task.Delay(10); shown = ReadFrameCode(player, handle);
                        if (shown == target) break;
                    }
                    Check(shown == target && clock.Elapsed.TotalMilliseconds <= 250, "Paused native seek displays exact encoded frame " + target + " within 250 ms");
                    frameResults.Add(new { fps = 24, target, shown, milliseconds = clock.Elapsed.TotalMilliseconds });
                }
                File.WriteAllText(Path.Combine(evidence, "exact-seek.json"), System.Text.Json.JsonSerializer.Serialize(new { frames = 120, fps = 24, results = frameResults, method = "8-bit frame ID encoded in source pixels; read from actual owned foreground video pixels after paused seek" }));
                player.Stop(); player.Close();
                var documentField = typeof(FilmsWorkspace).GetField("document", System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic)!;
                var currentDocument = (JsonNode)documentField.GetValue(film)!;
                await client.Call("edit-replace", new { edit = new { fps = "25/1", sample_rate = 48000, segments = Array.Empty<object>(), audio = Array.Empty<object>(), titles = Array.Empty<object>(), markers = Array.Empty<object>() } },
                    currentDocument["id"]!.ToString(), currentDocument["revision"]!.ToString());
                ((Grid)film.Content).Children.OfType<WrapPanel>().First().Children.OfType<Button>().First(b => b.Content?.ToString() == "Reload").RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
                for (int i = 0; i < 100 && ((JsonNode?)documentField.GetValue(film))?["edit"]?["fps"]?.ToString() != "25/1"; i++) await Task.Delay(50);
                Check(((JsonNode?)documentField.GetValue(film))?["edit"]?["fps"]?.ToString() == "25/1", "Actual Reload accepts the shared-interface rational 25/1 fps edit");
                string coded25 = Path.Combine(evidence, "frame-code-25-main.mp4");
                if (!File.Exists(coded25))
                {
                    var encode = new ProcessStartInfo(Path.Combine(repository, "runtime/media/ffmpeg.exe")) { UseShellExecute = false, CreateNoWindow = true, RedirectStandardError = true };
                    foreach (string arg in new[] { "-nostdin", "-v", "error", "-i", coded, "-vf", "setpts=24/25*PTS", "-r", "25", "-frames:v", "120", "-an", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18", "-profile:v", "main", "-pix_fmt", "yuv420p", "-g", "25", coded25 }) encode.ArgumentList.Add(arg);
                    using var encoder = Process.Start(encode)!; var errors = encoder.StandardError.ReadToEndAsync(); await encoder.WaitForExitAsync();
                    if (encoder.ExitCode != 0) throw new IOException(await errors);
                }
                currentDocument = (JsonNode)documentField.GetValue(film)!;
                var importedFrame = await client.Call("asset-import", new { path = coded25, role = "take" }, currentDocument["id"]!.ToString(), currentDocument["revision"]!.ToString());
                var frameAsset = importedFrame["project"]!["assets"]!.AsArray().Last()!;
                ((Grid)film.Content).Children.OfType<WrapPanel>().First().Children.OfType<Button>().First(b => b.Content?.ToString() == "Reload").RaiseEvent(new RoutedEventArgs(Button.ClickEvent));
                for (int i = 0; i < 100 && !((JsonNode)documentField.GetValue(film)!)["assets"]!.AsArray().Any(a => a?["id"]?.ToString() == frameAsset["id"]!.ToString()); i++) await Task.Delay(50);
                string managedFrame = Path.Combine(App.Root, "user/films", currentDocument["id"]!.ToString(), frameAsset["path"]!.ToString());
                await OpenPlayer(managedFrame);
                player.Pause(); window.Activate(); await Task.Delay(200);
                var rateClock = Stopwatch.StartNew(); seek.Value = 37; int rateShown = -1;
                while (rateClock.ElapsedMilliseconds < 1000) { await Task.Delay(10); rateShown = ReadFrameCode(player, handle); if (rateShown == 37) break; }
                Check(seek.Maximum == 119 && rateShown == 37 && rateClock.Elapsed.TotalMilliseconds <= 250, "Paused frame seeking follows the saved rational project rate instead of assuming 24 fps");
                frameResults.Add(new { fps = 25, target = 37, shown = rateShown, maximum = seek.Maximum, natural_duration_seconds = player.NaturalDuration.TimeSpan.TotalSeconds, milliseconds = rateClock.Elapsed.TotalMilliseconds });
                rateClock.Restart(); seek.Value = 119; rateShown = -1;
                while (rateClock.ElapsedMilliseconds < 1000) { await Task.Delay(10); rateShown = ReadFrameCode(player, handle); if (rateShown == 119) break; }
                Check(rateShown == 119 && rateClock.Elapsed.TotalMilliseconds <= 250, "Source frame metadata keeps the final encoded frame reachable despite rounded Windows duration");
                frameResults.Add(new { fps = 25, target = 119, shown = rateShown, maximum = seek.Maximum, milliseconds = rateClock.Elapsed.TotalMilliseconds });
                File.WriteAllText(Path.Combine(evidence, "exact-seek.json"), System.Text.Json.JsonSerializer.Serialize(new { frames = 120, fps = new[] { 24, 25 }, results = frameResults, method = "8-bit frame ID encoded in source pixels; actual paused player and public project edit/reload" }));
                player.Stop(); player.Close();
                window.Width = 960; window.Height = 540;
                await window.Dispatcher.InvokeAsync(() => { }, DispatcherPriority.ApplicationIdle);
                Check(window.ActualHeight <= 540 && window.ActualWidth <= 960, "Window fits the 1080p / 200-percent logical working area");
                var imageSmall = new RenderTargetBitmap(960, 540, 96, 96, PixelFormats.Pbgra32); imageSmall.Render(window);
                var small = new PngBitmapEncoder(); small.Frames.Add(BitmapFrame.Create(imageSmall));
                using (var stream = File.Create(Path.Combine(evidence, "Dark-film-960x540.png"))) small.Save(stream);
            }
            catch (Exception ex) { failures.Add(ex.ToString()); }
            finally
            {
                File.WriteAllText(Path.Combine(evidence, "result.json"), System.Text.Json.JsonSerializer.Serialize(new { checks, failures }));
                Environment.ExitCode = failures.Count == 0 ? 0 : 1;
                foreach (var failure in failures) Console.Error.WriteLine(failure);
                app.Shutdown();
            }
        };
        window.Show(); app.Run();
    }

    private static int ReadFrameCode(MediaElement player, IntPtr window)
    {
        if (GetForegroundWindow() != window) throw new IOException("Exact-frame test lost its owned foreground window.");
        double scale = Math.Min(player.ActualWidth / 320, player.ActualHeight / 180);
        double left = (player.ActualWidth - 320 * scale) / 2, top = (player.ActualHeight - 180 * scale) / 2;
        var screen = GetDC(IntPtr.Zero); int code = 0;
        try
        {
            for (int bit = 0; bit < 8; bit++)
            {
                var point = player.PointToScreen(new Point(left + (bit * 40 + 20) * scale, top + 90 * scale));
                uint color = GetPixel(screen, (int)Math.Round(point.X), (int)Math.Round(point.Y));
                if (color == uint.MaxValue) throw new IOException("Could not read owned video pixels.");
                if ((color & 255) + ((color >> 8) & 255) + ((color >> 16) & 255) > 3 * 127) code |= 1 << bit;
            }
            return code;
        }
        finally { ReleaseDC(IntPtr.Zero, screen); }
    }

    private static string Capture(FrameworkElement visual, IntPtr window)
    {
        if (GetForegroundWindow() != window) throw new IOException("Seek capture stopped because the owned test window is not foreground.");
        var top = visual.PointToScreen(new Point(0, 0));
        var bottom = visual.PointToScreen(new Point(visual.ActualWidth, visual.ActualHeight));
        int width = Math.Max(1, (int)(bottom.X-top.X)), height = Math.Max(1, (int)(bottom.Y-top.Y));
        var screen = GetDC(IntPtr.Zero); var memory = CreateCompatibleDC(screen); var bitmap = CreateCompatibleBitmap(screen, width, height);
        var old = SelectObject(memory, bitmap);
        try
        {
            if (!BitBlt(memory, 0, 0, width, height, screen, (int)top.X, (int)top.Y, 0x00CC0020)) throw new IOException("Owned video capture failed.");
            var source = Imaging.CreateBitmapSourceFromHBitmap(bitmap, IntPtr.Zero, Int32Rect.Empty, BitmapSizeOptions.FromEmptyOptions());
            source = new FormatConvertedBitmap(source, PixelFormats.Bgra32, null, 0);
            int stride = (source.PixelWidth*source.Format.BitsPerPixel+7)/8;
            var pixels = new byte[stride*source.PixelHeight]; source.CopyPixels(pixels, stride, 0);
            bool visible = false;
            for (int i = 0; i < pixels.Length; i += 4) if (pixels[i] > 5 || pixels[i+1] > 5 || pixels[i+2] > 5) { visible = true; break; }
            if (!visible) return "BLACK";
            return Convert.ToHexString(SHA256.HashData(pixels));
        }
        finally { SelectObject(memory, old); DeleteObject(bitmap); DeleteDC(memory); ReleaseDC(IntPtr.Zero, screen); }
    }
    [DllImport("user32.dll")] private static extern IntPtr GetForegroundWindow();
    [DllImport("gdi32.dll")] private static extern uint GetPixel(IntPtr dc, int x, int y);
    [DllImport("user32.dll")] private static extern IntPtr GetDC(IntPtr window);
    [DllImport("user32.dll")] private static extern int ReleaseDC(IntPtr window, IntPtr dc);
    [DllImport("gdi32.dll")] private static extern IntPtr CreateCompatibleDC(IntPtr dc);
    [DllImport("gdi32.dll")] private static extern IntPtr CreateCompatibleBitmap(IntPtr dc, int width, int height);
    [DllImport("gdi32.dll")] private static extern IntPtr SelectObject(IntPtr dc, IntPtr value);
    [DllImport("gdi32.dll")] private static extern bool DeleteObject(IntPtr value);
    [DllImport("gdi32.dll")] private static extern bool DeleteDC(IntPtr dc);
    [DllImport("gdi32.dll")] private static extern bool BitBlt(IntPtr destination, int x, int y, int width, int height, IntPtr source, int sx, int sy, int operation);
}
