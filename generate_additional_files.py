#!/usr/bin/python

import os, gettext

DOMAIN = "mint-common"
PATH = "/usr/share/linuxmint/locale"

def generate(filename, prefix, name, comment, suffix):
    gettext.install(DOMAIN, PATH)
    desktopFile = open(filename, "w")

    desktopFile.writelines(prefix)

    desktopFile.writelines("Name=%s\n" % name)
    for directory in sorted(os.listdir(PATH)):
        if os.path.isdir(os.path.join(PATH, directory)):
            try:
                language = gettext.translation(DOMAIN, PATH, languages=[directory])
                language.install()
                if (_(name) != name):
                    desktopFile.writelines("Name[%s]=%s\n" % (directory, _(name)))
            except:
                pass

    desktopFile.writelines("Comment=%s\n" % comment)
    for directory in sorted(os.listdir(PATH)):
        if os.path.isdir(os.path.join(PATH, directory)):
            try:
                language = gettext.translation(DOMAIN, PATH, languages=[directory])
                language.install()
                if (_(comment) != comment):
                    desktopFile.writelines("Comment[%s]=%s\n" % (directory, _(comment)))
            except:
                pass

    desktopFile.writelines(suffix)

prefix = "[Nemo Action]\n"

suffix = """Exec=thunderbird -compose to=,\"attachment='%F'\"
Stock-Id=gtk-dnd-multiple
Selection=NotNone
Extensions=nodirs;
Dependencies=thunderbird;
Separator=,
"""

gettext.install(DOMAIN, PATH)
generate("usr/share/nemo/actions/mint-artwork-cinnamon-thunderbird.nemo_action", prefix, _("Send by Email"), _("Send as email attachment"), suffix)
