import gi
gi.require_version('XApp', '1.0')
from gi.repository import GLib, Gtk, GObject, Gdk, XApp, Pango

import gettext
APP = 'mint-common'
LOCALE_DIR = "/usr/share/linuxmint/locale"
t = gettext.translation(APP, LOCALE_DIR, fallback=True)
_ = t.gettext

from aptdaemon.gtk3widgets import AptConfirmDialog

######################### Subclass Apt's dialog to keep consistency

class ChangesConfirmDialog(AptConfirmDialog):

    """Dialog to confirm the changes that would be required by a
    transaction.
    """

    def __init__(self, transaction, task=None, parent=None):
        super(ChangesConfirmDialog, self).__init__(transaction, cache=None, parent=parent)
        self.parent_window = parent
        self.set_size_request(500, 350)
        self.task = task

    def _show_changes(self):
        """Show a message and the dependencies in the dialog."""
        self.treestore.clear()
        if not self.parent_window:
            self.set_skip_taskbar_hint(True)
            self.set_keep_above(True)

        # Run parent method for apt
        if not self.task or (self.task.pkginfo and self.task.pkginfo.pkg_hash.startswith("a")):
            """Show a message and the dependencies in the dialog."""
            self.treestore.clear()
            for pkg_list, msg, min_packages in (
                                  [self.task.to_install,      _("Install"), 1 if self.task.type == self.task.INSTALL_TASK else 0],
                                  [self.task.to_reinstall,    _("Reinstall"), 0],
                                  [self.task.to_remove,       _("Remove"), 1 if self.task.type == self.task.UNINSTALL_TASK else 0],
                                  [self.task.to_purge,        _("Purge"), 0],
                                  [self.task.to_update,       _("Upgrade"), 0],
                                  [self.task.to_downgrade,    _("Downgrade"), 0],
                                  [self.task.to_skip_upgrade, _("Skip upgrade"), 0]
                                 ):

                if len(pkg_list) > min_packages:
                    piter = self.treestore.append(None, ["<b>%s</b>" % msg])

                    for pkg in pkg_list:
                        if pkg_list == self.task.to_install and pkg.get_name() == self.task.name:
                            continue

                        self.treestore.append(piter, [pkg.get_name()])
            # If there is only one type of changes (e.g. only installs) expand the
            # tree
            # FIXME: adapt the title and message accordingly
            # FIXME: Should we have different modes? Only show dependencies, only
            #       initial packages or both?
            msg = _("Please take a look at the list of changes below.")
            if len(self.treestore) == 1:
                filtered_store = self.treestore.filter_new(Gtk.TreePath.new_first())
                self.treeview.expand_all()
                self.treeview.set_model(filtered_store)
                self.treeview.set_show_expanders(False)
                if len(self.task.to_install) > 1:
                    title = _("Additional software will be installed")
                elif len(self.task.to_reinstall) > 0:
                    title = _("Additional software will be re-installed")
                elif len(self.task.to_remove) > 0:
                    title = _("Additional software will be removed")
                elif len(self.task.to_purge) > 0:
                    title = _("Additional software will be purged")
                elif len(self.task.to_update) > 0:
                    title = _("Additional software will be upgraded")
                elif len(self.task.to_downgrade) > 0:
                    title = _("Additional software will be downgraded")
                elif len(self.task.to_skip_upgrade) > 0:
                    title = _("Updates will be skipped")
                if len(filtered_store) < 6:
                    self.set_resizable(False)
                    self.scrolled.set_policy(Gtk.PolicyType.AUTOMATIC,
                                             Gtk.PolicyType.NEVER)
                else:
                    self.treeview.set_size_request(350, 200)
            else:
                title = _("Additional changes are required")
                self.treeview.set_size_request(350, 200)
                self.treeview.collapse_all()
            if self.task.download_size > 0:
                msg += "\n"
                msg += (_("%s will be downloaded in total.") %
                        GLib.format_size(self.task.download_size))
            if self.task.freed_size > 0:
                msg += "\n"
                msg += (_("%s of disk space will be freed.") %
                        GLib.format_size(self.task.freed_size))
            elif self.task.install_size > 0:
                msg += "\n"
                msg += (_("%s more disk space will be used.") %
                        GLib.format_size(self.task.install_size))
            self.label.set_markup("<b><big>%s</big></b>\n\n%s" % (title, msg))
        else:
            # flatpak
            self.set_title(_("Flatpaks"))

            min_packages = 1 if self.task.type == self.task.INSTALL_TASK else 0
            if len(self.task.to_install) > min_packages:
                piter = self.treestore.append(None, ["<b>%s</b>" % _("Install")])

                for ref in self.task.to_install:
                    if self.task.pkginfo and self.task.pkginfo.refid == ref.format_ref():
                        continue

                    self.treestore.append(piter, [ref.get_name()])

            min_packages = 1 if self.task.type == self.task.UNINSTALL_TASK else 0
            if len(self.task.to_remove) > min_packages:
                piter = self.treestore.append(None, ["<b>%s</b>" % _("Remove")])

                for ref in self.task.to_remove:
                    if self.task.pkginfo and self.task.pkginfo.refid == ref.format_ref():
                        continue

                    self.treestore.append(piter, [ref.get_name()])

            if len(self.task.to_update) > 0:
                # If this is an update task (like from mintupdate) we may have selected updates explicitly, and there may be
                # updates we *didn't* select but are required for an update we did. We only want to add those updates that
                # are pulled in the second case, since the updates we did select do not need to be displayed again (this is
                # following apt behavior, where we only list dependencies here and unexpected changes).
                header_added = False
                for ref in self.task.to_update:
                    if self.task.type == self.task.UPDATE_TASK:
                        if len(self.task.initial_refs_to_update) == 0 or ref.format_ref() in self.task.initial_refs_to_update:
                            continue

                    if not header_added:
                        piter = self.treestore.append(None, ["<b>%s</b>" % _("Upgrade")])
                        header_added = True

                    self.treestore.append(piter, [ref.get_name()])

            msg = _("Please take a look at the list of changes below.")

            if len(self.treestore) == 1:
                filtered_store = self.treestore.filter_new(
                    Gtk.TreePath.new_first())
                self.treeview.expand_all()
                self.treeview.set_model(filtered_store)
                self.treeview.set_show_expanders(False)

                if len(self.task.to_install) > 1:
                    title = _("Additional software will be installed")
                elif len(self.task.to_remove) > 0:
                    title = _("Additional software will be removed")
                elif len(self.task.to_update) > 0:
                    title = _("Additional software will be upgraded")

                if len(filtered_store) < 6:
                    self.set_resizable(False)
                    self.scrolled.set_policy(Gtk.PolicyType.AUTOMATIC,
                                             Gtk.PolicyType.NEVER)
                else:
                    self.treeview.set_size_request(350, 200)
            else:
                title = _("Additional changes are required")
                self.treeview.set_size_request(350, 200)
                self.treeview.collapse_all()

            if self.task.download_size > 0:
                msg += "\n"
                msg += (_("%s will be downloaded in total.") %
                        GLib.format_size(self.task.download_size))
            if self.task.freed_size > 0:
                msg += "\n"
                msg += (_("%s of disk space will be freed.") %
                        GLib.format_size(self.task.freed_size))
            elif self.task.install_size > 0:
                msg += "\n"
                msg += (_("%s more disk space will be used.") %
                        GLib.format_size(self.task.install_size))
            self.label.set_markup("<b><big>%s</big></b>\n\n%s" % (title, msg))

    def map_package(self, pkg):
        """Map a package to a different object type, e.g. applications
        and return a list of those.

        By default return the package itself inside a list.

        Override this method if you don't want to store package names
        in the treeview.
        """
        return [pkg]

    def render_package_desc(self, column, cell, model, iter, data):
        value = model.get_value(iter, 0)

        cell.set_property("markup", value)


