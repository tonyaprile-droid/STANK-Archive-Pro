STANK Archive Pro v1.0.0 - Release Builder

This folder contains the source project plus release build scripts.

IMPORTANT
- To create a Windows .exe, run the build on a Windows computer.
- The build machine needs Python installed.
- End users do NOT need Python if you send them the finished Portable ZIP created by build_release.bat.

HOW TO BUILD THE SENDABLE PORTABLE ZIP
1. Extract this folder anywhere on your Windows PC.
2. Double-click build_release.bat.
3. Wait for PyInstaller to finish.
4. When complete, look in the release folder.
5. Send this file to users:
   STANK_Archive_Pro_v1.0.0_Portable.zip

WHAT USERS DO
1. Extract STANK_Archive_Pro_v1.0.0_Portable.zip.
2. Open the folder.
3. Double-click StankArchivePro.exe.

OPTIONAL INSTALLER
An Inno Setup script is included as installer/STANK_Archive_Pro.iss.
After running build_release.bat, install Inno Setup and compile that script if you want a normal Windows installer.

NOTES
- The app archives by moving files from the source folder to the archive folder.
- Archive filename format:
  Original Name (Archived MM-DD-YYYY-HH꞉MM).ext
- Windows does not allow normal colons in filenames, so the app uses a Windows-safe colon-style character.
