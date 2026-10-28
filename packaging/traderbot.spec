# PyInstaller spec for TraderBot (one-folder build; the installer wraps it).
#   pyinstaller packaging/traderbot.spec --noconfirm --clean
import os

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))  # noqa: F821 (SPECPATH is set by PyInstaller)


def here(*parts):
    return os.path.join(ROOT, *parts)


datas = [
    (here("research", "REPORT.md"), "research"),
    (here("traderbot", "resources"), os.path.join("traderbot", "resources")),
    (here("traderbot", "skills", "filers.json"), os.path.join("traderbot", "skills")),
    (here("traderbot", "skills", "share_classes.json"), os.path.join("traderbot", "skills")),
    (here("traderbot", "skills", "LICENSE"), os.path.join("traderbot", "skills")),
]

a = Analysis(  # noqa: F821
    [here("packaging", "launcher.py")],
    pathex=[ROOT],
    datas=datas,
    hiddenimports=["PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineCore", "PySide6.QtWebChannel"],
    excludes=["tkinter", "matplotlib", "pandas", "scipy", "IPython", "PyQt5", "PyQt6",
              "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput", "PySide6.Qt3DLogic",
              "PySide6.Qt3DExtras", "PySide6.Qt3DAnimation", "PySide6.QtCharts",
              "PySide6.QtDataVisualization", "PySide6.QtGraphs", "PySide6.QtMultimedia",
              "PySide6.QtMultimediaWidgets", "PySide6.QtQuick3D", "PySide6.QtBluetooth",
              "PySide6.QtNfc", "PySide6.QtSensors", "PySide6.QtSerialPort",
              "PySide6.QtTextToSpeech", "PySide6.QtSpatialAudio", "PySide6.QtPdf",
              "PySide6.QtPdfWidgets", "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtSql",
              "PySide6.QtTest", "PySide6.QtRemoteObjects", "PySide6.QtScxml",
              "PySide6.QtStateMachine", "pyqtgraph.opengl", "OpenGL"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TraderBot",
    console=False,
    icon=here("packaging", "traderbot.ico"),
    version=here("packaging", "version_info.txt"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="TraderBot")  # noqa: F821
