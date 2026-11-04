using Microsoft.UI.Xaml;
using Windows.Globalization;
namespace MediaDownloader;
public partial class App : Application
{
 private static readonly Mutex InstallGuard = new(false, @"Local\MediaDownloader.Native.Running");
 private Window? window;
 public App()
 {
  GC.KeepAlive(InstallGuard);
  try { ApplicationLanguages.PrimaryLanguageOverride = "zh-CN"; } catch { }
  InitializeComponent();
  if (Option("--smoke-report") is { } trace) {
   DebugSettings.IsXamlResourceReferenceTracingEnabled = true;
   DebugSettings.XamlResourceReferenceFailed += (_, args) => File.AppendAllText(trace+".resources",args.Message+"\n");
  }
  UnhandledException += (_, e) => {
   var output=Option("--smoke-report");
   if(output is not null) File.WriteAllText(output+".error",e.Exception.GetType().FullName+"\n"+(e.Exception is Microsoft.UI.Xaml.Markup.XamlParseException ? e.Exception.Message : "")+"\n"+e.Exception.StackTrace);
  };
 }
 protected override void OnLaunched(LaunchActivatedEventArgs args) { window=new MainWindow();window.Activate(); }
 public static string? Option(string key) {
  var args=Environment.GetCommandLineArgs();var i=Array.IndexOf(args,key);
  return i>=0 && i+1<args.Length ? args[i+1] : null;
 }
}

