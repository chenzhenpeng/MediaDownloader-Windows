using System.Text.Json;
using System.Runtime.InteropServices.WindowsRuntime;
using Microsoft.UI.Xaml.Media.Imaging;
using Windows.Graphics.Imaging;
using Windows.Storage;

namespace MediaDownloader;

public sealed partial class MainWindow
{
    private bool capturing;
    private async Task CaptureIfRequestedAsync()
    {
        var output = App.Option("--smoke-report");
        if (output is null || capturing || snapshot.ValueKind != JsonValueKind.Object) return;
        if (!snapshot.GetProperty("platforms").EnumerateArray().Any(p => p.Bool("available"))) return;
        capturing = true;
        try {
            var page = App.Option("--smoke-page") ?? "home";
            if (page == "settings") Nav.SelectedItem = Nav.SettingsItem;
            else if (page is "downloads" or "in_progress" or "completed" or "failed") {
                GoDownloads(page switch { "in_progress" => "active", "completed" => "completed", "failed" => "failed", _ => "" });
                await ChangeViewAsync();
            } else GoHome();
            if (page == "settings" && App.Option("--smoke-settings-expanded") == "true") connectionSection.IsExpanded = true;
            if (page == "settings" && App.Option("--smoke-cookie-fixture") == "true") {
                await CallAsync("connection", new { platform = "bilibili", cookie = "test_cookie=fixture" });
                await LoadSavedCookieAsync();
            }
            if (App.Option("--smoke-nav-collapsed") == "true") Nav.IsPaneOpen = false;
            await Task.Delay(1200);
            Root.UpdateLayout();
            var layout = CheckLayout(page);
            var bitmap = new RenderTargetBitmap();
            var scale = Root.XamlRoot.RasterizationScale;
            await bitmap.RenderAsync(Root, (int)(Root.ActualWidth * scale), (int)(Root.ActualHeight * scale));
            var pixels = await bitmap.GetPixelsAsync();
            Directory.CreateDirectory(System.IO.Path.GetDirectoryName(System.IO.Path.GetFullPath(output))!);
            var imagePath = System.IO.Path.ChangeExtension(output, ".png");
            File.WriteAllBytes(imagePath, []);
            var file = await StorageFile.GetFileFromPathAsync(System.IO.Path.GetFullPath(imagePath));
            using (var stream = await file.OpenAsync(FileAccessMode.ReadWrite)) {
                var encoder = await BitmapEncoder.CreateAsync(BitmapEncoder.PngEncoderId, stream);
                encoder.SetPixelData(BitmapPixelFormat.Bgra8, BitmapAlphaMode.Premultiplied, (uint)bitmap.PixelWidth, (uint)bitmap.PixelHeight, 96 * scale, 96 * scale, pixels.ToArray());
                await encoder.FlushAsync();
            }
            File.WriteAllText(output, JsonSerializer.Serialize(new { native_ui = "WinUI 3", page, scale, layout, backend = snapshot }, new JsonSerializerOptions { WriteIndented = true }));
        } catch (Exception e) { File.WriteAllText(output + ".error", e.GetType().FullName + "\n" + e.StackTrace); }
        finally { allowClose = true; if (backend is not null) await backend.DisposeAsync(); Close(); }
    }

    private object CheckLayout(string page)
    {
        double Left(Microsoft.UI.Xaml.FrameworkElement element) => element.TransformToVisual(Root).TransformPoint(new Windows.Foundation.Point()).X;
        double Right(Microsoft.UI.Xaml.FrameworkElement element) => Left(element) + element.ActualWidth;
        var left = Left(ContentHost); var right = Right(ContentHost);
        var checks = new Dictionary<string, bool>();
        if (page == "home") {
            checks["input_starts_at_page_margin"] = Math.Abs(Left(linkInput) - left - 24) < 2;
            checks["parse_button_inside_viewport"] = Right(parseButton) <= right + 1 && Left(parseButton) >= left;
            checks["input_inside_viewport"] = Right(linkInput) <= right + 1;
            checks["home_uses_available_width"] = right - Right(parseButton) >= 23 && right - Right(parseButton) <= 27;
        }
        if (page is "downloads" or "in_progress" or "completed" or "failed" && visibleTasks.Count == 0) {
            var button = (Microsoft.UI.Xaml.FrameworkElement)taskEmpty.Children[^1];
            checks["empty_button_centered"] = Math.Abs(Left(button) + button.ActualWidth / 2 - Left(taskEmpty) - taskEmpty.ActualWidth / 2) < 1;
            checks["empty_panel_inside_viewport"] = Left(taskEmpty) >= left && Right(taskEmpty) <= right + 1;
        }
        checks["navigation_is_consolidated"] = Nav.MenuItems.Count == 2;
        checks["no_empty_navigation_footer"] = Nav.PaneFooter is null;
        if (App.Option("--smoke-nav-collapsed") == "true") checks["navigation_collapsed"] = !Nav.IsPaneOpen;
        if (page is "downloads" or "in_progress" or "completed" or "failed") {
            checks["four_task_filters"] = taskFilter.Items.Count == 4;
            checks["task_filter_selected"] = SelectedTaskState == (page switch { "in_progress" => "active", "completed" => "completed", "failed" => "failed", _ => "" });
        }
        if (page == "settings") {
            checks["cookie_uses_masked_control"] = cookieInput.PasswordRevealMode == Microsoft.UI.Xaml.Controls.PasswordRevealMode.Peek;
            if (App.Option("--smoke-cookie-fixture") == "true") checks["saved_cookie_is_reloaded"] = cookieInput.Password == "test_cookie=fixture";
            checks["theme_picker_inside_viewport"] = Left(themePicker) >= left && Right(themePicker) <= right + 1;
            checks["compact_setting_row"] = settingsThemeRow.ActualHeight <= 72;
            checks["worker_choice_matches_setting"] = workerCount.SelectedIndex + 1 == Math.Clamp(snapshot.GetProperty("settings").Number("max_workers"), 1, 4);
            checks["worker_control_inside_viewport"] = Left(workerCount) >= left && Right(workerCount) <= right + 1;
            checks["about_row_inside_page_width"] = Left(settingsAboutRow) >= left && Right(settingsAboutRow) <= right + 1;
            checks["product_version_readable"] = !productVersion.Text.Contains(".dev", StringComparison.Ordinal) && productVersion.Text.StartsWith("版本 ", StringComparison.Ordinal);
            if (!snapshot.GetProperty("update").Bool("configured")) {
                checks["official_update_entry_visible"] = updateCheck.Visibility == Microsoft.UI.Xaml.Visibility.Visible && (updateCheck.Content as string) == "检查官方更新";
                if (!snapshot.GetProperty("update").Bool("can_rollback") && !snapshot.GetProperty("update").Bool("locked"))
                    checks["unavailable_update_options_hidden"] = updateAdvanced.Visibility == Microsoft.UI.Xaml.Visibility.Collapsed;
            }
            if (App.Option("--smoke-theme") is "dark" or "light")
                checks["requested_theme_applied"] = Root.ActualTheme.ToString().Equals(App.Option("--smoke-theme"), StringComparison.OrdinalIgnoreCase);
        }
        if (checks.Values.Any(pass => !pass)) throw new InvalidOperationException("Layout bounds check failed: " + string.Join(",", checks.Where(c => !c.Value).Select(c => c.Key)));
        return new { viewport_width = ContentHost.ActualWidth, checks };
    }
}
