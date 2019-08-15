#!/usr/bin/python3

import gettext
import os
import subprocess
import sys

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk

import mintcommon.aptdaemon

# i18n
gettext.install("mint-common", "/usr/share/linuxmint/locale")

class MintRemoveWindow:

    def __init__(self, desktopFile):
        self.desktopFile = desktopFile
        process = subprocess.run(["dpkg", "-S", self.desktopFile], stdout=subprocess.PIPE)
        output = process.stdout.decode("utf-8")
        package = output[:output.find(":")].split(",")[0]
        if process.returncode != 0:
            if not self.try_remove_flatpak(desktopFile):
                warnDlg = Gtk.MessageDialog(None, 0, Gtk.MessageType.WARNING, Gtk.ButtonsType.YES_NO, _("This menu item is not associated to any package. Do you want to remove it from the menu anyway?"))
                warnDlg.set_keep_above(True)

                warnDlg.get_widget_for_response(Gtk.ResponseType.YES).grab_focus()
                warnDlg.vbox.set_spacing(10)
                response = warnDlg.run()
                if response == Gtk.ResponseType.YES:
                    print ("removing '%s'" % self.desktopFile)
                    subprocess.run(["rm", "-f", self.desktopFile])
                    subprocess.run(["rm", "-f", "%s.desktop" % self.desktopFile])
                warnDlg.destroy()

            sys.exit(0)

        warnDlg = Gtk.MessageDialog(None, 0, Gtk.MessageType.WARNING, Gtk.ButtonsType.OK_CANCEL, _("The following packages will be removed:"))
        warnDlg.set_keep_above(True)

        warnDlg.get_widget_for_response(Gtk.ResponseType.OK).grab_focus()
        warnDlg.vbox.set_spacing(10)

        treeview = Gtk.TreeView()
        column1 = Gtk.TreeViewColumn(_("Packages to be removed"))
        renderer = Gtk.CellRendererText()
        column1.pack_start(renderer, False)
        column1.add_attribute(renderer, "text", 0)
        treeview.append_column(column1)

        packages = []
        model = Gtk.ListStore(str)
        dependenciesString = subprocess.getoutput("apt-get -s -q remove " + package + " | grep Remv")
        dependencies = dependenciesString.split("\n")
        for dependency in dependencies:
            dependency = dependency.replace("Remv ", "")
            model.append([dependency])
            packages.append(dependency.split()[0])
        treeview.set_model(model)
        treeview.show()

        scrolledwindow = Gtk.ScrolledWindow()
        scrolledwindow.set_shadow_type(Gtk.ShadowType.ETCHED_OUT)
        scrolledwindow.set_size_request(150, 150)
        scrolledwindow.add(treeview)
        scrolledwindow.show()

        warnDlg.get_content_area().add(scrolledwindow)

        self.apt = mintcommon.aptdaemon.APT(warnDlg)

        response = warnDlg.run()
        if response == Gtk.ResponseType.OK:
            self.apt.set_finished_callback(self.on_finished)
            self.apt.remove_packages(packages)
        elif response == Gtk.ResponseType.CANCEL:
            sys.exit(0)

        warnDlg.destroy()

    def try_remove_flatpak(self, desktopFile):
        if not "flatpak" in desktopFile:
            return False

        if not os.path.exists('/usr/bin/mintinstall-remove-app'):
            return False

        flatpak_remover = subprocess.Popen(['/usr/bin/mintinstall-remove-app', desktopFile])
        retcode = flatpak_remover.wait()

        return retcode == 0

    def on_finished(self, transaction=None, exit_state=None):
        sys.exit(0)

if __name__ == "__main__":

    # Exit if the given path does not exist
    if len(sys.argv) < 2 or not os.path.exists(sys.argv[1]):
        sys.exit(1)

    mainwin = MintRemoveWindow(sys.argv[1])
    Gtk.main()
