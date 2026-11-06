using System.Collections.ObjectModel;
using System.Runtime.InteropServices;
using System.Text.Json;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Windows.Graphics;
using Windows.Storage;
using Windows.Storage.Pickers;
using Windows.System;

namespace MediaDownloader;

public sealed partial class MainWindow : Window
{
    private BackendBridge? backend;
    private readonly Dictionary<string, TaskItem> models = new();
    private readonly ObservableCollection<TaskItem> visibleTasks = new(), parsingResults = new();
    private readonly Grid homePage = new(), taskPage = new(), settingsPage = new();
    private JsonElement snapshot;
    private bool initialized, loadingSnapshot, allowClose;
    private string currentPage = "home";
    private readonly DispatcherTimer searchTimer = new() { Interval = TimeSpan.FromMilliseconds(250) };
    private readonly DispatcherTimer noticeTimer = new() { Interval = TimeSpan.FromSeconds(5) };
    private IconElement? paneToggleIcon;
    private string[] navigationToggleVisuals = [];
    [DllImport("user32.dll")] private static extern uint GetDpiForWindow(nint window);

    public MainWindow()
    {
        InitializeComponent(); Root.Language = "zh-CN";
        Nav.Loaded += (_, _) => AlignNavigationIcons();
        noticeTimer.Tick += (_, _) => { noticeTimer.Stop(); GlobalNotice.IsOpen = false; };
        ExtendsContentIntoTitleBar = true; SetTitleBar(AppTitleBar);
        Root.ActualThemeChanged += (_, _) => ApplyCaptionTheme();
        AppWindow.SetIcon(System.IO.Path.Combine(AppContext.BaseDirectory, "Assets", "AppIcon.ico"));
        var scale = GetDpiForWindow(WinRT.Interop.WindowNative.GetWindowHandle(this)) / 96.0;
        var area = Microsoft.UI.Windowing.DisplayArea.GetFromWindowId(AppWindow.Id, Microsoft.UI.Windowing.DisplayAreaFallback.Primary).WorkArea;
        var initialWidth = int.TryParse(App.Option("--smoke-width"), out var requestedWidth) ? Math.Clamp(requestedWidth, 760, 2400) : 1280;
        AppWindow.Resize(new SizeInt32(Math.Min((int)(initialWidth * scale), area.Width - 40), Math.Min((int)(800 * scale), area.Height - 40)));
        if (App.Option("--smoke-maximized") == "true" && AppWindow.Presenter is Microsoft.UI.Windowing.OverlappedPresenter presenter) presenter.Maximize();
        BuildHome(); BuildTasks(); BuildSettings();
        ContentHost.Children.Add(homePage); ContentHost.Children.Add(taskPage); ContentHost.Children.Add(settingsPage);
        searchTimer.Tick += async (_, _) => { searchTimer.Stop(); await ChangeViewAsync(); };
        initialized = true; Nav.SelectedItem = Nav.MenuItems[0];
        AppWindow.Closing += async (_, args) => {
            if (allowClose) return;
            args.Cancel = true;
            if (snapshot.ValueKind == JsonValueKind.Object && snapshot.GetProperty("counts").Number("active") > 0)
                if (!await ConfirmAsync("退出应用", "未结束的任务会被取消，已下载的文件会保留。", "退出应用")) return;
            allowClose = true;
            if (backend is not null) await backend.DisposeAsync();
            Close();
        };
        Root.Loaded += async (_, _) => {
            if (backend is not null) return;
            try {
                backend = new BackendBridge(App.Option("--data-dir"));
                backend.Snapshot += value => DispatcherQueue.TryEnqueue(() => ApplySnapshot(value));
                backend.Failed += message => DispatcherQueue.TryEnqueue(() => ShowError(message));
                if (App.Option("--smoke-theme") is "light" or "dark" && App.Option("--smoke-report") is not null)
                    await backend.CallAsync("settings", new { theme = App.Option("--smoke-theme") });
                await backend.CallAsync("hello");
            } catch { ShowError("无法启动任务服务，请完整解压应用后重试。"); }
        };
    }

    private void Nav_SelectionChanged(NavigationView sender, NavigationViewSelectionChangedEventArgs args)
    {
        if (!initialized) return;
        noticeTimer.Stop(); GlobalNotice.IsOpen = false;
        currentPage = args.IsSettingsSelected ? "settings" : (args.SelectedItemContainer?.Tag as string ?? "home");
        homePage.Visibility = currentPage == "home" ? Visibility.Visible : Visibility.Collapsed;
        taskPage.Visibility = currentPage == "downloads" ? Visibility.Visible : Visibility.Collapsed;
        settingsPage.Visibility = currentPage == "settings" ? Visibility.Visible : Visibility.Collapsed;
        if (currentPage == "settings") _ = LoadSavedCookieAsync();
        else credentialReadRevision++;
        _ = ChangeViewAsync();
    }

