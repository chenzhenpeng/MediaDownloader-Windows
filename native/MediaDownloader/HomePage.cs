using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Automation;
using Microsoft.UI.Xaml.Input;
using Windows.ApplicationModel.DataTransfer;
using Windows.System;

namespace MediaDownloader;

public sealed partial class MainWindow
{
    private readonly HashSet<string> pendingInspections = new();
    private readonly TextBox linkInput = new() { Header = "作品链接", PlaceholderText = "粘贴链接或分享文案，也可以一次添加多个作品", AcceptsReturn = true, TextWrapping = TextWrapping.Wrap, Height = 130, MaxLength = 32768 };
    private string downloadRoot = "";
    private readonly Button parseButton = new() { Content = "解析并预览", MinWidth = 132, IsEnabled = false };
    private readonly HyperlinkButton platformLink = new() { Content = "支持的平台与文件类型", Padding = new Thickness(0) };
    private readonly StackPanel readySection = new() { Spacing = 12, Visibility = Visibility.Collapsed };
    private readonly TextBlock recentEmpty = new() { Text = "下载成功的作品会显示在这里。", TextWrapping = TextWrapping.Wrap, Margin = new Thickness(0, 8, 0, 0) };

    private void BuildHome()
    {
        var body = new StackPanel { Spacing = 28, HorizontalAlignment = HorizontalAlignment.Stretch };
        body.Children.Add(PageHeader("新建下载", "从一个链接开始，把视频、图片和图文保存到电脑。"));
        var composer = new StackPanel { Spacing = 16 };
        AutomationProperties.SetName(linkInput, "作品链接或分享文案");
        linkInput.TextChanged += (_, _) => parseButton.IsEnabled = !string.IsNullOrWhiteSpace(linkInput.Text);
        var shortcut = new KeyboardAccelerator { Key = VirtualKey.Enter, Modifiers = VirtualKeyModifiers.Control };
        shortcut.Invoked += async (_, e) => { e.Handled = true; await ParseAsync(); };
        linkInput.KeyboardAccelerators.Add(shortcut);
        composer.Children.Add(linkInput);
        var actions = new Grid { ColumnSpacing = 12 };
        actions.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        actions.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        var secondary = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 4 };
        secondary.Children.Add(ActionButton("粘贴链接", async (_, _) => {
            try { var content = Clipboard.GetContent(); if (content.Contains(StandardDataFormats.Text)) linkInput.Text = await content.GetTextAsync(); }
            catch { ShowError("无法读取剪贴板，请直接粘贴到链接输入框。"); }
        }));
        secondary.Children.Add(ActionButton("清空", (_, _) => linkInput.Text = ""));
        actions.Children.Add(secondary);
        parseButton.Style = (Style)Application.Current.Resources["AccentButtonStyle"];
        parseButton.Click += async (_, _) => await ParseAsync();
        ToolTipService.SetToolTip(parseButton, "解析并预览（Ctrl+Enter）");
        Grid.SetColumn(parseButton, 1); actions.Children.Add(parseButton); composer.Children.Add(actions);
        body.Children.Add(Card(composer));
        var hint = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 16 };
        platformLink.Click += async (_, _) => await ShowPlatformsAsync(); hint.Children.Add(platformLink);
        hint.Children.Add(Text("具体格式以作品预览为准", "SecondaryText")); body.Children.Add(hint);
        readySection.Children.Add(Text("待确认的作品", "SubtitleTextBlockStyle"));
        readySection.Children.Add(TaskList(readyTasks)); body.Children.Add(readySection);
        var recent = new StackPanel { Spacing = 12 };
        var recentHeader = new Grid(); recentHeader.ColumnDefinitions.Add(new ColumnDefinition()); recentHeader.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        recentHeader.Children.Add(Text("最近保存", "SubtitleTextBlockStyle"));
        var all = new HyperlinkButton { Content = "查看全部", Padding = new Thickness(0) };
        all.Click += (_, _) => GoDownloads("completed"); Grid.SetColumn(all, 1); recentHeader.Children.Add(all);
        recent.Children.Add(recentHeader); recent.Children.Add(recentEmpty); recent.Children.Add(TaskList(recentTasks));
        body.Children.Add(recent);
        homePage.Children.Add(Scroller(body, double.PositiveInfinity));
    }

    private async Task ParseAsync()
    {
        if (string.IsNullOrWhiteSpace(linkInput.Text)) return;
        parseButton.IsEnabled = false; GlobalNotice.IsOpen = false;
        var result = await CallAsync("inspect", new { text = linkInput.Text, output_root = downloadRoot });
        if (result is not null) {
            pendingInspections.Clear();
            foreach (var id in result.Value.GetProperty("ids").EnumerateArray()) pendingInspections.Add(id.GetString()!);
            linkInput.Text = ""; ShowInfo("正在解析作品，预览准备好后会显示在下方。");
        }
        else parseButton.IsEnabled = !string.IsNullOrWhiteSpace(linkInput.Text);
    }

    private async Task ShowPlatformsAsync()
    {
        if (snapshot.ValueKind != System.Text.Json.JsonValueKind.Object) return;
        var all = snapshot.GetProperty("platforms").EnumerateArray().Select(p => p.Clone()).ToList();
        var search = new TextBox { PlaceholderText = "搜索平台", Margin = new Thickness(0, 0, 0, 16) };
        var rows = new StackPanel { Spacing = 16 };
        void Refresh() {
            rows.Children.Clear();
            foreach (var p in all.Where(p => p.String("name").Contains(search.Text, StringComparison.OrdinalIgnoreCase))) {
                var row = new Grid { ColumnSpacing = 24 }; row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(136) }); row.ColumnDefinitions.Add(new ColumnDefinition());
                row.Children.Add(Text(p.String("name")));
                var types = p.GetProperty("types").EnumerateArray().Select(t => t.GetString() switch { "video" => "视频", "image" => "图片 / 图集", "music" => "音频", "article" => "图文 / Markdown", "text" => "文本", _ => "媒体" });
                var text = Text(string.Join("、", types) + (p.Bool("available") ? "" : " · 组件暂不可用"), "SecondaryText");
                Grid.SetColumn(text, 1); row.Children.Add(text); rows.Children.Add(row);
            }
            if (rows.Children.Count == 0) rows.Children.Add(Text("没有匹配的平台。", "SecondaryText"));
        }
        search.TextChanged += (_, _) => Refresh(); Refresh();
        var content = new StackPanel(); content.Children.Add(search); content.Children.Add(new ScrollViewer { Content = rows, MaxHeight = 400 });
        await new ContentDialog { XamlRoot = Root.XamlRoot, RequestedTheme = Root.ActualTheme, Title = "支持的平台与文件类型", Content = content, CloseButtonText = "关闭" }.ShowAsync();
    }
}

