using System.IO;
using System.Runtime.InteropServices;
using System.Text.Json;
using System.Windows;
using System.Windows.Interop;
using System.Windows.Media;
using Microsoft.Win32;

namespace ImageStudio;

public static class ThemeManager
{
    public static string Preference { get; private set; } = "Dark";
    public static bool IsDark { get; private set; } = true;
    private static bool initialized;
    private static readonly string PathName = Path.Combine(App.Root, "user", "appearance.json");
    public static event Action? Changed;
    private static readonly string[] Keys = ["Rail", "Window", "Panel", "Input", "Elevated", "Border", "InputBorder", "Muted", "Text", "Accent", "AccentText", "Selected", "SelectedText", "Error", "Success", "Warning", "CheckerA", "CheckerB", "Preview", "Track", "Waveform"];
    private static readonly string[] Dark = ["#141B27", "#101722", "#1C2635", "#131E2D", "#29364A", "#64768E", "#8193AC", "#B7C5D8", "#F1F5FC", "#8AB8FF", "#10233F", "#29466B", "#EDF5FF", "#FFACB8", "#94DDB3", "#F5CE86", "#263244", "#1C2635", "#10141C", "#263244", "#9BC8FF"];
    private static readonly string[] Light = ["#E9EDF4", "#F4F6FA", "#FFFFFF", "#F7F9FC", "#EDF1F8", "#8896AA", "#78879D", "#526175", "#19263B", "#1763D9", "#FFFFFF", "#D8E7FF", "#124FAE", "#A51D35", "#17683A", "#805315", "#F3F5F9", "#E0E5EE", "#F3F5F9", "#E0E5EE", "#1763D9"];

    public static void Initialize()
    {
        if (initialized) return;
        initialized = true;
        try
        {
            if (File.Exists(PathName)) Preference = JsonSerializer.Deserialize<string>(File.ReadAllText(PathName)) ?? "Dark";
        }
        catch (Exception ex) when (ex is IOException or JsonException) { Preference = "Dark"; }
        if (Preference is not ("Dark" or "Light" or "System")) Preference = "Dark";
        SystemEvents.UserPreferenceChanged += SystemChanged;
        SystemParameters.StaticPropertyChanged += ParametersChanged;
        EventManager.RegisterClassHandler(typeof(Window), FrameworkElement.LoadedEvent, new RoutedEventHandler((sender, _) => ApplyTitleBar((Window)sender)));
        Apply();
    }

    public static void Select(string preference)
    {
        if (preference is not ("Dark" or "Light" or "System")) throw new ArgumentException("Choose Dark, Light or System.");
        Directory.CreateDirectory(Path.GetDirectoryName(PathName)!);
        var temporary = PathName + "." + Guid.NewGuid().ToString("N") + ".tmp";
        File.WriteAllText(temporary, JsonSerializer.Serialize(preference));
        File.Move(temporary, PathName, true);
        Preference = preference;
        Apply();
    }

    private static void SystemChanged(object sender, UserPreferenceChangedEventArgs e) => Refresh();
    private static void ParametersChanged(object? sender, System.ComponentModel.PropertyChangedEventArgs e) => Refresh();
    private static void Refresh() => Application.Current?.Dispatcher.BeginInvoke(Apply);
    private static void Apply()
    {
        bool systemDark = true;
        using (var key = Registry.CurrentUser.OpenSubKey(@"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"))
            systemDark = key?.GetValue("AppsUseLightTheme") is not int value || value == 0;
        IsDark = Preference == "Dark" || Preference == "System" && systemDark;
        var resources = Application.Current.Resources;
        for (int i = 0; i < Keys.Length; i++)
        {
            Color color = (Color)ColorConverter.ConvertFromString((IsDark ? Dark : Light)[i]);
            if (SystemParameters.HighContrast)
                color = Keys[i] switch
                {
                    "Accent" or "Selected" => SystemColors.HighlightColor,
                    "AccentText" or "SelectedText" => SystemColors.HighlightTextColor,
                    "Text" or "Muted" or "Error" or "Success" or "Warning" or "Border" or "InputBorder" or "Waveform" => SystemColors.WindowTextColor,
                    _ => SystemColors.WindowColor
                };
            var brush = new SolidColorBrush(color); brush.Freeze();
            resources[Keys[i] + "Brush"] = brush;
        }
        // Shared Freezable drawings do not reliably re-resolve nested resources after freezing.
        var tiles = new DrawingGroup();
        tiles.Children.Add(new GeometryDrawing((Brush)resources["CheckerABrush"], null, new RectangleGeometry(new Rect(0, 0, 24, 24))));
        tiles.Children.Add(new GeometryDrawing((Brush)resources["CheckerBBrush"], null, Geometry.Parse("M0,0 H12 V12 H0 Z M12,12 H24 V24 H12 Z")));
        var checker = new DrawingBrush(tiles) { TileMode = TileMode.Tile, Viewport = new Rect(0, 0, 24, 24), ViewportUnits = BrushMappingMode.Absolute, Viewbox = new Rect(0, 0, 24, 24), ViewboxUnits = BrushMappingMode.Absolute };
        checker.Freeze(); resources["CheckerboardBrush"] = checker;
        foreach (Window window in Application.Current.Windows) ApplyTitleBar(window);
        Changed?.Invoke();
    }

    public static void ApplyTitleBar(Window window)
    {
        var handle = new WindowInteropHelper(window).Handle;
        if (handle == IntPtr.Zero) return;
        int enabled = IsDark && !SystemParameters.HighContrast ? 1 : 0;
        DwmSetWindowAttribute(handle, 20, ref enabled, sizeof(int));
    }
    [DllImport("dwmapi.dll")]
    private static extern int DwmSetWindowAttribute(IntPtr window, int attribute, ref int value, int size);
}
