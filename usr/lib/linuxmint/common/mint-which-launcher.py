#!/usr/bin/python

import os
import sys
import gettext

gettext.install("mint-common", "/usr/share/linuxmint/locale")

if len( sys.argv ) == 2:
    message = sys.argv[1]
else:
    message = _("Please enter your password")

launcher = "gksu  --message \"<b>" + message + "</b>\""
if os.path.exists("/etc/linuxmint/info"):
	sys.path.append('/usr/lib/linuxmint/common')
	from configobj import ConfigObj
	config = ConfigObj("/etc/linuxmint/info")
	if (config['DESKTOP'] == "KDE"):
		launcher = "kdesudo -i /usr/share/linuxmint/logo.png -d --comment \"<b>" + message + "</b>\""

print launcher



