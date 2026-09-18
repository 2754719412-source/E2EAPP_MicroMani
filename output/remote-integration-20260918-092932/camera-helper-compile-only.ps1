
$code = @'
using System;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
using System.Text;

public static class AppstationDirectShowCameraEnum
{
    [ComImport, Guid("29840822-5B84-11D0-BD3B-00A0C911CE86"),
     InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface ICreateDevEnum
    {
        int CreateClassEnumerator(
            [In] ref Guid pType,
            out IEnumMoniker ppEnumMoniker,
            int dwFlags);
    }

    [ComImport, Guid("55272A00-42CB-11CE-8135-00AA004BB851"),
     InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IPropertyBag
    {
        [PreserveSig]
        int Read(
            [MarshalAs(UnmanagedType.LPWStr)] string pszPropName,
            ref object pVar,
            IntPtr pErrorLog);

        [PreserveSig]
        int Write(
            [MarshalAs(UnmanagedType.LPWStr)] string pszPropName,
            ref object pVar);
    }

    public static string List()
    {
        var sb = new StringBuilder();
        Guid systemDeviceEnum = new Guid("62BE5D10-60EB-11D0-BD3B-00A0C911CE86");
        Guid videoInputDevice = new Guid("860BB310-5D01-11D0-BD3B-00A0C911CE86");
        Type type = Type.GetTypeFromCLSID(systemDeviceEnum);
        var devEnum = (ICreateDevEnum)Activator.CreateInstance(type);
        IEnumMoniker enumMoniker;
        int hr = devEnum.CreateClassEnumerator(ref videoInputDevice, out enumMoniker, 0);
        if (hr != 0 || enumMoniker == null) return "NO_DEVICES hr=" + hr;

        IMoniker[] monikers = new IMoniker[1];
        IntPtr fetched = Marshal.AllocCoTaskMem(4);
        int index = 0;
        try
        {
            while (enumMoniker.Next(1, monikers, fetched) == 0)
            {
                string friendly = ReadBag(monikers[0], "FriendlyName");
                string devicePath = ReadBag(monikers[0], "DevicePath");
                string displayName = "";
                try
                {
                    IBindCtx ctx;
                    CreateBindCtx(0, out ctx);
                    monikers[0].GetDisplayName(ctx, null, out displayName);
                }
                catch { }

                sb.AppendLine("INDEX=" + index);
                sb.AppendLine("FriendlyName=" + friendly);
                sb.AppendLine("DevicePath=" + devicePath);
                sb.AppendLine("DisplayName=" + displayName);
                sb.AppendLine();
                Marshal.ReleaseComObject(monikers[0]);
                index++;
            }
        }
        finally
        {
            Marshal.FreeCoTaskMem(fetched);
            Marshal.ReleaseComObject(enumMoniker);
            Marshal.ReleaseComObject(devEnum);
        }
        return sb.ToString();
    }

    [ComImport, Guid("28F54685-06FD-11D2-B27A-00A0C9223196"),
     InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IKsControl
    {
        [PreserveSig]
        int KsProperty(IntPtr property, int propertySize, IntPtr data, int dataSize, out int returned);
        [PreserveSig]
        int KsMethod(IntPtr property, int propertySize, IntPtr data, int dataSize, out int returned);
        [PreserveSig]
        int KsEvent(IntPtr property, int propertySize, IntPtr data, int dataSize, out int returned);
    }

    public static string SetFixedFrameRate(string devicePath)
    {
        var type = Type.GetTypeFromCLSID(new Guid("62BE5D10-60EB-11D0-BD3B-00A0C911CE86"));
        var devEnum = (ICreateDevEnum)Activator.CreateInstance(type);
        IEnumMoniker enumerator = null;
        try
        {
            Guid category = new Guid("860BB310-5D01-11D0-BD3B-00A0C911CE86");
            if (devEnum.CreateClassEnumerator(ref category, out enumerator, 0) != 0)
                throw new InvalidOperationException("Camera enumeration failed");
            var monikers = new IMoniker[1];
            while (enumerator.Next(1, monikers, IntPtr.Zero) == 0)
            {
                try
                {
                    if (!String.Equals(ReadBag(monikers[0], "DevicePath"), devicePath,
                                       StringComparison.OrdinalIgnoreCase)) continue;
                    object filter;
                    Guid iid = new Guid("56A86895-0AD4-11CE-B03A-0020AF0BA770");
                    monikers[0].BindToObject(null, null, ref iid, out filter);
                    try
                    {
                        var control = (IKsControl)filter;
                        EnableAutoExposure(control);
                        return DisableLowLightCompensation(control);
                    }
                    finally { Marshal.ReleaseComObject(filter); }
                }
                finally { Marshal.ReleaseComObject(monikers[0]); }
            }
            throw new InvalidOperationException("Camera device path not found");
        }
        finally
        {
            if (enumerator != null) Marshal.ReleaseComObject(enumerator);
            Marshal.ReleaseComObject(devEnum);
        }
    }

    static void EnableAutoExposure(IKsControl control)
    {
        // 自动曝光优先级属性仅在曝光已为 Auto 时有效。
        IntPtr data = Marshal.AllocCoTaskMem(40);
        try
        {
            for (int i = 0; i < 40; i += 4) Marshal.WriteInt32(data, i, 0);
            ControlHeader(data, 4, 1); // KSPROPERTY_CAMERACONTROL_EXPOSURE, GET
            int returned;
            Marshal.ThrowExceptionForHR(control.KsProperty(data, 40, data, 40, out returned));
            if ((Marshal.ReadInt32(data, 28) & 1) == 0)
            {
                ControlHeader(data, 4, 2);
                Marshal.WriteInt32(data, 28, 1); // KSPROPERTY_CAMERACONTROL_FLAGS_AUTO
                Marshal.ThrowExceptionForHR(control.KsProperty(data, 40, data, 40, out returned));
            }
        }
        finally { Marshal.FreeCoTaskMem(data); }
    }

    static string DisableLowLightCompensation(IKsControl control)
    {
        // KSPROPERTY_CAMERACONTROL_S is 40 bytes with 8-byte alignment on Windows.
        IntPtr data = Marshal.AllocCoTaskMem(40);
        try
        {
            for (int i = 0; i < 40; i += 4) Marshal.WriteInt32(data, i, 0);
            ControlHeader(data, 19, 1);
            int returned;
            Marshal.ThrowExceptionForHR(control.KsProperty(data, 40, data, 40, out returned));
            int before = Marshal.ReadInt32(data, 24);
            if (before != 0)
            {
                ControlHeader(data, 19, 2);
                Marshal.WriteInt32(data, 24, 0);
                Marshal.WriteInt32(data, 28, 2); // KSPROPERTY_CAMERACONTROL_FLAGS_MANUAL
                Marshal.ThrowExceptionForHR(control.KsProperty(data, 40, data, 40, out returned));
            }
            // Get may overwrite the property header, so rebuild it for each call.
            ControlHeader(data, 19, 1);
            Marshal.ThrowExceptionForHR(control.KsProperty(data, 40, data, 40, out returned));
            if (Marshal.ReadInt32(data, 24) != 0)
                throw new InvalidOperationException("Low-light compensation remained enabled");
            return "fixed_frame_rate=1 previous_priority=" + before;
        }
        finally { Marshal.FreeCoTaskMem(data); }
    }

    static void ControlHeader(IntPtr data, int property, int operation)
    {
        Marshal.StructureToPtr(new Guid("C6E13370-30AC-11D0-A18C-00A0C9118956"), data, false);
        Marshal.WriteInt32(data, 16, property);
        Marshal.WriteInt32(data, 20, operation);
    }

    static string ReadBag(IMoniker moniker, string name)
    {
        object bagObj;
        Guid bagId = typeof(IPropertyBag).GUID;
        try
        {
            moniker.BindToStorage(null, null, ref bagId, out bagObj);
            var bag = (IPropertyBag)bagObj;
            object value = null;
            int hr = bag.Read(name, ref value, IntPtr.Zero);
            Marshal.ReleaseComObject(bag);
            if (hr == 0 && value != null) return value.ToString();
        }
        catch { }
        return "";
    }

    [DllImport("ole32.dll")]
    static extern int CreateBindCtx(int reserved, out IBindCtx ppbc);
}
'@
Add-Type -TypeDefinition $code -Language CSharp
