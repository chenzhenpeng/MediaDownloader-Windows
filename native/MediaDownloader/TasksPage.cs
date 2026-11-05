using System.Collections.ObjectModel;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Windows.ApplicationModel.DataTransfer;

namespace MediaDownloader;

public sealed partial class MainWindow
{
    private readonly TextBlock taskTitle = new(), taskDescription = new(), taskCount = new(), taskEmptyTitle = new();
    private readonly TextBox taskSearch = new() { PlaceholderText = "搜索作品或平台", MinWidth = 180 };
    private readonly SelectorBar taskFilter = new();
    private readonly StackPanel taskEmpty = new() { Spacing = 12, HorizontalAlignment = HorizontalAlignment.Center, VerticalAlignment = VerticalAlignment.Center, MaxWidth = 360, Margin = new Thickness(24) };
    private readonly StackPanel pager = new() { Orientation = Orientation.Horizontal, Spacing = 12, HorizontalAlignment = HorizontalAlignment.Right };
    private readonly Button previousPage = new() { Content = "上一页" }, nextPage = new() { Content = "下一页" };
    private ListView taskList = null!;

    private ListView TaskList(ObservableCollection<TaskItem> items)
    {
        var list = new ListView { ItemsSource = items, ItemTemplate = (DataTemplate)Root.Resources["TaskTemplate"],
            SelectionMode = ListViewSelectionMode.None, IsItemClickEnabled = true, HorizontalContentAlignment = HorizontalAlignment.Stretch };
        var style = new Style(typeof(ListViewItem));
        style.Setters.Add(new Setter(Control.HorizontalContentAlignmentProperty, HorizontalAlignment.Stretch));
        style.Setters.Add(new Setter(Control.PaddingProperty, new Thickness(0)));
        style.Setters.Add(new Setter(FrameworkElement.MarginProperty, new Thickness(0, 0, 0, 4)));
        list.ItemContainerStyle = style;
        list.ItemClick += async (_, e) => { if (e.ClickedItem is TaskItem item) await ShowTaskAsync(item); };
        return list;
    }

    private void BuildTasks()
    {
        taskPage.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        taskPage.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        taskPage.RowDefinitions.Add(new RowDefinition());
        taskPage.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        var header = new Grid(); header.ColumnDefinitions.Add(new ColumnDefinition()); header.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        var titles = new StackPanel { Spacing = 6 }; taskTitle.Style = (Style)Application.Current.Resources["PageTitle"];
        taskDescription.Style = (Style)Application.Current.Resources["SecondaryText"]; taskDescription.TextWrapping = TextWrapping.Wrap;
        taskTitle.Text = "下载管理"; taskDescription.Text = "查看所有下载，管理进度与已保存的作品。";
        titles.Children.Add(taskTitle); titles.Children.Add(taskDescription); header.Children.Add(titles);
        var add = ActionButton("新建下载", (_, _) => GoHome()); Grid.SetColumn(add, 1); header.Children.Add(add); taskPage.Children.Add(header);
        var tools = new Grid { Margin = new Thickness(0, 24, 0, 16), ColumnSpacing = 12 };
        tools.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        tools.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        tools.ColumnDefinitions.Add(new ColumnDefinition()); tools.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        taskFilter.Margin = new Thickness(0, 0, 0, 12);
        foreach (var (name, tag) in new[] { ("全部", ""), ("进行中", "active"), ("已完成", "completed"), ("失败", "failed") }) taskFilter.Items.Add(new SelectorBarItem { Text = name, Tag = tag });
        taskFilter.SelectedItem = taskFilter.Items[0];
        Grid.SetColumnSpan(taskFilter, 2); tools.Children.Add(taskFilter);
        Grid.SetRow(taskSearch, 1); tools.Children.Add(taskSearch);
        taskCount.VerticalAlignment = VerticalAlignment.Center; taskCount.Style = (Style)Application.Current.Resources["SecondaryText"];
        Grid.SetColumn(taskCount, 1); Grid.SetRow(taskCount, 1); tools.Children.Add(taskCount); Grid.SetRow(tools, 1); taskPage.Children.Add(tools);
        taskSearch.TextChanged += (_, _) => { if (!loadingSnapshot) { searchTimer.Stop(); searchTimer.Start(); } };
        taskFilter.SelectionChanged += async (_, _) => { if (!loadingSnapshot) await ChangeViewAsync(); };
        var content = new Grid(); taskList = TaskList(visibleTasks); content.Children.Add(taskList);
        taskEmpty.Children.Add(new Border { Style = (Style)Application.Current.Resources["ProcessBadge"], Width = 64, Height = 64,
            CornerRadius = new CornerRadius(32), Child = new FontIcon { Glyph = "\uE896", FontSize = 28 }, HorizontalAlignment = HorizontalAlignment.Center });
        taskEmptyTitle.Style = (Style)Application.Current.Resources["SectionTitle"]; taskEmptyTitle.HorizontalAlignment = HorizontalAlignment.Center;
        taskEmptyTitle.TextAlignment = TextAlignment.Center; taskEmptyTitle.TextWrapping = TextWrapping.Wrap;
        taskEmpty.Children.Add(taskEmptyTitle);
        var emptyDescription = Text("添加作品链接，预览后即可开始下载。", "SecondaryText");
        emptyDescription.TextAlignment = TextAlignment.Center;
        taskEmpty.Children.Add(emptyDescription);
        var emptyAction = ActionButton("添加下载", (_, _) => GoHome(), true);
        emptyAction.HorizontalAlignment = HorizontalAlignment.Center;
        taskEmpty.Children.Add(emptyAction);
        content.Children.Add(taskEmpty); Grid.SetRow(content, 2); taskPage.Children.Add(content);
        previousPage.Click += async (_, _) => await ChangeViewAsync(Math.Max(0, snapshot.Number("offset") - 50));
        nextPage.Click += async (_, _) => await ChangeViewAsync(snapshot.Number("offset") + 50);
        pager.Children.Add(previousPage); pager.Children.Add(nextPage); Grid.SetRow(pager, 3); taskPage.Children.Add(pager);
    }

