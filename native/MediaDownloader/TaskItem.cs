using System.ComponentModel;
using System.Text.Json;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Media.Imaging;
using Windows.Storage.Streams;

namespace MediaDownloader;

public sealed class TaskItem : INotifyPropertyChanged
{
    public string Id { get; private set; } = "";
    public string Title { get; private set; } = "";
    public string State { get; private set; } = "";
    public string PlatformName { get; private set; } = "";
    public string Path { get; private set; } = "";
    public string Error { get; private set; } = "";
    public string[] Media { get; private set; } = [];
    public bool Invalid { get; private set; }
    public string Progress { get; private set; } = "";
    public double Percent { get; private set; }
    public bool Indeterminate { get; private set; }
    public string Size { get; private set; } = "";
    public string Ended { get; private set; } = "";
    public BitmapImage? Image { get; private set; }
    private string thumbnail = "";
    public string StateLabel => Invalid ? "文件无效" : State switch {
        "queued" => "等待中", "parsing" => "正在解析", "ready" => "待确认", "downloading" => "下载中",
        "finalizing" => "正在保存", "completed" => "已完成", "failed" => "失败", "interrupted" => "已中断",
        "cancelled" => "已取消", "cancelling" => "正在取消", _ => "等待中"
    };
    public string Subtitle => Invalid ? $"{PlatformName} · 文件无效，请重新下载" : $"{PlatformName} · {Media.FirstOrDefault() ?? "正在获取作品信息"}";
    public string StatusLine => string.Join(" · ", new[] { StateLabel, Size, Ended }.Where(v => !string.IsNullOrWhiteSpace(v)));
    public string PrimaryLabel => State switch { "completed" => "打开文件", "ready" => "开始下载", "failed" or "interrupted" or "cancelled" => "重试", _ => "取消" };
    public bool CanStart => State is "ready" or "failed" or "interrupted" or "cancelled";
    public bool CanCancel => State is "queued" or "parsing" or "ready" or "downloading";
    public bool PrimaryEnabled => State == "completed" || CanStart || CanCancel;
    public Visibility ProgressVisibility => State is "parsing" or "downloading" or "finalizing" ? Visibility.Visible : Visibility.Collapsed;
    public Visibility ImageVisibility => Image is null ? Visibility.Collapsed : Visibility.Visible;
    public Visibility PlaceholderVisibility => Image is null ? Visibility.Visible : Visibility.Collapsed;
    public event PropertyChangedEventHandler? PropertyChanged;

    public void Update(JsonElement task)
    {
        Id = task.String("id"); Title = task.String("title"); State = task.String("state");
        PlatformName = task.String("platform_name"); Path = task.String("path"); Error = task.String("error");
        Invalid = task.Bool("invalid"); Progress = task.String("progress");
        Media = task.GetProperty("media").EnumerateArray().Select(m => m.GetString() ?? "").ToArray();
        Indeterminate = !task.TryGetProperty("percent", out var percent) || percent.ValueKind != JsonValueKind.Number || !percent.TryGetDouble(out var number);
        Percent = Indeterminate ? 0 : percent.GetDouble();
        Size = task.TryGetProperty("size", out var size) && size.ValueKind == JsonValueKind.Number && size.TryGetInt64(out var bytes) && bytes > 0 ? FormatSize(bytes) : "";
        Ended = DateTimeOffset.TryParse(task.String("ended_at"), out var date) ? date.ToLocalTime().ToString("MM-dd HH:mm") : "";
        if (task.TryGetProperty("thumbnail", out var image) && image.ValueKind == JsonValueKind.String) {
            var encoded = image.GetString() ?? "";
            if (encoded != thumbnail) { thumbnail = encoded; _ = LoadImageAsync(encoded); }
        }
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(""));
    }

    private async Task LoadImageAsync(string encoded)
    {
        try {
            if (encoded.Length == 0 || encoded.Length > 160000) { Image = null; return; }
            var bytes = Convert.FromBase64String(encoded);
            using var stream = new InMemoryRandomAccessStream();
            using (var writer = new DataWriter(stream.GetOutputStreamAt(0))) { writer.WriteBytes(bytes); await writer.StoreAsync(); }
            stream.Seek(0);
            var bitmap = new BitmapImage(); await bitmap.SetSourceAsync(stream);
            if (thumbnail == encoded) Image = bitmap;
        } catch { Image = null; }
        finally { PropertyChanged?.Invoke(this, new PropertyChangedEventArgs("")); }
    }

    public static string FormatSize(long bytes)
    {
        string[] units = ["B", "KB", "MB", "GB", "TB"];
        double value = bytes; var index = 0;
        while (value >= 1024 && index < units.Length - 1) { value /= 1024; index++; }
        return $"{value:0.#} {units[index]}";
    }
}
