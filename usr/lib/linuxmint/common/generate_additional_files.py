#!/usr/bin/python

import os, gettext

DOMAIN = "mint-common"
PATH = "/usr/share/linuxmint/locale"

def generate(filename, prefix, name, comment, suffix):
    print "HERE"
    os.environ['LANG'] = "en_US.UTF-8"
    gettext.install(DOMAIN, PATH)
    desktopFile = open(filename, "w")

    desktopFile.writelines(prefix)

    desktopFile.writelines("Name=%s\n" % name)
    print ("Name=%s\n" % name)
    for directory in sorted(os.listdir(PATH)):
        if os.path.isdir(os.path.join(PATH, directory)):
            try:
                language = gettext.translation(DOMAIN, PATH, languages=[directory])
                language.install()
                if (_(name) != name):
                    desktopFile.writelines("Name[%s]=%s\n" % (directory, _(name)))
                    print ("Name[%s]=%s\n" % (directory, _(name)))
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

