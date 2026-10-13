# SPDX-FileCopyrightText: 2026 cin330
# SPDX-License-Identifier: AGPL-3.0-only

import sys

from PySide6.QtWidgets import QApplication

from gui.gui import Traffic_monitor


if __name__ == "__main__":

    app = QApplication(sys.argv)

    window = Traffic_monitor()

    window.show()

    sys.exit(app.exec())