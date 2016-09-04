#!/usr/bin/python3

import subprocess
import sys

try:
    version = subprocess.getoutput("dpkg-query -W %s 2>/dev/null | cut -f2" % sys.argv[1])
    if version is not None:
        print (version)
    else:
        print ("")
except:
    print ("")
