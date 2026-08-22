Dim objShell, fileSystem, sourcePath, projectRoot, launcher
Set objShell = CreateObject("WScript.Shell")
Set fileSystem = CreateObject("Scripting.FileSystemObject")

sourcePath = fileSystem.GetParentFolderName(WScript.ScriptFullName)
projectRoot = fileSystem.GetParentFolderName(sourcePath)
launcher = projectRoot & "\START_KOMI_REPORT.cmd"

' Compatibility wrapper: Windows runtime and canonical source checks live in the root launcher.
objShell.Run "cmd.exe /c """ & launcher & """", 0, False
