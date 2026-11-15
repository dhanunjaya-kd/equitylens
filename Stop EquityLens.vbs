' ==========================================================================
'  Stop EquityLens (the windowless server started by EquityLens.vbs).
' ==========================================================================
Option Explicit
Dim sh, fso, root, be, port, url, pid, wmi, procs, p, stopped, h, f, quiet
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
be = root & "\backend"
quiet = (WScript.Arguments.Count > 0)
port = "8600"
If fso.FileExists(be & "\.env") Then
  Set f = fso.OpenTextFile(be & "\.env", 1)
  Do Until f.AtEndOfStream
    p = Trim(f.ReadLine)
    If UCase(Left(p, 9)) = "EQL_PORT=" Then port = Trim(Mid(p, 10))
  Loop
  f.Close
End If
url = "http://localhost:" & port
stopped = False

' 1) Ask the server to stop itself (only works from this computer).
On Error Resume Next
Set h = CreateObject("MSXML2.ServerXMLHTTP.6.0")
h.setTimeouts 1000, 1000, 2000, 2000
h.Open "POST", url & "/api/shutdown", False
h.Send
If Err.Number = 0 Then
  If h.Status = 200 Then stopped = True
End If
Err.Clear
On Error GoTo 0

' 2) If it didn't answer, end the process recorded in data\equitylens.pid.
If Not stopped And fso.FileExists(be & "\data\equitylens.pid") Then
  Set f = fso.OpenTextFile(be & "\data\equitylens.pid", 1)
  pid = Trim(f.ReadAll)
  f.Close
  If IsNumeric(pid) Then
    Set wmi = GetObject("winmgmts:\\.\root\cimv2")
    Set procs = wmi.ExecQuery("SELECT * FROM Win32_Process WHERE ProcessId = " & CLng(pid))
    For Each p In procs
      If InStr(LCase(p.Name), "python") > 0 Then
        p.Terminate
        stopped = True
      End If
    Next
  End If
End If

If Not quiet Then
  If stopped Then
    MsgBox "EquityLens has stopped.", 64, "EquityLens"
  Else
    MsgBox "EquityLens was not running.", 64, "EquityLens"
  End If
End If
