import sys

from codedna.cli import main

# The guard matters: worker processes started with "spawn" (always the case on Windows)
# import this module again, and must not run the command line a second time.
if __name__ == "__main__":
    sys.exit(main())
