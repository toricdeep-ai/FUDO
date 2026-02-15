$desktop = [Environment]::GetFolderPath('Desktop')
$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut([System.IO.Path]::Combine($desktop, 'FUDO.lnk'))
$sc.TargetPath = "C:\Users\toric\FUDO\start_fudo.bat"
$sc.WorkingDirectory = "C:\Users\toric\FUDO"
$sc.Save()
