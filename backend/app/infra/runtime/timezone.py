"""Keep process-local clocks aligned with the application's calendar timezone."""

import os
import time

from app.entities.defaults import APP_TIMEZONE_NAME


def configure_process_timezone() -> None:
    os.environ["TZ"] = APP_TIMEZONE_NAME
    if hasattr(time, "tzset"):
        time.tzset()
