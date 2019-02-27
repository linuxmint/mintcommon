#!/usr/bin/python3

import shlex
import subprocess
import sys


def get_version(pkg_name):
    try:
        (status, version) = subprocess.getstatusoutput("/usr/bin/dpkg-query -f '${Version}' -W %s" % shlex.quote(pkg_name))
        if status == 0 and version is not None:
            return version
        else:
            return ""
    except:
        return ""

if __name__ == "__main__":
    if len(sys.argv) == 2:
        print(get_version(sys.argv[1]))
    else:
        print ("")