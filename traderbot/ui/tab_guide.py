"""Rehber tab: the research behind the features (research/ARASTIRMA.md) and the
numbers of the strategy study (research/REPORT.md), readable in the app."""

from PySide6 import QtCore, QtWidgets

from .. import paths
from . import theme

DOCS = [("ARASTIRMA.md", "Trading araştırması: ne işe yarıyor?"),
        ("REPORT.md", "Strateji testi: bütün sayılar")]


class GuideTab(QtWidgets.QWidget):
    status = QtCore.Signal(str)

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.current = None
        self.view = QtWidgets.QTextBrowser()
        self.view.setOpenExternalLinks(True)
        self.buttons = QtWidgets.QButtonGroup(self)
        self.buttons.setExclusive(True)
        bar = QtWidgets.QHBoxLayout()
        for name, title in DOCS:
            b = theme.button(title, checkable=True)
            b.setProperty("doc", name)
            self.buttons.addButton(b)
            bar.addWidget(b)
        self.buttons.buttonClicked.connect(lambda b: self.show_doc(b.property("doc")))
        bar.addStretch(1)
        bar.addWidget(theme.label("Yatırım tavsiyesi değildir. Bağlantılar tarayıcıda açılır.",
                                  "muted"))
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.addLayout(bar)
        lay.addWidget(self.view, 1)
        self.show_doc(DOCS[0][0])

    def show_doc(self, name):
        path = paths.resource("research", name)
        try:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        except OSError:
            text = "Belge bulunamadı: %s" % path
        self.view.setMarkdown(text)
        self.current = name
        for b in self.buttons.buttons():
            b.setChecked(b.property("doc") == name)
