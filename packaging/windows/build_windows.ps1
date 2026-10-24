# Build Windows Release Packages (.exe Setup Installer + Portable .zip)
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$DistDir = Join-Path $RepoRoot "dist"
$IconsDir = Join-Path $DistDir "icons"
$StageDir = Join-Path $DistDir "stage_windows"
$Version = "0.2.0"

Write-Host "==> [1/4] Preparando carpetas de salida en $DistDir..." -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path $DistDir | Out-Null
New-Item -ItemType Directory -Force -Path $IconsDir | Out-Null
if (Test-Path $StageDir) { Remove-Item -Recurse -Force $StageDir }
New-Item -ItemType Directory -Force -Path $StageDir | Out-Null

# Locate Python with Pillow
$pyExe = "python"
$venvPy = "C:\Users\Public\.local\share\media_manager\venv\Scripts\python.exe"
if (Test-Path $venvPy) { $pyExe = $venvPy }

Write-Host "==> [2/4] Generando iconos de alta resolucion (.ico y .png)..." -ForegroundColor Cyan
& $pyExe (Join-Path $RepoRoot "packaging\generate_icons.py") $IconsDir | Out-Null
$IcoPath = Join-Path $IconsDir "media_manager.ico"

Write-Host "==> [3/4] Empaquetando archivo portable (MediaManager-Windows-x64-Portable.zip)..." -ForegroundColor Cyan
$pkgFolder = Join-Path $StageDir "MediaManager"
New-Item -ItemType Directory -Force -Path (Join-Path $pkgFolder "media_manager") | Out-Null
Copy-Item -Path (Join-Path $RepoRoot "media_manager\*.py") -Destination (Join-Path $pkgFolder "media_manager") -Force
Copy-Item -Path (Join-Path $RepoRoot "setup.py") -Destination $pkgFolder -Force
Copy-Item -Path (Join-Path $RepoRoot "install.ps1") -Destination $pkgFolder -Force
Copy-Item -Path (Join-Path $RepoRoot "README.md") -Destination $pkgFolder -Force
Copy-Item -Path $IcoPath -Destination $pkgFolder -Force

$launcherBat = @"
@echo off
title Instalador de Media Manager
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
pause
"@
Set-Content -Path (Join-Path $pkgFolder "Instalar-Media-Manager.bat") -Value $launcherBat -Encoding ASCII

$ZipPath = Join-Path $DistDir "MediaManager-$Version-Windows-x64-Portable.zip"
if (Test-Path $ZipPath) { Remove-Item -Force $ZipPath }
Compress-Archive -Path "$pkgFolder\*" -DestinationPath $ZipPath -Force
Write-Host "[OK] Creado: $ZipPath" -ForegroundColor Green

Write-Host "==> [4/4] Compilando instalador ejecutable (MediaManager-Setup-$Version-Windows-x64.exe)..." -ForegroundColor Cyan
$SetupExePath = Join-Path $DistDir "MediaManager-Setup-$Version-Windows-x64.exe"
if (Test-Path $SetupExePath) { Remove-Item -Force $SetupExePath }

# Check if Inno Setup (ISCC.exe) is available
$iscc = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
if (-not $iscc) {
    $defaultIscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
    if (Test-Path $defaultIscc) { $iscc = $defaultIscc }
}

if ($iscc) {
    $isccExe = if ($iscc.Source) { $iscc.Source } else { $iscc }
    & $isccExe (Join-Path $PSScriptRoot "installer.iss")
}

