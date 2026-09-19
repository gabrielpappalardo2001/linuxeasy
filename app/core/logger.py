import os
import sys
import logging

def setup_app_dir_and_logging():
    home_dir = os.path.expanduser("~")
    app_dir = os.path.join(home_dir, ".config", "linux_easy")
    os.makedirs(app_dir, exist_ok=True)
    
    log_file = os.path.join(app_dir, "error.log")
    
    logging.basicConfig(
        filename=log_file,
        level=logging.ERROR,
        format="%(asctime)s - %(levelname)s - %(message)s"
    )

    def handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        logging.error("Eccezione non gestita:", exc_info=(exc_type, exc_value, exc_traceback))

    sys.excepthook = handle_exception
    return app_dir