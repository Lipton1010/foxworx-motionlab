using ImageStudio;
using System.Diagnostics;
using System.IO;

// An engine launcher exits after starting a long-lived server. The server must
// not keep the UI waiting for inherited redirected pipe handles to close.
var root = AppContext.BaseDirectory;
File.WriteAllText(Path.Combine(root, "launch.py"), "# isolated startup fixture");
File.WriteAllText(Path.Combine(root, "Start Image Studio.ps1"), """
    $ErrorActionPreference='Stop'
    Start-Process -FilePath $env:ComSpec -ArgumentList '/c ping -n 7 127.0.0.1 >nul' -WindowStyle Hidden -RedirectStandardOutput (Join-Path $PSScriptRoot 'child.out') -RedirectStandardError (Join-Path $PSScriptRoot 'child.err') | Out-Null
    Write-Output 'Fixture server launched; launcher exiting.'
    """);
var engine = new StudioEngine();
var watch = Stopwatch.StartNew();
var ready = engine.EnsureStarted(Console.WriteLine);
if (await Task.WhenAny(ready, Task.Delay(2500)) != ready)
    throw new Exception("FAIL: model initialization remains blocked after the launcher exits.");
await ready;
Console.WriteLine($"PASS: engine launcher returned in {watch.ElapsedMilliseconds} ms; catalog loading can continue.");

File.WriteAllText(Path.Combine(root, "Start Image Studio.ps1"), "exit 17");
try
{
    await engine.EnsureStarted(_ => { });
    throw new Exception("FAIL: a failed launcher must not report ready.");
}
catch (IOException ex) when (ex.Message.Contains("Refresh library"))
{
    Console.WriteLine("PASS: launcher failure provides a recovery action instead of reporting ready.");
}

var portableMarker = Path.Combine(root, "portable.json");
File.WriteAllText(portableMarker, "{}");
try
{
    _ = App.PythonPath;
    throw new Exception("FAIL: a portable app must not silently use this computer's shared Python.");
}
catch (IOException ex) when (ex.Message.Contains("Setup.cmd"))
{
    Console.WriteLine("PASS: an unconfigured portable app gives setup instructions and never uses shared Python.");
}
var bundledPython = Path.Combine(root, "runtime", "ComfyUI_windows_portable", "python_embeded", "python.exe");
Directory.CreateDirectory(Path.GetDirectoryName(bundledPython)!);
try
{
    File.WriteAllText(bundledPython, "Test path only; never executed.");
    if (App.PythonPath != bundledPython) throw new Exception("FAIL: portable Python did not take precedence.");
    Console.WriteLine("PASS: the portable app resolves its own Python after relocation.");
}
finally { File.Delete(bundledPython); File.Delete(portableMarker); }
