using System.Diagnostics;
using System.Text;
using System.Text.Json;
using System.Collections.Concurrent;

namespace MediaDownloader;

public sealed class BackendBridge : IAsyncDisposable
{
    private readonly Process process;
    private readonly SemaphoreSlim writer = new(1, 1);
    private readonly ConcurrentDictionary<long, TaskCompletionSource<JsonElement>> pending = new();
    private long nextId;
    private bool closing;
    public event Action<JsonElement>? Snapshot;
    public event Action<string>? Failed;

    public BackendBridge(string? dataDirectory = null)
    {
        var basePath = AppContext.BaseDirectory;
        var executable = Path.Combine(basePath, "backend", "MediaBackend.exe");
        var start = new ProcessStartInfo(executable) {
            UseShellExecute = false, CreateNoWindow = true,
            RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true,
            StandardInputEncoding = new UTF8Encoding(false), StandardOutputEncoding = Encoding.UTF8,
            StandardErrorEncoding = Encoding.UTF8, WorkingDirectory = basePath
        };
        start.ArgumentList.Add("--engine-dir");
        start.ArgumentList.Add(Path.Combine(basePath, "engine"));
        if (!string.IsNullOrWhiteSpace(dataDirectory)) start.Environment["MEDIA_DOWNLOADER_DATA_DIR"] = dataDirectory;
        process = new Process { StartInfo = start, EnableRaisingEvents = true };
        process.Start();
        _ = ReadAsync();
        _ = DrainErrorsAsync();
    }

    private async Task ReadAsync()
    {
        try {
            while (await process.StandardOutput.ReadLineAsync() is { } line) {
                if (line.Length > 12 * 1024 * 1024) throw new InvalidDataException();
                using var document = JsonDocument.Parse(line);
                var message = document.RootElement;
                switch (message.String("event")) {
                    case "snapshot": Snapshot?.Invoke(message.GetProperty("data").Clone()); break;
                    case "response":
                        if (message.TryGetProperty("id", out var id) && id.TryGetInt64(out var key) && pending.TryRemove(key, out var reply)) {
                            if (message.TryGetProperty("error", out var error)) reply.TrySetException(new InvalidOperationException(error.String("message")));
                            else reply.TrySetResult(message.GetProperty("result").Clone());
                        }
                        break;
                    case "fatal": Failed?.Invoke(message.String("message")); break;
                }
            }
            if (!closing) Failed?.Invoke("任务服务已停止，请重新打开应用。");
        } catch { if (!closing) Failed?.Invoke("无法连接任务服务，请检查应用文件是否完整。"); }
        finally {
            foreach (var reply in pending.Values) reply.TrySetException(new IOException("任务服务不可用。"));
            pending.Clear();
        }
    }

    private async Task DrainErrorsAsync()
    {
        try { var buffer = new char[4096]; while (await process.StandardError.ReadAsync(buffer) > 0) { } }
        catch { /* No raw third-party logs or credentials are surfaced by the UI. */ }
    }

    public async Task<JsonElement> CallAsync(string method, object? args = null)
    {
        var id = Interlocked.Increment(ref nextId);
        var reply = new TaskCompletionSource<JsonElement>(TaskCreationOptions.RunContinuationsAsynchronously);
        pending[id] = reply;
        try {
            await writer.WaitAsync();
            try { await process.StandardInput.WriteLineAsync(JsonSerializer.Serialize(new { bridge = 1, id, method, @params = args ?? new { } })); await process.StandardInput.FlushAsync(); }
            finally { writer.Release(); }
            return await reply.Task.WaitAsync(TimeSpan.FromSeconds(30));
        } finally { pending.TryRemove(id, out _); }
    }

    public async ValueTask DisposeAsync()
    {
        if (closing) return;
        closing = true;
        try { await CallAsync("shutdown"); } catch { }
        try { process.StandardInput.Close(); await process.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(8)); }
        catch { try { process.Kill(entireProcessTree: true); } catch { } }
        process.Dispose();
    }
}

public static class JsonFields
{
    public static string String(this JsonElement value, string key, string fallback = "") =>
        value.ValueKind == JsonValueKind.Object && value.TryGetProperty(key, out var field) && field.ValueKind == JsonValueKind.String ? field.GetString() ?? fallback : fallback;
    public static bool Bool(this JsonElement value, string key) => value.TryGetProperty(key, out var field) && field.ValueKind == JsonValueKind.True;
    public static int Number(this JsonElement value, string key) => value.TryGetProperty(key, out var field) && field.TryGetInt32(out var number) ? number : 0;
}
