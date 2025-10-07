from gi.repository import Gimp, Gtk, GLib, Gdk # type: ignore
from gi.repository.GdkPixbuf import Pixbuf # type: ignore
import os
import urllib.request
import ssl
import shutil

from label import AIHubLabel

IGNORES = ["__pycache__", ".git", ".gitignore", "websocket"]

class UpdateDialog(Gtk.Dialog):
    def __init__(self, parent, version):
        super().__init__(title="Update Gimp AIHub", parent=parent, flags=0)
        self.set_default_size(400, 300)

        self.set_keep_above(True)

        content_area = self.get_content_area()
        self.content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.content_box.set_border_width(10)
        content_area.add(self.content_box)

        self.content_box.pack_start(Gtk.Label(label="GIMP AIHub Version: " + (version if version else "unknown")), False, False, 0)

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
            self.content_box.pack_start(Gtk.Label(label="A new version is available: " + self.online_version), False, False, 0)
            # add an update button
            self.update_button = Gtk.Button(label="Update Now")
            self.update_button.connect("clicked", self.on_update_clicked)
            self.content_box.pack_start(self.update_button, False, False, 0)
        elif self.online_version is None:
            self.content_box.pack_start(Gtk.Label(label="Could not check for updates, check your connection"), False, False, 0)
            if (error_message is not None):
                self.content_box.pack_start(AIHubLabel(error_message).get_widget(), False, False, 0)
            self.add_button(Gtk.STOCK_CLOSE, Gtk.ResponseType.CLOSE)
        else:
            self.content_box.pack_start(Gtk.Label(label="You are up to date!"), False, False, 0)

        self.show_all()

    def on_update_clicked(self, button):
        self.update_button.set_sensitive(False)
        self.update_button.set_label("Updating...")

        # first lets create a backup of the current installation
        local_path = os.path.dirname(os.path.abspath(__file__))
        backup_path = os.path.join(local_path, "backup")
        n = 0
        while os.path.exists(backup_path):
            n += 1
            backup_path = os.path.join(local_path, f"backup-{n}")
        os.makedirs(backup_path)

        global IGNORES
        for item in os.listdir(local_path):
            if item in IGNORES or item.startswith("backup"):
                continue
            s = os.path.join(local_path, item)
            d = os.path.join(backup_path, item)
            if os.path.isdir(s):
                shutil.copytree(s, d)
            else:
                shutil.copy2(s, d)

        # remove update directory if it exist
        if os.path.exists(os.path.join(local_path, "update")):
            shutil.rmtree(os.path.join(local_path, "update"))

        context = ssl._create_unverified_context()
        for file in self.files_to_update:
            try:
                with urllib.request.urlopen(f"https://raw.githubusercontent.com/otavanopisto/AIHub-Gimp/refs/heads/main/{file}", context=context) as response:
                    file_content = response.read()
                local_file_path = os.path.join(local_path, "update", file)
                local_dir = os.path.dirname(local_file_path)
                if not os.path.exists(local_dir):
                    os.makedirs(local_dir)
                with open(local_file_path, "wb") as f:
                    f.write(file_content)
            except Exception as e:
                # remove update directory
                shutil.rmtree(os.path.join(local_path, "update"))

                self.update_button.set_label("Update Failed")

                self.content_box.pack_start(AIHubLabel(str(e)).get_widget(), False, False, 0)
                self.add_button(Gtk.STOCK_CLOSE, Gtk.ResponseType.CLOSE)
                self.show_all()
                return
            
        # now move the update files to the local path
        update_path = os.path.join(local_path, "update")
        for item in os.listdir(update_path):
            s = os.path.join(update_path, item)
            d = os.path.join(local_path, item)
            if os.path.isdir(s):
                if os.path.exists(d):
                    shutil.rmtree(d)
                shutil.move(s, d)
            else:
                shutil.move(s, d)

        # remove update directory
        shutil.rmtree(os.path.join(local_path, "update"))

        self.update_button.set_label("Update Complete")

        # show a message dialog requesting to restart AIHub to apply the update
        self.content_box.pack_start(AIHubLabel("Update complete, please restart AIHub to apply the update.").get_widget(), False, False, 0)
        self.add_button(Gtk.STOCK_CLOSE, Gtk.ResponseType.CLOSE)
        self.show_all()

    def on_close(self, callback):
        self.connect("response", lambda dialog, response: callback() or self.destroy())
