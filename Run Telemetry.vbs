Set shell = CreateObject("WScript.Shell")
projectDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
pythonw = projectDir & "\server\.venv\Scripts\pythonw.exe"
launcher = projectDir & "\telemetry_launcher.py"

Set fso = CreateObject("Scripting.FileSystemObject")
If Not fso.FileExists(pythonw) Then
    MsgBox "Project Python environment not found." & vbCrLf & vbCrLf & _
           "Run the Windows setup commands in README.md first.", vbExclamation, "SHT40 Telemetry"
    WScript.Quit 1
End If

shell.Run Chr(34) & pythonw & Chr(34) & " " & Chr(34) & launcher & Chr(34), 0, False