# Fallback / Standalone WinForms GUI Installer compiler using built-in .NET csc.exe
if (-not (Test-Path $SetupExePath)) {
    $csc = Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\csc.exe"
    if (-not (Test-Path $csc)) {
        $csc = Join-Path $env:WINDIR "Microsoft.NET\Framework\v4.0.30319\csc.exe"
    }
    $csFile = Join-Path $StageDir "SetupProgram.cs"
    $csCode = @"
using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Windows.Forms;

[assembly: AssemblyTitle("Media Manager Setup")]
[assembly: AssemblyProduct("Media Manager")]
[assembly: AssemblyVersion("0.2.0.0")]

namespace MediaManagerSetup {
    public class InstallerForm : Form {
        private RadioButton rbAllUsers;
        private RadioButton rbCurrentUser;
        private Button btnInstall;
        private Button btnCancel;
        private Label lblStatus;
        private ProgressBar progressBar;

        public InstallerForm() {
            this.Text = "Instalador de Media Manager v0.2.0";
            this.Size = new Size(480, 310);
            this.FormBorderStyle = FormBorderStyle.FixedDialog;
            this.MaximizeBox = false;
            this.StartPosition = FormStartPosition.CenterScreen;
            this.BackColor = Color.FromArgb(243, 244, 246);
            this.Font = new Font("Segoe UI", 9.5f);

            Panel header = new Panel();
            header.Dock = DockStyle.Top;
            header.Height = 64;
            header.BackColor = Color.FromArgb(43, 49, 58);

            Label title = new Label();
            title.Text = "Media Manager v0.2.0";
            title.ForeColor = Color.FromArgb(240, 243, 246);
            title.Font = new Font("Segoe UI Semibold", 13f, FontStyle.Bold);
            title.Location = new Point(20, 12);
            title.AutoSize = true;

            Label sub = new Label();
            sub.Text = "Aplicación de Escritorio (Flutter GUI) + Terminal (TUI / CLI)";
            sub.ForeColor = Color.FromArgb(180, 190, 200);
            sub.Font = new Font("Segoe UI", 9f);
            sub.Location = new Point(22, 36);
            sub.AutoSize = true;

            header.Controls.Add(title);
            header.Controls.Add(sub);
            this.Controls.Add(header);

            Label lblScope = new Label();
            lblScope.Text = "Seleccioná el modo de instalación:";
            lblScope.Location = new Point(24, 82);
            lblScope.AutoSize = true;
            lblScope.Font = new Font("Segoe UI Semibold", 9.5f, FontStyle.Bold);
            this.Controls.Add(lblScope);

            rbAllUsers = new RadioButton();
            rbAllUsers.Text = "Todos los usuarios del equipo (Recomendado - C:\\Users\\Public)";
            rbAllUsers.Location = new Point(28, 110);
            rbAllUsers.AutoSize = true;
            rbAllUsers.Checked = true;
            this.Controls.Add(rbAllUsers);

            rbCurrentUser = new RadioButton();
            rbCurrentUser.Text = "Solo para mi usuario actual";
            rbCurrentUser.Location = new Point(28, 138);
            rbCurrentUser.AutoSize = true;
            this.Controls.Add(rbCurrentUser);

            lblStatus = new Label();
            lblStatus.Text = "Incluye motor aria2c, accesos directos e interfaz gráfica.";
            lblStatus.ForeColor = Color.FromArgb(87, 96, 106);
            lblStatus.Location = new Point(24, 176);
            lblStatus.Size = new Size(420, 22);
            this.Controls.Add(lblStatus);

            progressBar = new ProgressBar();
            progressBar.Location = new Point(24, 200);
            progressBar.Size = new Size(416, 12);
            progressBar.Style = ProgressBarStyle.Marquee;
            progressBar.Visible = false;
            this.Controls.Add(progressBar);

            btnInstall = new Button();
            btnInstall.Text = "Instalar";
            btnInstall.Size = new Size(110, 34);
            btnInstall.Location = new Point(216, 224);
            btnInstall.BackColor = Color.FromArgb(74, 114, 158);
            btnInstall.ForeColor = Color.White;
            btnInstall.FlatStyle = FlatStyle.Flat;
            btnInstall.Click += OnInstallClick;
            this.Controls.Add(btnInstall);

            btnCancel = new Button();
            btnCancel.Text = "Cancelar";
            btnCancel.Size = new Size(100, 34);
            btnCancel.Location = new Point(340, 224);
            btnCancel.FlatStyle = FlatStyle.System;
            btnCancel.Click += (s, e) => this.Close();
            this.Controls.Add(btnCancel);
        }

        private void OnInstallClick(object sender, EventArgs e) {
            btnInstall.Enabled = false;
            rbAllUsers.Enabled = false;
            rbCurrentUser.Enabled = false;
            progressBar.Visible = true;
            lblStatus.Text = "Instalando Media Manager, por favor esperá...";

            bool allUsers = rbAllUsers.Checked;
            System.Threading.ThreadPool.QueueUserWorkItem(_ => {
                string tempDir = Path.Combine(Path.GetTempPath(), "MediaManagerSetup_" + Guid.NewGuid().ToString("N"));
                try {
                    Directory.CreateDirectory(tempDir);
                    string zipFile = Path.Combine(tempDir, "payload.zip");
                    using (Stream res = Assembly.GetExecutingAssembly().GetManifestResourceStream("payload.zip")) {
                        using (FileStream fs = new FileStream(zipFile, FileMode.Create, FileAccess.Write)) {
                            res.CopyTo(fs);
                        }
                    }
                    ZipFile.ExtractToDirectory(zipFile, tempDir);
                    string ps1 = Path.Combine(tempDir, "install.ps1");
                    string flag = allUsers ? "-AllUsers" : "-CurrentUser";

                    ProcessStartInfo psi = new ProcessStartInfo("powershell.exe", "-NoProfile -ExecutionPolicy Bypass -File \"" + ps1 + "\" " + flag);
                    psi.UseShellExecute = false;
                    Process proc = Process.Start(psi);
                    proc.WaitForExit();

                    this.Invoke((Action)(() => {
                        progressBar.Visible = false;
                        if (proc.ExitCode == 0) {
                            MessageBox.Show(this, "¡Media Manager se instaló correctamente!\n\nYa podés abrirlo desde el Escritorio, el Menú Inicio o ejecutando 'media-manager' en la terminal.", "Instalación completada", MessageBoxButtons.OK, MessageBoxIcon.Information);
                            this.Close();
                        } else {
                            lblStatus.Text = "La instalación finalizó con código " + proc.ExitCode;
                            btnInstall.Enabled = true;
                        }
                    }));
                } catch (Exception ex) {
                    this.Invoke((Action)(() => {
                        progressBar.Visible = false;
                        MessageBox.Show(this, "Error durante la instalación: " + ex.Message, "Error", MessageBoxButtons.OK, MessageBoxIcon.Error);
                        btnInstall.Enabled = true;
                    }));
                } finally {
                    try { Directory.Delete(tempDir, true); } catch {}
                }
            });
        }

        [STAThread]
        public static void Main() {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new InstallerForm());
        }
    }
}
"@
    Set-Content -Path $csFile -Value $csCode -Encoding UTF8
    & $csc /target:winexe /out:"$SetupExePath" /win32icon:"$IcoPath" /resource:"$ZipPath,payload.zip" /r:System.IO.Compression.FileSystem.dll /r:System.Windows.Forms.dll /r:System.Drawing.dll "$csFile" | Out-Null
}

if (Test-Path $SetupExePath) {
    Write-Host "[OK] Creado instalador ejecutable: $SetupExePath" -ForegroundColor Green
}

Remove-Item -Recurse -Force $StageDir -ErrorAction SilentlyContinue
