using System.Text.Json;
using System.Runtime.InteropServices.WindowsRuntime;
using Microsoft.UI.Xaml.Media.Imaging;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml;
using Windows.Graphics.Imaging;
using Windows.Storage;

namespace MediaDownloader;

public sealed partial class MainWindow
{
    private bool capturing;
    private bool downloadTransitionStable;
    private async Task CaptureIfRequestedAsync()
    {
        var output = App.Option("--smoke-report");
        if (output is null || capturing || snapshot.ValueKind != JsonValueKind.Object) return;
        if (!snapshot.GetProperty("platforms").EnumerateArray().Any(p => p.Bool("available"))) return;
        capturing = true;
        try {
            var page = App.Option("--smoke-page") ?? "home";
            if (App.Option("--smoke-notice-navigation") == "true") { GoHome(); ShowInfo("界面验收：旧页面提示"); }
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
            var updateFixture = App.Option("--smoke-update-state");
            if (page == "settings" && updateFixture is ("checking" or "downloading" or "validating" or "waiting" or "available" or "cancelling" or "failed" or "unconfigured")) {
                var status = updateFixture is "validating" ? "downloading" : updateFixture is "cancelling" ? "checking" : updateFixture;
                ApplyUpdateState(JsonSerializer.SerializeToElement(new {
                    configured = updateFixture != "unconfigured", status,
                    message = "界面验收：更新状态示例", busy = status is "checking" or "downloading" or "waiting",
                    locked = false, auto = false, can_rollback = false, cancel_requested = updateFixture == "cancelling",
                    downloaded_bytes = updateFixture == "validating" ? 1000 : 400, total_bytes = 1000,
                    official = new { status = "idle", message = "界面验收：尚未配置更新源" }
                }));
                await Task.Delay(200);
            }
            var parseFixture = App.Option("--smoke-parse-state");
            if (page == "home" && parseFixture is ("ready" or "parsing" or "failed" or "download-transition")) {
                var item = new TaskItem();
                var transition = parseFixture == "download-transition";
                item.Update(JsonSerializer.SerializeToElement(new {
                    id = "visual-smoke-only", title = "界面验收示例", state = transition ? "ready" : parseFixture,
                    action = "inspect", has_preview = transition || parseFixture == "ready",
                    platform_name = "哔哩哔哩", path = "", error = parseFixture == "failed" ? "示例：作品暂时不可用" : "",
                    media = transition || parseFixture == "ready" ? new[] { "视频 · MP4 · 1280 × 720 · 0:16" } : Array.Empty<string>()
                }));
                RefreshParsing([item]);
                if (transition) {
                    downloadTransitionStable = parsingResults.Count == 1;
                    foreach (var state in new[] { "queued", "parsing", "downloading" }) {
                        item.Update(JsonSerializer.SerializeToElement(new {
                            id = "visual-smoke-only", title = "界面验收示例", state, action = "download", has_preview = true,
                            platform_name = "哔哩哔哩", path = "", error = "",
                            media = new[] { "视频 · MP4 · 1280 × 720 · 0:16" }
                        }));
                        RefreshParsing([item]);
                        downloadTransitionStable &= parsingResults.Count == 1 && ReferenceEquals(parsingResults[0], item)
                            && parseProgress.Visibility == Visibility.Collapsed && parseFinished.Text == "已解析 1 个 · 失败 0 个"
                            && item.StateLabel == (state == "queued" ? "等待下载" : state == "parsing" ? "准备下载" : "下载中");
                        await Task.Delay(100);
                    }
                }
                await Task.Delay(250);
            }
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
            File.WriteAllText(output, JsonSerializer.Serialize(new { native_ui = "WinUI 3", page, parse_visual_fixture = parseFixture, update_visual_fixture = updateFixture, scale, layout, backend = snapshot }, new JsonSerializerOptions { WriteIndented = true }));
            if (int.TryParse(App.Option("--smoke-hold-seconds"), out var seconds)) await Task.Delay(Math.Clamp(seconds, 0, 120) * 1000);
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
            checks["home_uses_available_width"] = Math.Abs(Right(composerCard) - Right(parseButton) - 24) < 2;
            checks["parse_flow_uses_available_width"] = Math.Abs(right - Right(parseFlowCard)) < 2;
            checks["composer_and_flow_do_not_overlap"] = workbenchWide == true
                ? Right(composerCard) + 15 <= Left(parseFlowCard)
                : parseFlowCard.TransformToVisual(composerCard).TransformPoint(new Windows.Foundation.Point()).Y >= composerCard.ActualHeight + 15;
            var fixture = App.Option("--smoke-parse-state");
            checks["home_results_are_current_batch"] = parsingResults.Count == (fixture is "ready" or "failed" or "download-transition" ? 1 : 0);
            if (fixture == "download-transition") checks["download_preparation_keeps_preview"] = downloadTransitionStable;
            checks["parse_activity_matches_stage"] = (parseProgress.Visibility == Microsoft.UI.Xaml.Visibility.Visible) == (fixture == "parsing");
            checks["workbench_matches_window_width"] = workbenchWide == (ContentHost.ActualWidth >= 960);
            if (fixture is "ready" or "failed") checks["result_row_is_rendered"] = parsingList.ContainerFromIndex(0) is ListViewItem row && row.ActualHeight >= 80;
            if (fixture == "failed") checks["failure_reason_is_visible"] = parsingResults[0].ErrorVisibility == Microsoft.UI.Xaml.Visibility.Visible;
        }
        if (page is "downloads" or "in_progress" or "completed" or "failed" && visibleTasks.Count == 0) {
            var button = (Microsoft.UI.Xaml.FrameworkElement)taskEmpty.Children[^1];
            checks["empty_button_centered"] = Math.Abs(Left(button) + button.ActualWidth / 2 - Left(taskEmpty) - taskEmpty.ActualWidth / 2) < 1;
            checks["empty_panel_inside_viewport"] = Left(taskEmpty) >= left && Right(taskEmpty) <= right + 1;
        }
        checks["navigation_is_consolidated"] = Nav.MenuItems.Count == 2;
        checks["no_empty_navigation_footer"] = Nav.PaneFooter is null;
        checks["navigation_icons_share_size"] = Nav.MenuItems.OfType<NavigationViewItem>().All(item => item.Icon is FontIcon icon && icon.FontSize == 20 && icon.Width == 20) && Nav.SettingsItem is NavigationViewItem settings && settings.Icon is FontIcon settingsIcon && settingsIcon.FontSize == 20;
        checks["pane_toggle_matches_navigation"] = paneToggleIcon?.Width == 20 && paneToggleIcon.Height == 20;
        if (App.Option("--smoke-nav-collapsed") == "true") checks["navigation_collapsed"] = !Nav.IsPaneOpen;
        if (page is "downloads" or "in_progress" or "completed" or "failed") {
            checks["four_task_filters"] = taskFilter.Items.Count == 4;
            checks["task_filter_selected"] = SelectedTaskState == (page switch { "in_progress" => "active", "completed" => "completed", "failed" => "failed", _ => "" });
        }
        if (page == "settings") {
            checks["setting_and_expander_text_align"] = Math.Abs(Left((FrameworkElement)settingsThemeRow.Children[0]) - Left((FrameworkElement)connectionHeader.Children[1])) < 2;
            checks["update_actions_inside_card"] = Left(updateActions) >= Left(settingsUpdateRow) && Right(updateActions) <= Right(settingsUpdateRow) - 15;
            checks["one_contextual_update_action"] = updateActions.Children.OfType<FrameworkElement>().Count(child => child.Visibility == Microsoft.UI.Xaml.Visibility.Visible) == 1;
            if (App.Option("--smoke-notice-navigation") == "true") checks["old_notice_cleared_on_navigation"] = !GlobalNotice.IsOpen;
            var updateFixture = App.Option("--smoke-update-state");
            if (updateFixture is "checking" or "downloading" or "validating" or "waiting" or "cancelling") checks["cancel_action_stays_in_row"] = updateCancel.Visibility == Microsoft.UI.Xaml.Visibility.Visible && updateCheck.Visibility == Microsoft.UI.Xaml.Visibility.Collapsed;
            if (updateFixture == "downloading") checks["actual_download_progress_rendered"] = !updateProgress.IsIndeterminate && updateProgress.Value == 40;
            if (updateFixture == "cancelling") checks["repeated_cancel_disabled"] = !updateCancel.IsEnabled;
            if (updateFixture == "available") checks["install_action_visible"] = updateInstall.Visibility == Microsoft.UI.Xaml.Visibility.Visible;
            checks["settings_uses_available_width"] = right - Right(settingsThemeRow) >= 0 && right - Right(settingsThemeRow) <= 48;
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
        return new { viewport_width = ContentHost.ActualWidth, checks, navigation_toggle_visuals = navigationToggleVisuals };
    }
}
