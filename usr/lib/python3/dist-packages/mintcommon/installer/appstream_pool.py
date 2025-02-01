#!/usr/bin/python3

import locale
import os

import gi
gi.require_version('Xmlb', '2.0')
from gi.repository import GLib, Xmlb

from .misc import debug_query, debug, warn, print_timing

KIND_APP = 0
KIND_RUNTIME = 1

# From appstream-1.0.2 (as-utils.c)
def locale_to_bcp47(locale):
    has_variant = False
    if locale == None:
        return None

    ret = locale
    if "@" in ret:
        ret, variant = ret.split("@")
        if variant == "cyrillic":
            ret += "-Cyrl"
        elif variant == "devanagari":
            ret += "-Deva"
        elif variant == "latin":
            ret += "-Latn"
        elif variant == "shaw":
            ret += "-Shaw"
        elif variant != "euro":
            ret += "-" + variant

    return ret

class Icon():
    def __init__(self, icon_node):
        pass

class Image():
    __slots__ = (
        "width",
        "height",
        "scale",
        "url",
        "is_source"
    )

    def __init__(self, img_node):

        try:
            self.height = int(img_node.get_attr("height"))
            self.width = int(img_node.get_attr("width"))
        except TypeError:
            # probably a source image, we don't care about size for them.
            self.height = 0
            self.width = 0
        # optional
        try:
            self.scale = int(img_node.get_attr("scale"))
        except:
            self.scale = 1
        self.is_source = img_node.get_attr("type") == "source"

        self.url = img_node.get_text()

class Screenshot():
    __slots__ = (
        "caption",
        "images",
        "source_image",
        "ss_node"
    )

    def __init__(self, ss_node, caption):
        self.caption = caption
        self.images = {}
        self.source_image = None
        self.ss_node = ss_node

        images = ss_node.query("image", 0)
        for image in images:
            img = Image(image)
            if img.is_source:
                self.source_image = img
                continue
            key = self.make_key(img.width, img.scale)
            self.images[key] = img

    def make_key(self, width, scale):
        return f"{width}x{scale}"

    def get_image(self, width, height, scale=1):
        key = self.make_key(width, scale)
        try:
            return self.images[key]
        except KeyError:
            return self._get_closest_image(width, height, scale)

    def _get_closest_image(self, width, height, scale):
        closest = None
        closest_diff = 999999

        for key, img in self.images.items():
            w_diff = abs(img.width - width)

            if w_diff < closest_diff:
                closest = img
                closest_diff = w_diff

        return closest or self.source_image

    def get_source_image(self):
        return self.source_image

