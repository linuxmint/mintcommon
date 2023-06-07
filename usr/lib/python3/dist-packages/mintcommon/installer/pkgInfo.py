import sys
if sys.version_info.major < 3:
    raise "python3 required"
import os

import gi
gi.require_version("AppStreamGlib", "1.0")
gi.require_version("Gtk", "3.0")
from gi.repository import AppStreamGlib, Gtk

def capitalize(string):
    if string and len(string) > 1:
        return (string[0].upper() + string[1:])
    else:
        return (string)

class PkgInfo:
    def __init__(self, pkg_hash=None):
        # Saved stuff
        self.pkg_hash = None
        if pkg_hash:
            self.pkg_hash = pkg_hash

        self.name = None
        # some flatpak-specific things
        self.refid=""
        self.remote = ""
        self.kind = 0
        self.arch = ""
        self.branch = ""
        self.commit = ""
        self.remote_url = ""

        # Display info fetched by methods always
        self.display_name = None
        self.summary = None
        self.description = None
        self.version = None
        self.icon = {}
        self.screenshots = []
        self.homepage_url = None
        self.help_url = None

        # Runtime categories
        self.categories = []

class AptPkgInfo(PkgInfo):
    def __init__(self, pkg_hash=None, apt_pkg=None):
        super(AptPkgInfo, self).__init__(pkg_hash)

        if apt_pkg:
            self.name = apt_pkg.name

    @classmethod
    def from_json(cls, json_data:dict):
        inst = cls()
        inst.pkg_hash = json_data["pkg_hash"]
        inst.name = json_data["name"]

        return inst

    def to_json(self):
        trimmed_dict = {}

        for key in ("pkg_hash",
                    "name"):
            trimmed_dict[key] = self.__dict__[key]

        return trimmed_dict

    def get_display_name(self, apt_pkg=None):
        # fastest
        if self.display_name:
            return self.display_name

        if apt_pkg:
            self.display_name = apt_pkg.name.capitalize()

        if not self.display_name:
            self.display_name = self.name.capitalize()

        self.display_name = self.display_name.replace(":i386", "")

        return self.display_name

    def get_summary(self, apt_pkg=None):
        # fastest
        if self.summary:
            return self.summary

        if apt_pkg and apt_pkg.candidate:
            candidate = apt_pkg.candidate

            summary = ""
            if candidate.summary is not None:
                summary = candidate.summary

                self.summary = capitalize(summary)

        if self.summary is None:
            self.summary = ""

        return self.summary

    def get_description(self, apt_pkg=None):
        # fastest
        if self.description:
            return self.description

        if apt_pkg and apt_pkg.candidate:
            candidate = apt_pkg.candidate

            description = ""
            if candidate.description is not None:
                description = candidate.description
                description = description.replace("<p>", "").replace("</p>", "\n")
                for tags in ["<ul>", "</ul>", "<li>", "</li>"]:
                    description = description.replace(tags, "")

                self.description = capitalize(description)

        if self.description is None:
            self.description = ""

        return self.description

    def get_icon(self, pkginfo, apt_pkg=None, size=64):
        try:
            return self.icon[size]
        except:
            pass

        theme = Gtk.IconTheme.get_default()

        for name in [pkginfo.name, pkginfo.name.split(":")[0], pkginfo.name.split("-")[0], pkginfo.name.split(".")[-1].lower()]:
            if theme.has_icon(name):
                self.icon[size] = name
                return self.icon[size]

        # Look in app-install-data and pixmaps
        for extension in ['svg', 'png', 'xpm']:
            for suffix in ['', '-icon']:
                icon_path = "/usr/share/app-install/icons/%s%s.%s" % (pkginfo.name, suffix, extension)
                if os.path.exists(icon_path):
                    self.icon[size] = icon_path
                    return self.icon[size]

                icon_path = "/usr/share/pixmaps/%s.%s" % (pkginfo.name, extension)
                if os.path.exists(icon_path):
                    self.icon[size] = icon_path
                    return self.icon[size]

        return None

    def get_screenshots(self, apt_pkg=None):
        return [] # handled in mintinstall for now

    def get_version(self, apt_pkg=None):
        if self.version:
            return self.version

        if apt_pkg:
            if apt_pkg.is_installed:
                self.version = apt_pkg.installed.version
            else:
                self.version = apt_pkg.candidate.version

        if self.version is None:
            self.version = ""

        return self.version

    def get_homepage_url(self, apt_pkg=None):
        if self.homepage_url:
            return self.homepage_url

        if apt_pkg:
            if apt_pkg.is_installed:
                self.homepage_url = apt_pkg.installed.homepage
            else:
                self.homepage_url = apt_pkg.candidate.homepage

        if self.homepage_url is None:
            self.homepage_url = ""

        return self.homepage_url

    def get_help_url(self, apt_pkg=None):
        # We can only get the homepage from apt
        return ""

