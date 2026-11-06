using System.IO;
using ImageStudio;

string testRoot = Path.Combine(Path.GetTempPath(), "ImageStudio-RecycleChecks-" + Guid.NewGuid().ToString("N"));
string output = Path.Combine(testRoot, "output");
Directory.CreateDirectory(output);
Directory.CreateDirectory(Path.Combine(testRoot, "output-other"));
string image = Path.Combine(output, "generated.png");
string metadata = image + ".json";
string video = Path.Combine(output, "generated.mp4");
string outside = Path.Combine(testRoot, "outside.png");
string prefixSibling = Path.Combine(testRoot, "output-other", "outside.png");
string textFile = Path.Combine(output, "keep.txt");
int checks = 0;
void Check(bool condition, string message)
{
    if (!condition) throw new Exception(message);
    checks++;
}
void Reject(string path)
{
    try { ImageLibrary.Recycle(output, path); }
    catch (IOException) { checks++; return; }
    throw new Exception("Unsafe path was not rejected: " + path);
}

try
{
    foreach (var path in new[] { image, outside, prefixSibling, textFile }) File.WriteAllText(path, "Disposable Image Studio recycle test fixture");
    File.WriteAllText(metadata, "{\"testFixture\":true}");
    Check(ImageLibrary.CanRecycle(output, image), "A generated PNG should be deletable.");
    Check(!ImageLibrary.CanRecycle(output, outside), "An external image must be protected.");
    Check(!ImageLibrary.CanRecycle(output, prefixSibling), "A folder sharing the output prefix must be protected.");
    Check(!ImageLibrary.CanRecycle(output, textFile), "Non-PNG files must be protected.");
    Check(!ImageLibrary.CanRecycle(output, null), "An empty preview cannot be deleted.");
    Reject(outside);
    Reject(prefixSibling);
    Reject(textFile);
    Reject(Path.Combine(output, "..", "outside.png"));
    Check(File.Exists(outside) && File.Exists(prefixSibling) && File.Exists(textFile), "Rejected files must remain intact.");
    ImageLibrary.Recycle(output, image);
    Check(!File.Exists(image) && !File.Exists(metadata), "Image and paired metadata must both be recycled.");
    Check(!ImageLibrary.CanRecycle(output, image), "A recycled image must no longer be offered for deletion.");
    File.WriteAllText(video, "Disposable video fixture");
    File.WriteAllText(video + ".json", "{}");
    Check(ImageLibrary.CanRecycle(output, video), "Generated videos should support the same safe deletion as images.");
    ImageLibrary.Recycle(output, video);
    Check(!File.Exists(video) && !File.Exists(video + ".json"), "Video deletion must remove the video and sidecar from their actual folder.");
foreach (var managed in new[] { "films", "production-jobs" })
{
    string protectedPath = System.IO.Path.Combine(output, managed, "protected.png");
    System.IO.Directory.CreateDirectory(System.IO.Path.GetDirectoryName(protectedPath)!);
    System.IO.File.WriteAllText(protectedPath, "Synthetic protected asset");
    Check(!ImageLibrary.CanRecycle(output, protectedPath), "Managed " + managed + " stays protected even with a stale gallery path.");
    try { ImageLibrary.Recycle(output, protectedPath); throw new Exception("Managed asset was accepted for recycling."); }
    catch (System.IO.IOException) { Check(System.IO.File.Exists(protectedPath), "The actual recycle boundary preserves " + managed + " bytes."); }
    System.IO.File.Delete(protectedPath);
    System.IO.Directory.Delete(System.IO.Path.GetDirectoryName(protectedPath)!);
}
Console.WriteLine($"Passed {checks} recycle checks; only newly created test fixtures were recycled.");
}
finally
{
    foreach (var path in new[] { image, metadata, video, video + ".json", outside, prefixSibling, textFile })
        if (File.Exists(path)) File.Delete(path);
    Directory.Delete(Path.Combine(testRoot, "output-other"));
    Directory.Delete(output);
    Directory.Delete(testRoot);
}
