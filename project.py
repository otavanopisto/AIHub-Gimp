from gi.repository import Gimp, GimpUi, Gtk, GLib, Gdk # type: ignore
from gi.repository.GdkPixbuf import Pixbuf # type: ignore
from gi.repository.GdkPixbuf import InterpType # type: ignore
from gi.repository import Gio # type: ignore
import threading

import gettext
textdomain = "gimp30-python"
gettext.textdomain(textdomain)
_ = gettext.gettext

# create a new Gtk Dialog from gimp to handle the specific project data
class ProjectDialog(Gtk.Dialog):
    def __init__(self, title, parent, project_file_contents, project_current_timeline_folder):
        super().__init__(title=title, transient_for=parent, flags=0)
        self.set_default_size(600, 400)
        self.project_file_contents = project_file_contents
        self.project_current_timeline_folder = project_current_timeline_folder
        self.update_project_timeline = None

        self.main_box = self.get_content_area()
        self.main_box.set_spacing(10)
        self.main_box.set_border_width(10)

        self.project_data_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.main_box.pack_start(self.project_data_box, False, False, 0)

        self.set_keep_above(True)

        # Add more widgets to display and edit project data as needed
        self.rebuild_ui()
        self.show_all()

    def refresh(self, new_project_file_contents, new_project_current_timeline_folder):
        # Refresh the dialog with the latest project data
        self.project_file_contents = new_project_file_contents
        self.project_current_timeline_folder = new_project_current_timeline_folder
        # Update the UI elements with the new project data
        self.rebuild_ui()

    def rebuild_ui(self):
        # we need to do something special and that is building a graph with the project file contents of
        # the timelines and the current timeline that we are at
        pass

    def on_close(self, callback):
        self.connect("response", lambda dialog, response: callback() or self.destroy())

    def on_change_timeline(self, callback):
        self.update_project_timeline = callback