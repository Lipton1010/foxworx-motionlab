using System.Windows;
using System.Windows.Controls;
using System.Windows.Automation;

namespace ImageStudio;

public static class StudioDialog
{
    public static bool Confirm(Window owner, string message, string title)
    {
        var window = new Window { Title = title, Width = 500, SizeToContent = SizeToContent.Height,
            MaxHeight = 650, WindowStartupLocation = WindowStartupLocation.CenterOwner, ResizeMode = ResizeMode.NoResize,
            ShowInTaskbar = false };
        if (owner.IsVisible) window.Owner = owner;
        var panel = new StackPanel { Margin = new Thickness(24) };
        panel.Children.Add(new TextBlock { Text = message, Margin = new Thickness(0, 0, 0, 20) });
        var buttons = new StackPanel { Orientation = Orientation.Horizontal, HorizontalAlignment = HorizontalAlignment.Right };
        var cancel = new Button { Content = "Cancel", IsCancel = true, IsDefault = true, Margin = new Thickness(0, 0, 10, 0) };
        var confirm = new Button { Content = "Confirm" };
        AutomationProperties.SetAutomationId(confirm, "Confirm");
        confirm.Click += (_, _) => window.DialogResult = true;
        cancel.Click += (_, _) => window.DialogResult = false;
        buttons.Children.Add(cancel); buttons.Children.Add(confirm); panel.Children.Add(buttons);
        window.Content = panel;
        return window.ShowDialog() == true;
    }
}
