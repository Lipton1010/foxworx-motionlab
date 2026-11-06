using ImageStudio;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Text.Json;
using System.Windows;
using System.Windows.Automation;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Interop;
using System.Windows.Media;
using System.Windows.Media.Imaging;

internal static class AcceptanceChecks
{
    [StructLayout(LayoutKind.Sequential)] private struct HighContrast { public uint Size, Flags; public IntPtr Scheme; }
    [StructLayout(LayoutKind.Sequential)] private struct KeyboardInput { public ushort Key, Scan; public uint Flags, Time; public IntPtr Extra; }
    [StructLayout(LayoutKind.Explicit, Size = 32)] private struct InputUnion { [FieldOffset(0)] public KeyboardInput Keyboard; }
    [StructLayout(LayoutKind.Sequential)] private struct NativeInput { public uint Type; public InputUnion Data; }
    [DllImport("user32.dll", SetLastError = true)] private static extern bool SystemParametersInfo(uint action, uint parameter, ref HighContrast value, uint flags);
    [DllImport("user32.dll")] private static extern void keybd_event(byte key, byte scan, uint flags, UIntPtr extra);
    [DllImport("user32.dll", SetLastError = true)] private static extern uint SendInput(uint count, NativeInput[] inputs, int size);
    [DllImport("user32.dll")] private static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] private static extern uint GetWindowThreadProcessId(IntPtr window, out uint process);
    [DllImport("user32.dll")] private static extern uint GetDpiForWindow(IntPtr window);

    public static async Task Run(MainWindow window, App app, string evidence, int? physicalScale = null)
    {
        var checks = new List<string>(); var failures = new List<string>();
        var handle = new WindowInteropHelper(window).Handle;
        var tabs = (TabControl)window.FindName("WorkspaceTabs");
        void Check(bool condition, string message) { Console.WriteLine((condition ? "PASS: " : "FAIL: ") + message); (condition ? checks : failures).Add(message); }
        void OwnFocus()
        {
            GetWindowThreadProcessId(GetForegroundWindow(), out uint process);
            if (process != Environment.ProcessId) throw new IOException("Keyboard test stopped because another application's window is foreground.");
        }
        async Task Press(byte key, bool control = false, bool shift = false)
        {
            OwnFocus();
            if (control) keybd_event(0x11, 0, 0, UIntPtr.Zero);
            if (shift) keybd_event(0x10, 0, 0, UIntPtr.Zero);
            try { keybd_event(key, 0, 0, UIntPtr.Zero); await Task.Delay(20); keybd_event(key, 0, 2, UIntPtr.Zero); }
            finally { if (shift) keybd_event(0x10, 0, 2, UIntPtr.Zero); if (control) keybd_event(0x11, 0, 2, UIntPtr.Zero); }
            await Task.Delay(30);
        }
        async Task Reach(Func<DependencyObject?, bool> matches, bool reverse = false)
        {
            var focus = new List<string>();
            for (int i = 0; i < 160; i++)
            {
                if (matches(Keyboard.FocusedElement as DependencyObject)) return;
                if (i < 45 && Keyboard.FocusedElement is FrameworkElement item) focus.Add(item.GetType().Name + ":" + item.Name + ":" + (item is Button b ? b.Content : AutomationProperties.GetName(item)));
                await Press(0x09, shift: reverse);
            }
            throw new IOException("Requested control was not reachable with Tab: " + string.Join(" / ", focus));
        }
        async Task Type(string value)
        {
            await Press(0x41, control: true);
            foreach (char letter in value)
            {
                OwnFocus();
                var inputs = new[] {
                    new NativeInput { Type = 1, Data = new InputUnion { Keyboard = new KeyboardInput { Scan = letter, Flags = 4 } } },
                    new NativeInput { Type = 1, Data = new InputUnion { Keyboard = new KeyboardInput { Scan = letter, Flags = 6 } } } };
                if (SendInput(2, inputs, Marshal.SizeOf<NativeInput>()) != 2) throw new Win32Exception(Marshal.GetLastWin32Error());
            }
            await Task.Delay(100);
        }
        async Task Edit(string name, string value)
        {
            await Reach(d => d is TextBox && AutomationProperties.GetName(d) == name);
            await Type(value);
            Check(Keyboard.FocusedElement is TextBox box && box.Text == value, name + " accepts actual keyboard text after Tab navigation");
        }
        async Task Button(string content)
        {
            await Reach(d => d is Button button && button.Content?.ToString() == content, reverse: content == "New film");
            await Press(0x20);
        }
        window.Activate(); await Task.Delay(200);
        if (physicalScale is int scalePercent)
        {
            double scale = scalePercent / 100d;
            window.Width = 1920 / scale; window.Height = 1080 / scale; window.Left = 0; window.Top = 0;
            Check(GetDpiForWindow(handle) == 96 * scale, "Real native window DPI matches " + scalePercent + "% Windows display scaling");
            var targets = new[] { "Image description", "Video description", "New film title", "Search output library", "Appearance", "", "Subject and action", "" };
            for (int i = 0; i < tabs.Items.Count; i++)
            {
                var tab = (TabItem)tabs.Items[i]; tab.Focus(); await Task.Delay(100);
                try
                {
                    await Reach(d => i == 5 ? d is Button button && button.Content?.ToString() == "+  Add images" :
                        i == 7 ? d is Button refresh && refresh.Content?.ToString() == "Refresh library" :
                        d != null && AutomationProperties.GetName(d) == targets[i]);
                    var focused = (FrameworkElement)Keyboard.FocusedElement;
                    var bounds = focused.TransformToAncestor(window).TransformBounds(new Rect(focused.RenderSize));
                    Check(bounds.Left >= -1 && bounds.Top >= -1 && bounds.Right <= window.ActualWidth + 1 && bounds.Bottom <= window.ActualHeight + 1,
                        AutomationProperties.GetName(tab) + " primary input/action is keyboard reachable inside the 1080p working size at actual " + scalePercent + "%");
                    Save(window, Path.Combine(evidence, $"physical-{scalePercent}-workspace-{i}.png"), scale);
                }
                catch (Exception ex) { Check(false, AutomationProperties.GetName(tab) + ": " + ex.Message); }
            }
            File.WriteAllText(Path.Combine(evidence, "physical-" + scalePercent + ".json"), JsonSerializer.Serialize(new { checks, failures, native_window_dpi = GetDpiForWindow(handle), logical_width = window.ActualWidth, logical_height = window.ActualHeight }));
            if (failures.Count > 0) throw new IOException("Physical DPI checks failed: " + string.Join("; ", failures));
            return;
        }
        // Bootstrap focus on each navigation item; all task navigation/input thereafter uses OS keyboard events.
        foreach (TabItem tab in tabs.Items)
        {
            string name = AutomationProperties.GetName(tab);
            try
            {
                tab.Focus(); await Task.Delay(200);
                Check(tab.IsSelected && window.IsKeyboardFocusWithin, name + " navigation selection retains keyboard focus in the window");
                switch (name)
                {
                    case "Create · Still images": await Edit("Image description", "keyboard still fixture"); break;
                    case "Create · Videos": await Edit("Video description", "keyboard video fixture"); break;
                    case "Films":
                        await Edit("New film title", "KEYBOARD FILM FIXTURE"); await Button("New film"); await Task.Delay(800);
                        Check(((ComboBox)((FilmsWorkspace)window.FindName("FilmWorkspace")).FindName("Projects")).Items.Count > 0, "Films creates a persisted project with keyboard controls"); break;
                    case "Library": await Edit("Search output library", "keyboard"); break;
                    case "Settings":
                        await Reach(d => d is ComboBox && AutomationProperties.GetName(d) == "Appearance");
                        await Press(0x24); await Press(0x28); Check(ThemeManager.Preference == "Light", "Settings selects Light with keyboard");
                        await Press(0x23); Check(ThemeManager.Preference == "System", "Settings selects System with keyboard"); break;
                    case "References":
                        await Button("+  Add images"); await Task.Delay(400);
                        Check(GetForegroundWindow() != handle, "References opens its real OS file picker with keyboard");
                        await Press(0x1B); await Task.Delay(300); Check(GetForegroundWindow() == handle, "References cancels its OS file picker with Escape"); break;
                    case "Prompt Builder":
                        await Edit("Subject and action", "keyboard builder fixture"); await Button("Build prompt →");
                        Check(((TextBox)window.FindName("BuiltPrompt")).Text.Contains("keyboard builder fixture"), "Prompt Builder composes its draft using keyboard action"); break;
                    case "Models & LoRAs":
                        await Button("Refresh library"); await Task.Delay(1200);
                        Check(!((TextBlock)window.FindName("ModelsSummary")).Text.Contains("Reading"), "Models exposes and completes keyboard refresh/readiness"); break;
                }
            }
            catch (Exception ex) { Check(false, name + ": " + ex.Message); }
        }
        var original = new HighContrast { Size = (uint)Marshal.SizeOf<HighContrast>() };
        if (!SystemParametersInfo(0x42, original.Size, ref original, 0)) throw new Win32Exception(Marshal.GetLastWin32Error());
        File.WriteAllText(Path.Combine(evidence, "high-contrast-before.json"), JsonSerializer.Serialize(new { original.Flags, preference = ThemeManager.Preference }));
        string preference = ThemeManager.Preference;
        bool restored = false;
        try
        {
            var enabled = original; enabled.Flags |= 1;
            if (!SystemParametersInfo(0x43, enabled.Size, ref enabled, 2)) throw new Win32Exception(Marshal.GetLastWin32Error());
            var watch = Stopwatch.StartNew();
            while (!SystemParameters.HighContrast && watch.Elapsed.TotalSeconds < 10) await Task.Delay(100);
            await Task.Delay(500);
            Check(SystemParameters.HighContrast, "Real Windows high-contrast transition reaches WPF");
            Check(((SolidColorBrush)app.Resources["TextBrush"]).Color == SystemColors.WindowTextColor && ((SolidColorBrush)app.Resources["PanelBrush"]).Color == SystemColors.WindowColor,
                "Live high contrast applies actual system foreground/background colours");
            Check(ThemeManager.Preference == preference, "High contrast preserves the saved appearance preference");
            var palette = new Dictionary<string, string>();
            foreach (string key in new[] { "Text", "Panel", "Selected", "SelectedText", "Accent", "AccentText" }) palette[key] = ((SolidColorBrush)app.Resources[key + "Brush"]).Color.ToString();
            var film = (FilmsWorkspace)window.FindName("FilmWorkspace");
            Check(((SolidColorBrush)film.Foreground).Color == SystemColors.WindowTextColor && ((SolidColorBrush)((TextBlock)film.FindName("Status")).Foreground).Color == SystemColors.WindowTextColor,
                "Actual Films control and queue text follow the live high-contrast foreground");
            File.WriteAllText(Path.Combine(evidence, "high-contrast-palette.json"), JsonSerializer.Serialize(palette));
            foreach (TabItem tab in tabs.Items)
            {
                tabs.SelectedItem = tab; await Task.Delay(80); window.UpdateLayout();
                Save(window, Path.Combine(evidence, "high-contrast-" + tabs.SelectedIndex + ".png"), 1);
            }
        }
        catch (Exception ex) { Check(false, "Windows high contrast: " + ex.Message); }
        finally
        {
            if (!SystemParametersInfo(0x43, original.Size, ref original, 2)) throw new Win32Exception(Marshal.GetLastWin32Error());
            var watch = Stopwatch.StartNew();
            while (SystemParameters.HighContrast != ((original.Flags & 1) != 0) && watch.Elapsed.TotalSeconds < 10) await Task.Delay(100);
            var actual = new HighContrast { Size = original.Size };
            if (!SystemParametersInfo(0x42, actual.Size, ref actual, 0)) throw new Win32Exception(Marshal.GetLastWin32Error());
            restored = (actual.Flags & 1) == (original.Flags & 1) && SystemParameters.HighContrast == ((original.Flags & 1) != 0);
            Check(restored, "Original Windows high-contrast state is restored");
        }
        foreach (double scale in new[] { 1d, 1.5, 2d })
        {
            window.Width = 1920 / scale; window.Height = 1080 / scale; window.UpdateLayout();
            foreach (TabItem tab in tabs.Items)
            {
                tabs.SelectedItem = tab; await Task.Delay(50); window.UpdateLayout();
                Save(window, Path.Combine(evidence, $"rendered-{scale * 100:0}-workspace-{tabs.SelectedIndex}.png"), scale);
            }
            Check(window.ActualWidth <= 1920 / scale + 1 && window.ActualHeight <= 1080 / scale + 1, "All workspaces render at the " + scale * 100 + "% logical working size");
        }
        File.WriteAllText(Path.Combine(evidence, "accessibility.json"), JsonSerializer.Serialize(new { checks, failures,
            native_window_dpi = GetDpiForWindow(handle), high_contrast_restored = restored,
            keyboard_method = "Navigation-item focus bootstrap; task uses real OS Tab, keys and Unicode SendInput; no task Invoke/SetValue",
            dpi_limit = "100/150/200% raster and logical-size coverage; only native_window_dpi is a physical OS scale measurement" }));
        if (failures.Count > 0) throw new IOException("Accessibility checks failed: " + string.Join("; ", failures));
    }
    private static void Save(FrameworkElement window, string path, double scale)
    {
        var bitmap = new RenderTargetBitmap((int)(window.ActualWidth * scale), (int)(window.ActualHeight * scale), 96 * scale, 96 * scale, PixelFormats.Pbgra32);
        bitmap.Render(window); var encoder = new PngBitmapEncoder(); encoder.Frames.Add(BitmapFrame.Create(bitmap));
        using var file = File.Create(path); encoder.Save(file);
    }
}
