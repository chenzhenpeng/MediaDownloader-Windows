using System.Text.Json;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Automation;
using Windows.Storage;
using Windows.Storage.Pickers;

namespace MediaDownloader;

public sealed partial class MainWindow
{
    private readonly TextBlock settingsFolder = new() { TextTrimming = TextTrimming.CharacterEllipsis, MaxLines = 1 };
    private readonly ComboBox themePicker = new() { Width = 180 };
    private readonly ComboBox workerCount = new() { Width = 140 };
    private readonly ComboBox platformPicker = new() { HorizontalAlignment = HorizontalAlignment.Stretch };
    private readonly PasswordBox cookieInput = new() { Header = "登录 Cookie", PlaceholderText = "输入平台 Cookie", PasswordRevealMode = PasswordRevealMode.Peek, MaxLength = 32768 };
    private long credentialReadRevision;
    private readonly TextBox proxyInput = new() { Header = "代理地址", PlaceholderText = "留空保留现有设置，例如 http://127.0.0.1:7890", MaxLength = 2048 };
    private readonly TextBlock credentialHint = new() { TextWrapping = TextWrapping.Wrap }, connectionState = new(), updateMessage = new() { TextWrapping = TextWrapping.Wrap }, versionText = new() { TextWrapping = TextWrapping.Wrap };
    private readonly Expander connectionSection = new() { Header = "平台连接", HorizontalAlignment = HorizontalAlignment.Stretch, HorizontalContentAlignment = HorizontalAlignment.Stretch };
    private readonly ToggleSwitch updateAuto = new(), updateLock = new();
    private readonly TextBlock productVersion = new();
    private readonly TextBlock componentVersions = new() { TextWrapping = TextWrapping.Wrap };
    private readonly TextBlock runtimeVersions = new() { TextWrapping = TextWrapping.Wrap }, runtimeMessage = new() { TextWrapping = TextWrapping.Wrap };
    private readonly TextBlock ffmpegVersions = new() { TextWrapping = TextWrapping.Wrap }, ytdlpVersions = new() { TextWrapping = TextWrapping.Wrap };
    private readonly StackPanel runtimeActions = new() { Orientation = Orientation.Horizontal, Spacing = 8 };
    private readonly ProgressBar runtimeProgress = new() { Height = 3, IsIndeterminate = true, Visibility = Visibility.Collapsed, Margin = new Thickness(0, 6, 0, 0) };
    private Button runtimeCheck = null!, runtimeInstall = null!, runtimeCancel = null!;
    private Grid settingsRuntimeRow = null!;
    private readonly Expander updateAdvanced = new() { Header = "更新选项", HorizontalAlignment = HorizontalAlignment.Stretch, HorizontalContentAlignment = HorizontalAlignment.Stretch };
    private readonly StackPanel updateActions = new() { Orientation = Orientation.Horizontal, Spacing = 8 };
    private Grid settingsThemeRow = null!, settingsAboutRow = null!;
    private Grid settingsUpdateRow = null!, connectionHeader = null!;
    private readonly ProgressBar updateProgress = new() { Height = 3, IsIndeterminate = true, Visibility = Visibility.Collapsed, Margin = new Thickness(0, 6, 0, 0) };
    private Button updateCheck = null!, updateInstall = null!, updateCancel = null!, updateRollback = null!;

