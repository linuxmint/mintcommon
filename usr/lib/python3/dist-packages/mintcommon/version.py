#!/usr/bin/python3

import subprocess
import sys


def get_version(pkg_name):
    try:
        return subprocess.run(["/usr/bin/dpkg-query", "-Wf", "${Version}", pkg_name],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout.decode()
    except:
        return ""

if __name__ == "__main__":
    if len(sys.argv) == 2:
        print(get_version(sys.argv[1]))
    else:
        print ("")
