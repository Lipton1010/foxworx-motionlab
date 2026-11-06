using System.IO;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Windows;

namespace ImageStudio;

public static class ImageLibrary
{
    public static bool IsVideo(string path) => Path.GetExtension(path).ToLowerInvariant() is ".mp4" or ".mov" or ".webm" or ".mkv" or ".wmv";
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct ShellOperation
    {
        public IntPtr Window;
        public uint Function;
        [MarshalAs(UnmanagedType.LPWStr)] public string Source;
        [MarshalAs(UnmanagedType.LPWStr)] public string? Target;
        public ushort Flags;
        [MarshalAs(UnmanagedType.Bool)] public bool Aborted;
        public IntPtr Mappings;
        [MarshalAs(UnmanagedType.LPWStr)] public string? ProgressTitle;
    }

    [DllImport("shell32.dll", CharSet = CharSet.Unicode, EntryPoint = "SHFileOperationW")]
    private static extern int SHFileOperation(ref ShellOperation operation);

    private static string ValidatePath(string outputRoot, string imagePath)
    {
        string root = Path.TrimEndingDirectorySeparator(Path.GetFullPath(outputRoot));
        string path = Path.GetFullPath(imagePath);
        string relative = Path.GetRelativePath(root, path).Replace('\\', '/');
        if (relative.StartsWith("films/", StringComparison.OrdinalIgnoreCase) ||
            relative.StartsWith("production-jobs/", StringComparison.OrdinalIgnoreCase))
            throw new IOException("Managed film assets are protected. Manage them from their film project.");
        if (!path.StartsWith(root + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase) ||
            !(Path.GetExtension(path).Equals(".png", StringComparison.OrdinalIgnoreCase) || IsVideo(path)))
            throw new IOException("Only PNG images and videos inside the output folder can be deleted here.");
        if (!File.Exists(path)) throw new FileNotFoundException("This image no longer exists.", path);
        for (string? current = path; current != null; current = Path.GetDirectoryName(current))
        {
            if ((File.GetAttributes(current) & FileAttributes.ReparsePoint) != 0)
                throw new IOException("Linked images or folders cannot be deleted from the app.");
            if (current.Equals(root, StringComparison.OrdinalIgnoreCase)) break;
        }
        string metadata = path + ".json";
        if (File.Exists(metadata) && (File.GetAttributes(metadata) & FileAttributes.ReparsePoint) != 0)
            throw new IOException("This image's settings are linked to another file and cannot be deleted here.");
        return path;
    }

    public static bool CanRecycle(string outputRoot, string? imagePath)
    {
        if (imagePath == null) return false;
        try { ValidatePath(outputRoot, imagePath); return true; }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or ArgumentException) { return false; }
    }

    public static void Recycle(string outputRoot, string imagePath)
    {
        string path = ValidatePath(outputRoot, imagePath);
        RecycleFile(path);
        if (File.Exists(path + ".json")) RecycleFile(path + ".json");
    }

    private static void RecycleFile(string path)
    {
        const ushort AllowUndo = 0x0040, NoConfirmation = 0x0010, WantNukeWarning = 0x4000,
            Silent = 0x0004, NoConnectedElements = 0x2000;
        var operation = new ShellOperation
        {
            Window = Process.GetCurrentProcess().MainWindowHandle,
            Function = 3,
            Source = path + '\0', // The marshaler adds the second null required by the Shell file list.
            Flags = AllowUndo | NoConfirmation | WantNukeWarning | Silent | NoConnectedElements
        };
        int result = SHFileOperation(ref operation);
        if (operation.Aborted) throw new OperationCanceledException();
        if (result != 0) throw new IOException($"Windows could not recycle this file (error 0x{result:X}): {Path.GetFileName(path)}");
    }
}

