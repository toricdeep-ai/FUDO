$desktop = [Environment]::GetFolderPath('Desktop')
$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut([System.IO.Path]::Combine($desktop, 'FUDO Cloud.lnk'))
$sc.TargetPath = "https://bptdmddktkqexyappuzrjsb.streamlit.app/"
$sc.Hotkey = "CTRL+ALT+F"
$sc.Save()