class FlatpakPkgInfo(PkgInfo):
    def __init__(self, pkg_hash=None, remote=None, ref=None, remote_url=None, installed=False):
        super(FlatpakPkgInfo, self).__init__(pkg_hash)

        if not pkg_hash:
            return

        self.name = ref.get_name() # org.foo.Bar
        self.remote = remote # "flathub"
        self.remote_url = remote_url

        self.installed = installed

        self.refid = ref.format_ref() # app/org.foo.Bar/x86_64/stable
        self.kind = ref.get_kind() # Will be app for now
        self.arch = ref.get_arch()
        self.branch = ref.get_branch()
        self.commit = ref.get_commit()

    @classmethod
    def from_json(cls, json_data:dict):
        inst = cls()
        inst.pkg_hash = json_data["pkg_hash"]
        inst.name = json_data["name"]
        inst.refid = json_data["refid"]
        inst.remote = json_data["remote"]
        inst.kind = json_data["kind"]
        inst.arch = json_data["arch"]
        inst.branch = json_data["branch"]
        inst.commit = json_data["commit"]
        inst.remote_url = json_data["remote_url"]

        return inst

    def to_json(self):
        trimmed_dict = {}

        for key in ("pkg_hash",
                    "name",
                    "refid",
                    "remote",
                    "kind",
                    "arch",
                    "branch",
                    "commit",
                    "remote_url"):
            trimmed_dict[key] = self.__dict__[key]

        return trimmed_dict

    def get_display_name(self, as_component=None):
        # fastest
        if self.display_name:
            return self.display_name

        if as_component:
            display_name = as_component.get_name()

            if display_name is not None:
                self.display_name = capitalize(display_name)

        if self.display_name is None:
            self.display_name = self.name

        return self.display_name

    def get_summary(self, as_component=None):
        # fastest
        if self.summary:
            return self.summary

        if as_component:
            summary = as_component.get_comment()

            if summary is not None:
                self.summary = summary

        if self.summary is None:
            self.summary = ""

        return self.summary

    def get_description(self, as_component=None):
        # fastest
        if self.description:
            return self.description

        if as_component:
            description = as_component.get_description()

            if description is not None:
                description = description.replace("<p>", "").replace("</p>", "\n")
                for tags in ["<ul>", "</ul>", "<li>", "</li>"]:
                    description = description.replace(tags, "")
                self.description = capitalize(description)

        if self.description is None:
            self.description = ""

        return self.description

    def get_icon(self, pkginfo, as_component=None, size=64):
        try:
            return self.icon[size]
        except:
            pass

        if as_component:
            icons = as_component.get_icons()

            if icons:
                icon_to_use = None
                remote_icon = None
                first_local_icon = None
                good_size_icon = None

                for icon in icons:
                    if icon.get_kind() == AppStreamGlib.IconKind.REMOTE:
                        remote_icon = icon
                        continue

                    if icon.get_kind() in (AppStreamGlib.IconKind.LOCAL,  \
                                           AppStreamGlib.IconKind.CACHED, \
                                           AppStreamGlib.IconKind.STOCK):
                        first_local_icon = icon
                        if icon.get_height() == size or ("%dx%d" % (size, size)) in icon.get_prefix():
                            test_path = os.path.join(icon.get_prefix(), icon.get_name())
                            if not os.path.exists(test_path):
                                continue

                            good_size_icon = icon
                            break

                icon_to_use = good_size_icon or first_local_icon or remote_icon
                kind = icon_to_use.get_kind()

                if icon_to_use is not None:
                    if kind in (AppStreamGlib.IconKind.LOCAL, AppStreamGlib.IconKind.CACHED):
                        self.icon[size] = os.path.join(icon_to_use.get_prefix(), icon_to_use.get_name())
                    elif kind == AppStreamGlib.IconKind.REMOTE:
                        self.icon[size] = icon_to_use.get_url()
                    elif kind == AppStreamGlib.IconKind.STOCK:
                        self.icon[size] = icon_to_use.get_name()
                else:
                    # All else fails, try using the package's name (which icon names should match for flatpaks).
                    # You may end up with a third-party icon, but it's better than none.
                    self.icon[size] = pkginfo.name

        try:
            return self.icon[size]
        except:
            return None

    def get_screenshots(self, as_component=None):
        if len(self.screenshots) > 0:
            return self.screenshots

        if as_component:
            self.screenshots = as_component.get_screenshots()

        return self.screenshots

    def get_version(self, as_component=None):
        if self.version:
            # as_component.get_release_default().get_version()
            return self.version

        if as_component:
            releases = as_component.get_releases()

            if len(releases) > 0:
                releases.sort(key=lambda r: r.get_timestamp(), reverse=True)
                version = releases[0].get_version()

                if version:
                    self.version = version

        if self.version is None:
            self.version = ""

        return self.version

    def get_homepage_url(self, as_component=None):
        if self.homepage_url:
            return self.homepage_url

        if as_component:
            url = as_component.get_url_item(AppStreamGlib.UrlKind.HOMEPAGE)

            if url is not None:
                self.homepage_url = url

        return self.homepage_url

    def get_help_url(self, as_component=None):
        if self.help_url:
            return self.help_url

        if as_component:
            url = as_component.get_url_item(AppStreamGlib.UrlKind.HELP)

            if url is not None:
                self.help_url = url

        if self.help_url is None:
            self.help_url = ""

        return self.help_url