public partial class MainWindow
{
    private void DeleteImage(object sender, RoutedEventArgs e)
    {
        if (busy || previewPath == null) return;
        string path = previewPath;
        string output = Path.Combine(App.Root, "output");
        try
        {
            if (!ImageLibrary.CanRecycle(output, path)) throw new IOException("Select a generated image inside the output folder to delete it.");
            var linked = references.Where(image => Path.GetFullPath(image.Path).Equals(path, StringComparison.OrdinalIgnoreCase)).ToArray();
            bool firstFrame = videoSource != null && Path.GetFullPath(videoSource).Equals(path, StringComparison.OrdinalIgnoreCase);
            string message = "Move “" + Path.GetFileName(path) + "” and its saved settings to the Recycle Bin?";
            if (linked.Length > 0) message += "\n\nThis image is used by " + linked.Length + " current reference(s). Those references will also be removed.";
            if (firstFrame) message += "\n\nThis image is also your video's first frame. That selection will be cleared.";
            message += "\n\nFiles in the Recycle Bin can be restored. Windows will warn if permanent deletion is required.";
            if (!StudioDialog.Confirm(this, message, "Delete image?")) return;
            try
            {
                ImageLibrary.Recycle(output, path);
                SetStatus("Image and saved settings moved from the output folder to the Recycle Bin.");
            }
            finally
            {
                if (!File.Exists(path))
                {
                    foreach (var reference in linked) references.Remove(reference);
                    if (firstFrame) { videoSource = null; VideoSourcePreview.Source = null; VideoSourceName.Text = "Choose an image for the first frame"; VideoSourceName.ToolTip = null; }
                    RefreshReferences();
                    previewPath = null; Preview.Source = null; EmptyPreview.Visibility = Visibility.Visible; ImageInfo.Text = "";
                    OpenButton.IsEnabled = SaveButton.IsEnabled = UseButton.IsEnabled = AnimateButton.IsEnabled = DeleteButton.IsEnabled = false;
                    LoadGallery();
                    if (Gallery.Items.Count > 0) Gallery.SelectedIndex = 0;
                    SaveSettings();
                }
            }
        }
        catch (OperationCanceledException) { SetStatus(File.Exists(path) ? "Deletion cancelled." : "Image removed; its saved settings were kept."); }
        catch (Exception ex) { ShowError(ex); }
    }

    private void DeleteVideo(object sender, RoutedEventArgs e)
    {
        if (busy || videoPreview == null) return;
        string path = videoPreview;
        string output = Path.Combine(App.Root, "output");
        try
        {
            if (!ImageLibrary.CanRecycle(output, path)) throw new IOException("Select a video inside the output folder to delete it.");
            string message = "Move “" + Path.GetFileName(path) + "” and its saved settings to the Recycle Bin?\n\nFiles in the Recycle Bin can be restored. Windows will warn if permanent deletion is required.";
            if (!StudioDialog.Confirm(this, message, "Delete video?")) return;
            videoTimer.Stop(); VideoPlayer.Close(); videoPlaying = false; VideoPlayButton.Content = "Play";
            try
            {
                ImageLibrary.Recycle(output, path);
                SetStatus("Video and saved settings moved from the output folder to the Recycle Bin.");
            }
            finally
            {
                if (!File.Exists(path))
                {
                    videoPreview = null; VideoPlayer.Source = null; VideoInfo.Text = "";
                    EmptyVideo.Visibility = Visibility.Visible;
                    VideoPlayButton.IsEnabled = VideoSeek.IsEnabled = VideoOpenButton.IsEnabled = VideoSaveButton.IsEnabled = VideoDeleteButton.IsEnabled = false;
                    LoadVideoGallery();
                    if (VideoGallery.Items.Count > 0) VideoGallery.SelectedIndex = 0;
                    SaveWorkspace();
                }
                else ShowVideo(path);
            }
        }
        catch (OperationCanceledException) { SetStatus(File.Exists(path) ? "Deletion cancelled." : "Video removed; its saved settings were kept."); }
        catch (Exception ex) { ShowError(ex); }
    }
}
