#!/usr/bin/python

import os
import sys
import gettext

gettext.install("mint-common", "/usr/share/linuxmint/locale")

launcher = "gksu  --message \"<b>" + _("Please enter your password") + "</b>\""
if os.path.exists("/etc/linuxmint/info"):
	sys.path.append('/usr/lib/linuxmint/common')
	from configobj import ConfigObj
	config = ConfigObj("/etc/linuxmint/info")
	if (config['DESKTOP'] == "KDE"):
		launcher = "kdesudo -i /usr/share/linuxmint/logo.png -d --comment \"<b>" + _("Please enter your password") + "</b>\""

print launcher



