// OAS 启动器（编译产物：oas.exe）
//
// 作用与官方 deploy/launcher/oas-gui.bat 类似：双击即可启动 OAS，
// 但额外支持 Web 服务模式（配合 OASX 面板）、环境自检等。
//
// 编译：见同目录 build-oas-exe.ps1（使用 Windows 自带的 csc.exe，无需安装任何工具链）
//
// 用法：
//   oas.exe                  启动 GUI（pythonw gui.py）
//   oas.exe --server         启动 Web 服务（python server.py，前台显示日志）
//   oas.exe --update         先执行 python -m deploy.installer，再启动 GUI
//   oas.exe --console        打开带好 PATH 的命令行窗口（等价 console.bat）
//   oas.exe --check          检查环境后退出（根目录 / Python / 依赖 / 端口）
//   oas.exe --admin          以管理员权限重新启动
//   oas.exe --root <路径>     指定 OAS 根目录
//   oas.exe --python <路径>   指定 python.exe

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Text.RegularExpressions;

internal static class OasLauncher
{
    private const string LauncherVersion = "1.0.0";

    private static int Main(string[] args)
    {
        try { Console.OutputEncoding = Encoding.UTF8; }
        catch { /* 某些终端不支持，忽略 */ }

        Options opts;
        try
        {
            opts = Options.Parse(args);
        }
        catch (Exception e)
        {
            Console.WriteLine("[oas] 参数错误: " + e.Message);
            PrintHelp();
            return Pause(2);
        }

        if (opts.Help)
        {
            PrintHelp();
            return 0;
        }

        // ------------------------------------------------------------------ 定位根目录
        string startDir = opts.Root != null ? opts.Root : AppDomain.CurrentDomain.BaseDirectory;
        string root = FindRoot(startDir);
        if (root == null)
        {
            Console.WriteLine("[oas] 找不到 OAS 根目录（应包含 server.py 与 gui.py）");
            Console.WriteLine("      起始目录: " + startDir);
            return Pause(2);
        }

        // ------------------------------------------------------------------ 定位 python
        Python python = FindPython(root, opts.Python);
        if (python == null)
        {
            Console.WriteLine("[oas] 找不到 python.exe");
            Console.WriteLine("      已尝试: toolkit\\python.exe、PATH 中的 python、py 启动器");
            Console.WriteLine("      提示: 用 --python <路径> 手动指定");
            return Pause(2);
        }

        Console.WriteLine("[oas] 根目录 : " + root);
        Console.WriteLine("[oas] Python : " + python.Display);

        switch (opts.Mode)
        {
            case Mode.Check:
                return CheckEnvironment(root, python);

            case Mode.Console:
                return RunConsole(root);

            case Mode.Update:
                if (RunForeground(root, python, "-m deploy.installer") != 0)
                {
                    Console.WriteLine("[oas] 更新失败，已中止");
                    return Pause(1);
                }
                return StartGui(root, python, opts.Admin, true);

            case Mode.Server:
                return RunServer(root, python);

            default:
                return StartGui(root, python, opts.Admin, false);
        }
    }

    // ====================================================================== 根目录 / python
    private static string FindRoot(string startDir)
    {
        try
        {
            DirectoryInfo dir = new DirectoryInfo(Path.GetFullPath(startDir));
            string fallback = null;
            for (int i = 0; i < 5 && dir != null; i++)
            {
                bool hasServer = File.Exists(Path.Combine(dir.FullName, "server.py"));
                bool hasGui = File.Exists(Path.Combine(dir.FullName, "gui.py"));
                if (hasServer && hasGui)
                {
                    // 优先返回带 toolkit 的那一层（一键包根目录）
                    if (Directory.Exists(Path.Combine(dir.FullName, "toolkit")))
                        return dir.FullName;
                    if (fallback == null)
                        fallback = dir.FullName;
                }
                dir = dir.Parent;
            }
            return fallback;
        }
        catch
        {
            return null;
        }
    }

    private sealed class Python
    {
        public string Exe;
        public string Prefix;   // py 启动器需要 "-3"
        public string Display;

        public string Command(string arguments)
        {
            return Prefix.Length == 0 ? arguments : Prefix + " " + arguments;
        }
    }

    private static Python FindPython(string root, string explicitPath)
    {
        // 1) 命令行指定
        Python p = MakePython(explicitPath);
        if (p != null) return p;

        // 2) 一键包自带的 toolkit
        string toolkitPython = Path.Combine(root, "toolkit", "python.exe");
        p = MakePython(toolkitPython);
        if (p != null) return p;

        // 3) 系统 PATH
        p = MakePython("python.exe");
        if (p != null) return p;

        // 4) Windows 的 py 启动器
        p = MakePyLauncher();
        if (p != null) return p;

        return null;
    }

    private static Python MakePython(string exe)
    {
        if (string.IsNullOrEmpty(exe)) return null;
        string full;
        if (Path.IsPathRooted(exe))
        {
            if (!File.Exists(exe)) return null;
            full = exe;
        }
        else
        {
            full = FindOnPath(exe);
            if (full == null) return null;
        }
        Python p = new Python();
        p.Exe = full;
        p.Prefix = "";
        p.Display = full;
        return p;
    }

