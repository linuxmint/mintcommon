#!/usr/bin/python2

import os
import gettext

def strip_split_and_recombine(comma_separated):
    word_list = comma_separated.split(",")
    out = ""
    for item in word_list:
        out += item.strip()
        out+=";"

    return out

def generate(domain, path, filename, prefix, name, comment, suffix, genericName=None, keywords=None, append=False):
    os.environ['LANGUAGE'] = "en_US.UTF-8"
    gettext.install(domain, path)
    if append:
        desktopFile = open(filename, "a")
    else:
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

    if comment is not None:
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

    if keywords is not None:
        formatted = strip_split_and_recombine(keywords)
        desktopFile.writelines("Keywords=%s\n" % formatted)
        for directory in sorted(os.listdir(path)):
            if os.path.isdir(os.path.join(path, directory)):
                try:
                    language = gettext.translation(domain, path, languages=[directory])
                    language.install()
                    if (_(keywords) != keywords):
                        translated = strip_split_and_recombine(_(keywords))
                        desktopFile.writelines("Keywords[%s]=%s\n" % (directory, translated))
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
    os.environ['LANGUAGE'] = "en_US.UTF-8"
    gettext.install(domain, path)