    private async Task ChangeViewAsync(int offset = 0)
    {
        if (backend is null) return;
        try {
            await backend.CallAsync("view", new { scope = "all",
                query = currentPage == "downloads" ? taskSearch.Text : "",
                state = currentPage == "downloads" ? SelectedTaskState : "", offset });
        } catch (Exception e) { ShowError(e.Message); }
    }

    private void ApplySnapshot(JsonElement value)
    {
        if (capturing && (App.Option("--smoke-parse-state") is ("ready" or "parsing" or "failed" or "download-transition") || App.Option("--smoke-update-state") is not null)) return;
        snapshot = value; loadingSnapshot = true;
        var ids = new HashSet<string>();
        TaskItem Model(JsonElement data) {
            var id = data.String("id"); ids.Add(id);
            if (!models.TryGetValue(id, out var model)) models[id] = model = new TaskItem();
            model.Update(data); return model;
        }
        Sync(visibleTasks, value.GetProperty("tasks").EnumerateArray().Select(Model).ToList());
        foreach (var entry in value.GetProperty("ready").EnumerateArray()) Model(entry);
        foreach (var entry in value.GetProperty("recent").EnumerateArray()) Model(entry);
        if (value.TryGetProperty("detail", out var detail) && detail.ValueKind == JsonValueKind.Object) Model(detail);
        if (value.TryGetProperty("submitted", out var submitted)) {
            var added = submitted.EnumerateArray().Select(Model).ToList();
            RefreshParsing(added);
            var pending = added.Where(t => pendingInspections.Contains(t.Id)).ToList();
            if (pending.Count > 0 && pending.All(t => t.State is "ready" or "failed" or "cancelled" or "interrupted" or "completed")) {
                var failed = pending.FirstOrDefault(t => t.State == "failed");
                if (currentPage == "home") {
                    if (failed is not null) ShowError(failed.Error.Length > 0 ? failed.Error : "作品解析失败，请在下载管理中查看详情。");
                    else ShowInfo("作品已准备好，请确认预览后开始下载。");
                }
                pendingInspections.Clear();
            }
        }
        foreach (var key in models.Keys.Where(key => !ids.Contains(key)).ToList()) models.Remove(key);
        var settings = value.GetProperty("settings");
        downloadRoot = settings.String("output_root");
        settingsFolder.Text = downloadRoot;
        ToolTipService.SetToolTip(settingsFolder, downloadRoot);
        var theme = settings.String("theme", "system");
        Root.RequestedTheme = theme == "dark" ? ElementTheme.Dark : theme == "light" ? ElementTheme.Light : ElementTheme.Default;
        ApplyCaptionTheme();
        themePicker.SelectedIndex = theme == "light" ? 1 : theme == "dark" ? 2 : 0;
        workerCount.SelectedIndex = Math.Clamp(settings.Number("max_workers"), 1, 4) - 1;
        var counts = value.GetProperty("counts");
        DownloadBadge.Value = counts.Number("active");
        DownloadBadge.Visibility = counts.Number("active") > 0 ? Visibility.Visible : Visibility.Collapsed;
        taskCount.Text = $"共 {value.Number("total")} 项";
        taskEmpty.Visibility = visibleTasks.Count == 0 ? Visibility.Visible : Visibility.Collapsed;
        taskList.Visibility = visibleTasks.Count > 0 ? Visibility.Visible : Visibility.Collapsed;
        taskEmptyTitle.Text = taskSearch.Text.Length > 0 ? "没有匹配的任务" : SelectedTaskState switch {
            "active" => "暂无进行中的任务", "completed" => "还没有完成的下载", "failed" => "暂无失败任务", _ => "还没有下载记录" };
        platformLink.Content = $"支持 {value.GetProperty("platforms").GetArrayLength()} 个平台";
        pager.Visibility = value.Number("total") > 50 ? Visibility.Visible : Visibility.Collapsed;
        previousPage.IsEnabled = value.Number("offset") > 0;
        nextPage.IsEnabled = value.Number("offset") + 50 < value.Number("total");
        ApplyUpdateState(value.GetProperty("update"));
        componentVersions.Text = $"版本 {value.String("parser_version", "未知")} · 官方 PyPI 原包";
        runtimeVersions.Text = "Worker、Python 环境和媒体工具分别管理，切换与回滚以完整组合为单位。";
        workerVersionInfo.Text = value.String("worker_version", "未知");
        pythonVersionInfo.Text = value.String("runtime_version", "未知");
        if (value.TryGetProperty("media_tools", out var tools)) {
            static string ShortVersion(string version) { var parts = version.Split(' ', StringSplitOptions.RemoveEmptyEntries); return parts.Length > 2 && parts[1] == "version" ? parts[2] : version; }
            ffmpegVersions.Text = $"FFmpeg {ShortVersion(tools.String("ffmpeg", "未知"))} · ffprobe {ShortVersion(tools.String("ffprobe", "未知"))} · {(value.String("media_tools_source") == "local" ? "本地目录" : "独立工具包")}";
            ytdlpVersions.Text = $"{tools.String("yt-dlp", "版本未知")} · 随环境提供";
        }
        versionText.Text = $"应用 {value.String("client_version")} · Worker {value.String("worker_version")} · ParseHub {value.String("parser_version", "未知")} · Python 环境 {value.String("runtime_version")}";
        var clientVersion = value.String("client_version"); var devIndex = clientVersion.IndexOf(".dev", StringComparison.Ordinal);
        productVersion.Text = devIndex >= 0 ? $"版本 {clientVersion[..devIndex]} · 预览版 {clientVersion[(devIndex + 4)..]}" : $"版本 {clientVersion}";
        loadingSnapshot = false;
        _ = CaptureIfRequestedAsync();
    }

