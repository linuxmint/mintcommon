#!/usr/bin/python3

import os
import gettext
import re
from xml.sax.saxutils import escape, unescape

def strip_split_and_recombine(comma_separated):
    word_list = comma_separated.split(",")
    out = ""
    for item in word_list:
        out += item.strip()
        out+=";"

    return out

def generate(domain, path, filename, prefix, name, comment, suffix, genericName=None, keywords=None, append=False):
    if append:
        desktopFile = open(filename, "a")
    else:
        desktopFile = open(filename, "w")

    desktopFile.writelines(prefix)

    desktopFile.writelines("Name=%s\n" % name)
    for directory in sorted(os.listdir(path)):
        mo_file = os.path.join(path, directory, "LC_MESSAGES", "%s.mo" % domain)
        if os.path.exists(mo_file):
            try:
                language = gettext.translation(domain, path, languages=[directory])
                L_ = language.gettext
                if (L_(name) != name):
                    desktopFile.writelines("Name[%s]=%s\n" % (directory, L_(name)))
            except:
                pass

    if comment is not None:
        desktopFile.writelines("Comment=%s\n" % comment)
        for directory in sorted(os.listdir(path)):
            mo_file = os.path.join(path, directory, "LC_MESSAGES", "%s.mo" % domain)
            if os.path.exists(mo_file):
                try:
                    language = gettext.translation(domain, path, languages=[directory])
                    L_ = language.gettext
                    if (L_(comment) != comment):
                        desktopFile.writelines("Comment[%s]=%s\n" % (directory, L_(comment)))
                except:
                    pass

    if keywords is not None:
        formatted = strip_split_and_recombine(keywords)
        desktopFile.writelines("Keywords=%s\n" % formatted)
        for directory in sorted(os.listdir(path)):
            mo_file = os.path.join(path, directory, "LC_MESSAGES", "%s.mo" % domain)
            if os.path.exists(mo_file):
                try:
                    language = gettext.translation(domain, path, languages=[directory])
                    L_ = language.gettext
                    if (L_(keywords) != keywords):
                        translated = strip_split_and_recombine(L_(keywords))
                        desktopFile.writelines("Keywords[%s]=%s\n" % (directory, translated))
                except:
                    pass

    if genericName is not None:
        desktopFile.writelines("GenericName=%s\n" % genericName)
        for directory in sorted(os.listdir(path)):
            mo_file = os.path.join(path, directory, "LC_MESSAGES", "%s.mo" % domain)
            if os.path.exists(mo_file):
                try:
                    language = gettext.translation(domain, path, languages=[directory])
                    L_ = language.gettext
                    if (L_(genericName) != genericName):
                        desktopFile.writelines("GenericName[%s]=%s\n" % (directory, L_(genericName)))
                except:
                    pass

    desktopFile.writelines(suffix)
    desktopFile.close()

# Writes an xml element containing text, followed by one localized element
# for every locale that translates it.
def write_translated_element(xmlFile, domain, path, tag, text, indent=""):
    xmlFile.writelines("%s<%s>%s</%s>\n" % (indent, tag, escape(text), tag))

    for directory in sorted(os.listdir(path)):
        mo_file = os.path.join(path, directory, "LC_MESSAGES", "%s.mo" % domain)
        if os.path.exists(mo_file):
            try:
                language = gettext.translation(domain, path, languages=[directory])
                L_ = language.gettext
                if (L_(text) != text):
                    xmlFile.writelines("%s<%s xml:lang=\"%s\">%s</%s>\n" % (indent, tag, directory, escape(L_(text)), tag))
            except:
                pass

def generate_polkit_policy(domain, path, filename, prefix, message, suffix, append=False):
    if append:
        policyFile = open(filename, "a")
    else:
        policyFile = open(filename, "w")

    policyFile.writelines(prefix)

    write_translated_element(policyFile, domain, path, "message", message)

    policyFile.writelines(suffix)
    policyFile.close()

MIME_COMMENT = re.compile(r"^(\s*)<_comment>(.*)</_comment>\s*$")

# Copies a shared-mime-info file, expanding each intltool-style <_comment>
# into a plain <comment> plus a localized one per translation.
def generate_mime_file(domain, path, infilename, outfilename):
    inFile = open(infilename)
    mimeFile = open(outfilename, "w")

    for line in inFile:
        match = MIME_COMMENT.match(line)
        if match is None:
            mimeFile.writelines(line)
        else:
            indent, comment = match.groups()
            write_translated_element(mimeFile, domain, path, "comment", unescape(comment), indent)

    mimeFile.close()
    inFile.close()
