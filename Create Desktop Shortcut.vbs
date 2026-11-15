' ==========================================================================
'  Adds EquityLens to the Desktop and the Start menu (with its own icon),
'  plus a "Stop EquityLens" shortcut in the Start menu.
'  Optionally starts EquityLens automatically when Windows starts.
' ==========================================================================
Option Explicit
Dim sh, fso, root, wscript_exe, icon, places, folder, answer
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
wscript_exe = sh.ExpandEnvironmentStrings("%WINDIR%") & "\System32\wscript.exe"
icon = root & "\assets\equitylens.ico"

Sub MakeLink(path, script, desc)
  Dim lnk
  Set lnk = sh.CreateShortcut(path)
  lnk.TargetPath = wscript_exe
  lnk.Arguments = """" & root & "\" & script & """"
  lnk.WorkingDirectory = root
  If fso.FileExists(icon) Then lnk.IconLocation = icon & ",0"
  lnk.Description = desc
  lnk.Save
End Sub

MakeLink sh.SpecialFolders("Desktop") & "\EquityLens.lnk", "EquityLens.vbs", "EquityLens stock research"
MakeLink sh.SpecialFolders("Programs") & "\EquityLens.lnk", "EquityLens.vbs", "EquityLens stock research"
MakeLink sh.SpecialFolders("Programs") & "\Stop EquityLens.lnk", "Stop EquityLens.vbs", "Stop the EquityLens server"

answer = MsgBox("Shortcuts added to the Desktop and the Start menu." & vbCrLf & vbCrLf & _
                "Start EquityLens automatically when Windows starts?" & vbCrLf & _
                "(It runs quietly in the background, so your phone can reach it too.)", vbYesNo + vbQuestion, "EquityLens")
folder = sh.SpecialFolders("Startup")
If answer = vbYes Then
  ' /background: start the server at sign-in without opening a window
  Dim lnk
  Set lnk = sh.CreateShortcut(folder & "\EquityLens.lnk")
  lnk.TargetPath = wscript_exe
  lnk.Arguments = """" & root & "\EquityLens.vbs"" /background"
  lnk.WorkingDirectory = root
  If fso.FileExists(icon) Then lnk.IconLocation = icon & ",0"
  lnk.Save
  MsgBox "Done. EquityLens will start in the background each time you sign in to Windows.", 64, "EquityLens"
ElseIf fso.FileExists(folder & "\EquityLens.lnk") Then
  fso.DeleteFile folder & "\EquityLens.lnk"
End If
