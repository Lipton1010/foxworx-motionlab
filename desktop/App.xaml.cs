using System.IO;
using System.Windows;

namespace ImageStudio;

public partial class App : Application
{
    static App() { }
    private Mutex? instance;
    protected override void OnStartup(StartupEventArgs e)
    {
        // Avoid a blank WPF surface on affected graphics drivers; model inference still uses CUDA.
        System.Windows.Media.RenderOptions.ProcessRenderMode = System.Windows.Interop.RenderMode.SoftwareOnly;
        instance = new Mutex(true, "Local\\ImageStudioDesktop", out var first);
        if (!first) { MessageBox.Show("Image Studio is already open. Select its window in the taskbar.", "Image Studio"); Shutdown(); return; }
        ThemeManager.Initialize();
        base.OnStartup(e);
    }
    public static string Root { get; } = FindRoot();
    public static string PythonPath
    {
        get
        {
            string bundled = Path.Combine(Root, "runtime", "ComfyUI_windows_portable", "python_embeded", "python.exe");
            if (File.Exists(bundled)) return bundled;
            const string shared = @"D:\ComfyUI\python_embeded\python.exe";
            if (File.Exists(shared) && !File.Exists(Path.Combine(Root, "portable.json"))) return shared;
            throw new IOException("The local engine is not installed. Close Image Studio and run Setup.cmd in its folder.");
        }
    }
    public static string ProductionPythonPath => File.Exists(Path.Combine(Root, "runtime", "production-python", "python.exe"))
        ? Path.Combine(Root, "runtime", "production-python", "python.exe") : PythonPath;
    private static string FindRoot()
    {
        if (Environment.GetEnvironmentVariable("IMAGE_STUDIO_ROOT") is { } explicitRoot &&
            Path.IsPathFullyQualified(explicitRoot) && File.Exists(Path.Combine(explicitRoot, "launch.py"))) return Path.GetFullPath(explicitRoot);
        for (var dir = new DirectoryInfo(AppContext.BaseDirectory); dir != null; dir = dir.Parent)
            if (File.Exists(Path.Combine(dir.FullName, "launch.py"))) return dir.FullName;
        return AppContext.BaseDirectory;
    }
}
