"""Writes version_info.txt for PyInstaller so FlowType.exe carries product name + version
(shown in the file's Properties > Details; required for code signing)."""
import re
import sys

version = (sys.argv[1] if len(sys.argv) > 1 else "0.0.0").lstrip("v")
nums = [int(x) for x in re.findall(r"\d+", version)[:4]]
nums += [0] * (4 - len(nums))
t = tuple(nums)
text = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={t}, prodvers={t}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'FlowType (open source)'),
      StringStruct('FileDescription', 'FlowType - voice typing'),
      StringStruct('FileVersion', '{version}'),
      StringStruct('InternalName', 'FlowType'),
      StringStruct('LegalCopyright', 'MIT License - Soumya Swarup Sahoo'),
      StringStruct('OriginalFilename', 'FlowType.exe'),
      StringStruct('ProductName', 'FlowType'),
      StringStruct('ProductVersion', '{version}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""
open("version_info.txt", "w", encoding="utf-8").write(text)
print("version_info.txt for", version)
