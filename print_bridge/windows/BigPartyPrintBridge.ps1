$ErrorActionPreference = 'Stop'
$appDir = Join-Path $env:LOCALAPPDATA 'BigPartyPrintBridge'
$configPath = Join-Path $appDir 'config.json'
$logPath = Join-Path $appDir 'bridge.log'

Add-Type @'
using System;
using System.Runtime.InteropServices;
public class RawPrinter {
  [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)] public class DOCINFO { public string pDocName; public string pOutputFile; public string pDataType; }
  [DllImport("winspool.drv", SetLastError=true, CharSet=CharSet.Unicode)] static extern bool OpenPrinter(string name, out IntPtr handle, IntPtr defaults);
  [DllImport("winspool.drv", SetLastError=true)] static extern bool ClosePrinter(IntPtr handle);
  [DllImport("winspool.drv", SetLastError=true, CharSet=CharSet.Unicode)] static extern int StartDocPrinter(IntPtr handle, int level, [In] DOCINFO info);
  [DllImport("winspool.drv", SetLastError=true)] static extern bool EndDocPrinter(IntPtr handle);
  [DllImport("winspool.drv", SetLastError=true)] static extern bool StartPagePrinter(IntPtr handle);
  [DllImport("winspool.drv", SetLastError=true)] static extern bool EndPagePrinter(IntPtr handle);
  [DllImport("winspool.drv", SetLastError=true)] static extern bool WritePrinter(IntPtr handle, byte[] data, int count, out int written);
  public static void Send(string queue, byte[] data) {
    IntPtr h; if (!OpenPrinter(queue, out h, IntPtr.Zero)) throw new System.ComponentModel.Win32Exception();
    try { var d = new DOCINFO { pDocName="BIG PARTY", pDataType="RAW" };
      if (StartDocPrinter(h,1,d)==0) throw new System.ComponentModel.Win32Exception();
      try { if (!StartPagePrinter(h)) throw new System.ComponentModel.Win32Exception();
        try { int n; if (!WritePrinter(h,data,data.Length,out n) || n!=data.Length) throw new System.ComponentModel.Win32Exception(); }
        finally { EndPagePrinter(h); }
      } finally { EndDocPrinter(h); }
    } finally { ClosePrinter(h); }
  }
}
'@

function Log([string]$message) {
  $line = "$(Get-Date -Format s) $message"
  Add-Content -LiteralPath $logPath -Value $line -Encoding UTF8
}

if (!(Test-Path -LiteralPath $configPath)) { throw 'Falta config.json. Ejecuta Instalar.cmd.' }
$config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
$headers = @{ Authorization = "Bearer $($config.token)" }
$nextUrl = "$($config.server.TrimEnd('/'))/impresoras/puente/api/trabajo/"
Log 'Mini app iniciada.'
while ($true) {
  try {
    $answer = Invoke-RestMethod -Method Post -Uri $nextUrl -Headers $headers -ContentType 'application/json' -Body '{}'
    if ($null -eq $answer.job) { Start-Sleep -Seconds 2; continue }
    $job = $answer.job
    try {
      [RawPrinter]::Send([string]$job.queue, [Convert]::FromBase64String([string]$job.payload))
      $body = @{ claim=$job.claim; ok=$true } | ConvertTo-Json -Compress
      Invoke-RestMethod -Method Post -Uri "$($nextUrl)$($job.id)/completar/" -Headers $headers -ContentType 'application/json' -Body $body | Out-Null
      Log "Trabajo $($job.id) enviado a $($job.queue)."
    } catch {
      $body = @{ claim=$job.claim; ok=$false; uncertain=$true; error=$_.Exception.Message } | ConvertTo-Json -Compress
      try { Invoke-RestMethod -Method Post -Uri "$($nextUrl)$($job.id)/completar/" -Headers $headers -ContentType 'application/json' -Body $body | Out-Null } catch {}
      Log "Trabajo $($job.id) fallo."
    }
  } catch {
    Log 'Servidor temporalmente no disponible.'
    Start-Sleep -Seconds 10
  }
}
