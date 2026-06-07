from __future__ import annotations

import sys

from PyQt6.QtCore import QThread
from PyQt6.QtWidgets import QApplication

from agama_cashu import CashuWorker
from cashu_ui import MainWindow


def main() -> int:
    app = QApplication(sys.argv)

    worker_thread = QThread()
    worker = CashuWorker()
    worker.moveToThread(worker_thread)

    window = MainWindow()
    window.action_requested.connect(worker.run_action)
    window.mint_requested.connect(worker.set_mint)
    window.debug_changed.connect(worker.set_debug)
    worker.log_signal.connect(window.append_debug)
    worker.status_signal.connect(window.set_status)
    worker.data_signal.connect(window.update_view)
    worker.mints_signal.connect(window.set_mints)
    worker.mint_index_signal.connect(window.set_mint_index)
    worker_thread.started.connect(worker.initialize)

    app.aboutToQuit.connect(worker_thread.quit)
    worker_thread.finished.connect(worker.deleteLater)

    worker_thread.start()
    window.show()
    exit_code = app.exec()
    worker_thread.wait(3000)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
