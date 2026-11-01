using System.Collections.ObjectModel;
using System.Windows;
using System.Windows.Controls;

namespace ImageStudio;

public partial class LoraPicker : UserControl
{
    public sealed class Row
    {
        public string Name { get; set; } = "";
        public bool Enabled { get; set; } = true;
        public double Strength { get; set; } = 0.8;
        public string[] Available { get; set; } = [];
    }
    private readonly ObservableCollection<Row> rows = [];
    private string[] available = [];
    private bool restoring;
    public event EventHandler? SelectionEdited;
    public LoraPicker() { InitializeComponent(); Rows.ItemsSource = rows; }
    public LoraSelection[] Selection => rows.Select(x => new LoraSelection(x.Name, x.Strength, x.Enabled)).ToArray();
    public void Restore(string[] files, LoraSelection[] selections)
    {
        restoring = true;
        available = files;
        rows.Clear();
        foreach (var lora in selections)
            rows.Add(new() { Name = lora.Name, Enabled = lora.Enabled, Strength = lora.Strength, Available = files.Append(lora.Name).Distinct().ToArray() });
        UpdateEmpty();
        restoring = false;
    }
    private void UpdateEmpty() => Empty.Visibility = rows.Count == 0 ? Visibility.Visible : Visibility.Collapsed;
    private void Add(object sender, RoutedEventArgs e)
    {
        if (available.Length == 0) { Empty.Text = "No LoRAs found. Add files, then refresh Models."; return; }
        rows.Add(new() { Name = available[0], Available = available });
        UpdateEmpty();
        SelectionEdited?.Invoke(this, EventArgs.Empty);
    }
    private void Remove(object sender, RoutedEventArgs e)
    {
        if (((FrameworkElement)sender).DataContext is Row row) rows.Remove(row);
        UpdateEmpty();
        SelectionEdited?.Invoke(this, EventArgs.Empty);
    }
    private void Changed(object sender, RoutedEventArgs e)
    {
        if (!restoring) Dispatcher.BeginInvoke(() => SelectionEdited?.Invoke(this, EventArgs.Empty));
    }
}