    private static Python MakePyLauncher()
    {
        string full = FindOnPath("py.exe");
        if (full == null) return null;
        Python p = new Python();
        p.Exe = full;
        p.Prefix = "-3";
        p.Display = full + " -3";
        return p;
    }

    private static string FindOnPath(string fileName)
    {
        string path = Environment.GetEnvironmentVariable("PATH");
        if (string.IsNullOrEmpty(path)) return null;
        foreach (string raw in path.Split(';'))
        {
            string dir = raw.Trim().Trim('"');
            if (dir.Length == 0) continue;
            try
            {
                string candidate = Path.Combine(dir, fileName);
                if (File.Exists(candidate)) return candidate;
            }
            catch { }
        }
        return null;
    }

    // 与 deploy/launcher/oas-gui.bat 保持一致的 PATH 组装
    private static string BuildPath(string root)
    {
        string toolkit = Path.Combine(root, "toolkit");
        string[] extra = new string[]
        {
            Path.Combine(toolkit, "alias"),
            Path.Combine(toolkit, "command"),
            toolkit,
            Path.Combine(toolkit, "Scripts"),
            Path.Combine(toolkit, "Git", "mingw64", "bin"),
            Path.Combine(toolkit, "Lib", "site-packages", "adbutils", "binaries"),
        };
        string current = Environment.GetEnvironmentVariable("PATH");
        return string.Join(";", extra) + ";" + (current == null ? "" : current);
    }

    // ====================================================================== 进程启动
    private static ProcessStartInfo MakeStartInfo(string root, Python python, string arguments)
    {
        ProcessStartInfo info = new ProcessStartInfo();
        info.FileName = python.Exe;
        info.Arguments = python.Command(arguments);
        info.WorkingDirectory = root;
        info.UseShellExecute = false;
        info.EnvironmentVariables["PATH"] = BuildPath(root);
        return info;
    }

    private static int RunForeground(string root, Python python, string arguments)
    {
        try
        {
            using (Process proc = Process.Start(MakeStartInfo(root, python, arguments)))
            {
                proc.WaitForExit();
                return proc.ExitCode;
            }
        }
        catch (Exception e)
        {
            Console.WriteLine("[oas] 启动失败: " + e.Message);
            return 1;
        }
    }

    private static int StartGui(string root, Python python, bool admin, bool quiet)
    {
        // GUI 用 pythonw 启动，避免多一个黑框；官方 bat 也是这个行为
        string pythonw = Path.Combine(Path.GetDirectoryName(python.Exe), "pythonw.exe");
        string exe = File.Exists(pythonw) ? pythonw : python.Exe;

        ProcessStartInfo info = new ProcessStartInfo();
        info.FileName = exe;
        info.Arguments = python.Command("gui.py");
        info.WorkingDirectory = root;
        info.UseShellExecute = false;
        info.EnvironmentVariables["PATH"] = BuildPath(root);

        try
        {
            Process.Start(info);
        }
        catch (Exception e)
        {
            Console.WriteLine("[oas] 启动 GUI 失败: " + e.Message);
            return Pause(1);
        }

        if (!quiet)
        {
            Console.WriteLine("[oas] GUI 已启动（若窗口没出现，用 --check 检查依赖，或看图形的日志）");
            Console.WriteLine("[oas] 需要 Web 服务给 OASX 面板用: oas.exe --server");
        }
        return 0;
    }

    private static int RunServer(string root, Python python)
    {
        Console.WriteLine("[oas] 启动 Web 服务（Ctrl+C 结束）");
        Console.WriteLine("[oas] 面板/浏览器访问: http://127.0.0.1:<config\\deploy.yaml 里的 WebuiPort>");
        return RunForeground(root, python, "server.py");
    }

    private static int RunConsole(string root)
    {
        ProcessStartInfo info = new ProcessStartInfo();
        info.FileName = "cmd.exe";
        info.Arguments = "/Q /K";
        info.WorkingDirectory = root;
        info.UseShellExecute = false;
        info.EnvironmentVariables["PATH"] = BuildPath(root);
        try
        {
            Process.Start(info);
            return 0;
        }
        catch (Exception e)
        {
            Console.WriteLine("[oas] 打开命令行失败: " + e.Message);
            return Pause(1);
        }
    }

