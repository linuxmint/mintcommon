def localized_gladefile(gladefile, gettext):
    """ Returns localized contents of gladefile

    Parameters:
        gladefile: Path to glade file
        gettext: Callback to gettext.gettext() / _()

    Workaround for Gtk.Builder/GLib.dgettext creating encoding issues in non-UTF-8
    environments. It translates all translatable strings in the gladefile via the
    gettext callback before you pass it to Gtk.Builder.

    Usage:
        builder = Gtk.Builder.new_from_string(localized_gladefile(gladefile, _), -1)
    """
    from xml.etree import ElementTree
    tree = ElementTree.parse(gladefile)
    for node in tree.iter():
        if "translatable" in node.attrib:
            del node.attrib["translatable"]
            node.text = gettext(node.text)
    return ElementTree.tostring(tree.getroot(), encoding="unicode", method="xml")