class Package():
    __slots__ = (
        "name",
        "remote_name",
        "remote",
        "appstream_dir",
        "xbnode",
        "kind",
        "verified",
        "bundle_id",
        "keywords"
    )

    def __init__(self, name, remote, xbnode):
        self.name = name
        self.remote = remote
        self.remote_name = remote.get_name()
        self.appstream_dir = remote.get_appstream_dir()
        self.xbnode = xbnode
        self.kind = self.xbnode.get_attr("type")
        self.verified = None
        self.bundle_id = None
        self.keywords = []

    def get_name(self):
        return self.name

    def query_for_node(self, node, xpath):
        result = None

        try:
            result = node.query_first(xpath)
        except GLib.Error as e:
            debug_query(f"Could not make query: {xpath} - {e.message}")

        return result

    def query_string(self, node, xpath):
        str_node = self.query_for_node(node, xpath)

        return str_node.get_text() if str_node is not None else None

    def get_display_name(self):
        name = self.query_string(self.xbnode, "name")
        if name is None:
            name = self.name

        return name

    def get_summary(self):
        return self.query_string(self.xbnode, "summary")

    def get_description(self):
        desc_node = self.query_for_node(self.xbnode, "description")

        if desc_node is not None:
            try:
                return desc_node.export(
                    Xmlb.NodeExportFlags.FORMAT_MULTILINE |
                    Xmlb.NodeExportFlags.FORMAT_INDENT |
                    Xmlb.NodeExportFlags.ONLY_CHILDREN)
            except GLib.Error as e:
                pass

        return None

    def get_url(self, urlkind=None):
        return self.query_string(self.xbnode, f"url[@type='{urlkind}']")

    def get_homepage_url(self):
        return self.get_url("homepage")

    def get_help_url(self):
        return self.get_url("help")

    def get_version(self):
        releases_node = self.query_for_node(self.xbnode, "releases")
        if releases_node is None:
            return None

        releases = releases_node.query("release", 0)
        newest_timestamp = 0
        newest_version = None

        for release in releases:
            timestamp = int(release.get_attr("timestamp"))
            if timestamp > newest_timestamp:
                newest_timestamp = timestamp
                newest_version = release.get_attr("version")

        return newest_version

    def get_bundle_id(self):
        bundle_id = None

        if self.bundle_id is None:
            bundle_id = self.query_string(self.xbnode, "bundle[@type='flatpak']")
            # GNOME apps tend to have bundle info under <custom>
            if bundle_id is None:
                self.bundle_id = self.query_string(self.xbnode, "custom/bundle[@type='flatpak']")

            if bundle_id is not None:
                self.bundle_id = bundle_id

        return self.bundle_id

    def get_verified(self):
        if self.verified is None:
            try:
                self.verified = self.xbnode.query_first(
                    "custom/value[(@key='flathub::verification::verified') and (text()='true')]"
                ) is not None
            except:
                try:
                    self.verified = self.xbnode.query_first(
                        "metadata/value[(@key='flathub::verification::verified') and (text()='true')]"
                    ) is not None
                except:
                    self.verified = False

        return self.verified

    def get_developer(self):
        # "developer" is recent, replacing "developer_name". Currently both are allowed, though older
        # libappstream doesn't support it, causing us to only see the developer name in mintinstall if they're
        # still using "developer_name". If all else fails, project_group may have something.
        dev_name = None

        try:
            developer_node = self.xbnode.query_first("developer")
            dev_name = self.query_string(developer_node, "name")
        except:
            pass

        if dev_name is None:
            try:
                dev_name = self.query_string(self.xbnode, "developer_name")
            except:
                pass

        if dev_name is None:
            try:
                dev_name = self.query_string(self.xbnode, "project_group")
            except:
                pass

        return dev_name

    def get_keywords(self):
        if len(self.keywords) == 0:
            kw_node = self.query_for_node(self.xbnode, "keywords")

            if kw_node is None:
                return []

            keywords = kw_node.query("keyword", 0)
            for keyword in keywords:
                self.keywords.append(keyword.get_text())

        return self.keywords

    def get_screenshots(self):
        ss_node = self.query_for_node(self.xbnode, "screenshots")

        if ss_node is None:
            return []

        screenshots = ss_node.query("screenshot", 0)
        ret = []

        for screenshot_node in screenshots:
            caption = self.query_string(screenshot_node, "caption")
            ret.append(Screenshot(screenshot_node, caption))

        return ret

    def get_addons(self):
        root_node = self.query_for_node(self.xbnode, "..")
        addon_nodes = []

        try:
            addon_nodes = root_node.query(
                f"component[@type='addon']/extends[starts-with(text(),'{self.name}')]/..", 0
            )
        except GLib.Error as e:
            debug_query(f"Could not query for addons or there are none: {self.name} - {e.message}")
            return []

        addons = []
        for addon_node in addon_nodes:
            name = self.query_string(addon_node, "id")
            addon_pkg = Package(name, self.remote, addon_node)
            addons.append(addon_pkg)

        return addons

    def get_launchables(self):
        launchables = None

        try:
            l_nodes = self.xbnode.query(
                "launchable[@type='desktop-id']", 0
            )

            launchables = []

            for node in l_nodes:
                launchables.append(node.get_text())
        except GLib.Error as e:
            debug_query(f"Could not query for launchables or there are none: {self.name} - {e.message}")

        return launchables

    def get_icon(self, size=64):
        icon_to_use = None
        remote_icon = None
        local_exists_icon = None
        theme_icon = None
        try:
            icons = self.xbnode.query(
                f"icon", 0
            )
        except GLib.Error as e:
            debug_query(f"No icon size {size} found or unable to query: {self.name} - {e.message}")
            return None

        def get_height(i):
            height = i.get_attr("height")
            if height is not None:
                return int(height)
            return 999
        icons = sorted(icons, key=get_height, reverse=False)
        for icon in icons:
            test_height = icon.get_attr("height")
            if test_height is None:
                test_height = 64

            kind = icon.get_attr("type")
            # Some icons of the same size will have both cached and remote entries. Prefer the cached one,
            # but keep track of the remote
            if kind == "remote":
                remote_icon = icon.get_text()
            elif kind in ("cached", "local"):
                text = icon.get_text()
                if text.startswith("/"):
                    if os.path.exists(text):
                        local_exists_icon = text
                else:
                    icon_path = f"{self.appstream_dir.get_path()}/icons/{test_height}x{test_height}/{text}"
                    if os.path.exists(icon_path):
                        theme_icon = icon_path
            elif kind == "stock":
                theme_icon = icon.get_text()

            icon_to_use = theme_icon or local_exists_icon or remote_icon
            if icon_to_use:
                if test_height and int(test_height) >= size:
                    return icon_to_use

        # All else fails, try using the package's name (which icon names should match for flatpaks).
        # You may end up with a third-party icon, but it's better than none.
        return icon_to_use or self.name

