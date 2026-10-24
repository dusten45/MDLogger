// 설치 대상의 Python/Qt DLL을 사용하지 않는 Windows 업데이트 도우미.
using System;
using System.Collections;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Win32;

internal static class UpdateHelper
{
    private const string AppId = "F0987F41-0A8B-4B2E-9C61-9CDD4F8E7C00";
    private const string AppMutex = @"Global\MDLogger.Application." + AppId;
    private const string UpdateMutex = @"Global\MDLogger.Update." + AppId;
    private const long MaximumInstallerSize = 1024L * 1024 * 1024;
    private static readonly UTF8Encoding Utf8 = new UTF8Encoding(false, true);
    private static readonly Regex StableVersion = new Regex(@"\A(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})\z");
    private static string directory;
    private static string token;
    private static string targetVersion;
    private static bool parentExited;

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool SetDllDirectory(string path);

    private sealed class Payload : IDisposable
    {
        internal string Version;
        internal string Installer;
        internal FileStream LockedInstaller;
        internal DateTime Expires;
        public void Dispose() { if (LockedInstaller != null) LockedInstaller.Dispose(); }
    }

    private static Dictionary<string, object> Parse(byte[] data, int maximum)
    {
        if (data.Length == 0 || data.Length > maximum)
            throw new InvalidDataException("업데이트 정보의 크기가 올바르지 않습니다.");
        JavaScriptSerializer parser = new JavaScriptSerializer();
        parser.MaxJsonLength = maximum;
        parser.RecursionLimit = 32;
        Dictionary<string, object> result = parser.DeserializeObject(Utf8.GetString(data)) as Dictionary<string, object>;
        if (result == null) throw new InvalidDataException("업데이트 정보 형식이 올바르지 않습니다.");
        return result;
    }

