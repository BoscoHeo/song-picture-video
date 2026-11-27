
using System;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Threading.Tasks;
using System.Windows.Forms;

internal static class Launcher
{
    [STAThread]
    private static int Main(string[] args)
    {
        string root = AppDomain.CurrentDomain.BaseDirectory;
        string python = Path.Combine(root, "runtime", "python", "pythonw.exe");
        string app = Path.Combine(root, "app", "app.py");
        string tools = Path.Combine(root, "runtime", "ffmpeg", "bin");
        bool check = args.Length == 1 && args[0] == "--self-test";
        try
        {
            if (!File.Exists(python) || !File.Exists(app))
                throw new InvalidOperationException("ZIP 전체를 한 폴더에 압축 해제한 뒤 실행해 주세요.");
            var launch = new ProcessStartInfo(python, "-I -B -X utf8 \"" + app + "\"" +
                (check ? " --self-test" : ""));
            launch.WorkingDirectory = root;
            launch.UseShellExecute = false;
            launch.CreateNoWindow = true;
            launch.RedirectStandardError = true;
            launch.StandardErrorEncoding = Encoding.UTF8;
            launch.EnvironmentVariables["PATH"] = tools + ";" +
                Path.Combine(root, "runtime", "python") + ";" +
                Environment.GetFolderPath(Environment.SpecialFolder.System) + ";" + Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "WindowsPowerShell", "v1.0");
            launch.EnvironmentVariables["PYTHONUTF8"] = "1";
            string tcl = Path.Combine(root, "runtime", "python", "tcl");
            launch.EnvironmentVariables["TCL_LIBRARY"] = Path.Combine(tcl, "tcl8.6");
            launch.EnvironmentVariables["TK_LIBRARY"] = Path.Combine(tcl, "tk8.6");
            using (Process child = Process.Start(launch))
            {
                Task<string> errors = Task.Factory.StartNew(() => child.StandardError.ReadToEnd());
                child.WaitForExit();
                string details = errors.Result;
                if (child.ExitCode != 0)
                    throw new InvalidOperationException(String.IsNullOrWhiteSpace(details) ?
                        "프로그램 초기화에 실패했습니다." : details);
                return 0;
            }
        }
        catch (Exception error)
        {
            if (!check)
                MessageBox.Show(error.Message, "노래 그림 영상 만들기",
                    MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }
}



