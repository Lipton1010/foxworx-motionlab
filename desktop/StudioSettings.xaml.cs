using System.IO;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Controls;

namespace ImageStudio;

public partial class StudioSettings : UserControl
{
    private bool ready;
    public StudioSettings()
    {
        InitializeComponent();
        Appearance.SelectedItem = Appearance.Items.OfType<ComboBoxItem>().First(i => i.Content.ToString() == ThemeManager.Preference);
        Storage.Text = "Films: " + Path.Combine(App.Root, "user", "films") + "\nGenerated media: " + Path.Combine(App.Root, "output") + "\nManaged film assets and runner outputs are protected from ordinary recycling.";
        var path = Path.Combine(App.Root, "user", "production-tools.json");
        try
        {
            if (File.Exists(path))
            {
                var settings = JsonNode.Parse(File.ReadAllText(path)); FFmpeg.Text = settings?["ffmpeg"]?.ToString(); FFprobe.Text = settings?["ffprobe"]?.ToString();
            }
        }
        catch (Exception ex) when (ex is IOException or JsonException) { Status.Text = ex.Message; }
        ready = true;
    }
    private void AppearanceChanged(object sender, SelectionChangedEventArgs e)
    {
        if (!ready || Appearance.SelectedItem is not ComboBoxItem item) return;
        try { ThemeManager.Select(item.Content.ToString()!); Status.Text = "Appearance saved · " + ThemeManager.Preference; }
        catch (IOException ex) { Status.Text = "Appearance could not be saved: " + ex.Message; }
    }
    private async void CheckReadiness(object sender, RoutedEventArgs e)
    {
        try { Readiness.Text = (await new ProductionClient().Call("readiness")).ToJsonString(new JsonSerializerOptions { WriteIndented = true }); }
        catch (Exception ex) { Readiness.Text = ex.Message; }
    }
    private void SaveTools(object sender, RoutedEventArgs e)
    {
        try
        {
            foreach (var path in new[] { FFmpeg.Text, FFprobe.Text })
                if (!File.Exists(path)) throw new IOException("Select an existing executable: " + path);
            string target = Path.Combine(App.Root, "user", "production-tools.json");
            Directory.CreateDirectory(Path.GetDirectoryName(target)!);
            var settings = File.Exists(target) ? JsonNode.Parse(File.ReadAllText(target))!.AsObject() : new JsonObject();
            settings["ffmpeg"] = Path.GetFullPath(FFmpeg.Text); settings["ffprobe"] = Path.GetFullPath(FFprobe.Text);
            File.WriteAllText(target + ".tmp", settings.ToJsonString());
            File.Move(target + ".tmp", target, true); Status.Text = "Media tool paths saved.";
        }
        catch (Exception ex) when (ex is IOException or ArgumentException or JsonException or InvalidOperationException) { Status.Text = ex.Message; }
    }
}
