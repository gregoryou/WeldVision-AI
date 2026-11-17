Option Explicit
Dim shell, fs, scriptDir, py, scriptPath
Set shell = CreateObject("WScript.Shell")
Set fs = CreateObject("Scripting.FileSystemObject")
scriptDir = fs.GetParentFolderName(WScript.ScriptFullName)
py = shell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\WeldVisionAI\venv\Scripts\pythonw.exe"
scriptPath = scriptDir & "\WeldVision_AI.pyw"
If Not fs.FileExists(py) Then
    MsgBox "Najpierw uruchom Install_Base.bat w folderze WeldVision AI.", vbExclamation, "WeldVision AI"
Else
    shell.Run Chr(34) & py & Chr(34) & " " & Chr(34) & scriptPath & Chr(34), 1, False
End If
