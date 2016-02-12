#!/usr/bin/python2

import sys
import os
import commands

link = ' '.join(sys.argv[1:])
link = link.replace("\"", "")
link = "\"" + link + "\""

if os.path.exists("/usr/bin/gconftool-2"):
    browser = commands.getoutput("gconftool-2 --get /desktop/gnome/url-handlers/http/command")
    browser = browser.replace("\"%s\"", link)
    browser = browser.replace("%s", link)
else:
    browser = "firefox " + link

os.system(browser + " &")
