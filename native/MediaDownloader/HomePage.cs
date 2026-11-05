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
    private readonly TextBox linkInput = new() { PlaceholderText = "粘贴作品链接或分享文案\n多个作品可以分行输入", AcceptsReturn = true, TextWrapping = TextWrapping.Wrap, Height = 160, MaxLength = 32768, Padding = new Thickness(12) };
    private string downloadRoot = "";
    private readonly Button parseButton = new() { Content = "解析并预览", MinWidth = 132, IsEnabled = false };
    private readonly HyperlinkButton platformLink = new() { Content = "支持的平台与文件类型", Padding = new Thickness(0) };
    private readonly TextBlock parseSubmitted = new(), parseWorking = new(), parseFinished = new();
    private readonly TextBlock parseResultEmpty = new() { Text = "解析完成后，在这里确认作品并开始下载。", TextWrapping = TextWrapping.Wrap };
    private readonly ProgressBar parseProgress = new() { IsIndeterminate = true, Visibility = Visibility.Collapsed };
    private readonly StackPanel parseFlow = new() { Spacing = 12 };
    private readonly Grid homeWorkbench = new() { ColumnSpacing = 16, RowSpacing = 16 }, parseStages = new() { ColumnSpacing = 16, RowSpacing = 20 };
    private Border composerCard = null!, parseFlowCard = null!;
    private readonly List<StackPanel> parseStagePanels = new();
    private readonly TextBlock parseResultCount = new();
    private readonly TextBlock parseEmptyTitle = new();
    private bool? workbenchWide;
    private readonly List<Border> parseBadges = new();
    private readonly List<TextBlock> parseNumbers = new();
    private ListView parsingList = null!;

    private void BuildHome()
    {
        var body = new StackPanel { Spacing = 24, HorizontalAlignment = HorizontalAlignment.Stretch };
        body.Children.Add(PageHeader("新建下载", "添加作品链接，确认解析结果后保存到电脑。"));
        var composer = new StackPanel { Spacing = 16 };
        var composeHeading = new StackPanel { Spacing = 4 };
        composeHeading.Children.Add(Text("作品链接", "SectionTitle"));
        composeHeading.Children.Add(Text("支持视频、图片 / 图集、音频、文本及图文 / Markdown", "SecondaryText"));
        composer.Children.Add(composeHeading);
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
        platformLink.Click += async (_, _) => await ShowPlatformsAsync();
        platformLink.FontSize = 12; composer.Children.Add(platformLink);
        composerCard = Card(composer); homeWorkbench.Children.Add(composerCard);
        parseFlow.Children.Add(Text("解析流程", "SectionTitle"));
        foreach (var (title, status) in new[] { ("提交链接", parseSubmitted), ("解析作品", parseWorking), ("生成预览", parseFinished) }) {
            var stage = new StackPanel { Spacing = 8 };
            var heading = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 10 };
            var number = Text((parseStagePanels.Count + 1).ToString(), "CaptionTextBlockStyle");
            number.HorizontalAlignment = HorizontalAlignment.Center; number.VerticalAlignment = VerticalAlignment.Center;
            var badge = new Border { Style = (Style)Application.Current.Resources["ProcessBadge"], Child = number };
            parseBadges.Add(badge); parseNumbers.Add(number); heading.Children.Add(badge);
            var label = Text(title); label.VerticalAlignment = VerticalAlignment.Center;
            heading.Children.Add(label); stage.Children.Add(heading);
            status.Style = (Style)Application.Current.Resources["SecondaryText"];
            status.TextWrapping = TextWrapping.Wrap; stage.Children.Add(status);
            parseStagePanels.Add(stage); parseStages.Children.Add(stage);
        }
        parseFlow.Children.Add(parseStages); parseFlow.Children.Add(parseProgress);
        parseFlowCard = Card(parseFlow); homeWorkbench.Children.Add(parseFlowCard);
        homeWorkbench.SizeChanged += (_, e) => ArrangeWorkbench(e.NewSize.Width);
        body.Children.Add(homeWorkbench);
        var results = new StackPanel { Spacing = 12 };
        var resultHeading = new Grid(); resultHeading.ColumnDefinitions.Add(new ColumnDefinition()); resultHeading.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        resultHeading.Children.Add(Text("解析结果", "SectionTitle"));
        parseResultCount.Style = (Style)Application.Current.Resources["SecondaryText"]; parseResultCount.VerticalAlignment = VerticalAlignment.Center;
        Grid.SetColumn(parseResultCount, 1); resultHeading.Children.Add(parseResultCount); results.Children.Add(resultHeading);
        parseResultEmpty.Style = (Style)Application.Current.Resources["SecondaryText"];
        var resultEmptyBody = new StackPanel { Spacing = 6 };
        parseEmptyTitle.Style = (Style)Application.Current.Resources["BodyStrongTextBlockStyle"];
        resultEmptyBody.Children.Add(parseEmptyTitle); resultEmptyBody.Children.Add(parseResultEmpty);
        var resultEmptyCard = Card(resultEmptyBody);
        parsingList = TaskList(parsingResults);
        results.Children.Add(resultEmptyCard); results.Children.Add(parsingList); body.Children.Add(results);
        parsingResults.CollectionChanged += (_, _) => resultEmptyCard.Visibility = parsingResults.Count == 0 ? Visibility.Visible : Visibility.Collapsed;
        RefreshParsing([]);
        homePage.Children.Add(Scroller(body, double.PositiveInfinity));
    }

    private void ArrangeWorkbench(double width)
    {
        var wide = width >= 960;
        if (workbenchWide == wide) return;
        workbenchWide = wide;
        homeWorkbench.ColumnDefinitions.Clear(); homeWorkbench.RowDefinitions.Clear();
        homeWorkbench.ColumnDefinitions.Add(new ColumnDefinition());
        homeWorkbench.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        if (wide) homeWorkbench.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(280) });
        else homeWorkbench.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        Grid.SetColumn(parseFlowCard, wide ? 1 : 0); Grid.SetRow(parseFlowCard, wide ? 0 : 1);
        parseStages.RowDefinitions.Clear(); parseStages.ColumnDefinitions.Clear();
        for (var i = 0; i < parseStagePanels.Count; i++) {
            if (wide) parseStages.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            else parseStages.ColumnDefinitions.Add(new ColumnDefinition());
            Grid.SetRow(parseStagePanels[i], wide ? i : 0); Grid.SetColumn(parseStagePanels[i], wide ? 0 : i);
        }
    }

    private void RefreshParsing(List<TaskItem> batch)
    {
        var active = batch.Count(t => !t.HasPreview && t.State is ("queued" or "parsing"));
        var success = batch.Count(t => t.HasPreview);
        var failed = batch.Count(t => t.State == "failed" && !t.HasPreview);
        Sync(parsingResults, batch.Where(t => t.HasPreview || t.State is not ("queued" or "parsing")).ToList());
        parseSubmitted.Text = batch.Count == 0 ? "等待输入链接" : $"已提交 {batch.Count} 个链接";
        parseWorking.Text = batch.Count == 0 ? "等待开始" : active > 0 ? $"正在处理 {active} 个作品" : "本次解析已结束";
        parseFinished.Text = batch.Count == 0 ? "尚无解析结果" : $"已解析 {success} 个 · 失败 {failed} 个";
        parseResultCount.Text = batch.Count == 0 ? "本次提交" : $"{parsingResults.Count} 个结果";
        for (var i = 0; i < parseBadges.Count; i++) {
            var running = batch.Count > 0 && active > 0 && i == 1;
            var error = batch.Count > 0 && active == 0 && failed > 0 && i == 2;
            var complete = batch.Count > 0 && (i == 0 || i == 1 && active == 0 || i == 2 && active == 0 && success > 0 && failed == 0);
            parseBadges[i].Style = (Style)Application.Current.Resources[running ? "ActiveProcessBadge" : "ProcessBadge"];
            parseNumbers[i].Style = (Style)Application.Current.Resources[running ? "ActiveStepNumber" : error ? "CriticalCaption" : "CaptionTextBlockStyle"];
            parseNumbers[i].Text = error ? "!" : complete ? "✓" : (i + 1).ToString();
        }
        parseProgress.Visibility = active > 0 ? Visibility.Visible : Visibility.Collapsed;
        parseProgress.IsIndeterminate = active > 0;
        parseResultEmpty.Visibility = parsingResults.Count == 0 ? Visibility.Visible : Visibility.Collapsed;
        parseResultEmpty.Text = active > 0 ? "正在解析作品，结果会陆续显示在这里。" : "解析完成后，在这里确认作品并开始下载。";
        parseEmptyTitle.Text = active > 0 ? "正在获取作品信息" : "等待解析结果";
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

