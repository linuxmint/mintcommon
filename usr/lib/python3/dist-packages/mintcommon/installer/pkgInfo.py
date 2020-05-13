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
        self.icon = None
        self.screenshots = []
        self.url = None

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
                summary = summary.replace("<", "&lt;")
                summary = summary.replace("&", "&amp;")

                self.summary = capitalize(summary)

        if self.summary == None:
            self.summary = ""

        return self.summary

    def get_description(self, apt_pkg=None):
        # fastest
        if self.description:
            return self.description

        if apt_pkg and apt_pkg.candidate:
            candidate = apt_pkg.candidate

            description = ""
            if candidate.description != None:
                description = candidate.description
                description = description.replace("<p>", "").replace("</p>", "\n")
                for tags in ["<ul>", "</ul>", "<li>", "</li>"]:
                    description = description.replace(tags, "")

                self.description = capitalize(description)

        if self.description == None:
            self.description = ""

        return self.description

    def get_icon(self, pkginfo, apt_pkg=None, size=64):
        if self.icon:
            return self.icon

        theme = Gtk.IconTheme.get_default()

        for name in [pkginfo.name, pkginfo.name.split(":")[0], pkginfo.name.split("-")[0], pkginfo.name.split(".")[-1].lower()]:
            if theme.has_icon(name):
                self.icon = name
                return self.icon

        # Look in app-install-data and pixmaps
        for extension in ['svg', 'png', 'xpm']:
            for suffix in ['', '-icon']:
                icon_path = "/usr/share/app-install/icons/%s%s.%s" % (pkginfo.name, suffix, extension)
                if os.path.exists(icon_path):
                    self.icon = icon_path
                    return self.icon

                icon_path = "/usr/share/pixmaps/%s.%s" % (pkginfo.name, extension)
                if os.path.exists(icon_path):
                    self.icon = icon_path
                    return self.icon

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

            if self.version == None:
                self.version = ""

        return self.version

    def get_url(self, apt_pkg=None):
        if self.url:
            return self.url

        if apt_pkg:
            if apt_pkg.is_installed:
                self.url = apt_pkg.installed.homepage
            else:
                self.url = apt_pkg.candidate.homepage

        if self.url == None:
            self.url = ""

        return self.url


class FlatpakPkgInfo(PkgInfo):
    def __init__(self, pkg_hash=None, remote=None, ref=None, remote_url=None, installed=False):
        super(FlatpakPkgInfo, self).__init__(pkg_hash)

        if not pkg_hash:
            return

        self.name = ref.get_name() # org.foo.Bar
        self.remote = remote # "flathub"
        self.remote_url = remote_url

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

            if display_name != None:
                self.display_name = capitalize(display_name)

        if self.display_name == None:
            self.display_name = self.name

        return self.display_name

    def get_summary(self, as_component=None):
        # fastest
        if self.summary:
            return self.summary

        if as_component:
            summary = as_component.get_comment()

            if summary != None:
                self.summary = summary

        if self.summary == None:
            self.summary = ""

        return self.summary

    def get_description(self, as_component=None):
        # fastest
        if self.description:
            return self.description

        if as_component:
            description = as_component.get_description()

            if description != None:
                description = description.replace("<p>", "").replace("</p>", "\n")
                for tags in ["<ul>", "</ul>", "<li>", "</li>"]:
                    description = description.replace(tags, "")
                self.description = capitalize(description)

        if self.description == None:
            self.description = ""

        return self.description

    def get_icon(self, pkginfo, as_component=None, size=64):
        if self.icon:
            return self.icon

        if as_component:
            icons = as_component.get_icons()

            if icons:
                icon_to_use = None
                first_icon = None

                for icon in icons:
                    if first_icon == None:
                        first_icon = icon

                    if icon.get_height() == size:
                        icon_to_use = icon
                        break

                if icon_to_use == None:
                    icon_to_use = first_icon

                if icon_to_use.get_kind() in (AppStreamGlib.IconKind.LOCAL, AppStreamGlib.IconKind.CACHED):
                    self.icon = os.path.join(icon_to_use.get_prefix(), icon_to_use.get_name())
                elif icon_to_use.get_kind() == AppStreamGlib.IconKind.REMOTE:
                    self.icon = icon_to_use.get_url()
                elif icon_to_use.get_kind() == AppStreamGlib.IconKind.STOCK:
                    self.icon = icon_to_use.get_name()

        if self.icon == None:
            self.icon == ""
            return None

        return self.icon

    def get_screenshots(self, as_component=None):
        if len(self.screenshots) > 0:
            return self.screenshots

        if as_component:
            screenshots = as_component.get_screenshots()

            for ss in screenshots:
                images = ss.get_images()

                if len(images) == 0:
                    continue

                # FIXME: there must be a better way.  Finding an optimal size to use without just
                # resorting to an original source.

                best = None
                largest = None

                for image in images:
                    if image.get_kind() == AppStreamGlib.ImageKind.SOURCE:
                        continue

                    w = image.get_width()

                    if w > 500 and w < 625:
                        best = image
                        break

                    if w > 625:
                        continue

                    if largest == None or (largest != None and largest.get_width() < w):
                        largest = image

                if best == None and largest == None:
                    continue

                if best == None:
                    best = largest

                if ss.get_kind() == AppStreamGlib.ScreenshotKind.DEFAULT:
                    self.screenshots.insert(0, best.get_url())
                else:
                    self.screenshots.append(best.get_url())

        return self.screenshots

    def get_version(self, as_component=None):
        if self.version:
            return self.version

        if as_component:
            releases = as_component.get_releases()

            if len(releases) > 0:
                version = releases[0].get_version()

                if version:
                    self.version = version

        if self.version == None:
            self.version = ""

        return self.version

    def get_url(self, as_component=None):
        if self.url:
            return self.url

        if as_component:
            url = as_component.get_url(AppStreamGlib.UrlKind.HOMEPAGE)

            if url != None:
                self.url = url

        if self.url == None:
            self.url = self.remote_url

        return self.url