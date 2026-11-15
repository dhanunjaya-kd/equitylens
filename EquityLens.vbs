' ==========================================================================
'  EquityLens - start without a black console window and open the app.
'  Double-click this file (or the desktop shortcut made by
'  "Create Desktop Shortcut.vbs"). Logs: backend\data\logs\equitylens.log
'  To stop it: "Stop EquityLens.vbs".
'  Optional settings in backend\.env:
'    EQL_PORT=8600        web port
'    EQL_OPEN=app         app = its own window (Edge app mode), browser = normal tab
' ==========================================================================
Option Explicit
Dim sh, fso, root, be, pyw, port, url, i, rc, bg
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
be = root & "\backend"
pyw = be & "\venv\Scripts\pythonw.exe"
port = ReadEnv("EQL_PORT", "8600")
url = "http://localhost:" & port
bg = False                                  ' /background (used at Windows sign-in): start, don't open
If WScript.Arguments.Count > 0 Then bg = (LCase(WScript.Arguments(0)) = "/background")

' Already running? Just open it.
If IsUp() Then
  OpenApp
  WScript.Quit 0
End If

' First run, or new packages after "git pull": install (a window shows progress).
If Not fso.FileExists(pyw) Or NeedsInstall() Then
  sh.Popup "Setting up EquityLens (first run or after an update)." & vbCrLf & "This takes 1 to 3 minutes. The app opens by itself when ready.", 5, "EquityLens", 64
  rc = sh.Run("cmd /c """"" & root & "\start.bat"" setup""", 1, True)
  If rc <> 0 Or Not fso.FileExists(pyw) Then
    MsgBox "Setup did not finish." & vbCrLf & vbCrLf & "Double-click start.bat once to see the error, or install Python 3.11+ from python.org (tick 'Add python.exe to PATH').", 16, "EquityLens"
    WScript.Quit 1
  End If
End If

' Start the server with pythonw.exe: no window at all.
sh.CurrentDirectory = be
sh.Run """" & pyw & """ """ & be & "\run.py""", 0, False

For i = 1 To 90
  WScript.Sleep 1000
  If IsUp() Then
    OpenApp
    WScript.Quit 0
  End If
Next

MsgBox "EquityLens did not start within 90 seconds." & vbCrLf & vbCrLf & "The log opens next. Common causes: another program is using port " & port & ", or a package is missing (run start.bat once).", 48, "EquityLens"
If fso.FileExists(be & "\data\logs\console.log") Then sh.Run "notepad """ & be & "\data\logs\console.log""", 1, False
If fso.FileExists(be & "\data\logs\equitylens.log") Then sh.Run "notepad """ & be & "\data\logs\equitylens.log""", 1, False
WScript.Quit 1


' --------------------------------------------------------------------------
Function IsUp()
  Dim h
  IsUp = False
  On Error Resume Next
  Set h = CreateObject("MSXML2.ServerXMLHTTP.6.0")
  h.setTimeouts 1000, 1000, 2000, 2000
  h.Open "GET", url & "/api/health", False
  h.Send
  If Err.Number = 0 Then
    If h.Status = 200 Then IsUp = True
  End If
  Err.Clear
  On Error GoTo 0
End Function

Sub OpenApp()
  Dim edge, p
  If bg Then Exit Sub
  edge = ""
  If LCase(ReadEnv("EQL_OPEN", "app")) = "app" Then
    For Each p In Array(sh.ExpandEnvironmentStrings("%ProgramFiles(x86)%") & "\Microsoft\Edge\Application\msedge.exe", _
                        sh.ExpandEnvironmentStrings("%ProgramFiles%") & "\Microsoft\Edge\Application\msedge.exe", _
                        sh.ExpandEnvironmentStrings("%LocalAppData%") & "\Microsoft\Edge\Application\msedge.exe")
      If edge = "" And fso.FileExists(p) Then edge = p
    Next
  End If
  If edge <> "" Then
    sh.Run """" & edge & """ --app=" & url & " --window-size=1440,900", 1, False
  Else
    sh.Run url, 1, False
  End If
End Sub

Function NeedsInstall()
  NeedsInstall = (ReadAll(be & "\requirements.txt") <> ReadAll(be & "\venv\eql_req.txt"))
End Function

Function ReadAll(path)
  Dim f
  ReadAll = ""
  If fso.FileExists(path) Then
    If fso.GetFile(path).Size > 0 Then
      Set f = fso.OpenTextFile(path, 1)
      ReadAll = f.ReadAll
      f.Close
    End If
  End If
End Function

Function ReadEnv(key, def)
  Dim f, line, k
  ReadEnv = def
  If Not fso.FileExists(be & "\.env") Then Exit Function
  Set f = fso.OpenTextFile(be & "\.env", 1)
  Do Until f.AtEndOfStream
    line = Trim(f.ReadLine)
    If InStr(line, "=") > 1 And Left(line, 1) <> "#" Then
      k = Trim(Left(line, InStr(line, "=") - 1))
      If Len(k) > 0 And Asc(Left(k, 1)) > 127 Then k = Mid(k, 2)
      If UCase(Right(k, Len(key))) = UCase(key) And Len(k) <= Len(key) + 3 Then
        ReadEnv = Trim(Replace(Replace(Mid(line, InStr(line, "=") + 1), """", ""), "'", ""))
        If ReadEnv = "" Then ReadEnv = def
      End If
    End If
  Loop
  f.Close
End Function
