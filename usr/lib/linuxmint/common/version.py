#!/usr/bin/python3

import shlex
import subprocess
import sys

try:
    (status, version) = subprocess.getstatusoutput("/usr/bin/dpkg-query -f '${Version}' -W %s" % shlex.quote(sys.argv[1]))
    if status == 0 and version is not None:
        print (version)
    else:
        print ("")
except:
    print ("")

