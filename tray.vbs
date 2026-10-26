' Double-click to run Screen Share in the system tray (no console window)
Set fso = CreateObject("Scripting.FileSystemObject")
folder = fso.GetParentFolderName(WScript.ScriptFullName)
CreateObject("WScript.Shell").Run "cmd /c pythonw """ & folder & "\tray.py""", 0, False
