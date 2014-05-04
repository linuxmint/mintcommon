#!/usr/bin/python

import os, gettext

def generate(domain, path, filename, prefix, name, comment, suffix, genericName=None):
    gettext.install(domain, path)
    desktopFile = open(filename, "w")

    desktopFile.writelines(prefix)

    desktopFile.writelines("Name=%s\n" % name)
    for directory in sorted(os.listdir(path)):
        if os.path.isdir(os.path.join(path, directory)):
            try:
                language = gettext.translation(domain, path, languages=[directory])
                language.install()
                if (_(name) != name):
                    desktopFile.writelines("Name[%s]=%s\n" % (directory, _(name)))
            except:
                pass

    desktopFile.writelines("Comment=%s\n" % comment)
    for directory in sorted(os.listdir(path)):
        if os.path.isdir(os.path.join(path, directory)):
            try:
                language = gettext.translation(domain, path, languages=[directory])
                language.install()
                if (_(comment) != comment):
                    desktopFile.writelines("Comment[%s]=%s\n" % (directory, _(comment)))
            except:
                pass
        
    if genericName is not None:
        desktopFile.writelines("GenericName=%s\n" % genericName)
        for directory in sorted(os.listdir(path)):
            if os.path.isdir(os.path.join(path, directory)):
                try:
                    language = gettext.translation(domain, path, languages=[directory])
                    language.install()
                    if (_(genericName) != genericName):
                        desktopFile.writelines("GenericName[%s]=%s\n" % (directory, _(genericName)))
                except:
                    pass

    desktopFile.writelines(suffix)
    os.environ['LANG'] = "en_US.UTF-8"
    gettext.install(domain, path)

