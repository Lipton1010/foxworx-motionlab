using System.Diagnostics;
using System.IO;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Windows.Automation;
using System.Runtime.InteropServices;

internal static class Program
{
    [DllImport("user32.dll")]
    private static extern bool PostMessage(IntPtr window, uint message, IntPtr key, IntPtr data);
    [DllImport("user32.dll")]
    private static extern bool SetForegroundWindow(IntPtr window);
    [DllImport("user32.dll")]
    private static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")]
    private static extern void keybd_event(byte key, byte scan, uint flags, UIntPtr extra);
    [DllImport("dwmapi.dll")]
    private static extern int DwmGetWindowAttribute(IntPtr window, int attribute, out int value, int size);
    [STAThread]
    static async Task Main(string[] args)
    {
        string package = Path.GetFullPath(args[0]);
        string evidence = Path.GetFullPath(args[1]);
        var failures = new List<string>();
        int checks = 0;
        void Check(bool condition, string message) { checks++; Console.WriteLine((condition ? "PASS: " : "FAIL: ") + message); if (!condition) failures.Add(message); }
        var start = new ProcessStartInfo(Path.Combine(package, "app", "Image Studio.exe")) { UseShellExecute = false, WorkingDirectory = package };
        bool pilot = args.Length > 3 && args[2] == "--pilot";
        if (pilot) start.Environment["IMAGE_STUDIO_ROOT"] = Path.GetFullPath(args[3]);
        using var process = Process.Start(start) ?? throw new IOException("Published app did not launch.");
        try
        {
            AutomationElement? window = null;
            for (int i = 0; i < 100 && window == null; i++)
            {
                if (process.HasExited) throw new IOException("Published app exited before creating its window.");
                process.Refresh();
                if (process.MainWindowHandle != IntPtr.Zero) window = AutomationElement.FromHandle(process.MainWindowHandle);
                else await Task.Delay(100);
            }
            if (window == null) throw new IOException("Published WPF window did not appear.");
            AutomationElement Find(string name, ControlType? type = null) => window.FindFirst(TreeScope.Descendants,
                type == null ? new PropertyCondition(AutomationElement.NameProperty, name) : new AndCondition(new PropertyCondition(AutomationElement.NameProperty, name), new PropertyCondition(AutomationElement.ControlTypeProperty, type)))
                ?? throw new IOException("Missing published control: " + name);
            void Click(string name) => ((InvokePattern)Find(name, ControlType.Button).GetCurrentPattern(InvokePattern.Pattern)).Invoke();
            void SelectTab(string name) => ((SelectionItemPattern)Find(name, ControlType.TabItem).GetCurrentPattern(SelectionItemPattern.Pattern)).Select();
            Check(window.Current.Name == "FoxWorx MotionLab", "Fresh extracted executable has the FoxWorx MotionLab native window title");
            Check(DwmGetWindowAttribute(process.MainWindowHandle, 20, out int darkTitle, sizeof(int)) == 0 && darkTitle == 1, "Published app applies its default Dark native title-bar attribute");
            if (pilot)
            {
                string studio = Path.GetFullPath(args[3]);
                var controller = JsonNode.Parse(File.ReadAllText(Path.Combine(Directory.GetParent(studio)!.FullName, "controller.json")))!;
                var cut = controller["multi_scene_sound_cut"]!;
                SelectTab("Films"); await Task.Delay(700);
                var projects = Find("Film project", ControlType.ComboBox);
                ((ExpandCollapsePattern)projects.GetCurrentPattern(ExpandCollapsePattern.Pattern)).Expand(); await Task.Delay(150);
                AutomationElement? film = null;
                string[] names = [];
                for (int i = 0; i < 40 && film == null; i++)
                {
                    var choices = projects.FindAll(TreeScope.Descendants, new PropertyCondition(AutomationElement.ControlTypeProperty, ControlType.ListItem))
                        .Cast<AutomationElement>().ToArray();
                    names = choices.Select(e => e.Current.Name).ToArray();
                    film = choices.FirstOrDefault(e => e.Current.Name.Contains("FOLLOW-UP VALIDATION"));
                    if (film == null) await Task.Delay(250);
                }
                if (film == null) throw new IOException("Live project not exposed. List items: " + string.Join(" | ", names));
                ((SelectionItemPattern)film.GetCurrentPattern(SelectionItemPattern.Pattern)).Select();
                ((ExpandCollapsePattern)projects.GetCurrentPattern(ExpandCollapsePattern.Pattern)).Collapse(); await Task.Delay(1000);
                var shots = Find("Film shots", ControlType.List);
                Check(shots.FindAll(TreeScope.Children, new PropertyCondition(AutomationElement.ControlTypeProperty, ControlType.ListItem)).Count == 3,
                    "Published native app opens the same three-generated-shot project as the CLI");
                SelectTab("Review"); await Task.Delay(200);
                var cuts = Find("Review cuts", ControlType.List);
                if (cuts.TryGetCurrentPattern(ScrollPattern.Pattern, out var pattern) && ((ScrollPattern)pattern).Current.VerticallyScrollable)
                    ((ScrollPattern)pattern).SetScrollPercent(ScrollPattern.NoScroll, 100);
                await Task.Delay(100);
                var rows = cuts.FindAll(TreeScope.Descendants, new PropertyCondition(AutomationElement.ControlTypeProperty, ControlType.ListItem));
                ((SelectionItemPattern)rows[rows.Count - 1].GetCurrentPattern(SelectionItemPattern.Pattern)).Select();
                await Task.Delay(500);
                Check(window.FindAll(TreeScope.Descendants, new PropertyCondition(AutomationElement.ControlTypeProperty, ControlType.Text))
                    .Cast<AutomationElement>().Any(e => e.Current.Name.Contains(cut["sha256"]!.ToString())),
                    "Published Review selects the exact immutable multi-scene sound cut by its displayed SHA-256");
                var seek = (RangeValuePattern)Find("Film frame seek", ControlType.Slider).GetCurrentPattern(RangeValuePattern.Pattern);
                var watch = Stopwatch.StartNew(); var positions = new List<double>();
                while (watch.Elapsed.TotalSeconds < 20)
                {
                    positions.Add(seek.Current.Value);
                    if (positions[^1] >= 359) break;
                    await Task.Delay(300);
                }
                Check(seek.Current.Maximum == 359 && positions.Any(p => p > 20) && positions[^1] >= 359 && watch.Elapsed.TotalSeconds >= 10,
                    "Actual published WPF player traverses the full 15-second encoded cut at playback speed");
                Click("Pause");
                File.WriteAllText(Path.Combine(evidence, "published-pilot-playback.json"), JsonSerializer.Serialize(new {
                    cut_sha256 = cut["sha256"]!.ToString(), frames = 360, fps = 24, seconds_observed = watch.Elapsed.TotalSeconds, positions,
                    scope = "Real UI project/cut selection and timed encoded playback; no human listening or motion/seam approval" }));
                return;
            }
            SelectTab("Films"); await Task.Delay(800);
            ((ValuePattern)Find("New film title", ControlType.Edit).GetCurrentPattern(ValuePattern.Pattern)).SetValue("PUBLISHED UI / CLI FIXTURE");
            Click("New film"); await Task.Delay(1200); Click("+ Shot"); await Task.Delay(800);
            var python = new ProcessStartInfo(Path.Combine(package, "runtime/production-python/python.exe")) { UseShellExecute = false, CreateNoWindow = true, RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true };
            python.ArgumentList.Add(Path.Combine(package, "desktop/production_service.py")); python.ArgumentList.Add(package);
            using (var helper = Process.Start(python)!)
            {
                var output = helper.StandardOutput.ReadToEndAsync(); var errors = helper.StandardError.ReadToEndAsync();
                await helper.StandardInput.WriteAsync(JsonSerializer.Serialize(new { version = 1, operation = "list", request_id = "published-ui-cli-list", payload = new { } })); helper.StandardInput.Close();
                await helper.WaitForExitAsync();
                var reply = JsonNode.Parse(await output)!;
                Check(reply["ok"]?.GetValue<bool>() == true, "Fresh embedded helper answers outside the developer checkout");
                var project = reply["result"]!.AsArray().FirstOrDefault(p => p?["title"]?.ToString() == "PUBLISHED UI / CLI FIXTURE");
                Check(project?["shots"]?.GetValue<int>() == 1, "A film and shot created with published UI controls are visible through the same CLI");
                _ = await errors;
            }
            SelectTab("Settings"); await Task.Delay(300);
            var appearance = Find("Appearance", ControlType.ComboBox);
            ((ExpandCollapsePattern)appearance.GetCurrentPattern(ExpandCollapsePattern.Pattern)).Expand(); await Task.Delay(200);
            var light = AutomationElement.RootElement.FindFirst(TreeScope.Descendants, new AndCondition(new PropertyCondition(AutomationElement.ProcessIdProperty, process.Id), new PropertyCondition(AutomationElement.NameProperty, "Light"), new PropertyCondition(AutomationElement.ControlTypeProperty, ControlType.ListItem)));
            if (light == null) throw new IOException("Published appearance popup did not expose Light.");
            ((ExpandCollapsePattern)appearance.GetCurrentPattern(ExpandCollapsePattern.Pattern)).Collapse();
            SetForegroundWindow(process.MainWindowHandle);
            appearance.SetFocus();
            await Task.Delay(100);
            foreach (byte key in new byte[] { 0x24, 0x28, 0x0D })
            {
                if (GetForegroundWindow() != process.MainWindowHandle) throw new IOException("Test window lost focus; refusing global key input.");
                keybd_event(key, 0, 0, UIntPtr.Zero);
                keybd_event(key, 0, 2, UIntPtr.Zero);
                await Task.Delay(100);
            }
            await Task.Delay(300);
            Check(File.ReadAllText(Path.Combine(package, "user/appearance.json")).Contains("Light"), "Published app switches and persists Light through its real popup");
            Check(DwmGetWindowAttribute(process.MainWindowHandle, 20, out int lightTitle, sizeof(int)) == 0 && lightTitle == 0, "Published app updates its native title bar live for Light");
            ((ExpandCollapsePattern)appearance.GetCurrentPattern(ExpandCollapsePattern.Pattern)).Collapse();
        }
        catch (Exception ex) { failures.Add(ex.ToString()); }
        finally
        {
            process.CloseMainWindow();
            using var wait = new CancellationTokenSource(TimeSpan.FromSeconds(10));
            try { await process.WaitForExitAsync(wait.Token); }
            catch (OperationCanceledException) { if (!process.HasExited) process.Kill(entireProcessTree: true); }
            Directory.CreateDirectory(evidence);
            File.WriteAllText(Path.Combine(evidence, pilot ? "published-pilot-ui.json" : "published-ui.json"), JsonSerializer.Serialize(new { checks, failures, package }));
            foreach (var failure in failures) Console.Error.WriteLine(failure);
            Environment.ExitCode = failures.Count == 0 ? 0 : 1;
        }
    }
}
