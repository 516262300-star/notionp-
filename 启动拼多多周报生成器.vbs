Option Explicit

Dim shell, fso, appDir, pythonw, command

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

appDir = fso.GetParentFolderName(WScript.ScriptFullName)
pythonw = appDir & "\.venv\Scripts\pythonw.exe"

If Not fso.FileExists(pythonw) Then
    pythonw = "pythonw"
End If

command = """" & pythonw & """ """ & appDir & "\weekly_report_app.pyw" & """"
shell.Run command, 0, False