    private static void Sync(ObservableCollection<TaskItem> target, List<TaskItem> values)
    {
        for (var i = 0; i < values.Count; i++) {
            if (i < target.Count && ReferenceEquals(target[i], values[i])) continue;
            var index = target.IndexOf(values[i]);
            if (index >= 0) target.Move(index, i); else target.Insert(i, values[i]);
        }
        while (target.Count > values.Count) target.RemoveAt(target.Count - 1);
    }
    private async Task<JsonElement?> CallAsync(string method, object? args = null)
    {
        if (backend is null) { ShowError("任务服务尚未就绪，请稍候。"); return null; }
        try { return await backend.CallAsync(method, args); }
        catch (Exception e) { ShowError(e.Message); return null; }
    }
    private void ShowError(string text) { noticeTimer.Stop(); GlobalNotice.Title = "操作未完成"; GlobalNotice.Message = text; GlobalNotice.Severity = InfoBarSeverity.Error; GlobalNotice.IsOpen = true; }
    private void ShowInfo(string text) { GlobalNotice.Title = ""; GlobalNotice.Message = text; GlobalNotice.Severity = InfoBarSeverity.Informational; GlobalNotice.IsOpen = true; noticeTimer.Stop(); noticeTimer.Start(); }
    private static IEnumerable<DependencyObject> Descendants(DependencyObject root) {
        for (var i = 0; i < Microsoft.UI.Xaml.Media.VisualTreeHelper.GetChildrenCount(root); i++) {
            var child = Microsoft.UI.Xaml.Media.VisualTreeHelper.GetChild(root, i); yield return child;
            foreach (var nested in Descendants(child)) yield return nested;
        }
    }
    private void AlignNavigationIcons() {
        if (Nav.SettingsItem is NavigationViewItem settings) settings.Icon = new FontIcon { Glyph = "\uE713", Style = (Style)Application.Current.Resources["NavigationIcon"] };
        var toggle = Descendants(Nav).OfType<Button>().FirstOrDefault(button => button.Name == "TogglePaneButton");
        if (toggle is null) return;
        toggle.ApplyTemplate();
        navigationToggleVisuals = Descendants(toggle).Select(child => child.GetType().Name + ":" + (child as FrameworkElement)?.Name).ToArray();
        foreach (var icon in Descendants(toggle).OfType<IconElement>()) {
            if (icon is FontIcon font) { font.FontFamily = (Microsoft.UI.Xaml.Media.FontFamily)Application.Current.Resources["SymbolThemeFontFamily"]; font.FontSize = 20; } icon.Width = 20; icon.Height = 20;
            paneToggleIcon = icon;
        }
    }
    private void ApplyCaptionTheme()
    {
        var dark = Root.ActualTheme == ElementTheme.Dark;
        var foreground = dark ? Microsoft.UI.Colors.White : Microsoft.UI.Colors.Black;
        if (new Windows.UI.ViewManagement.AccessibilitySettings().HighContrast)
            foreground = new Windows.UI.ViewManagement.UISettings().GetColorValue(Windows.UI.ViewManagement.UIColorType.Foreground);
        AppWindow.TitleBar.ButtonForegroundColor = foreground;
        AppWindow.TitleBar.ButtonInactiveForegroundColor = foreground;
        AppWindow.TitleBar.ButtonBackgroundColor = Microsoft.UI.Colors.Transparent;
        AppWindow.TitleBar.ButtonInactiveBackgroundColor = Microsoft.UI.Colors.Transparent;
    }
    private async Task<bool> ConfirmAsync(string title, string text, string action)
    {
        var dialog = new ContentDialog { XamlRoot = Root.XamlRoot, RequestedTheme = Root.ActualTheme, Title = title,
            Content = new TextBlock { Text = text, TextWrapping = TextWrapping.Wrap },
            PrimaryButtonText = action, CloseButtonText = "取消", DefaultButton = ContentDialogButton.Close };
        return await dialog.ShowAsync() == ContentDialogResult.Primary;
    }
    private static TextBlock Text(string text, string? style = null) => new() {
        Text = text, TextWrapping = TextWrapping.Wrap,
        Style = style is null ? null : (Style)Application.Current.Resources[style]
    };
    private static Button ActionButton(string text, RoutedEventHandler action, bool primary = false)
    {
        var button = new Button { Content = text, VerticalAlignment = VerticalAlignment.Center };
        if (primary) button.Style = (Style)Application.Current.Resources["AccentButtonStyle"];
        button.Click += action; return button;
    }
    private static Border Card(UIElement child) => new() { Style = (Style)Application.Current.Resources["SurfaceCard"], Child = child };
    private static ScrollViewer Scroller(FrameworkElement content, double maxWidth = 1040)
    {
        // Keep a finite, left-aligned content width even when the window is wider
        // than MaxWidth. Do not let ScrollContentPresenter arrange a stretched,
        // constrained StackPanel beyond the visible viewport.
        content.HorizontalAlignment = HorizontalAlignment.Left;
        var viewer = new ScrollViewer { Content = content,
            HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled,
            HorizontalScrollMode = ScrollMode.Disabled,
            HorizontalContentAlignment = HorizontalAlignment.Left,
            VerticalContentAlignment = VerticalAlignment.Top };
        void Fit() {
            var width = viewer.ViewportWidth > 0 ? viewer.ViewportWidth : viewer.ActualWidth;
            if (width > 0) content.Width = Math.Min(maxWidth, width);
        }
        viewer.SizeChanged += (_, _) => Fit();
        viewer.Loaded += (_, _) => Fit();
        return viewer;
    }
    private StackPanel PageHeader(string title, string subtitle) {
        var panel = new StackPanel { Spacing = 6 }; panel.Children.Add(Text(title, "PageTitle")); panel.Children.Add(Text(subtitle, "SecondaryText")); return panel;
    }
    private void GoHome() { Nav.SelectedItem = Nav.MenuItems[0]; }
    private string SelectedTaskState => taskFilter.SelectedItem?.Tag as string ?? "";
    private void GoDownloads(string state = "")
    {
        Nav.SelectedItem = Nav.MenuItems[1];
        loadingSnapshot = true;
        taskSearch.Text = "";
        taskFilter.SelectedItem = taskFilter.Items.First(item => (item.Tag as string ?? "") == state);
        loadingSnapshot = false;
        _ = ChangeViewAsync();
    }
    private async Task OpenPathAsync(TaskItem task, bool media)
    {
        var result = await CallAsync("file", new { id = task.Id, media });
        if (result is null) return;
        try {
            var path = result.Value.String("path");
            if (Directory.Exists(path)) await Launcher.LaunchFolderAsync(await StorageFolder.GetFolderFromPathAsync(path));
            else await Launcher.LaunchFileAsync(await StorageFile.GetFileFromPathAsync(path));
        } catch { ShowError("无法打开文件，请检查保存位置或 Windows 默认应用设置。"); }
    }
    private async Task PickFolderAsync()
    {
        var picker = new FolderPicker(); picker.FileTypeFilter.Add("*");
        WinRT.Interop.InitializeWithWindow.Initialize(picker, WinRT.Interop.WindowNative.GetWindowHandle(this));
        var folder = await picker.PickSingleFolderAsync();
        if (folder is not null) await CallAsync("settings", new { output_root = folder.Path });
    }
}

