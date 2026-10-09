import logging
from datetime import date

from backend.app.data.updater import DataUpdater
from backend.app.db.session import initialize_database

logging.basicConfig(level=logging.INFO)


def main():
    print("Initializing database...")
    initialize_database()

    updater = DataUpdater()
    print("Running updater for FPT...")
    try:
        updater.refresh_all(["FPT"], date.today())
        print("Data layer phase 2 test completed successfully.")
    except Exception as e:
        print(f"Test failed: {e}")


if __name__ == "__main__":
    main()
