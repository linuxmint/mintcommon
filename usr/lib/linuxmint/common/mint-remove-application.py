#!/usr/bin/python3

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk

import sys
import os
import gettext
import subprocess

from pathlib import Path
from xapp.pkgCache import installer

# i18n
gettext.install("mint-common", "/usr/share/linuxmint/locale")

class MintRemoveWindow:
    def __init__(self, desktopFile):
        self.desktopFile = desktopFile

        self.installer = installer.Installer().init(self.on_installer_ready)

    def on_installer_ready(self):
        pkg_name = None

        pkg_name = self.get_apt_name()

        if pkg_name == None:
            pkg_name = self.get_fp_name()

        if pkg_name == None:
            self.do_no_packages_dialog()

        pkginfo = self.installer.find_pkginfo(pkg_name)

        if pkginfo and self.installer.pkginfo_is_installed(pkginfo):
            self.installer.select_pkginfo(pkginfo, self.on_installer_ready_to_remove)
        else:
            self.do_no_packages_dialog()

    def on_installer_ready_to_remove(self, task):
        self.installer.execute_task(task, self.on_finished)

    def do_no_packages_dialog(self):
        warnDlg = Gtk.MessageDialog(None, 0, Gtk.MessageType.WARNING, Gtk.ButtonsType.YES_NO, _("This menu item is not associated to any package. Do you want to remove it from the menu anyway?"))
        warnDlg.get_widget_for_response(Gtk.ResponseType.YES).grab_focus()
        warnDlg.vbox.set_spacing(10)

        response = warnDlg.run()

        if response == Gtk.ResponseType.YES:
            print ("removing '%s'" % self.desktopFile)
            os.system("rm -f '%s'" % self.desktopFile)
            os.system("rm -f '%s.desktop'" % self.desktopFile)

        warnDlg.destroy()
        sys.exit(0)

    def get_apt_name(self):
        (status, output) = subprocess.getstatusoutput("dpkg -S " + self.desktopFile)
        package = output[:output.find(":")].split(",")[0]

        if status == 0:
            return package
        else:
            return None

    def get_fp_name(self):
        path = Path(self.desktopFile)

        if "flatpak" not in path.parts:
            return None

        return path.stem

    def on_finished(self, transaction=None, exit_state=None):
        sys.exit(0)

if __name__ == "__main__":

    # Exit if the given path does not exist
    if len(sys.argv) < 2 or not os.path.exists(sys.argv[1]):
        sys.exit(1)

    mainwin = MintRemoveWindow(sys.argv[1])
    Gtk.main()
