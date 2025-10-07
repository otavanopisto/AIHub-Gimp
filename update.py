from gi.repository import Gimp, Gtk, GLib, Gdk # type: ignore
from gi.repository.GdkPixbuf import Pixbuf # type: ignore
import os
import urllib.request
import ssl

from label import AIHubLabel

class UpdateDialog(Gtk.Dialog):
    def __init__(self, parent, version):
        super().__init__(title="Update Gimp AIHub", parent=parent, flags=0)
        self.set_default_size(400, 300)

        self.set_keep_above(True)

        content_area = self.get_content_area()
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        content_box.set_border_width(10)
        content_area.add(content_box)

        content_box.pack_start(Gtk.Label(label="GIMP AIHub Version: " + (version if version else "unknown")), False, False, 0)

        # https://raw.githubusercontent.com/otavanopisto/AIHub-Gimp/refs/heads/main/VERSION
        # contains the version as it is online hosted on github, we need to fetch it and compare it to the current version
        # using https library basic

        self.online_version = None
        self.files_to_update = []
        error_message = None
        context = ssl._create_unverified_context()
        try:
            with urllib.request.urlopen("https://raw.githubusercontent.com/otavanopisto/AIHub-Gimp/refs/heads/main/VERSION", context=context) as response:
                self.online_version = response.read().decode('utf-8').strip()
            with urllib.request.urlopen("https://raw.githubusercontent.com/otavanopisto/AIHub-Gimp/refs/heads/main/VERSION_FILES", context=context) as response:
                self.files_to_update = response.read().decode('utf-8').strip().splitlines()
        except Exception as e:
            self.online_version = None
            error_message = str(e)

        has_new_version = self.online_version and (self.online_version != version)

        if has_new_version:
            content_box.pack_start(Gtk.Label(label="A new version is available: " + self.online_version), False, False, 0)
            # add an update button
            update_button = Gtk.Button(label="Update Now")
            update_button.connect("clicked", self.on_update_clicked)
            content_box.pack_start(update_button, False, False, 0)
        elif self.online_version is None:
            content_box.pack_start(Gtk.Label(label="Could not check for updates, check your connection"), False, False, 0)
            if (error_message is not None):
                content_box.pack_start(AIHubLabel(error_message).get_widget(), False, False, 0)
            self.add_button(Gtk.STOCK_CLOSE, Gtk.ResponseType.CLOSE)
        else:
            content_box.pack_start(Gtk.Label(label="You are up to date!"), False, False, 0)

        self.show_all()

    def on_update_clicked(self, button):
        pass

    def on_close(self, callback):
        self.connect("response", lambda dialog, response: callback() or self.destroy())