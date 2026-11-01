using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Interop;
using System.Windows.Media.Imaging;

namespace ImageStudio;

internal static class MediaThumbnail
{
    [ComImport, Guid("bcc18b79-ba16-442f-80c4-8a59c30c463b"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IImageFactory { void GetImage(Size size, int flags, out IntPtr bitmap); }
    [StructLayout(LayoutKind.Sequential)] private struct Size { public int Width, Height; }
    [DllImport("shell32.dll", CharSet = CharSet.Unicode, PreserveSig = false)]
    private static extern void SHCreateItemFromParsingName(string path, IntPtr bind, ref Guid iid, [MarshalAs(UnmanagedType.Interface)] out IImageFactory factory);
    [DllImport("gdi32.dll")] private static extern bool DeleteObject(IntPtr handle);

    public static BitmapSource? Load(string path)
    {
        IImageFactory? factory = null; IntPtr bitmap = IntPtr.Zero;
        try
        {
            var id = typeof(IImageFactory).GUID;
            SHCreateItemFromParsingName(path, IntPtr.Zero, ref id, out factory);
            factory.GetImage(new Size { Width = 280, Height = 160 }, 8, out bitmap);
            var image = Imaging.CreateBitmapSourceFromHBitmap(bitmap, IntPtr.Zero, Int32Rect.Empty, BitmapSizeOptions.FromEmptyOptions());
            image.Freeze(); return image;
        }
        catch (COMException) { return null; }
        finally { if (bitmap != IntPtr.Zero) DeleteObject(bitmap); if (factory != null) Marshal.ReleaseComObject(factory); }
    }
}
