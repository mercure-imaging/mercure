from common.credentials import load_credentials
load_credentials()
from bookkeeping.bookkeeper import main

if __name__ == "__main__":
    main()
