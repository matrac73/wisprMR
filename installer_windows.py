"""Modern Windows GUI installer bootstrapper for Wispr MR.

Build with PyInstaller onefile and bundle WisprMR-Install.zip as data.
The installer extracts the app package, then delegates to setup.ps1.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


APP_NAME = "Wispr MR"
PACKAGE_NAME = "WisprMR-Install.zip"


def resource_path(name: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / name


def default_install_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "WisprMR"


class InstallWorker(QThread):
    log = Signal(str)
    finished_ok = Signal()
    failed = Signal(str)

    def __init__(
        self,
        install_dir: Path,
        profile: str,
        install_ollama: bool,
        autostart: bool,
        launch: bool,
    ) -> None:
        super().__init__()
        self.install_dir = install_dir
        self.profile = profile
        self.install_ollama = install_ollama
        self.autostart = autostart
        self.launch = launch

    def run(self) -> None:
        try:
            root = self._extract_package(self.install_dir.expanduser().resolve())
            setup = root / "setup.ps1"
            if not setup.exists():
                raise FileNotFoundError("setup.ps1 introuvable apres extraction.")

            args = [
                "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-WindowStyle",
                "Hidden",
                "-File",
                str(setup),
                "-Profile",
                self.profile,
            ]
            if not self.install_ollama:
                args.append("-SkipOllama")
            if not self.autostart:
                args.append("-NoAutostart")
            if self.launch:
                args.append("-Launch")

            self.log.emit("Installation des dependances et modeles...")
            process = subprocess.Popen(
                args,
                cwd=root,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                startupinfo=self._hidden_startupinfo(),
                creationflags=self._creation_flags(),
            )
            assert process.stdout is not None
            for line in process.stdout:
                clean_line = line.strip()
                if clean_line:
                    self.log.emit(clean_line)
            exit_code = process.wait()
            if exit_code != 0:
                raise RuntimeError(f"Installation interrompue (code {exit_code}).")
            self.log.emit("Installation terminee.")
            self.finished_ok.emit()
        except Exception as exc:  # noqa: BLE001
            self.log.emit(f"ERREUR: {exc}")
            self.failed.emit(str(exc))

    def _extract_package(self, target: Path) -> Path:
        package = resource_path(PACKAGE_NAME)
        if not package.exists():
            raise FileNotFoundError(f"Package introuvable: {package}")

        if target.exists():
            backup = target.with_name(target.name + ".previous")
            if backup.exists():
                shutil.rmtree(backup, ignore_errors=True)
            target.rename(backup)
        target.mkdir(parents=True, exist_ok=True)

        self.log.emit("Extraction des fichiers...")
        with zipfile.ZipFile(package) as archive:
            archive.extractall(target)

        nested = target / "WisprMR"
        if nested.exists():
            for child in nested.iterdir():
                destination = target / child.name
                if destination.exists():
                    if destination.is_dir():
                        shutil.rmtree(destination)
                    else:
                        destination.unlink()
                child.rename(destination)
            nested.rmdir()
        return target

    @staticmethod
    def _creation_flags() -> int:
        if sys.platform != "win32":
            return 0
        return subprocess.CREATE_NO_WINDOW

    @staticmethod
    def _hidden_startupinfo() -> subprocess.STARTUPINFO | None:
        if sys.platform != "win32":
            return None
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        return startupinfo


class InstallerApp(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} Installer")
        self.setMinimumSize(980, 660)
        self.resize(1040, 700)

        self.install_path = QLineEdit(str(default_install_dir()))
        self.profile_buttons: dict[str, QRadioButton] = {}
        self.install_ollama = QCheckBox("Configurer Ollama pour le polishing local")
        self.autostart = QCheckBox("Lancer Wispr MR au demarrage de Windows")
        self.launch = QCheckBox("Ouvrir Wispr MR a la fin")
        self.install_ollama.setChecked(True)
        self.autostart.setChecked(True)
        self.launch.setChecked(True)

        self.current_step = 0
        self.worker: InstallWorker | None = None
        self.step_labels: list[QLabel] = []
        self.steps = [
            ("Welcome", "Ce qui va etre installe"),
            ("Location", "Dossier local"),
            ("Profile", "Fast, Balanced ou Quality"),
            ("Options", "Autostart et polishing"),
            ("Install", "Execution silencieuse"),
        ]

        self.pages = QStackedWidget()
        self.back_button = QPushButton("Retour")
        self.next_button = QPushButton("Suivant")
        self.install_button = QPushButton("Installer")
        self.quit_button = QPushButton("Quitter")
        self.log_box = QTextEdit()

        self._apply_style()
        self._build()
        self._show_step(0)

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QWidget {
                background: #080808;
                color: #f7f7f2;
                font-family: "Segoe UI";
                font-size: 14px;
            }
            QLabel#Brand {
                font-family: Georgia;
                font-size: 34px;
                color: #f7f7f2;
            }
            QLabel#Title {
                font-family: Georgia;
                font-size: 44px;
                color: #f7f7f2;
            }
            QLabel#Subtitle, QLabel#Muted {
                color: #9f9f99;
                line-height: 1.45;
            }
            QFrame#Sidebar {
                background: #0d0d0d;
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 18px;
            }
            QFrame#Panel {
                background: #111111;
                border: 1px solid rgba(255,255,255,0.14);
                border-radius: 22px;
            }
            QFrame.Card {
                background: #171717;
                border: 1px solid rgba(255,255,255,0.12);
                border-radius: 16px;
            }
            QFrame.Card:hover {
                border: 1px solid #f7f7f2;
                background: #1d1d1d;
            }
            QLabel.Step {
                color: #777770;
                background: transparent;
                padding: 12px 14px;
                border-radius: 12px;
            }
            QLabel.StepActive {
                color: #080808;
                background: #f7f7f2;
                padding: 12px 14px;
                border-radius: 12px;
            }
            QPushButton {
                background: #151515;
                color: #f7f7f2;
                border: 1px solid rgba(255,255,255,0.16);
                border-radius: 12px;
                padding: 12px 20px;
                font-weight: 700;
            }
            QPushButton:hover {
                background: #f7f7f2;
                color: #080808;
                border-color: #f7f7f2;
            }
            QPushButton:disabled {
                color: #666660;
                background: #101010;
                border-color: rgba(255,255,255,0.08);
            }
            QPushButton#Primary {
                background: #f7f7f2;
                color: #080808;
                border-color: #f7f7f2;
            }
            QPushButton#Primary:hover {
                background: #dcdcd4;
            }
            QLineEdit {
                background: #080808;
                color: #f7f7f2;
                border: 1px solid rgba(255,255,255,0.16);
                border-radius: 12px;
                padding: 13px 14px;
            }
            QLineEdit:focus {
                border-color: #f7f7f2;
            }
            QRadioButton, QCheckBox {
                spacing: 10px;
                font-weight: 700;
            }
            QTextEdit {
                background: #070707;
                color: #deded8;
                border: 1px solid rgba(255,255,255,0.14);
                border-radius: 14px;
                padding: 12px;
                font-family: "Cascadia Code", Consolas;
                font-size: 12px;
            }
            """
        )

    def _build(self) -> None:
        root_layout = QHBoxLayout(self)
        root_layout.setContentsMargins(18, 18, 18, 18)
        root_layout.setSpacing(18)

        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(280)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(22, 24, 22, 24)
        sidebar_layout.setSpacing(12)

        brand = QLabel("Wispr MR")
        brand.setObjectName("Brand")
        sidebar_layout.addWidget(brand)
        sidebar_layout.addSpacing(20)
        for index, (title, subtitle) in enumerate(self.steps, start=1):
            step_label = QLabel(f"{index:02d}  {title}\n     {subtitle}")
            step_label.setProperty("class", "Step")
            step_label.setWordWrap(True)
            sidebar_layout.addWidget(step_label)
            self.step_labels.append(step_label)
        sidebar_layout.addStretch()

        panel = QFrame()
        panel.setObjectName("Panel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(34, 30, 34, 26)
        panel_layout.setSpacing(22)

        self.pages.addWidget(self._welcome_page())
        self.pages.addWidget(self._location_page())
        self.pages.addWidget(self._profile_page())
        self.pages.addWidget(self._options_page())
        self.pages.addWidget(self._install_page())
        panel_layout.addWidget(self.pages, 1)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.back_button.clicked.connect(self._previous_step)
        self.next_button.clicked.connect(self._next_step)
        self.install_button.clicked.connect(self._start_install)
        self.quit_button.clicked.connect(self.close)
        self.next_button.setObjectName("Primary")
        self.install_button.setObjectName("Primary")
        actions.addWidget(self.back_button)
        actions.addWidget(self.quit_button)
        actions.addStretch()
        actions.addWidget(self.next_button)
        actions.addWidget(self.install_button)
        panel_layout.addLayout(actions)

        root_layout.addWidget(sidebar)
        root_layout.addWidget(panel, 1)

    def _page(self, title: str, subtitle: str) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)
        title_label = QLabel(title)
        title_label.setObjectName("Title")
        title_label.setWordWrap(True)
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("Subtitle")
        subtitle_label.setWordWrap(True)
        layout.addWidget(title_label)
        layout.addWidget(subtitle_label)
        return page

    def _card(self, title: str, body: str, control: QWidget | None = None) -> QFrame:
        card = QFrame()
        card.setProperty("class", "Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(8)
        if control:
            layout.addWidget(control)
        else:
            title_label = QLabel(title)
            title_label.setFont(QFont("Segoe UI", 12, QFont.Bold))
            layout.addWidget(title_label)
        body_label = QLabel(body)
        body_label.setObjectName("Muted")
        body_label.setWordWrap(True)
        layout.addWidget(body_label)
        return card

    def _welcome_page(self) -> QWidget:
        page = self._page(
            "Installe Wispr MR en 2 minutes.",
            "Un wizard moderne, une chose a faire par ecran. Garde les choix recommandes si tu veux aller vite.",
        )
        layout = page.layout()
        assert layout is not None
        layout.addWidget(self._card("Local-first", "Les fichiers sont installes localement. Pas de compte, pas d'API payante."))
        layout.addWidget(self._card("Raccourci global", "Tu maintiens le raccourci, tu parles, Wispr MR colle le texte dans l'app active."))
        layout.addWidget(self._card("Reparable", "Tu peux relancer l'installer plus tard : il remplace proprement l'installation precedente."))
        layout.addStretch()
        return page

    def _location_page(self) -> QWidget:
        page = self._page(
            "Choisis le dossier.",
            "Le dossier local par defaut est recommande. Evite OneDrive et les dossiers reseau.",
        )
        layout = page.layout()
        assert layout is not None
        row = QHBoxLayout()
        row.addWidget(self.install_path, 1)
        browse_button = QPushButton("Choisir")
        browse_button.clicked.connect(self._choose_dir)
        row.addWidget(browse_button)
        layout.addLayout(row)
        layout.addWidget(self._card("Pourquoi local ?", "Les modeles et dependances demarrent plus vite depuis un disque local utilisateur."))
        layout.addStretch()
        return page

    def _profile_page(self) -> QWidget:
        page = self._page(
            "Choisis le profil.",
            "Tu peux changer ce choix plus tard dans config.yaml. Balanced est le meilleur point de depart.",
        )
        layout = page.layout()
        assert layout is not None
        button_group = QButtonGroup(self)
        for title, value, body in (
            ("Balanced - recommande", "balanced", "Bon compromis vitesse / precision pour mails, notes, meetings et usage quotidien."),
            ("Fast", "fast", "Plus rapide et leger. Ideal sur PC modeste ou si tu veux une latence minimale."),
            ("Quality", "quality", "Plus precis mais plus lourd. Ideal sur machine puissante ou pour longues dictées."),
        ):
            radio = QRadioButton(title)
            radio.setChecked(value == "balanced")
            self.profile_buttons[value] = radio
            button_group.addButton(radio)
            layout.addWidget(self._card(title, body, radio))
        layout.addStretch()
        return page

    def _options_page(self) -> QWidget:
        page = self._page(
            "Dernieres options.",
            "Garde tout coche pour une installation fluide. Decoche seulement si ton environnement l'exige.",
        )
        layout = page.layout()
        assert layout is not None
        options = (
            (self.install_ollama, "Active le polishing local avec un modele separe quand c'est possible."),
            (self.autostart, "Wispr MR se lance avec Windows pour etre disponible sans y penser."),
            (self.launch, "L'application s'ouvre a la fin pour verifier immediatement que tout marche."),
        )
        for checkbox, body in options:
            layout.addWidget(self._card(checkbox.text(), body, checkbox))
        layout.addStretch()
        return page

    def _install_page(self) -> QWidget:
        page = self._page(
            "Pret a installer.",
            "Clique sur Installer. Le terminal PowerShell reste cache ; tu suis tout depuis cette fenetre.",
        )
        layout = page.layout()
        assert layout is not None
        layout.addWidget(self._summary_card())
        self.log_box.setReadOnly(True)
        layout.addWidget(self.log_box, 1)
        return page

    def _summary_card(self) -> QFrame:
        self.summary_label = QLabel()
        self.summary_label.setObjectName("Muted")
        self.summary_label.setWordWrap(True)
        card = QFrame()
        card.setProperty("class", "Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 16)
        title = QLabel("Resume")
        title.setFont(QFont("Segoe UI", 12, QFont.Bold))
        layout.addWidget(title)
        layout.addWidget(self.summary_label)
        return card

    def _choose_dir(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Choisir le dossier", str(default_install_dir().parent))
        if selected:
            self.install_path.setText(selected)

    def _selected_profile(self) -> str:
        for profile, button in self.profile_buttons.items():
            if button.isChecked():
                return profile
        return "balanced"

    def _update_summary(self) -> None:
        if not hasattr(self, "summary_label"):
            return
        self.summary_label.setText(
            f"Dossier : {self.install_path.text()}\n"
            f"Profil : {self._selected_profile()}\n"
            f"Ollama : {'oui' if self.install_ollama.isChecked() else 'non'} | "
            f"Autostart : {'oui' if self.autostart.isChecked() else 'non'} | "
            f"Lancement final : {'oui' if self.launch.isChecked() else 'non'}"
        )

    def _show_step(self, index: int) -> None:
        self.current_step = max(0, min(index, self.pages.count() - 1))
        self.pages.setCurrentIndex(self.current_step)
        for step_index, label in enumerate(self.step_labels):
            label.setProperty("class", "StepActive" if step_index == self.current_step else "Step")
            label.style().unpolish(label)
            label.style().polish(label)
        self._update_summary()
        self._update_actions()

    def _update_actions(self) -> None:
        running = self.worker is not None and self.worker.isRunning()
        self.back_button.setEnabled(self.current_step > 0 and not running)
        self.next_button.setVisible(self.current_step < self.pages.count() - 1)
        self.install_button.setVisible(self.current_step == self.pages.count() - 1)
        self.next_button.setEnabled(not running)
        self.install_button.setEnabled(not running)
        self.quit_button.setEnabled(not running)

    def _next_step(self) -> None:
        self._show_step(self.current_step + 1)

    def _previous_step(self) -> None:
        self._show_step(self.current_step - 1)

    def _start_install(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            return
        self.log_box.clear()
        self._append_log("Demarrage de l'installation...")
        self.worker = InstallWorker(
            install_dir=Path(self.install_path.text()),
            profile=self._selected_profile(),
            install_ollama=self.install_ollama.isChecked(),
            autostart=self.autostart.isChecked(),
            launch=self.launch.isChecked(),
        )
        self.worker.log.connect(self._append_log)
        self.worker.finished_ok.connect(self._install_finished)
        self.worker.failed.connect(self._install_failed)
        self.worker.finished.connect(self._update_actions)
        self.worker.start()
        self._update_actions()

    def _append_log(self, message: str) -> None:
        self.log_box.append(message)

    def _install_finished(self) -> None:
        self._update_actions()
        QMessageBox.information(self, APP_NAME, "Wispr MR est installe.")

    def _install_failed(self, message: str) -> None:
        self._update_actions()
        QMessageBox.critical(self, APP_NAME, message)


def main() -> int:
    app = QApplication(sys.argv)
    window = InstallerApp()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