    private static byte[] ReadBounded(string path, int maximum)
    {
        RejectReparse(path);
        using (FileStream file = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read))
        {
            if (file.Length > maximum) throw new InvalidDataException("업데이트 정보가 너무 큽니다.");
            byte[] data = new byte[(int)file.Length];
            int offset = 0;
            while (offset < data.Length)
            {
                int count = file.Read(data, offset, data.Length - offset);
                if (count == 0) throw new EndOfStreamException("업데이트 정보를 끝까지 읽지 못했습니다.");
                offset += count;
            }
            return data;
        }
    }

    private static object Field(Dictionary<string, object> data, string name)
    {
        object value;
        if (!data.TryGetValue(name, out value)) throw new InvalidDataException("업데이트 정보에 필수 필드가 없습니다.");
        return value;
    }

    private static string Text(Dictionary<string, object> data, string name)
    {
        string value = Field(data, name) as string;
        if (value == null || value.Length > 32768) throw new InvalidDataException("업데이트 문자열이 올바르지 않습니다.");
        return value;
    }

    private static long Integer(Dictionary<string, object> data, string name)
    {
        object value = Field(data, name);
        if (value is int) return (int)value;
        if (value is long) return (long)value;
        throw new InvalidDataException("업데이트 숫자 형식이 올바르지 않습니다.");
    }

    private static void Schema(Dictionary<string, object> data)
    {
        if (Integer(data, "schema") != 1) throw new InvalidDataException("지원하지 않는 업데이트 형식입니다.");
    }

    private static int CompareVersions(string left, string right)
    {
        if (!StableVersion.IsMatch(left) || !StableVersion.IsMatch(right))
            throw new InvalidDataException("업데이트 버전 형식이 올바르지 않습니다.");
        string[] a = left.Split('.');
        string[] b = right.Split('.');
        for (int index = 0; index < 3; index++)
        {
            int comparison = Int32.Parse(a[index], CultureInfo.InvariantCulture).CompareTo(Int32.Parse(b[index], CultureInfo.InvariantCulture));
            if (comparison != 0) return comparison;
        }
        return 0;
    }

    private static byte[] Base64(Dictionary<string, object> data, string name)
    {
        string value = Text(data, name);
        if (value.Length > 8192 || !Regex.IsMatch(value, @"\A[A-Za-z0-9+/]*={0,2}\z"))
            throw new InvalidDataException("업데이트 서명 형식이 올바르지 않습니다.");
        return Convert.FromBase64String(value);
    }

    private static void VerifySignature(byte[] manifest, Dictionary<string, object> envelope)
    {
        Schema(envelope);
        string keyId = Text(envelope, "key_id");
        if (!Regex.IsMatch(keyId, @"\A[A-Za-z0-9_-]{1,64}\z"))
            throw new InvalidDataException("업데이트 키 이름이 올바르지 않습니다.");
        byte[] rawKeys;
        using (Stream resource = Assembly.GetExecutingAssembly().GetManifestResourceStream("MDLogger.UpdateTrustedKeys.json"))
        {
            if (resource == null || resource.Length > 65536) throw new InvalidDataException("신뢰할 업데이트 공개 키가 없습니다.");
            using (MemoryStream buffer = new MemoryStream()) { resource.CopyTo(buffer); rawKeys = buffer.ToArray(); }
        }
        Dictionary<string, object> config = Parse(rawKeys, 65536);
        Schema(config);
        object[] keys = Field(config, "keys") as object[];
        if (keys == null) throw new InvalidDataException("업데이트 공개 키 형식이 올바르지 않습니다.");
        Dictionary<string, object> selected = null;
        foreach (object entry in keys)
        {
            Dictionary<string, object> key = entry as Dictionary<string, object>;
            if (key == null || Text(key, "key_id") != keyId) continue;
            if (selected != null) throw new InvalidDataException("업데이트 공개 키가 중복되었습니다.");
            selected = key;
        }
        if (selected == null) throw new InvalidDataException("신뢰할 수 없는 업데이트 서명 키입니다.");
        byte[] modulus = Base64(selected, "modulus");
        byte[] exponent = Base64(selected, "exponent");
        if (modulus.Length < 384 || modulus.Length > 512 || modulus[0] < 128 ||
            exponent.Length != 3 || exponent[0] != 1 || exponent[1] != 0 || exponent[2] != 1)
            throw new InvalidDataException("업데이트 공개 키가 보안 조건을 충족하지 않습니다.");
        using (RSACryptoServiceProvider rsa = new RSACryptoServiceProvider())
        {
            rsa.PersistKeyInCsp = false;
            rsa.ImportParameters(new RSAParameters { Modulus = modulus, Exponent = exponent });
            using (SHA256 hash = SHA256.Create())
            {
                if (!rsa.VerifyData(manifest, hash, Base64(envelope, "signature")))
                    throw new InvalidDataException("업데이트 서명이 유효하지 않습니다. 설치하지 않았습니다.");
            }
        }
    }

    private static Payload VerifyPayload(string root)
    {
        byte[] manifest = ReadBounded(Path.Combine(root, "update.json"), 65536);
        Dictionary<string, object> envelope = Parse(ReadBounded(Path.Combine(root, "update.json.sig"), 8192), 8192);
        VerifySignature(manifest, envelope);
        Dictionary<string, object> data = Parse(manifest, 65536);
        Schema(data);
        string version = Text(data, "version");
        CompareVersions(version, version);
        if (Text(data, "platform") != "windows-x64" || Text(data, "key_id") != Text(envelope, "key_id"))
            throw new InvalidDataException("현재 앱에 적용할 수 없는 업데이트입니다.");
        DateTime issued = DateTime.ParseExact(Text(data, "issued_at"), "yyyy-MM-dd'T'HH:mm:ss'Z'", CultureInfo.InvariantCulture, DateTimeStyles.AssumeUniversal | DateTimeStyles.AdjustToUniversal);
        DateTime expires = DateTime.ParseExact(Text(data, "expires_at"), "yyyy-MM-dd'T'HH:mm:ss'Z'", CultureInfo.InvariantCulture, DateTimeStyles.AssumeUniversal | DateTimeStyles.AdjustToUniversal);
        if (issued > DateTime.UtcNow.AddMinutes(5) || expires <= DateTime.UtcNow || expires <= issued || expires - issued > TimeSpan.FromDays(366))
            throw new InvalidDataException("업데이트 서명이 만료되었거나 아직 유효하지 않습니다.");
        Dictionary<string, object> asset = Field(data, "installer") as Dictionary<string, object>;
        if (asset == null) throw new InvalidDataException("업데이트 설치 파일 정보가 없습니다.");
        string name = "MDLoggerSetup-" + version + ".exe";
        string url = "https://github.com/dusten45/MDLogger/releases/download/v" + version + "/" + name;
        string digest = Text(asset, "sha256");
        long size = Integer(asset, "size");
        if (Text(asset, "name") != name || Text(asset, "url") != url || size <= 0 || size > MaximumInstallerSize || !Regex.IsMatch(digest, @"\A[0-9a-f]{64}\z"))
            throw new InvalidDataException("업데이트 설치 파일 정보가 올바르지 않습니다.");
        string installer = Path.Combine(root, name);
        RejectReparse(installer);
        FileStream locked = new FileStream(installer, FileMode.Open, FileAccess.Read, FileShare.Read);
        try
        {
            string actual;
            using (SHA256 sha = SHA256.Create()) { actual = BitConverter.ToString(sha.ComputeHash(locked)).Replace("-", "").ToLowerInvariant(); }
            if (locked.Length != size || actual != digest) throw new InvalidDataException("설치 파일 해시 검증에 실패했습니다.");
            return new Payload { Version = version, Installer = installer, LockedInstaller = locked, Expires = expires };
        }
        catch { locked.Dispose(); throw; }
    }

    private static void RejectReparse(string path)
    {
        string current = Path.GetFullPath(path);
        while (!String.IsNullOrEmpty(current))
        {
            if ((File.GetAttributes(current) & FileAttributes.ReparsePoint) != 0)
                throw new InvalidDataException("연결된 파일이나 폴더에서는 업데이트를 실행할 수 없습니다.");
            current = Path.GetDirectoryName(current);
        }
    }

    private static bool SamePath(string left, string right)
    {
        return String.Equals(Path.GetFullPath(left).TrimEnd(Path.DirectorySeparatorChar), Path.GetFullPath(right).TrimEnd(Path.DirectorySeparatorChar), StringComparison.OrdinalIgnoreCase);
    }

    private static void WriteJson(string filename, Dictionary<string, object> value)
    {
        string destination = Path.Combine(directory, filename);
        string temporary = destination + ".tmp";
        if (File.Exists(destination)) RejectReparse(destination);
        if (File.Exists(temporary)) RejectReparse(temporary);
        byte[] bytes = Utf8.GetBytes(new JavaScriptSerializer().Serialize(value));
        using (FileStream stream = new FileStream(temporary, FileMode.Create, FileAccess.Write, FileShare.None))
        {
            stream.Write(bytes, 0, bytes.Length);
            stream.Flush(true);
        }
        if (File.Exists(destination)) File.Replace(temporary, destination, null);
        else File.Move(temporary, destination);
    }

    private static void State(string phase, string message, string version)
    {
        WriteJson("state.json", new Dictionary<string, object> {
            { "schema", 1 }, { "token", token }, { "phase", phase },
            { "message", message }, { "version", version },
            { "updated_at", DateTime.UtcNow.ToString("yyyy-MM-dd'T'HH:mm:ss'Z'", CultureInfo.InvariantCulture) }
        });
    }

    private static bool Cancelled()
    {
        string path = Path.Combine(directory, "cancel.json");
        return File.Exists(path) && Text(Parse(ReadBounded(path, 8192), 8192), "token") == token;
    }

    private static string InstalledVersion(string executable)
    {
        using (RegistryKey machine = RegistryKey.OpenBaseKey(RegistryHive.LocalMachine, RegistryView.Registry64))
        using (RegistryKey installed = machine.OpenSubKey(@"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{" + AppId + "}_is1"))
        {
            if (installed == null) throw new InvalidDataException("관리자 범위의 MDLogger 설치를 찾을 수 없습니다.");
            string location = installed.GetValue("InstallLocation") as string;
            string version = installed.GetValue("DisplayVersion") as string;
            if (String.IsNullOrEmpty(location) || !SamePath(location, Path.GetDirectoryName(executable)) || String.IsNullOrEmpty(version))
                throw new InvalidDataException("설치 경로나 버전을 확인할 수 없습니다.");
            CompareVersions(version, version);
            return version;
        }
    }

    private static bool AppStillRunning()
    {
        try { using (Mutex existing = Mutex.OpenExisting(AppMutex)) { return true; } }
        catch (WaitHandleCannotBeOpenedException) { return false; }
    }

    private static bool StartApplication(string executable, string dataDirectory, string version, bool recovery)
    {
        State(recovery ? "recovering" : "starting", recovery ? "설치 전 취소되어 기존 앱을 다시 실행합니다." : "새 앱의 시작을 확인하고 있습니다.", version);
        ProcessStartInfo info = new ProcessStartInfo(executable);
        info.UseShellExecute = false;
        info.WorkingDirectory = Path.GetDirectoryName(executable);
        info.EnvironmentVariables["MDLOGGER_UPDATE_JOB"] = directory;
        info.EnvironmentVariables["MDLOGGER_UPDATE_TOKEN"] = token;
        info.EnvironmentVariables["PYINSTALLER_RESET_ENVIRONMENT"] = "1";
        if (dataDirectory == null) info.EnvironmentVariables.Remove("MDLOGGER_DATA_DIR");
        else info.EnvironmentVariables["MDLOGGER_DATA_DIR"] = dataDirectory;
        using (Process child = Process.Start(info))
        {
            if (child == null) throw new InvalidOperationException("MDLogger를 다시 실행하지 못했습니다.");
            Stopwatch wait = Stopwatch.StartNew();
            while (wait.Elapsed < TimeSpan.FromSeconds(60))
            {
                string receiptPath = Path.Combine(directory, "started.json");
                if (File.Exists(receiptPath))
                {
                    Dictionary<string, object> receipt = Parse(ReadBounded(receiptPath, 8192), 8192);
                    if (Text(receipt, "token") == token && Text(receipt, "version") == version && Integer(receipt, "pid") == child.Id)
                    {
                        State(recovery ? "cancelled" : "complete", recovery ? "설치를 취소하고 기존 앱을 다시 실행했습니다." : "업데이트와 앱 재시작을 완료했습니다.", version);
                        return true;
                    }
                }
                if (child.WaitForExit(200)) break;
            }
        }
        State("startup_failed", "앱의 정상 시작을 확인하지 못했습니다. 실행 중인 앱을 강제 종료하지 않았습니다.", version);
        MessageBox.Show("앱의 정상 시작을 확인하지 못했습니다. 실행 중인 앱을 강제 종료하지 않았습니다.\n업데이트 기록: " + directory, "MDLogger 업데이트", MessageBoxButtons.OK, MessageBoxIcon.Warning);
        return false;
    }

    private static int RunJob(string jobPath)
    {
        string fullJob = Path.GetFullPath(jobPath);
        if (Path.GetFileName(fullJob) != "job.json") throw new InvalidDataException("업데이트 작업 파일이 올바르지 않습니다.");
        string root = Path.GetDirectoryName(fullJob);
        string expected = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "MDLogger", "updates");
        if (!Regex.IsMatch(Path.GetFileName(root), @"\A[0-9a-f]{32}\z") || !SamePath(Path.GetDirectoryName(root), expected) ||
            !SamePath(Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location), root))
            throw new InvalidDataException("허용되지 않은 업데이트 작업 폴더입니다.");
        RejectReparse(root);
        Dictionary<string, object> job = Parse(ReadBounded(fullJob, 65536), 65536);
        Schema(job);
        string jobToken = Text(job, "token");
        if (!Regex.IsMatch(jobToken, @"\A[0-9a-f]{64}\z")) throw new InvalidDataException("업데이트 작업 토큰이 올바르지 않습니다.");
        directory = root;
        token = jobToken;
        targetVersion = Text(job, "version");
        if (!Environment.Is64BitOperatingSystem || new WindowsPrincipal(WindowsIdentity.GetCurrent()).IsInRole(WindowsBuiltInRole.Administrator))
            throw new InvalidOperationException("업데이트는 64비트 Windows의 일반 사용자 권한으로 시작해야 합니다.");
        string executable = Text(job, "executable");
        if (!Path.IsPathRooted(executable) || Path.GetFileName(executable) != "MDLogger.exe")
            throw new InvalidDataException("설치된 MDLogger 실행 파일이 아닙니다.");
        RejectReparse(executable);
        string dataDirectory = Field(job, "data_dir") as string;
        if (Field(job, "data_dir") != null && (String.IsNullOrEmpty(dataDirectory) || !Path.IsPathRooted(dataDirectory)))
            throw new InvalidDataException("사용자 데이터 경로가 올바르지 않습니다.");
        string oldVersion = InstalledVersion(executable);
        bool created;
        using (Mutex update = new Mutex(false, UpdateMutex, out created))
        {
            if (!created) throw new InvalidOperationException("다른 업데이트 작업이 실행 중입니다.");
            using (Payload payload = VerifyPayload(root))
            using (Process parent = Process.GetProcessById(checked((int)Integer(job, "parent_pid"))))
            {
                if (payload.Version != targetVersion || CompareVersions(payload.Version, oldVersion) <= 0)
                    throw new InvalidDataException("설치된 버전보다 새로운 업데이트가 아닙니다.");
                if (parent.HasExited || !SamePath(parent.MainModule.FileName, executable))
                    throw new InvalidDataException("업데이트를 요청한 앱 프로세스를 확인하지 못했습니다.");
                State("ready", "앱의 정상 종료를 기다리고 있습니다.", payload.Version);
                Stopwatch wait = Stopwatch.StartNew();
                while (!parent.WaitForExit(100))
                {
                    if (Cancelled()) { State("cancelled", "업데이트를 취소하고 현재 앱을 유지했습니다.", oldVersion); return 2; }
                    if (wait.Elapsed > TimeSpan.FromSeconds(120))
                        throw new TimeoutException("앱이 종료되지 않아 설치하지 않았습니다. 앱을 강제 종료하지 않았습니다.");
                }
                parentExited = true;
                if (Cancelled()) { State("cancelled", "업데이트를 취소했습니다.", oldVersion); return 2; }
                string authorizationPath = Path.Combine(root, "install-authorized.json");
                if (!File.Exists(authorizationPath))
                {
                    State("cancelled", "앱이 설치 인계를 확인하지 않아 설치하지 않았습니다.", oldVersion);
                    return 2;
                }
                Dictionary<string, object> authorization = Parse(ReadBounded(authorizationPath, 8192), 8192);
                if (Text(authorization, "token") != token || Text(authorization, "version") != payload.Version)
                    throw new InvalidDataException("업데이트 설치 인계 정보가 일치하지 않습니다.");
                if (AppStillRunning()) throw new InvalidOperationException("다른 MDLogger가 실행 중이어서 설치하지 않았습니다.");
                if (payload.Expires <= DateTime.UtcNow) throw new InvalidDataException("대기 중 업데이트 서명이 만료되어 설치하지 않았습니다.");
                // 검증부터 설치 종료까지 읽기 잠금을 유지하여 파일 교체를 막는다.
                State("installing", "설치 중입니다. Windows 관리자 승인이 필요할 수 있습니다.", payload.Version);
                ProcessStartInfo installer = new ProcessStartInfo(payload.Installer);
                installer.UseShellExecute = true;
                installer.Verb = "runas";
                installer.WorkingDirectory = root;
                installer.Arguments = "/SP- /SILENT /SUPPRESSMSGBOXES /NORESTART /RESTARTEXITCODE=3010 /NOCLOSEAPPLICATIONS /NORESTARTAPPLICATIONS /NOFORCECLOSEAPPLICATIONS /DIR=\"" + Path.GetDirectoryName(executable) + "\" /LOG=\"" + Path.Combine(root, "install.log") + "\"";
                int exitCode;
                try
                {
                    using (Process installation = Process.Start(installer))
                    {
                        if (installation == null) throw new InvalidOperationException("설치 프로그램을 시작하지 못했습니다.");
                        installation.WaitForExit();
                        exitCode = installation.ExitCode;
                    }
                }
                catch (Win32Exception error)
                {
                    if (error.NativeErrorCode != 1223) throw;
                    return StartApplication(executable, dataDirectory, oldVersion, true) ? 2 : 4;
                }
                if (exitCode == 3010)
                {
                    State("reboot_required", "설치는 끝났지만 Windows 재시작이 필요합니다. 자동으로 재시작하지 않았습니다.", payload.Version);
                    MessageBox.Show("설치는 끝났지만 Windows 재시작이 필요합니다. 컴퓨터를 자동으로 재시작하지 않았습니다.\n작업을 저장한 뒤 직접 다시 시작해 주세요.", "MDLogger 업데이트", MessageBoxButtons.OK, MessageBoxIcon.Information);
                    return 3010;
                }
                if (exitCode != 0) throw new InvalidOperationException("설치가 완료되지 않았습니다. 종료 코드: " + exitCode.ToString(CultureInfo.InvariantCulture) + "\n다운로드한 설치 파일과 install.log를 보존했습니다. 이전 상태로 완전히 복구되었다고 보장할 수 없습니다.");
                if (InstalledVersion(executable) != payload.Version)
                    throw new InvalidDataException("설치된 버전이 업데이트 버전과 일치하지 않습니다.");
                return StartApplication(executable, dataDirectory, payload.Version, false) ? 0 : 4;
            }
        }
    }

    [STAThread]
    private static int Main(string[] args)
    {
        bool verifyOnly = args.Length == 2 && args[0] == "--verify-payload";
        try
        {
            if (!SetDllDirectory(null)) throw new InvalidOperationException("업데이트 실행 환경을 준비하지 못했습니다.");
            if (verifyOnly) { using (Payload payload = VerifyPayload(Path.GetFullPath(args[1]))) { return 0; } }
            if (args.Length != 2 || args[0] != "--job") return 2;
            return RunJob(args[1]);
        }
        catch (Exception error)
        {
            if (verifyOnly) return 2;
            string message = "업데이트를 완료하지 못했습니다.\n" + error.Message;
            if (directory != null && token != null)
            {
                try { State("failed", message, targetVersion); } catch (Exception) { }
            }
            if (parentExited) MessageBox.Show(message, "MDLogger 업데이트", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return 4;
        }
    }
}