    private static Grid SettingRow(string title, string description, FrameworkElement control)
    {
        var row = new Grid { ColumnSpacing = 24, Padding = new Thickness(16, 12, 16, 12), MinHeight = 64 };
        row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(24) }); row.ColumnDefinitions.Add(new ColumnDefinition()); row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(180) });
        var words = new StackPanel { Spacing = 4, VerticalAlignment = VerticalAlignment.Center };
        words.Children.Add(Text(title));
        var detail = Text(description, "SecondaryText"); detail.FontSize = 12;
        words.Children.Add(detail); Grid.SetColumn(words, 1); row.Children.Add(words);
        control.HorizontalAlignment = HorizontalAlignment.Right; control.VerticalAlignment = VerticalAlignment.Center;
        Grid.SetColumn(control, 2); row.Children.Add(control);
        var icon = new FontIcon { FontSize = 20, VerticalAlignment = VerticalAlignment.Center, Glyph = title switch {
            "应用主题" => "\uE790", "保存位置" => "\uE8B7", "并发任务数" => "\uE8FD", "ParseHub 解析组件" => "\uE895", "worker、Python 与依赖" => "\uE950", "FFmpeg / ffprobe" => "\uE714", "yt-dlp" => "\uE896", _ => "\uE946" } };
        row.Children.Add(icon); return row;
    }

    private static Border SettingsCard(UIElement content) => new() { Style = (Style)Application.Current.Resources["SurfaceCard"], Padding = new Thickness(0), Child = content };
    private static StackPanel SettingsGroup(string title)
    {
        var group = new StackPanel { Spacing = 8 };
        var heading = Text(title); heading.FontWeight = Microsoft.UI.Text.FontWeights.SemiBold;
        group.Children.Add(heading); return group;
    }
    private static Grid ExpanderHeading(string glyph, string title, string description) {
        var heading = new Grid { ColumnSpacing = 24, MinHeight = 36 };
        heading.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(24) }); heading.ColumnDefinitions.Add(new ColumnDefinition());
        heading.Children.Add(new FontIcon { Glyph = glyph, FontSize = 20, VerticalAlignment = VerticalAlignment.Center });
        var words = new StackPanel { VerticalAlignment = VerticalAlignment.Center };
        words.Children.Add(Text(title));
        var caption = Text(description, "SecondaryText"); caption.FontSize = 12; caption.LineHeight = 16; words.Children.Add(caption);
        Grid.SetColumn(words, 1); heading.Children.Add(words); return heading;
    }

    private void BuildSettings()
    {
        var body = new StackPanel { Spacing = 20, HorizontalAlignment = HorizontalAlignment.Stretch };
        body.Children.Add(PageHeader("设置", "调整外观、保存位置与平台连接。"));
        foreach (var text in new[] { "跟随系统", "浅色", "深色" }) themePicker.Items.Add(text);
        AutomationProperties.SetName(themePicker, "应用主题");
        AutomationProperties.SetName(workerCount, "并发任务数");
        for (var count = 1; count <= 4; count++) workerCount.Items.Add($"{count} 个任务");
        themePicker.SelectionChanged += async (_, _) => {
            if (!loadingSnapshot) await CallAsync("settings", new { theme = themePicker.SelectedIndex == 1 ? "light" : themePicker.SelectedIndex == 2 ? "dark" : "system" });
        };
        var appearance = SettingsGroup("外观");
        settingsThemeRow = SettingRow("应用主题", "选择浅色、深色或跟随系统。", themePicker);
        appearance.Children.Add(SettingsCard(settingsThemeRow)); body.Children.Add(appearance);
        var downloadGroup = SettingsGroup("下载");
        var downloads = new StackPanel { Spacing = 0 };
        settingsFolder.Style = (Style)Application.Current.Resources["SecondaryText"];
        settingsFolder.FontSize = 12;
        var folder = SettingRow("保存位置", "", ActionButton("更改", async (_, _) => await PickFolderAsync()));
        ((StackPanel)folder.Children[0]).Children.RemoveAt(1);
        ((StackPanel)folder.Children[0]).Children.Add(settingsFolder); downloads.Children.Add(folder);
        ToolTipService.SetToolTip(folder, "按平台和作品分别归档，图集保留原帖顺序。");
        workerCount.SelectionChanged += async (_, _) => { if (!loadingSnapshot && workerCount.SelectedIndex >= 0) await CallAsync("settings", new { max_workers = workerCount.SelectedIndex + 1 }); };
        downloads.Children.Add(SettingRow("并发任务数", "下次启动应用时生效。", workerCount));
        downloadGroup.Children.Add(SettingsCard(downloads)); body.Children.Add(downloadGroup);
        var connectionGroup = SettingsGroup("平台连接");
        connectionHeader = ExpanderHeading("\uE774", "登录凭据与代理", "按平台管理 Cookie 与连接方式");
        connectionSection.Header = connectionHeader;
        var connections = new StackPanel { Spacing = 16, Padding = new Thickness(16) };
        platformPicker.SelectionChanged += async (_, _) => { cookieInput.Password = ""; proxyInput.Text = ""; RefreshConnection(); await LoadSavedCookieAsync(); };
        cookieInput.PasswordChanged += (_, _) => credentialReadRevision++;
        connections.Children.Add(platformPicker); connections.Children.Add(credentialHint); connections.Children.Add(connectionState);
        connections.Children.Add(proxyInput); connections.Children.Add(cookieInput);
        var buttons = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 8 };
        buttons.Children.Add(ActionButton("保存连接设置", async (_, _) => {
            if (platformPicker.SelectedItem is not ComboBoxItem selected) return;
            var revision = credentialReadRevision; var platform = selected.Tag as string;
            var result = await CallAsync("connection", new { platform = selected.Tag as string, cookie = cookieInput.Password, proxy = proxyInput.Text });
            if (result is not null) {
                if (((platformPicker.SelectedItem as ComboBoxItem)?.Tag as string) == platform && revision == credentialReadRevision) {
                    proxyInput.Text = ""; await LoadSavedCookieAsync();
                }
                ShowInfo("连接设置已加密保存，Cookie 默认隐藏，可按住眼睛查看。");
            }
        }, true));
        buttons.Children.Add(ActionButton("删除 Cookie", async (_, _) => {
            if (platformPicker.SelectedItem is ComboBoxItem selected && await ConfirmAsync("删除登录凭据", "删除后，需要登录的作品可能无法解析。", "删除 Cookie"))
            {
                await CallAsync("connection", new { platform = selected.Tag as string, clear_cookie = true });
                await LoadSavedCookieAsync();
            }
        }));
        buttons.Children.Add(ActionButton("移除代理", async (_, _) => {
            if (platformPicker.SelectedItem is ComboBoxItem selected) await CallAsync("connection", new { platform = selected.Tag as string, clear_proxy = true });
        }));
        connections.Children.Add(buttons); connectionSection.Content = connections;
        connectionGroup.Children.Add(connectionSection); body.Children.Add(connectionGroup);
        var updates = SettingsGroup("解析组件");
        updateCheck = ActionButton("检查更新", async (_, _) => {
            await CallAsync("update", new { action = "check", component = "parsehub" });
        });
        updateInstall = ActionButton("安装解析更新", async (_, _) => await CallAsync("update", new { action = "install", component = "parsehub" }), true);
        updateCancel = ActionButton("取消更新", async (_, _) => await CallAsync("update", new { action = "cancel" }));
        updateActions.Children.Add(updateCheck); updateActions.Children.Add(updateInstall); updateActions.Children.Add(updateCancel);
        var coreRow = SettingRow("ParseHub 解析组件", "", updateActions); coreRow.MinHeight = 84; settingsUpdateRow = coreRow;
        updateMessage.Style = (Style)Application.Current.Resources["SecondaryText"]; updateMessage.FontSize = 12;
        var coreWords = (StackPanel)coreRow.Children[0]; coreWords.Children.RemoveAt(1); coreWords.Children.Add(updateMessage); coreWords.Children.Add(updateProgress);
        var updateBody = new StackPanel(); updateBody.Children.Add(coreRow);
        componentVersions.Style = (Style)Application.Current.Resources["SecondaryText"]; componentVersions.FontSize = 12; componentVersions.Margin = new Thickness(64, 0, 16, 8);
        updateBody.Children.Add(componentVersions);
        var officialPage = new HyperlinkButton { Content = "查看 ParseHub 官方 PyPI 包", Padding = new Thickness(0), FontSize = 12 };
        officialPage.Click += async (_, _) => await Windows.System.Launcher.LaunchUriAsync(new Uri("https://pypi.org/project/parsehub/"));
        officialPage.Margin = new Thickness(64, 0, 16, 12); updateBody.Children.Add(officialPage);
        updates.Children.Add(SettingsCard(updateBody)); body.Children.Add(updates);
        var environment = SettingsGroup("执行环境");
        runtimeCheck = ActionButton("检查环境更新", async (_, _) => await CallAsync("update", new { action = "check", component = "engine" }));
        runtimeInstall = ActionButton("安装运行环境", async (_, _) => await CallAsync("update", new { action = "install", component = "engine" }), true);
        runtimeCancel = ActionButton("取消更新", async (_, _) => await CallAsync("update", new { action = "cancel" }));
        runtimeActions.Children.Add(runtimeCheck); runtimeActions.Children.Add(runtimeInstall); runtimeActions.Children.Add(runtimeCancel);
        settingsRuntimeRow = SettingRow("worker、Python 与依赖", "", runtimeActions); settingsRuntimeRow.MinHeight = 84;
        runtimeMessage.Style = (Style)Application.Current.Resources["SecondaryText"]; runtimeMessage.FontSize = 12;
        var runtimeWords = (StackPanel)settingsRuntimeRow.Children[0]; runtimeWords.Children.RemoveAt(1); runtimeWords.Children.Add(runtimeMessage); runtimeWords.Children.Add(runtimeProgress);
        var runtimeBody = new StackPanel(); runtimeBody.Children.Add(settingsRuntimeRow);
        runtimeVersions.Style = (Style)Application.Current.Resources["SecondaryText"]; runtimeVersions.FontSize = 12; runtimeVersions.Margin = new Thickness(64, 0, 16, 12); runtimeBody.Children.Add(runtimeVersions);
        environment.Children.Add(SettingsCard(runtimeBody)); body.Children.Add(environment);
        var tools = SettingsGroup("媒体工具"); var toolRows = new StackPanel();
        foreach (var (title, version, kind) in new[] { ("FFmpeg / ffprobe", ffmpegVersions, "ffmpeg"), ("yt-dlp", ytdlpVersions, "yt-dlp") }) {
            var row = SettingRow(title, "", ActionButton("查看详情", async (_, _) => await ShowToolDetailsAsync(kind)));
            version.Style = (Style)Application.Current.Resources["SecondaryText"]; version.FontSize = 12;
            ((StackPanel)row.Children[0]).Children.RemoveAt(1); ((StackPanel)row.Children[0]).Children.Add(version); toolRows.Children.Add(row);
        }
        tools.Children.Add(SettingsCard(toolRows)); body.Children.Add(tools);
        var options = new StackPanel { Spacing = 0 };
        updateAuto.Toggled += async (_, _) => { if (!loadingSnapshot) await CallAsync("update", new { action = "auto", value = updateAuto.IsOn }); };
        updateLock.Toggled += async (_, _) => { if (!loadingSnapshot) await CallAsync("update", new { action = "lock", value = updateLock.IsOn }); };
        updateRollback = ActionButton("恢复上一组合", async (_, _) => {
            if (await ConfirmAsync("恢复上一组合", "解析组件与运行环境将一起恢复为兼容组合。等待当前任务结束后切换，任务与文件会保留。", "恢复上一组合")) await CallAsync("update", new { action = "rollback" });
        });
        options.Children.Add(SettingRow("自动检查", "每 24 小时检查，仅提示可用更新。", updateAuto));
        options.Children.Add(SettingRow("锁定当前组合", "暂停解析组件和运行环境的安装与手动恢复。", updateLock));
        options.Children.Add(SettingRow("恢复上一组合", "一起恢复解析组件与配套环境，避免版本混用。", updateRollback));
        updateAdvanced.Header = ExpanderHeading("\uE713", "组件维护", "自动检查、组合锁定与恢复");
        updateAdvanced.Content = options;
        body.Children.Add(updateAdvanced);
        var about = SettingsGroup("应用包");
        var aboutRow = SettingRow("Media Downloader", "", ActionButton("版本详情", async (_, _) => await ShowVersionsAsync()));
        settingsAboutRow = aboutRow;
        productVersion.Style = (Style)Application.Current.Resources["SecondaryText"]; productVersion.FontSize = 12;
        ((StackPanel)aboutRow.Children[0]).Children.RemoveAt(1); ((StackPanel)aboutRow.Children[0]).Children.Add(productVersion);
        about.Children.Add(SettingsCard(aboutRow)); body.Children.Add(about);
        settingsPage.Children.Add(Scroller(body, double.PositiveInfinity));
    }

    private async Task LoadSavedCookieAsync()
    {
        if (currentPage != "settings" || platformPicker.SelectedItem is not ComboBoxItem selected || backend is null) return;
        var platform = selected.Tag as string;
        var revision = ++credentialReadRevision;
        var value = await CallAsync("connection_read", new { platform });
        if (value is not null && currentPage == "settings" && revision == credentialReadRevision && ((platformPicker.SelectedItem as ComboBoxItem)?.Tag as string) == platform)
            cookieInput.Password = value.Value.String("cookie");
    }

    private void ApplyUpdateState(JsonElement state)
    {
        if (platformPicker.Items.Count == 0) {
            foreach (var platform in snapshot.GetProperty("platforms").EnumerateArray()) platformPicker.Items.Add(new ComboBoxItem { Content = platform.String("name"), Tag = platform.String("id") });
            platformPicker.SelectedIndex = 0;
        }
        RefreshConnection();
        var configured = state.Bool("configured");
        var official = state.GetProperty("official");
        var scope = state.String("scope", "all");
        if (scope == "all") scope = state.String("component", "parsehub");
        if (!configured) scope = "parsehub";
        ApplyComponentCard(state, scope == "parsehub", true, updateCheck, updateInstall, updateCancel, updateMessage, updateProgress);
        ApplyComponentCard(state, scope == "engine", false, runtimeCheck, runtimeInstall, runtimeCancel, runtimeMessage, runtimeProgress);
        updateAdvanced.Visibility = configured || state.Bool("can_rollback") || state.Bool("locked") ? Visibility.Visible : Visibility.Collapsed;
        updateAuto.IsEnabled = true; updateAuto.IsOn = state.Bool("auto"); updateLock.IsOn = state.Bool("locked");
        updateRollback.IsEnabled = state.Bool("can_rollback") && !state.Bool("busy") && !state.Bool("locked");
    }

    private static void ApplyComponentCard(JsonElement state, bool active, bool parser, Button check, Button install, Button cancel, TextBlock message, ProgressBar bar)
    {
        var configured = state.Bool("configured"); var official = state.GetProperty("official");
        var status = active ? state.String("status") : "idle";
        var cancelling = active && state.Bool("cancel_requested");
        var cancellable = (configured || parser) && active && status is ("checking" or "downloading" or "waiting");
        message.Text = active ? state.String("message")
            : parser ? "直接更新官方 PyPI 原包，版本与上游一致；依赖变化时单独更新执行环境。" : "完整管理 worker、Python 和配套依赖。";
        check.Content = parser ? "检查官方更新" : "检查环境更新";
        install.Content = parser ? "安装解析组件" : "安装运行环境";
        check.Visibility = cancellable || status == "available" ? Visibility.Collapsed : Visibility.Visible;
        check.IsEnabled = !state.Bool("busy") && (configured || parser && official.String("status") != "checking");
        install.Visibility = active && status == "available" ? Visibility.Visible : Visibility.Collapsed;
        install.IsEnabled = !state.Bool("locked");
        cancel.Visibility = cancellable ? Visibility.Visible : Visibility.Collapsed;
        cancel.Content = cancelling ? "正在取消…" : status == "checking" ? "取消检查" : status == "downloading" ? "取消下载" : "取消更新";
        cancel.IsEnabled = !cancelling;
        var done = state.TryGetProperty("downloaded_bytes", out var downloaded) && downloaded.TryGetInt64(out var bytes) ? bytes : 0;
        var total = state.TryGetProperty("total_bytes", out var size) && size.TryGetInt64(out var count) ? count : 0;
        bar.Visibility = active && (state.Bool("busy") || parser && official.String("status") == "checking") ? Visibility.Visible : Visibility.Collapsed;
        bar.IsIndeterminate = status != "downloading" || total <= 0 || done >= total;
        bar.Value = total > 0 ? Math.Clamp(100.0 * done / total, 0, 100) : 0;
        if (active && status == "downloading" && total > 0 && done >= total && !cancelling) message.Text = "下载完成，正在校验与自检…";
    }

    private async Task ShowToolDetailsAsync(string kind)
    {
        var text = "版本信息暂不可用。";
        if (snapshot.TryGetProperty("media_tools", out var tools)) text = kind == "ffmpeg"
            ? $"FFmpeg：{tools.String("ffmpeg", "未知")}\n\nffprobe：{tools.String("ffprobe", "未知")}\n\n来源：随当前执行环境提供，两个工具成对管理。"
            : $"yt-dlp：{tools.String("yt-dlp", "未知")}\n\n来源：随当前执行环境提供。";
        var dialog = new ContentDialog { XamlRoot = Root.XamlRoot, RequestedTheme = Root.ActualTheme, Title = kind == "ffmpeg" ? "FFmpeg / ffprobe" : "yt-dlp",
            Content = new TextBlock { Text = text, TextWrapping = TextWrapping.Wrap, IsTextSelectionEnabled = true }, CloseButtonText = "关闭" };
        await dialog.ShowAsync();
    }

    private async Task ShowVersionsAsync()
    {
        var dialog = new ContentDialog { XamlRoot = Root.XamlRoot, RequestedTheme = Root.ActualTheme,
            Title = "版本信息", Content = new TextBlock { Text = versionText.Text, TextWrapping = TextWrapping.Wrap, IsTextSelectionEnabled = true },
            SecondaryButtonText = "导出诊断", CloseButtonText = "关闭", DefaultButton = ContentDialogButton.Close };
        if (await dialog.ShowAsync() == ContentDialogResult.Secondary) await ExportDiagnosticsAsync();
    }

    private void RefreshConnection()
    {
        if (snapshot.ValueKind != JsonValueKind.Object || platformPicker.SelectedItem is not ComboBoxItem selected) return;
        foreach (var platform in snapshot.GetProperty("platforms").EnumerateArray()) if (platform.String("id") == selected.Tag as string) {
            credentialHint.Text = platform.String("hint", "登录凭据仅在本机加密保存，留空将保留已有设置。");
            if (credentialHint.Text.Length == 0) credentialHint.Text = "登录凭据仅在本机加密保存，留空将保留已有设置。";
            connectionState.Text = $"Cookie：{(platform.Bool("cookie_saved") ? "已保存" : "未设置")} · 代理：{(platform.Bool("proxy_saved") ? "已设置" : "直连")}";
            break;
        }
    }

    private async Task ExportDiagnosticsAsync()
    {
        var data = await CallAsync("diagnostics"); if (data is null) return;
        var picker = new FileSavePicker { SuggestedFileName = "MediaDownloader-diagnostics" };
        picker.FileTypeChoices.Add("诊断文件", new List<string> { ".json" });
        WinRT.Interop.InitializeWithWindow.Initialize(picker, WinRT.Interop.WindowNative.GetWindowHandle(this));
        var file = await picker.PickSaveFileAsync();
        if (file is not null) { await FileIO.WriteTextAsync(file, data.Value.GetRawText()); ShowInfo("诊断文件已导出，不包含链接与登录凭据。"); }
    }
}


