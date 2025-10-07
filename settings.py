from gi.repository import Gimp, Gtk, GLib, Gdk # type: ignore
from gi.repository.GdkPixbuf import Pixbuf # type: ignore
import os

from workspace import ensure_aihub_folder, update_aihub_config

class SettingsDialog(Gtk.Dialog):
    def __init__(self, parent):
        super().__init__(title="Gimp AIHub Settings", parent=parent, flags=0)
        self.set_default_size(400, 300)

        self.set_keep_above(True)

        content_area = self.get_content_area()
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        content_box.set_border_width(10)
        content_area.add(content_box)

        self.config = ensure_aihub_folder()

        # add entry for host, port and apikey
        self.host_entry = Gtk.Entry()
        self.host_entry.set_text(self.config.get("api", "host", fallback=""))

        self.port_entry = Gtk.Entry()
        self.port_entry.set_text(self.config.get("api", "port", fallback=""))

        self.apikey_entry = Gtk.Entry()
        self.apikey_entry.set_text(self.config.get("api", "apikey", fallback=""))

        host_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        host_box.pack_start(Gtk.Label(label="Host:"), False, False, 0)
        host_box.pack_start(self.host_entry, True, True, 0)

        port_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        port_box.pack_start(Gtk.Label(label="Port:"), False, False, 0)
        port_box.pack_start(self.port_entry, True, True, 0)

        apikey_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        apikey_box.pack_start(Gtk.Label(label="API Key:"), False, False, 0)
        apikey_box.pack_start(self.apikey_entry, True, True, 0)

        content_box.pack_start(host_box, False, False, 0)
        content_box.pack_start(port_box, False, False, 0)
        content_box.pack_start(apikey_box, False, False, 0)

        self.add_button(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL)
        self.add_button(Gtk.STOCK_OK, Gtk.ResponseType.OK)

        self.show_all()

    def on_response(self, dialog, response):
        if response == Gtk.ResponseType.OK:
            host = self.host_entry.get_text().strip()
            port = self.port_entry.get_text().strip()
            apikey = self.apikey_entry.get_text().strip()

            self.config.set("api", "host", host)
            self.config.set("api", "port", port)
            self.config.set("api", "apikey", apikey)

            update_aihub_config(self.config)

            # show a dialog to specify that settings have been saved and that the application needs to be restarted
            info_dialog = Gtk.MessageDialog(
                transient_for=self,
                flags=0,
                message_type=Gtk.MessageType.INFO,
                buttons=Gtk.ButtonsType.OK,
                text="Settings saved",
            )
            info_dialog.set_keep_above(True)
            info_dialog.format_secondary_text("Settings have been saved. Please restart GIMP AIHub to apply the new settings.")
            info_dialog.run()

    def on_close(self, callback):
        self.connect("response", lambda dialog, response: self.on_response(dialog, response) or callback() or self.destroy())