using System.IO;
using System.Windows;
using System.Windows.Controls;

namespace ImageStudio;

public partial class StudioLibrary : UserControl
{
    private record Item(string Path, string Name);
    private Item[] items = [];
    public FilmsWorkspace? Films { get; set; }
    public StudioLibrary() { InitializeComponent(); Loaded += (_, _) => Load(); }
    private async void Load()
    {
        try
        {
            var output = Path.Combine(App.Root, "output");
            items = await Task.Run(() => Directory.Exists(output) ? Directory.EnumerateFiles(output, "*", SearchOption.AllDirectories)
                .Where(p => ImageLibrary.CanRecycle(output, p)).OrderByDescending(File.GetLastWriteTimeUtc)
                .Select(p => new Item(p, Path.GetRelativePath(output, p))).ToArray() : []);
            Filter();
        }
        catch (IOException ex) { Status.Text = ex.Message; }
    }
    private void Filter() => Files.ItemsSource = items.Where(i => i.Name.Contains(Search.Text, StringComparison.OrdinalIgnoreCase)).ToArray();
    private void SearchChanged(object s, TextChangedEventArgs e) { if (Files != null) Filter(); }
    private void RefreshLibrary(object s, RoutedEventArgs e) => Load();
    private async void Selected(object s, SelectionChangedEventArgs e)
    {
        if (Files.SelectedItem is not Item item) return;
        try { Details.Text = item.Path + "\n\n" + (File.Exists(item.Path + ".json") ? await File.ReadAllTextAsync(item.Path + ".json") : "No settings sidecar. Imported media remains unverified."); }
        catch (IOException ex) { Details.Text = ex.Message; }
    }
    private async void Adopt(object s, RoutedEventArgs e)
    {
        if (Files.SelectedItem is not Item item || Films == null) return;
        Status.Text = await Films.Import(item.Path, (Role.SelectedItem as ComboBoxItem)?.Content.ToString() ?? "keyframe");
    }
}