    // ====================================================================== 环境自检
    private static int CheckEnvironment(string root, Python python)
    {
        Console.WriteLine("[oas] 启动器版本: " + LauncherVersion);

        string toolkit = Path.Combine(root, "toolkit");
        Console.WriteLine("[oas] toolkit          : " + (Directory.Exists(toolkit) ? "存在" : "缺失（源码检出属于正常，一键包才有）"));
        Console.WriteLine("[oas] deploy/installer : " + (File.Exists(Path.Combine(root, "deploy", "installer.py")) ? "存在" : "缺失"));
        Console.WriteLine("[oas] config/deploy.yaml: " + (File.Exists(Path.Combine(root, "config", "deploy.yaml")) ? "存在" : "缺失（端口将用默认 22267）"));

        Console.WriteLine("[oas] python 版本      : " + RunCapture(python, "-V"));
        Console.WriteLine("[oas] Web 服务依赖     : " + Dependency(python, "import fastapi, uvicorn", "fastapi + uvicorn"));
        Console.WriteLine("[oas] GUI 依赖         : " + Dependency(python, "import PySide6", "PySide6"));
        Console.WriteLine("[oas] 脚本运行依赖     : " + Dependency(python, "import adbutils, onnxruntime", "adbutils + onnxruntime"));

        int port = ReadWebuiPort(root);
        bool busy = !IsPortFree(port);
        Console.WriteLine("[oas] Webui 端口       : " + port + (busy ? "（已被占用，可能 OAS 已在运行）" : "（空闲）"));
        return 0;
    }

    private static string Dependency(Python python, string importStatement, string label)
    {
        string output = RunCapture(python, "-c \"" + importStatement + "\"");
        return output.Length == 0 ? "可用（" + label + "）" : "缺失/异常（" + label + "）";
    }

    private static string RunCapture(Python python, string arguments)
    {
        try
        {
            ProcessStartInfo info = new ProcessStartInfo();
            info.FileName = python.Exe;
            info.Arguments = python.Command(arguments);
            info.UseShellExecute = false;
            info.RedirectStandardOutput = true;
            info.RedirectStandardError = true;
            info.CreateNoWindow = true;
            using (Process proc = Process.Start(info))
            {
                string stdout = proc.StandardOutput.ReadToEnd();
                string stderr = proc.StandardError.ReadToEnd();
                proc.WaitForExit();
                return (stdout + stderr).Trim();
            }
        }
        catch (Exception e)
        {
            return "执行失败: " + e.Message;
        }
    }

    private static int ReadWebuiPort(string root)
    {
        try
        {
            string yaml = Path.Combine(root, "config", "deploy.yaml");
            if (!File.Exists(yaml)) return 22267;
            foreach (string line in File.ReadAllLines(yaml))
            {
                Match m = Regex.Match(line, @"^\s*WebuiPort\s*:\s*(\d+)");
                if (m.Success)
                {
                    int port;
                    if (int.TryParse(m.Groups[1].Value, out port)) return port;
                }
            }
        }
        catch { }
        return 22267;
    }

    private static bool IsPortFree(int port)
    {
        TcpListener listener = null;
        try
        {
            listener = new TcpListener(IPAddress.Loopback, port);
            listener.Start();
            return true;
        }
        catch
        {
            return false;
        }
        finally
        {
            if (listener != null)
            {
                try { listener.Stop(); } catch { }
            }
        }
    }

    // ====================================================================== 参数
    private enum Mode { Gui, Server, Update, Console, Check }

    private sealed class Options
    {
        public Mode Mode = Mode.Gui;
        public bool Help;
        public bool Admin;
        public string Root;
        public string Python;

        public static Options Parse(string[] args)
        {
            Options o = new Options();
            for (int i = 0; i < args.Length; i++)
            {
                string a = args[i].ToLowerInvariant();
                switch (a)
                {
                    case "--server":
                    case "-s":
                    case "server":
                        o.Mode = Mode.Server;
                        break;
                    case "--update":
                    case "update":
                        o.Mode = Mode.Update;
                        break;
                    case "--console":
                    case "console":
                        o.Mode = Mode.Console;
                        break;
                    case "--check":
                    case "check":
                        o.Mode = Mode.Check;
                        break;
                    case "--admin":
                        o.Admin = true;
                        break;
                    case "--root":
                        o.Root = Next(args, ref i, "--root");
                        break;
                    case "--python":
                        o.Python = Next(args, ref i, "--python");
                        break;
                    case "--help":
                    case "-h":
                    case "/?":
                        o.Help = true;
                        break;
                    default:
                        throw new Exception("未知参数 " + args[i]);
                }
            }
            return o;
        }

        private static string Next(string[] args, ref int i, string name)
        {
            if (i + 1 >= args.Length) throw new Exception(name + " 缺少参数");
            i++;
            return args[i];
        }
    }

    private static void PrintHelp()
    {
        Console.WriteLine("OAS 启动器 v" + LauncherVersion);
        Console.WriteLine();
        Console.WriteLine("  oas.exe                  启动 GUI（等价官方 oas.exe）");
        Console.WriteLine("  oas.exe --server         启动 Web 服务（OASX 面板连这个）");
        Console.WriteLine("  oas.exe --update         先跑 deploy.installer 再启动 GUI");
        Console.WriteLine("  oas.exe --console        打开带 PATH 的命令行窗口");
        Console.WriteLine("  oas.exe --check          环境自检后退出");
        Console.WriteLine("  oas.exe --admin          以管理员权限重启自身");
        Console.WriteLine("  oas.exe --root <路径>     指定 OAS 根目录");
        Console.WriteLine("  oas.exe --python <路径>   指定 python.exe");
    }

    private static int Pause(int code)
    {
        Console.WriteLine();
        Console.WriteLine("按任意键退出...");
        try { Console.ReadKey(true); }
        catch { }
        return code;
    }
}
