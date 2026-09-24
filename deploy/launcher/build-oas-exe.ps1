<#
    编译 OAS 启动器 oas.exe

    用 Windows 自带的 C# 编译器（.NET Framework 4.x 的 csc.exe），
    不需要安装 Visual Studio / PyInstaller 等任何工具链，产物约 20KB。

    用法（在任意 PowerShell 里）：
        pwsh -File deploy\launcher\build-oas-exe.ps1                # 输出到仓库根目录 oas.exe
        pwsh -File deploy\launcher\build-oas-exe.ps1 -Out D:\x\oas.exe

    说明：oas.exe 被仓库 .gitignore 的 *.exe 规则忽略，属于本地构建产物，不进 git。
#>
param(
    [string]$Out = ''
)

$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot

if ([string]::IsNullOrEmpty($Out)) {
    $repo = (Resolve-Path (Join-Path $here '..\..')).Path
    $Out = Join-Path $repo 'oas.exe'
}

$csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path $csc)) {
    $csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe'
}
if (-not (Test-Path $csc)) {
    throw '找不到 csc.exe（Windows 自带 .NET Framework 4.x 才有）'
}

$source = Join-Path $here 'OasLauncher.cs'
$icon = Join-Path $here 'logo.ico'

$cscArgs = @(
    '/nologo',
    '/target:exe',
    '/platform:anycpu',
    '/optimize+',
    '/codepage:65001',
    "/out:$Out"
)
if (Test-Path $icon) {
    $cscArgs += "/win32icon:$icon"
}
$cscArgs += $source

& $csc @cscArgs
if ($LASTEXITCODE -ne 0) {
    throw "编译失败，exit=$LASTEXITCODE"
}

$size = (Get-Item $Out).Length
Write-Host "已生成: $Out ($size 字节)"