class FlatpakProgressWindow(Gtk.Dialog):
    """
    Progress dialog for standalone flatpak installs, removals, updates.
    Intended to be used when not working as part of a parent app (like mintinstall)
    """

    def __init__(self, task, parent=None):
        Gtk.Dialog.__init__(self, parent=parent)
        self.set_default_size(400, 140)
        self.task = task
        self.finished = False

        # Progress goes directly to this window
        task.client_progress_cb = self.window_client_progress_cb

        # finished callbacks route thru the installer
        # but we want to see them in this window also.
        self.final_finished_cb = task.client_finished_cb
        task.client_finished_cb = self.window_client_finished_cb
        self.pulse_timer = 0

        self.real_progress_text = None

        # Setup the dialog
        self.set_border_width(6)
        self.set_resizable(False)
        self.get_content_area().set_spacing(6)
        # Setup the cancel button
        self.button = Gtk.Button.new_from_stock(Gtk.STOCK_CANCEL)
        self.button.set_use_stock(True)
        self.get_action_area().pack_start(self.button, False, False, 0)
        self.button.connect("clicked", self.on_button_clicked)
        self.button.show()

        # labels and progressbar
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        vbox.set_spacing(12)
        vbox.set_border_width(10)

        self.label = Gtk.Label(max_width_chars=45)
        vbox.pack_start(self.label, False, False, 0)
        self.label.set_halign(Gtk.Align.START)
        self.label.set_line_wrap(True)

        self.progress = Gtk.ProgressBar()
        vbox.pack_end(self.progress, False, True, 0)
        self.get_content_area().pack_start(vbox, True, True, 0)

        self.set_title(_("Flatpak"))
        XApp.set_window_icon_name(self, "system-software-installer")

        vbox.show_all()
        self.realize()

        self.progress.set_size_request(350, -1)
        functions = Gdk.WMFunction.MOVE | Gdk.WMFunction.RESIZE
        try:
            self.get_window().set_functions(functions)
        except TypeError:
            # workaround for older and broken GTK typelibs
            self.get_window().set_functions(Gdk.WMFunction(functions))

        # catch ESC and behave as if cancel was clicked
        self.connect("delete-event", self._on_dialog_delete_event)

    def start_progress_pulse(self):
        if self.pulse_timer > 0:
            return

        self.progress.pulse()
        self.pulse_timer = GObject.timeout_add(1050, self.progress_pulse_tick)

    def progress_pulse_tick(self):
        self.progress.pulse()

        return GLib.SOURCE_CONTINUE

    def stop_progress_pulse(self):
        if self.pulse_timer > 0:
            GObject.source_remove(self.pulse_timer)
            self.pulse_timer = 0

    def _on_dialog_delete_event(self, dialog, event):
        self.button.clicked()
        return True

    def window_client_progress_cb(self, pkginfo, progress, estimating, status_text):
        if estimating:
            self.start_progress_pulse()
        else:
            self.stop_progress_pulse()

            self.progress.set_fraction(progress / 100.0)
            XApp.set_window_progress(self, progress)

        self.label.set_text(status_text)

    def window_client_finished_cb(self, task):
        self.finished = True

        self.destroy()
        self.final_finished_cb(task)

    def on_button_clicked(self, button):
        if not self.finished:
            self.task.cancel()

def show_error(message, parent_window=None):
    Gdk.threads_add_idle(GLib.PRIORITY_DEFAULT_IDLE, _show_error_mainloop, message, parent_window)

def _show_error_mainloop(message, parent_window):
    dialog = Gtk.MessageDialog(None,
                               Gtk.DialogFlags.DESTROY_WITH_PARENT,
                               Gtk.MessageType.ERROR,
                               Gtk.ButtonsType.OK,
                               "")
    if parent_window is not None:
        dialog.set_transient_for(parent_window)
        dialog.set_modal(True)
    dialog.set_title(GLib.get_application_name())

    text = _("An error occurred")
    dialog.set_markup("<big><b>%s</b></big>" % text)

    scroller = Gtk.ScrolledWindow(min_content_height = 75, max_content_height=400, min_content_width=400, propagate_natural_height=True)
    dialog.get_message_area().pack_start(scroller, False, False, 8)

    message_label = Gtk.Label(message, lines=20, wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR, selectable=True)
    message_label.set_max_width_chars(60)
    message_label.show()
    scroller.add(message_label)

    dialog.show_all()
    dialog.run()
    dialog.destroy()

    return GLib.SOURCE_REMOVE