    private async void TaskPrimary_Click(object sender, RoutedEventArgs e)
    {
        if ((sender as FrameworkElement)?.DataContext is not TaskItem item) return;
        if (item.State == "completed") await OpenPathAsync(item, true);
        else if (item.CanStart) { if (await CallAsync("download", new { id = item.Id }) is not null) ShowInfo(item.Media.Length == 0 ? "正在重新解析作品。" : "已加入下载队列。"); }
        else if (item.CanCancel) await CallAsync("cancel", new { id = item.Id });
    }

    private void TaskMore_Click(object sender, RoutedEventArgs e)
    {
        if (sender is not FrameworkElement target || target.DataContext is not TaskItem item) return;
        var menu = new MenuFlyout();
        void Add(string text, RoutedEventHandler action, bool enabled = true) { var entry = new MenuFlyoutItem { Text = text, IsEnabled = enabled }; entry.Click += action; menu.Items.Add(entry); }
        Add("作品详情", async (_, _) => await ShowTaskAsync(item));
        Add("打开文件夹", async (_, _) => await OpenPathAsync(item, false));
        Add("重新下载", async (_, _) => await CallAsync("download", new { id = item.Id }), item.State is "completed" or "failed" or "interrupted" or "cancelled");
        Add("复制标题", (_, _) => { var data = new DataPackage(); data.SetText(item.Title); Clipboard.SetContent(data); });
        if (item.State is "completed" or "failed" or "interrupted" or "cancelled") {
            menu.Items.Add(new MenuFlyoutSeparator());
            Add("移除记录", async (_, _) => { if (await ConfirmAsync("移除记录", "已下载的文件会保留。", "移除记录")) await CallAsync("remove", new { id = item.Id }); });
        }
        menu.ShowAt(target);
    }

    private async Task ShowTaskAsync(TaskItem item)
    {
        await CallAsync("detail", new { id = item.Id });
        var body = new StackPanel { Spacing = 16, MaxWidth = 700 };
        body.Children.Add(new TextBlock { Text = item.Title, TextWrapping = TextWrapping.Wrap, IsTextSelectionEnabled = true, Style = (Style)Application.Current.Resources["SubtitleTextBlockStyle"] });
        body.Children.Add(Text($"{item.PlatformName} · {item.StateLabel}", "SecondaryText"));
        if (item.Error.Length > 0) body.Children.Add(new InfoBar { IsOpen = true, IsClosable = false, Severity = InfoBarSeverity.Error, Message = item.Error });
        body.Children.Add(Text("保存位置", "CaptionTextBlockStyle"));
        body.Children.Add(new TextBlock { Text = item.Path, TextWrapping = TextWrapping.Wrap, IsTextSelectionEnabled = true });
        body.Children.Add(ActionButton("打开文件夹", async (_, _) => await OpenPathAsync(item, false)));
        body.Children.Add(Text(item.Invalid ? "原解析信息（不代表文件有效）" : "媒体信息", "CaptionTextBlockStyle"));
        body.Children.Add(Text(string.Join("\n", item.Media)));
        if (item.Image is not null) body.Children.Add(new Image { Source = item.Image, MaxHeight = 240, Stretch = Stretch.Uniform, HorizontalAlignment = HorizontalAlignment.Left });
        var dialog = new ContentDialog { XamlRoot = Root.XamlRoot, RequestedTheme = Root.ActualTheme, Title = "作品详情", Content = new ScrollViewer { Content = body, MaxHeight = 520 }, CloseButtonText = "关闭" };
        if (item.CanStart) { dialog.PrimaryButtonText = item.PrimaryLabel; dialog.DefaultButton = ContentDialogButton.Primary; }
        var result = await dialog.ShowAsync();
        await CallAsync("detail", new { id = "" });
        if (result == ContentDialogResult.Primary) await CallAsync("download", new { id = item.Id });
    }
}