class Pool():
    def __init__(self, remote):
        self.remote = remote
        self.appstream_dir = self.remote.get_appstream_dir()

        self.as_pool = None
        self.pkg_hash_to_as_pkg_dict = {}
        self.xmlb_silo = None

        self.locale_variants = []
        tmp = set()
        # There really needs to be some enforced consistency in appstream.
        # Need to account for hyphenated vs underscored, and all-lower vs
        # uppercase region codes.
        debug("Reported languages: %s" % str(GLib.get_language_names()))
        for name in GLib.get_language_names():
            if "." in name:
                continue
            if name == "C":
                continue

            tmp.add(name)
            tmp.add(name.replace("_", "-"))
            tmp.add(name.replace("_", "-").lower())
            tmp.add(name.replace("-", "_"))
            tmp.add(name.replace("-", "_").lower())

        # Live session has only C.UTF-8, assume en_US.
        if len(tmp) == 0:
            tmp = ['en-us', 'en', 'en_US', 'en_us', 'en-US']

        self.locale_variants = [locale_to_bcp47(v) for v in tmp]

        debug("Appstream languages: %s" % str(self.locale_variants))
        self._load_xmlb_silo()

    def lookup_appstream_package(self, pkginfo):
        debug_query("Lookup appstream package for %s" % pkginfo.refid)
        if self.xmlb_silo is None:
            return None

        package = None

        try:
            package = self.pkg_hash_to_as_pkg_dict[pkginfo.pkg_hash]
            debug_query("Found existing appstream package")
            return package
        except KeyError:
            base_node = None
            kind = pkginfo.kind

            try:
                if kind == KIND_APP:
                    try:
                        base_node = self.xmlb_silo.query_first(
                            f"components/component/id[text()='{pkginfo.name}']/.."
                        )
                    except GLib.Error as e:
                        base_node = self.xmlb_silo.query_first(
                            f"components/component/id[text()='{pkginfo.name}.desktop']/.."
                        )
                else:
                    base_nodes = self.xmlb_silo.query(
                        f"components/component/id[starts-with(text(),'{pkginfo.name}')]/..",
                        0
                    )
                    if base_nodes is not None:
                        for node in base_nodes:
                            bundle_id = node.query_first("bundle[@type='flatpak']")
                            if bundle_id.get_text() == pkginfo.refid:
                                base_node = node
                                break
            except GLib.Error as e:
                debug_query("Could not find appstream package")

            if base_node is not None:
                debug_query("Found matching appstream package: %s" % pkginfo.refid)
                package = Package(pkginfo.name, self.remote, base_node)

        if package is not None:
            self.pkg_hash_to_as_pkg_dict[pkginfo.pkg_hash] = package

        return package

    @print_timing
    def _load_xmlb_silo(self):
        xml_file = self.appstream_dir.get_child("appstream.xml")
        if not xml_file.query_exists(None):
            xml_file = self.appstream_dir.get_child("appstream.xml.gz")

        source = Xmlb.BuilderSource()
        try:
            ret = source.load_file(xml_file, Xmlb.BuilderSourceFlags.NONE, None)
            builder = Xmlb.Builder()
            for locale in self.locale_variants:
                builder.add_locale(locale)
            builder.import_source(source)
            self.xmlb_silo = builder.compile(
                Xmlb.BuilderCompileFlags.SINGLE_LANG | Xmlb.BuilderCompileFlags.SINGLE_ROOT,
                None
            )
        except GLib.Error as e:
            warn("Could not mmap appstream xml file for remote '%s': %s" % (self.remote.get_name(), e.message))
            self.xmlb_silo = None
