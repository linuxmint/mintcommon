#!/usr/bin/python

import os, gettext, sys
sys.path.append('/usr/lib/linuxmint/common')
import additionalfiles

DOMAIN = "mint-common"
PATH = "/usr/share/linuxmint/locale"

prefix = "[Nemo Action]\n"

suffix = """Exec=thunderbird -compose to=,\"attachment='%F'\"
Icon-Name=mail-attachment
Selection=NotNone
Extensions=nodirs;
Dependencies=thunderbird;
Separator=,
"""

os.environ['LANG'] = "en_US.UTF-8"
gettext.install(DOMAIN, PATH)
additionalfiles.generate(DOMAIN, PATH, "usr/share/nemo/actions/mint-artwork-cinnamon-thunderbird.nemo_action", prefix, _("Send by Email"), _("Send as email attachment"), suffix)
