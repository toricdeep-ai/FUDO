Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\Users\toric\FUDO"
WshShell.Run "python scheduler.py", 0, False
