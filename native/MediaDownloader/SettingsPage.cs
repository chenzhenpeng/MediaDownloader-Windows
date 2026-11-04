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
    private readonly Expander updateAdvanced = new() { Header = "更新选项", HorizontalAlignment = HorizontalAlignment.Stretch, HorizontalContentAlignment = HorizontalAlignment.Stretch };
    private readonly StackPanel updateActions = new() { Orientation = Orientation.Horizontal, Spacing = 8 };
    private Grid settingsThemeRow = null!, settingsAboutRow = null!;
    private Button updateCheck = null!, updateInstall = null!, updateCancel = null!, updateRollback = null!;

    private static Grid SettingRow(string title, string description, FrameworkElement control)
    {
        var row = new Grid { ColumnSpacing = 24, Padding = new Thickness(16, 12, 16, 12), MinHeight = 64 };
        row.ColumnDefinitions.Add(new ColumnDefinition()); row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(180) });
        var words = new StackPanel { Spacing = 4, VerticalAlignment = VerticalAlignment.Center };
        words.Children.Add(Text(title));
        var detail = Text(description, "SecondaryText"); detail.FontSize = 12;
        words.Children.Add(detail); row.Children.Add(words);
        control.HorizontalAlignment = HorizontalAlignment.Right; control.VerticalAlignment = VerticalAlignment.Center;
        Grid.SetColumn(control, 1); row.Children.Add(control); return row;
    }

    private static Border SettingsCard(UIElement content) => new() { Style = (Style)Application.Current.Resources["SurfaceCard"], Padding = new Thickness(0), Child = content };
    private static StackPanel SettingsGroup(string title)
    {
        var group = new StackPanel { Spacing = 8 };
        var heading = Text(title); heading.FontWeight = Microsoft.UI.Text.FontWeights.SemiBold;
        group.Children.Add(heading); return group;
    }

    private void BuildSettings()
    {
        var body = new StackPanel { Spacing = 20, MaxWidth = 1040, HorizontalAlignment = HorizontalAlignment.Stretch };
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
        connectionSection.Header = "登录凭据与代理";
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
        var updates = SettingsGroup("更新");
        updateCheck = ActionButton("检查更新", async (_, _) => {
            if (snapshot.GetProperty("update").Bool("configured")) await CallAsync("update", new { action = "check" });
            else await CallAsync("official_update");
        });
        var coreRow = SettingRow("解析内核", "", updateCheck);
        updateMessage.Style = (Style)Application.Current.Resources["SecondaryText"]; updateMessage.FontSize = 12;
        ((StackPanel)coreRow.Children[0]).Children.RemoveAt(1); ((StackPanel)coreRow.Children[0]).Children.Add(updateMessage);
        updates.Children.Add(SettingsCard(coreRow));
        var officialPage = new HyperlinkButton { Content = "查看 ParseHub 官方发布", Padding = new Thickness(0), FontSize = 12 };
        officialPage.Click += async (_, _) => await Windows.System.Launcher.LaunchUriAsync(new Uri("https://github.com/z-mio/ParseHub/releases"));
        updates.Children.Add(officialPage);
        updateInstall = ActionButton("安装内核更新", async (_, _) => await CallAsync("update", new { action = "install" }), true);
        updateCancel = ActionButton("取消更新", async (_, _) => await CallAsync("update", new { action = "cancel" }));
        updateActions.Children.Add(updateInstall); updateActions.Children.Add(updateCancel); updates.Children.Add(updateActions);
        var options = new StackPanel { Spacing = 0 };
        updateAuto.Toggled += async (_, _) => { if (!loadingSnapshot) await CallAsync("update", new { action = "auto", value = updateAuto.IsOn }); };
        updateLock.Toggled += async (_, _) => { if (!loadingSnapshot) await CallAsync("update", new { action = "lock", value = updateLock.IsOn }); };
        updateRollback = ActionButton("回滚上一版本", async (_, _) => {
            if (await ConfirmAsync("回滚内核", "等待当前任务结束后切换，任务记录与文件会保留。", "回滚内核")) await CallAsync("update", new { action = "rollback" });
        });
        options.Children.Add(SettingRow("自动检查", "每 24 小时检查，仅提示可用更新。", updateAuto));
        options.Children.Add(SettingRow("锁定当前内核", "暂停安装与手动回滚。", updateLock));
        options.Children.Add(SettingRow("恢复上一版本", "遇到新内核问题时使用。", updateRollback));
        updateAdvanced.Content = options; updates.Children.Add(updateAdvanced); body.Children.Add(updates);
        var about = SettingsGroup("关于");
        var aboutRow = SettingRow("Media Downloader", "", ActionButton("版本详情", async (_, _) => await ShowVersionsAsync()));
        settingsAboutRow = aboutRow;
        productVersion.Style = (Style)Application.Current.Resources["SecondaryText"]; productVersion.FontSize = 12;
        ((StackPanel)aboutRow.Children[0]).Children.RemoveAt(1); ((StackPanel)aboutRow.Children[0]).Children.Add(productVersion);
        about.Children.Add(SettingsCard(aboutRow)); body.Children.Add(about);
        settingsPage.Children.Add(Scroller(body));
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
        updateMessage.Text = configured ? state.String("message") : official.String("message");
        updateCheck.Content = configured ? "检查内核更新" : "检查官方更新";
        updateCheck.Visibility = Visibility.Visible;
        updateCheck.IsEnabled = configured ? !state.Bool("busy") : official.String("status") != "checking";
        updateInstall.Visibility = state.String("status") == "available" ? Visibility.Visible : Visibility.Collapsed;
        updateInstall.IsEnabled = !state.Bool("locked");
        updateCancel.Visibility = state.String("status") is "checking" or "downloading" or "waiting" ? Visibility.Visible : Visibility.Collapsed;
        updateActions.Visibility = updateInstall.Visibility == Visibility.Visible || updateCancel.Visibility == Visibility.Visible ? Visibility.Visible : Visibility.Collapsed;
        updateAdvanced.Visibility = configured || state.Bool("can_rollback") || state.Bool("locked") ? Visibility.Visible : Visibility.Collapsed;
        updateAuto.IsEnabled = state.Bool("configured"); updateAuto.IsOn = state.Bool("auto"); updateLock.IsOn = state.Bool("locked");
        updateRollback.IsEnabled = state.Bool("can_rollback") && !state.Bool("busy") && !state.Bool("locked");
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


