#!/usr/bin/python3

import os
import sys

if __name__ == "__main__":

    # Exit if the given path does not exist
    if len(sys.argv) < 2 or not os.path.exists(sys.argv[1]):
        print("No argument or file not found")
        sys.exit(1)

    path = sys.argv[1]
    dpath = f"{path}.desktop"
    if not os.path.exists(path):
        if os.path.exists(dpath):
            path = dpath
        else:
            print("Path not found", path)
            sys.exit(1)

    os.remove(path)
