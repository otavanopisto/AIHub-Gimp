import os
from gi.repository import Gimp, Gtk, GLib, Gdk # type: ignore
from gi.repository.GdkPixbuf import Pixbuf # type: ignore
from gi.repository import Gio # type: ignore
import threading

import sys
import subprocess

import gettext
textdomain = "gimp30-python"
gettext.textdomain(textdomain)
_ = gettext.gettext

DEFAULT_THUMBNAIL = None
UNKNOWN_THUMBNAIL = None

EXTENSIONS_THUMBNAILS = {
    ".exe": "executable.png",
    ".dll": "executable.png",
    ".so": "executable.png",
    ".bin": "executable.png",
    ".txt": "text.png",
    ".md": "text.png",
    ".json": "json.png",
    ".xml": "markup.png",
    ".yml": "markup.png",
    ".yaml": "markup.png",
    ".csv": "text.png",
    ".log": "text.png",
    ".safetensors": "huggingface.png",
    ".ckpt": "huggingface.png",
    ".pt": "huggingface.png",
    ".pth": "huggingface.png",
    ".torch": "pytorch.png",
    ".pkl": "pytorch.png",
    ".h5": "tensorflow.png",
    ".hdf5": "tensorflow.png",
    ".tflite": "tensorflow.png",
    ".pb": "tensorflow.png",
    ".onnx": "onnx.png",
    ".mp4": "video.png",
    ".mov": "video.png",
    ".avi": "video.png",
    ".mkv": "video.png",
    ".webm": "video.png",
    ".flv": "video.png",
    ".wmv": "video.png",
    ".mp3": "audio.png",
    ".wav": "audio.png",
    ".flac": "audio.png",
    ".ogg": "audio.png",
    ".aac": "audio.png",
    ".wma": "audio.png",
    ".mid": "audio.png",
    ".midi": "audio.png",
    ".xcf": "gimp.png",
    ".lua": "script.png",
    ".py": "script.png",
    ".js": "script.png",
    ".sh": "script.png",
    ".bat": "script.png",
    ".ps1": "script.png",
}

EXTENSIONS_THUMBNAILS_CACHE = {}

SUPPORTED_IMAGE_EXTENSIONS = [
    ".png",
    ".jpg",
    ".jpeg",
    ".bmp",
    ".tiff",
    ".gif"
]

SUPPORTED_GIMP_OPENABLE_IMAGE_EXTENSIONS = [
    ".png",
    ".jpg",
    ".jpeg",
    ".bmp",
    ".tiff",
    ".gif",
    ".xcf",
    ".webp"
]

def open_file_with_default_app(path):
    if sys.platform.startswith("linux"):  # could be "linux", "linux2", "linux3", ...
        subprocess.run(["xdg-open", path])
    elif sys.platform == "darwin":
        subprocess.run(["open", path])
    elif os.name == "nt":
        os.startfile(path)

# create a new Gtk Dialog from gimp to handle the specific project data
class ProjectDialog(Gtk.Dialog):
    def __init__(
            self,
            title,
            parent,
            project_file_contents,
            project_current_timeline_folder,
            project_folder,
            image_model,
            on_focus_dialog
        ):
        super().__init__(title=title, transient_for=parent, flags=0)
        self.set_default_size(600, 800)
        self.project_file_contents = project_file_contents
        self.project_current_timeline_folder = project_current_timeline_folder
        self.project_folder = project_folder
        self.update_project_timeline = None
        self.update_project_file = None
        self.image_model = image_model

        self.images_opened = []

        self.custom_xcf_file_folder = os.path.join(self.project_folder, "xcf_files")

        if not os.path.exists(self.custom_xcf_file_folder):
            os.makedirs(self.custom_xcf_file_folder)

        self.main_box = self.get_content_area()
        self.main_box.set_spacing(10)
        self.main_box.set_border_width(10)

        self.scrolled_window = Gtk.ScrolledWindow()
        self.scrolled_window.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scrolled_window.set_size_request(600, 400)
        self.main_box.pack_start(self.scrolled_window, True, True, 0)

        self.internal_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.scrolled_window.add(self.internal_box)

        # make a top bar with a File menu
        header_bar = Gtk.HeaderBar()
        header_bar.set_title(title)
        header_bar.set_show_close_button(True)
        Gtk.Window.set_titlebar(self, header_bar)
        menu_button = Gtk.MenuButton()
        menu_image = Gtk.Image.new_from_icon_name("open-menu-symbolic", Gtk.IconSize.BUTTON)
        menu_button.add(menu_image)
        header_bar.pack_start(menu_button)
        menu = Gtk.Menu()
        menu_item_new = Gtk.MenuItem(label="New empty image")
        menu_item_new.connect("activate", self.on_menu_new_xcf_file)
        menu.append(menu_item_new)
        menu_item_add = Gtk.MenuItem(label="New image from open images")
        menu_item_add.connect("activate", self.on_menu_add_xcf_files)
        menu.append(menu_item_add)
        menu_item_import = Gtk.MenuItem(label="Import image from file")
        menu_item_import.connect("activate", self.on_menu_import_file)
        menu.append(menu_item_import)

        menu_button.set_popup(menu)
        menu.show_all()

        Gtk.Window.connect(self, "focus-in-event", on_focus_dialog)
        Gtk.Window.connect(self, "focus-in-event", self.refresh_non_dirty_images)

        self.set_keep_above(True)

        # Add more widgets to display and edit project data as needed
        self.rebuild_timeline_ui()
        self.update_xcf_file_list()
        self.show_all()

    def refresh(self, new_project_file_contents, new_project_current_timeline_folder):
        # Refresh the dialog with the latest project data
        self.project_file_contents = new_project_file_contents
        self.project_current_timeline_folder = new_project_current_timeline_folder
        # Update the UI elements with the new project data
        self.rebuild_timeline_ui()

    def rebuild_timeline_ui(self):
        # we need to do something special and that is building a graph with the project file contents of
        # the timelines and the current timeline that we are at
        self.rebuild_timeline_tree()
        self.rebuild_timeline_files()

    def on_timeline_selection_changed(self, selection):
        model, treeiter = selection.get_selected()
        if treeiter is not None:
            timeline_id = model[treeiter][1]
            if self.update_project_timeline is not None:
                self.update_project_timeline(timeline_id)

    def rebuild_timeline_tree(self):
        if not hasattr(self, 'timeline_tree_widget'):
            # one column the name, the other column the id
            self.timeline_tree_store = Gtk.TreeStore(str, str)

            box_inside_to_force_set_margins = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            box_inside_to_force_set_margins.set_margin_start(10)
            box_inside_to_force_set_margins.set_margin_end(50)

            self.timeline_tree_widget = Gtk.TreeView(model=self.timeline_tree_store)
            renderer = Gtk.CellRendererText()
            column = Gtk.TreeViewColumn("Timelines", renderer, text=0)
            self.timeline_tree_widget.append_column(column)
            self.timeline_tree_widget.set_headers_visible(False)
            self.timeline_tree_widget.set_size_request(200, 300)
            self.timeline_tree_widget.get_selection().set_mode(Gtk.SelectionMode.SINGLE)
            self.timeline_tree_widget.get_selection().connect("changed", self.on_timeline_selection_changed)
            timelines_label = Gtk.Label(label="Project Timelines:")
            timelines_label.set_margin_top(10)
            timelines_label.set_margin_bottom(10)
            self.internal_box.pack_start(timelines_label, False, False, 0)
            self.internal_box.pack_start(box_inside_to_force_set_margins, False, False, 0)

            # add a menu to each timeline for a context menu on second click for deleting and renaming with a divider
            def on_timeline_right_click(treeview, event):
                if event.type == Gdk.EventType.BUTTON_PRESS and event.button == Gdk.BUTTON_SECONDARY:
                    # get the clicked row
                    path_info = treeview.get_path_at_pos(int(event.x), int(event.y))
                    if path_info is not None:
                        path, col, cellx, celly = path_info
                        treeview.grab_focus()
                        treeview.set_cursor(path, col, 0)
                        model, treeiter = treeview.get_selection().get_selected()
                        if treeiter is not None:
                            timeline_id = model[treeiter][1]
                            timeline_in_question = self.project_file_contents.get("timelines", {}).get(timeline_id, None)
                            if timeline_in_question is not None:
                                menu = Gtk.Menu()
                                menu_item_rename = Gtk.MenuItem(label="Rename Timeline")
                                def on_rename_activate(menu_item):
                                    self.rename_timeline(timeline_id)
                                menu_item_rename.connect("activate", on_rename_activate)
                                menu.append(menu_item_rename)

                                menu_item_delete = Gtk.MenuItem(label="Delete Timeline")
                                def on_delete_activate(menu_item):
                                    self.delete_timeline(timeline_id)
                                menu_item_delete.connect("activate", on_delete_activate)
                                menu.append(menu_item_delete)

                                menu.show_all()
                                menu.popup_at_pointer(event)
                    return True
                return False
            
            self.timeline_tree_widget.connect("button-press-event", on_timeline_right_click)

            # add scrollbar to the timeline tree widget
            timeline_tree_scrolled_window = Gtk.ScrolledWindow()
            timeline_tree_scrolled_window.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
            timeline_tree_scrolled_window.set_size_request(200, 300)
            timeline_tree_scrolled_window.add(self.timeline_tree_widget)
            box_inside_to_force_set_margins.pack_start(timeline_tree_scrolled_window, True, True, 0)

        # start adding the timelines to the tree store without clearing it
        existing_timelines = {}
        timeline_values = self.project_file_contents.get("timelines", {}).values()
        # we need to add the iter to the existing_timelines dict
        for row in self.timeline_tree_store:
            existing_timelines[row[1]] = row.iter
            # also add all children
            def add_children(parent_iter):
                child_iter = self.timeline_tree_store.iter_children(parent_iter)
                while child_iter is not None:
                    existing_timelines[self.timeline_tree_store[child_iter][1]] = child_iter
                    add_children(child_iter)
                    child_iter = self.timeline_tree_store.iter_next(child_iter)
            add_children(row.iter)

        # delete any timelines that are no longer present
        for timeline_id in list(existing_timelines.keys()):
            found = False
            for timeline in timeline_values:
                if timeline.get("id", None) == timeline_id:
                    found = True
                    break
            if not found:
                self.timeline_tree_store.remove(existing_timelines[timeline_id])
                del existing_timelines[timeline_id]

        nodes_skipped = -1
        past_nodes_skipped = None
        while nodes_skipped != 0:
            if past_nodes_skipped is not None and past_nodes_skipped == nodes_skipped:
                # we are not making any progress, break the loop
                # some nodes are probably orphaned
                break

            past_nodes_skipped = nodes_skipped
            nodes_skipped = 0
            for timeline in timeline_values:
                timeline_id = timeline.get("id", None)
                if timeline_id is None:
                    continue
                if timeline_id in existing_timelines:
                    # update the name if needed
                    existing_iter = existing_timelines[timeline_id]
                    timeline_name = timeline.get("name", "")
                    if timeline_name != self.timeline_tree_store[existing_iter][0]:
                        self.timeline_tree_store[existing_iter][0] = timeline_name
                else:
                    timeline_parent_id = timeline.get("parent_id", None)
                    timeline_name = timeline.get("name", "")
                    if timeline_parent_id is None or timeline_parent_id == "":
                        # add as root node
                        new_iter = self.timeline_tree_store.append(None, [timeline_name, timeline_id])
                        existing_timelines[timeline_id] = new_iter
                    elif timeline_parent_id in existing_timelines:
                        parent_iter = existing_timelines[timeline_parent_id]
                        new_iter = self.timeline_tree_store.append(parent_iter, [timeline_name, timeline_id])
                        existing_timelines[timeline_id] = new_iter
                    else:
                        nodes_skipped += 1

        current_selected_timeline_id = self.project_file_contents.get("current_timeline", None)
        if current_selected_timeline_id in existing_timelines:
            current_iter = existing_timelines[current_selected_timeline_id]
            path = self.timeline_tree_store.get_path(current_iter)
            self.timeline_tree_widget.expand_to_path(path)
            self.timeline_tree_widget.get_selection().select_path(path)

    def rebuild_timeline_files(self):
        timeline_files_folder = os.path.join(self.project_current_timeline_folder, "files")
        timeline_files = []
        if os.path.exists(timeline_files_folder) and os.path.isdir(timeline_files_folder):
            timeline_files = [f for f in os.listdir(timeline_files_folder)]
        # then we will create a Gtk FlowBox to show them with thumbnails if available
        if not hasattr(self, 'timeline_file_list_widget'):
            project_timeline_label = Gtk.Label(label="Timeline Files:")
            project_timeline_label.set_margin_top(20)
            project_timeline_label.set_margin_bottom(10)
            #project_timeline_label.set_halign(Gtk.Align.START)
            # add a separator before the label
            self.internal_box.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0)
            self.internal_box.pack_start(project_timeline_label, False, False, 0)

            self.timeline_file_list_widget = Gtk.FlowBox()
            #ensure max width is only 600 pixels
            self.timeline_file_list_widget.set_column_spacing(10)
            self.timeline_file_list_widget.set_row_spacing(10)

            self.internal_box.pack_start(self.timeline_file_list_widget, True, True, 0)

        # clean up existing children
        for child in self.timeline_file_list_widget.get_children():
            self.timeline_file_list_widget.remove(child)
            
        global SUPPORTED_IMAGE_EXTENSIONS
        global EXTENSIONS_THUMBNAILS
        global EXTENSIONS_THUMBNAILS_CACHE
        global UNKNOWN_THUMBNAIL
        if UNKNOWN_THUMBNAIL is None:
            # create an icon pixbuf for the unknown thumbnail
            UNKNOWN_THUMBNAIL = Pixbuf.new_from_file_at_scale(
                os.path.join(
                    os.path.dirname(os.path.abspath(__file__)),
                    "icons",
                    "unknown.png"
                ),
                100,
                100,
                True
            )
        for timeline_file in timeline_files:
            thumbnail = UNKNOWN_THUMBNAIL
            extension_with_dot = os.path.splitext(timeline_file)[1].lower()
            if extension_with_dot in SUPPORTED_IMAGE_EXTENSIONS:
                thumbnail_path = os.path.join(timeline_files_folder, timeline_file)
                thumbnail = Pixbuf.new_from_file_at_scale(thumbnail_path, 100, 100, True)
            elif extension_with_dot in EXTENSIONS_THUMBNAILS_CACHE:
                thumbnail = EXTENSIONS_THUMBNAILS_CACHE[extension_with_dot]
            elif extension_with_dot in EXTENSIONS_THUMBNAILS:
                thumbnail_path = os.path.join(
                    os.path.dirname(os.path.abspath(__file__)),
                    "icons",
                    EXTENSIONS_THUMBNAILS.get(extension_with_dot, "unknown.png")
                )
                thumbnail = Pixbuf.new_from_file_at_scale(thumbnail_path, 100, 100, True)
                EXTENSIONS_THUMBNAILS_CACHE[extension_with_dot] = thumbnail

            # first let's see if we already have this file in the list box
            existing_file_element = None
            for file_element in self.timeline_file_list_widget.get_children():
                label = file_element.get_child().get_child().get_children()[1]
                if label.get_text() == timeline_file:
                    existing_file_element = file_element
                    break
            if existing_file_element is not None:
                # If we found an existing file element, we can update it
                existing_file_element.get_child().get_child().get_children()[0].set_from_pixbuf(thumbnail)
            else:
                # If not, we need to create a new row
                # we need to be sure it is added in alphabetical order
                new_file_element_event_box = Gtk.EventBox()
                new_file_element = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
                new_file_element.set_margin_top(10)
                new_file_element.set_margin_bottom(10)
                new_file_element.set_margin_start(10)
                new_file_element.set_margin_end(10)
                new_file_element.pack_start(Gtk.Image.new_from_pixbuf(thumbnail), False, False, 0)
                new_file_element.pack_start(Gtk.Label(label=timeline_file), False, False, 0)
                new_file_element_event_box.add(new_file_element)

                def on_file_double_click(widget, event, timeline_file=timeline_file):
                    timeline_file_path = os.path.join(timeline_files_folder, timeline_file)
                    extension_with_dot = os.path.splitext(timeline_file_path)[1].lower()
                    
                    if event.type == Gdk.EventType._2BUTTON_PRESS and event.button == Gdk.BUTTON_PRIMARY:
                        open_file_with_default_app(timeline_file_path)
                    elif event.type == Gdk.EventType.BUTTON_PRESS and event.button == Gdk.BUTTON_SECONDARY:
                        # set the flowbox selection to this item
                        self.timeline_file_list_widget.select_child(widget.get_parent())
                        # Right-click detected, show context menu
                        menu = Gtk.Menu()
                        menu_item_open = Gtk.MenuItem(label="Open File")
                        menu_item_open.connect("activate", lambda item: open_file_with_default_app(timeline_file_path))
                        menu.append(menu_item_open)

                        if extension_with_dot in SUPPORTED_GIMP_OPENABLE_IMAGE_EXTENSIONS:
                            # NOTE does not work due to GIMP not setting the overwrite path correctly
                            #menu_item_open_gimp = Gtk.MenuItem(label="Open in GIMP")
                            #menu_item_open_gimp.connect("activate", lambda item: self.open_timeline_file_as_image(timeline_file_path))
                            #menu.append(menu_item_open_gimp)

                            menu_item_overwrite = Gtk.MenuItem(label="Overwrite with Reference Image")
                            menu_item_overwrite.connect("activate", lambda item: self.overwrite_timeline_file_with_reference_image(timeline_file_path))
                            menu.append(menu_item_overwrite)

                            menu_item_import = Gtk.MenuItem(label="Import as project XCF image")
                            menu_item_import.connect("activate", lambda item: self.on_import_file(timeline_file_path))
                            menu.append(menu_item_import)

                        # add a horizontal separator
                        separator = Gtk.SeparatorMenuItem()
                        menu.append(separator)

                        menu_item_delete = Gtk.MenuItem(label="Delete File")
                        menu_item_delete.connect("activate", lambda item: self.delete_timeline_file(timeline_file_path))
                        menu.append(menu_item_delete)

                        menu.show_all()
                        menu.popup_at_pointer(event)

                new_file_element_event_box.connect("button-press-event", on_file_double_click)

                inserted = False
                for i, existing_file_element in enumerate(self.timeline_file_list_widget.get_children()):
                    existing_label = existing_file_element.get_child().get_child().get_children()[1]
                    if timeline_file < existing_label.get_text():
                        self.timeline_file_list_widget.insert(new_file_element_event_box, i)
                        inserted = True
                        break
                if not inserted:
                    self.timeline_file_list_widget.add(new_file_element_event_box)

        self.timeline_file_list_widget.show_all()

    def rename_timeline(self, timeline_id):
        timeline_in_question = self.project_file_contents.get("timelines", {}).get(timeline_id, None)
        if timeline_in_question is None:
            return
        # we need to ask for the new name
        # first we must ask for confirmation
        dialog = Gtk.Dialog(title="Rename Timeline", parent=self, flags=0)
        dialog.set_keep_above(True)
        dialog.set_default_size(300, 100)
        content_area = dialog.get_content_area()
        content_area.set_spacing(10)
        content_area.set_border_width(10)
        entry = Gtk.Entry()
        entry.set_text(timeline_in_question.get("name", ""))
        content_area.pack_start(Gtk.Label(label="New name:"), False, False, 0)
        content_area.pack_start(entry, False, False, 0)
        dialog.add_button(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL)
        dialog.add_button(Gtk.STOCK_OK, Gtk.ResponseType.OK)
        dialog.show_all()
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            new_name = entry.get_text().strip()
            if new_name != "":
                timeline_in_question["name"] = new_name
                self.project_file_contents = self.project_file_contents.copy()
                self.update_project_file(self.project_file_contents)
        dialog.destroy()

    def actually_delete_timeline(self, timeline_id):
        deleted_current_timeline = timeline_id == self.project_file_contents.get("current_timeline", None)
        self.project_file_contents.get("timelines", {}).pop(timeline_id, None)

        for existing_timeline_element in self.project_file_contents.get("timelines", {}).values():
            if existing_timeline_element.get("parent_id", None) == timeline_id:
                that_deleted_current_timeline = self.actually_delete_timeline(existing_timeline_element.get("id", None))
                if that_deleted_current_timeline:
                    deleted_current_timeline = True

        # delete from the tree store
        for row in self.timeline_tree_store:
            if row[1] == timeline_id:
                self.timeline_tree_store.remove(row.iter)
                break

        return deleted_current_timeline

    def delete_timeline(self, timeline_id):
        timeline_in_question = self.project_file_contents.get("timelines", {}).get(timeline_id, None)
        if timeline_in_question is None:
            return
        # first we must ask for confirmation
        dialog = Gtk.MessageDialog(parent=self, flags=0, message_type=Gtk.MessageType.QUESTION,
                                   buttons=Gtk.ButtonsType.YES_NO, text=f"Are you sure you want to delete the timeline {timeline_in_question.get('name', 'unknown')}? " +
                                   "this action cannot be reversed and will delete any timeline files associated with it")
        dialog.set_keep_above(True)
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.YES:
            timeline_to_be_current = self.project_file_contents.get("current_timeline", None)
            deleted_current = self.actually_delete_timeline(timeline_id)

            if deleted_current:
                # pick the first initial timeline available
                first_timeline_id = None
                for t in self.project_file_contents.get("timelines", {}).values():
                    if t.get("initial", False):
                        first_timeline_id = t.get("id", None)
                    break

                if first_timeline_id is not None:
                    timeline_to_be_current = first_timeline_id
                else:
                    timeline_to_be_current = None

            # make a shallow copy of the project file contents and update the current timeline
            # that is because this is a dict and we want to avoid mutating the original one
            # that is a reference to the one in the tools.py
            self.project_file_contents = self.project_file_contents.copy()
            self.project_file_contents["current_timeline"] = timeline_to_be_current
            self.update_project_file(self.project_file_contents)
        
    def on_close(self, callback):
        self.connect("response", lambda dialog, response: callback() or self.destroy() or self.cleanup())

    def overwrite_timeline_file_with_reference_image(self, timeline_file):
        # first we set a dialog to select from the currently open images in GIMP
        dialog = Gtk.Dialog(title="Select Reference Image", parent=self, flags=0)
        dialog.set_default_size(300, 100)
        content_area = dialog.get_content_area()
        content_area.set_spacing(10)
        content_area.set_border_width(10)
        combo_box = Gtk.ComboBox.new_with_model(self.image_model)
        combo_box.set_entry_text_column(0)
        renderer_pixbuf = Gtk.CellRendererPixbuf()
        renderer_text = Gtk.CellRendererText()
        combo_box.pack_start(renderer_pixbuf, False)
        combo_box.add_attribute(renderer_pixbuf, "pixbuf", 2)
        combo_box.pack_start(renderer_text, True)
        combo_box.add_attribute(renderer_text, "text", 1)
        content_area.pack_start(Gtk.Label(label="Select an open image to use as reference:"), False, False, 0)
        content_area.pack_start(combo_box, False, False, 0)
        combo_box.set_active(0)
        dialog.add_button(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL)
        dialog.add_button(Gtk.STOCK_OK, Gtk.ResponseType.OK)
        dialog.set_keep_above(True)
        dialog.show_all()
        response = dialog.run()
        selected_iter = combo_box.get_active_iter()
        dialog.destroy()
        if response == Gtk.ResponseType.OK and selected_iter is not None:
            try:
                id_of_image = self.image_model[selected_iter][0]
                gimp_image = Gimp.Image.get_by_id(id_of_image)
                if gimp_image is None:
                    raise ValueError("Failed to get the selected image")
                gfile = Gio.File.new_for_path(timeline_file)
                Gimp.file_save(Gimp.RunMode.INTERACTIVE, gimp_image, gfile, None)

                # update the thumbnail in the timeline file list
                self.update_timeline_thumbnail(timeline_file)
            except ValueError as e:
                error_dialog = Gtk.MessageDialog(parent=self, flags=0, message_type=Gtk.MessageType.ERROR,
                                                 buttons=Gtk.ButtonsType.OK, text=str(e))
                error_dialog.set_keep_above(True)
                error_dialog.run()
                error_dialog.destroy()

    def delete_timeline_file(self, timeline_file):
        # first let's check if the file is open in GIMP
        for opened in self.images_opened:
            if opened["file_path"] == timeline_file:
                # refuse to delete the file if it is open in GIMP
                error_dialog = Gtk.MessageDialog(parent=self, flags=0, message_type=Gtk.MessageType.ERROR,
                                                 buttons=Gtk.ButtonsType.OK, text=f"Cannot delete {timeline_file} because it is currently open in GIMP.")
                error_dialog.set_keep_above(True)
                error_dialog.run()
                error_dialog.destroy()
                break

        # make a dialog asking the user to confirm deletion
        dialog = Gtk.MessageDialog(parent=self, flags=0, message_type=Gtk.MessageType.QUESTION,
                                   buttons=Gtk.ButtonsType.YES_NO, text=f"Are you sure you want to delete {timeline_file}? this action cannot be reversed and may corrupt the timeline")
        dialog.set_keep_above(True)

        response = dialog.run()
        dialog.destroy()

        if response != Gtk.ResponseType.YES:
            return
        
        try:
            # send it to the recycling bin or whatever the OS uses
            os.remove(timeline_file)
            
            for i, existing_file_element in enumerate(self.timeline_file_list_widget.get_children()):
                existing_label = existing_file_element.get_child().get_child().get_children()[1]
                if os.path.basename(timeline_file) == existing_label.get_text():
                    self.timeline_file_list_widget.remove(existing_file_element)
                    break

        except Exception as e:
            error_dialog = Gtk.MessageDialog(parent=self, flags=0, message_type=Gtk.MessageType.ERROR,
                                             buttons=Gtk.ButtonsType.OK, text=str(e))
            error_dialog.set_keep_above(True)
            error_dialog.run()
            error_dialog.destroy()

    def delete_xcf_file(self, xcf_file):
        # first let's check if the file is open in GIMP
        for opened in self.images_opened:
            if opened["file_path"] == xcf_file:
                # refuse to delete the file if it is open in GIMP
                error_dialog = Gtk.MessageDialog(parent=self, flags=0, message_type=Gtk.MessageType.ERROR,
                                                 buttons=Gtk.ButtonsType.OK, text=f"Cannot delete {xcf_file} because it is currently open in GIMP.")
                error_dialog.set_keep_above(True)
                error_dialog.run()
                error_dialog.destroy()
                break

        # make a dialog asking the user to confirm deletion
        dialog = Gtk.MessageDialog(parent=self, flags=0, message_type=Gtk.MessageType.QUESTION,
                                   buttons=Gtk.ButtonsType.YES_NO, text=f"Are you sure you want to delete {xcf_file}? this action cannot be reversed")
        dialog.set_keep_above(True)

        response = dialog.run()
        dialog.destroy()

        if response != Gtk.ResponseType.YES:
            return

        try:
            # send it to the recycling bin or whatever the OS uses
            os.remove(xcf_file)
            thumbnail_path = os.path.splitext(xcf_file)[0] + "_thumbnail.png"
            if os.path.exists(thumbnail_path):
                os.remove(thumbnail_path)
            
            for i, existing_file_element in enumerate(self.xcf_file_list_widget.get_children()):
                existing_label = existing_file_element.get_child().get_child().get_children()[1]
                if os.path.basename(xcf_file) == existing_label.get_text():
                    self.xcf_file_list_widget.remove(existing_file_element)
                    break

        except Exception as e:
            error_dialog = Gtk.MessageDialog(parent=self, flags=0, message_type=Gtk.MessageType.ERROR,
                                             buttons=Gtk.ButtonsType.OK, text=str(e))
            error_dialog.set_keep_above(True)
            error_dialog.run()
            error_dialog.destroy()

    def on_change_timeline(self, callback):
        self.update_project_timeline = callback

    def on_change_project_file(self, callback):
        self.update_project_file = callback

    def on_menu_new_xcf_file(self, menu_item):
        # first we build yet another dialog asking for width and height of the canvas in pixels
        # as well as the name of the file we want to create
        dialog = Gtk.Dialog(title="New Image", parent=self, flags=0)
        dialog.set_default_size(300, 200)

        content_area = dialog.get_content_area()
        content_area.set_spacing(10)
        content_area.set_border_width(10)

        # Create input fields for width, height, and file name
        width_entry = Gtk.Entry()
        height_entry = Gtk.Entry()
        file_name_entry = Gtk.Entry()

        # make 1024x1024 the default size
        width_entry.set_text("1024")
        height_entry.set_text("1024")

        content_area.pack_start(Gtk.Label(label="Width:"), False, False, 0)
        content_area.pack_start(width_entry, False, False, 0)
        content_area.pack_start(Gtk.Label(label="Height:"), False, False, 0)
        content_area.pack_start(height_entry, False, False, 0)
        content_area.pack_start(Gtk.Label(label="File Name:"), False, False, 0)
        content_area.pack_start(file_name_entry, False, False, 0)

        dialog.add_button(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL)
        dialog.add_button(Gtk.STOCK_OK, Gtk.ResponseType.OK)

        dialog.set_keep_above(True)

        dialog.show_all()
        response = dialog.run()

        width_value = width_entry.get_text()
        height_value = height_entry.get_text()
        file_name_value = file_name_entry.get_text()

        dialog.destroy()

        if response == Gtk.ResponseType.OK:
            try:
                width = int(width_value)
                height = int(height_value)
                file_name = file_name_value.strip()

                if not file_name:
                    raise ValueError("File name cannot be empty")

                if not file_name.endswith(".xcf"):
                    file_name = file_name + ".xcf"

                if width <= 0 or height <= 0:
                    raise ValueError("Invalid width or height")
                
                file_path = os.path.join(self.custom_xcf_file_folder, file_name)
                if os.path.exists(file_path):
                    raise ValueError(f"File {file_path} already exists")

                # Create a new blank image in GIMP
                gimp_image = Gimp.Image.new(width, height, Gimp.ImageBaseType.RGB)
                layer = Gimp.Layer.new(gimp_image, "Background", width, height, Gimp.ImageType.RGBA_IMAGE, 100, Gimp.LayerMode.NORMAL)
                gimp_image.insert_layer(layer, None, 0)
                layer.set_offsets(0,0)
                layer.set_opacity(100.0)
                layer.set_visible(True)

                # Save the image to the custom xcf file folder
                gfile = Gio.File.new_for_path(file_path)
                saved = Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, gimp_image, gfile, None)

                if not saved:
                    raise ValueError("Failed to create the new image file")

                # delete the gimp_image that we just created
                # since it has no display it has no problem being deleted
                Gimp.Image.delete(gimp_image)

                # Open the newly created image in GIMP and display it
                loaded_image = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, gfile)
                display = Gimp.Display.new(loaded_image)

                self.images_opened.append({
                    "image": loaded_image,
                    "display": display,
                    "file_path": file_path,
                    "xcf": True,
                })
                self.generate_preview_thumbnail_image(loaded_image)

                # Update the project timeline with the new XCF file
                self.update_xcf_file_list()
            except ValueError as e:
                error_dialog = Gtk.MessageDialog(parent=self, flags=0, message_type=Gtk.MessageType.ERROR,
                                                 buttons=Gtk.ButtonsType.OK, text=str(e))
                error_dialog.set_keep_above(True)
                error_dialog.run()
                error_dialog.destroy()

    def get_active_iter_text(self, combo_box):
        active_iter = combo_box.get_active_iter()
        if active_iter is None:
            return ""
        model = combo_box.get_model()
        if model is not None and active_iter is not None:
            return model[active_iter][1]
        return ""

    def on_menu_add_xcf_files(self, menu_item):
        # this function will add all currently open images in GIMP to the project
        # so as long as they are not already added, it will copy them to the custom xcf file folder
        # provided they are not already in that folder

        # first we generate a dialog asking the user to confirm adding an image with the ComboBox that uses
        # the image_model to show all currently open images in GIMP
        dialog = Gtk.Dialog(title="Add Open Image", parent=self, flags=0)
        dialog.set_default_size(300, 100)
        content_area = dialog.get_content_area()
        content_area.set_spacing(10)
        content_area.set_border_width(10)
        combo_box = Gtk.ComboBox.new_with_model(self.image_model)
        combo_box.set_entry_text_column(0)
        renderer_pixbuf = Gtk.CellRendererPixbuf()
        renderer_text = Gtk.CellRendererText()

        combo_box.pack_start(renderer_pixbuf, False)
        combo_box.add_attribute(renderer_pixbuf, "pixbuf", 2)
        combo_box.pack_start(renderer_text, True)
        combo_box.add_attribute(renderer_text, "text", 1)
        content_area.pack_start(Gtk.Label(label="Select an open image to add to the project:"), False, False, 0)
        content_area.pack_start(combo_box, False, False, 0)
        file_name_entry = Gtk.Entry()
        content_area.pack_start(file_name_entry, False, False, 0)
        combo_box.set_active(0)
        combo_box.connect("changed", lambda cb: file_name_entry.set_text(self.get_active_iter_text(cb)))
        file_name_entry.set_text(self.get_active_iter_text(combo_box))
        dialog.add_button(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL)
        dialog.add_button(Gtk.STOCK_OK, Gtk.ResponseType.OK)
        dialog.set_keep_above(True)
        dialog.show_all()
        response = dialog.run()
        selected_iter = combo_box.get_active_iter()
        file_name_value = file_name_entry.get_text()
        dialog.destroy()
        if response == Gtk.ResponseType.OK and selected_iter is not None:
            try:
                file_name = file_name_value.strip()

                if not file_name:
                    raise ValueError("File name cannot be empty")

                if not file_name.endswith(".xcf"):
                    file_name = file_name + ".xcf"

                file_path = os.path.join(self.custom_xcf_file_folder, file_name)

                id_of_image = self.image_model[selected_iter][0]
                gimp_image = Gimp.Image.get_by_id(id_of_image)
                gfile = Gio.File.new_for_path(file_path)
                Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, gimp_image, gfile, None)

                # Open the newly created image in GIMP and display it
                loaded_image = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, gfile)
                display = Gimp.Display.new(loaded_image)

                self.images_opened.append({
                    "image": loaded_image,
                    "display": display,
                    "file_path": file_path,
                    "xcf": True,
                })
                self.generate_preview_thumbnail_image(loaded_image)
                self.update_xcf_file_list([file_path])
            except ValueError as e:
                error_dialog = Gtk.MessageDialog(parent=self, flags=0, message_type=Gtk.MessageType.ERROR,
                                                 buttons=Gtk.ButtonsType.OK, text=str(e))
                error_dialog.set_keep_above(True)
                error_dialog.run()
                error_dialog.destroy()
                

    def on_menu_import_file(self, menu_item):
        # in this case we use a file chooser dialog to select an image file from disk
        dialog = Gtk.FileChooserNative(
            title="Import Image File",
            action=Gtk.FileChooserAction.OPEN,
            transient_for=self,
            accept_label="Open",
            cancel_label="Cancel",
        )
        imagefilter = Gtk.FileFilter()
        imagefilter.set_name("Image files")
        imagefilter.add_pattern("*.png")
        imagefilter.add_pattern("*.jpg")
        imagefilter.add_pattern("*.jpeg")
        imagefilter.add_pattern("*.bmp")
        imagefilter.add_pattern("*.tiff")
        imagefilter.add_pattern("*.gif")
        imagefilter.add_pattern("*.xcf")
        imagefilter.add_pattern("*.webp")
        dialog.add_filter(imagefilter)
        allfilter = Gtk.FileFilter()
        allfilter.set_name("All files")
        allfilter.add_pattern("*")
        dialog.add_filter(allfilter)
        
        dialog.set_modal(True)
        #dialog.set_keep_above(True)
        response = dialog.run()
        if response == Gtk.ResponseType.ACCEPT:
            file_path = dialog.get_filename()
            if file_path:
                self.on_import_file(file_path)

        dialog.destroy()

    def on_import_file(self, file_path):
        try:
            file_name = os.path.basename(file_path)
            # remove existing extension if any
            file_name = os.path.splitext(file_name)[0]
            filename_base = file_name
            file_name = file_name + ".xcf"
            dest_path = os.path.join(self.custom_xcf_file_folder, file_name)
            n = 1
            while os.path.exists(dest_path):
                dest_path = os.path.join(self.custom_xcf_file_folder, f"{filename_base}_{n}.xcf")
                n += 1
            gfile = Gio.File.new_for_path(file_path)
            loaded_image = Gimp.file_load(Gimp.RunMode.INTERACTIVE, gfile)
            if loaded_image is None:
                raise ValueError("Failed to load the selected image file")
            dest_gfile = Gio.File.new_for_path(dest_path)
            Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, loaded_image, dest_gfile, None)

            loaded_image.delete()

            loaded_image_final = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, dest_gfile)

            display = Gimp.Display.new(loaded_image_final)
            self.images_opened.append({
                "image": loaded_image_final,
                "display": display,
                "file_path": dest_path,
                "xcf": True,
            })
            self.generate_preview_thumbnail_image(loaded_image_final)
            self.update_xcf_file_list([dest_path])
        except ValueError as e:
            error_dialog = Gtk.MessageDialog(parent=self, flags=0, message_type=Gtk.MessageType.ERROR,
                                                     buttons=Gtk.ButtonsType.OK, text=str(e))
            error_dialog.set_keep_above(True)
            error_dialog.run()
            error_dialog.destroy()

    def update_xcf_file_list(self, update_specifically=None):
        # first we are going to list all xcf files in the custom xcf file folder
        xcf_files_in_folder = [f for f in os.listdir(self.custom_xcf_file_folder) if f.endswith(".xcf")]
        xcf_files = xcf_files_in_folder if update_specifically is None else [os.path.basename(f) for f in update_specifically]
        # then we will create a Gtk FlowBox to show them with thumbnails if available
        if not hasattr(self, 'xcf_file_list_widget'):
            project_file_label = Gtk.Label(label="XCF Files in Project:")
            project_file_label.set_margin_bottom(10)
            project_file_label.set_margin_top(20)
            #project_file_label.set_halign(Gtk.Align.START)
            # add a separator before the label
            self.internal_box.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0)
            self.internal_box.pack_start(project_file_label, False, False, 0)

            self.xcf_file_list_widget = Gtk.FlowBox()
            #ensure max width is only 600 pixels
            self.xcf_file_list_widget.set_column_spacing(10)
            self.xcf_file_list_widget.set_row_spacing(10)

            self.internal_box.pack_start(self.xcf_file_list_widget, True, True, 0)
            xcf_files = xcf_files_in_folder
        
        global DEFAULT_THUMBNAIL
        if DEFAULT_THUMBNAIL is None:
            # create an icon pixbuf for the default thumbnail
            DEFAULT_THUMBNAIL = Pixbuf.new_from_file_at_scale(
                os.path.join(
                    os.path.dirname(os.path.abspath(__file__)),
                    "icons",
                    "gimp.png"
                ),
                100,
                100,
                True
            )
        
        for xcf_file in xcf_files:
            thumbnail_path = os.path.splitext(os.path.join(self.custom_xcf_file_folder, xcf_file))[0] + "_thumbnail.png"
            thumbnail = DEFAULT_THUMBNAIL
            if os.path.exists(thumbnail_path):
                thumbnail = Pixbuf.new_from_file_at_scale(thumbnail_path, 100, 100, True)
            # first let's see if we already have this file in the list box
            existing_file_element = None
            for file_element in self.xcf_file_list_widget.get_children():
                label = file_element.get_child().get_child().get_children()[1]
                if label.get_text() == xcf_file:
                    existing_file_element = file_element
                    break
            if existing_file_element is not None:
                # If we found an existing file element, we can update it
                existing_file_element.get_child().get_child().get_children()[0].set_from_pixbuf(thumbnail)
            else:
                # If not, we need to create a new row
                # we need to be sure it is added in alphabetical order
                new_file_element_event_box = Gtk.EventBox()
                new_file_element = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
                new_file_element.set_margin_top(10)
                new_file_element.set_margin_bottom(10)
                new_file_element.set_margin_start(10)
                new_file_element.set_margin_end(10)
                new_file_element.pack_start(Gtk.Image.new_from_pixbuf(thumbnail), False, False, 0)
                new_file_element.pack_start(Gtk.Label(label=xcf_file), False, False, 0)
                new_file_element_event_box.add(new_file_element)

                inserted = False
                for i, existing_file_element in enumerate(self.xcf_file_list_widget.get_children()):
                    existing_label = existing_file_element.get_child().get_child().get_children()[1]
                    if xcf_file < existing_label.get_text():
                        self.xcf_file_list_widget.insert(new_file_element_event_box, i)
                        inserted = True
                        break
                if not inserted:
                    self.xcf_file_list_widget.add(new_file_element_event_box)

                # add an event on double click to open the xcf file in GIMP
                def on_xcf_file_double_click(widget, event, xcf_file=os.path.join(self.custom_xcf_file_folder, xcf_file)):
                    if event.type == Gdk.EventType._2BUTTON_PRESS and event.button == Gdk.BUTTON_PRIMARY:
                        self.open_xcf_file(xcf_file)
                    elif event.type == Gdk.EventType.BUTTON_PRESS and event.button == Gdk.BUTTON_SECONDARY:
                        # set the flowbox selection to this item
                        self.xcf_file_list_widget.select_child(widget.get_parent())
                        # Right-click detected, show context menu
                        menu = Gtk.Menu()

                        open_file_menu_item = Gtk.MenuItem(label="Open XCF File")
                        open_file_menu_item.connect("activate", lambda item: self.open_xcf_file(xcf_file))
                        menu.append(open_file_menu_item)

                        # add a horizontal separator
                        separator = Gtk.SeparatorMenuItem()
                        menu.append(separator)

                        menu_item_delete = Gtk.MenuItem(label="Delete XCF File")
                        menu_item_delete.connect("activate", lambda item: self.delete_xcf_file(xcf_file))
                        menu.append(menu_item_delete)
                        menu.show_all()
                        menu.popup_at_pointer(event)

                new_file_element_event_box.connect("button-press-event", on_xcf_file_double_click)

        self.xcf_file_list_widget.show_all()

    def generate_preview_thumbnail_image(self, image):
        xcf_file = image.get_xcf_file()
        if xcf_file is None:
            return False
        xcf_file_path = xcf_file.get_path()
        if xcf_file_path is None:
            return False
        thumbnail_pixbuf = image.get_thumbnail(200, 200, Gimp.PixbufTransparency.KEEP_ALPHA)
        if thumbnail_pixbuf is None:
            return False
        thumbnail_file_path = os.path.splitext(xcf_file_path)[0] + "_thumbnail.png"
        success, bytes = thumbnail_pixbuf.save_to_bufferv("png", [], [])

        if not success:
            return False

        # compare to existing file if it exists
        if os.path.exists(thumbnail_file_path):
            existing_bytes = None
            with open(thumbnail_file_path, "rb") as f:
                existing_bytes = f.read()
            if existing_bytes == bytes:
                return False # no need to update
            
        with open(thumbnail_file_path, "wb") as f:
            f.write(bytes)

        return True
    
    def open_timeline_file_as_image(self, timeline_file_path):
        # NOTE, does not work because GIMP does not set the overwrite path correctly
        # left here for reference as the functionality was implemented
        if not os.path.exists(timeline_file_path):
            raise ValueError(f"File {timeline_file_path} does not exist")
        gfile = Gio.File.new_for_path(timeline_file_path)
        loaded_image = Gimp.file_load(Gimp.RunMode.INTERACTIVE, gfile)
        if loaded_image is None:
            raise ValueError(f"Failed to load the image file {timeline_file_path}")
        display = Gimp.Display.new(loaded_image)
        self.images_opened.append({
            "image": loaded_image,
            "display": display,
            "file_path": timeline_file_path,
            "xcf": False,
        })
    
    def open_xcf_file(self, xcf_file_path):
        if not os.path.exists(xcf_file_path):
            raise ValueError(f"File {xcf_file_path} does not exist")
        gfile = Gio.File.new_for_path(xcf_file_path)
        loaded_image = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, gfile)
        if loaded_image is None:
            raise ValueError(f"Failed to load the image file {xcf_file_path}")
        display = Gimp.Display.new(loaded_image)
        self.images_opened.append({
            "image": loaded_image,
            "display": display,
            "file_path": xcf_file_path,
            "xcf": True,
        })
        self.generate_preview_thumbnail_image(loaded_image)
        self.update_xcf_file_list([xcf_file_path])

    def remove_invalid_images(self):
        valid_images = []
        for img in self.images_opened:
            image = img["image"]
            is_valid = False
            try:
                is_valid = image.is_valid()
            except Exception:
                pass

            if is_valid:
                valid_images.append(img)

        self.images_opened = valid_images

    def update_timeline_thumbnail(self, timeline_file):
        # check if the image extension is SUPPORTED_IMAGE_EXTENSIONS
        extension_with_dot = os.path.splitext(timeline_file)[1].lower()
        if extension_with_dot in SUPPORTED_IMAGE_EXTENSIONS:
            # now we need to update the timeline file image
            # for that we need to build a pixbuf from the image
            image_pixbuf = Pixbuf.new_from_file_at_scale(timeline_file, 100, 100, True)
            if image_pixbuf is not None:
                # now we need to find the corresponding timeline file element
                # in our ui
                for file_element in self.timeline_file_list_widget.get_children():
                    label = file_element.get_child().get_child().get_children()[1]
                    if label.get_text() == os.path.basename(timeline_file):
                        file_element.get_child().get_child().get_children()[0].set_from_pixbuf(image_pixbuf)
                        break

    def refresh_non_dirty_images(self, widget=None, event=None):
        self.remove_invalid_images()
        clean_images = [img for img in self.images_opened if not img["image"].is_dirty()]
        updated_xcf_files = []
        global SUPPORTED_IMAGE_EXTENSIONS
        for img in clean_images:
            if img["xcf"] is not True:
                self.update_timeline_thumbnail(img["file_path"])
                continue
            updated = self.generate_preview_thumbnail_image(img["image"])
            if updated:
                updated_xcf_files.append(img["image"].get_xcf_file().get_path())
        if len(updated_xcf_files) > 0:
            self.update_xcf_file_list(updated_xcf_files)

    def cleanup_opened_files(self):
        self.remove_invalid_images()
        for img in self.images_opened:
            image = img["image"]
            do_not_close = False
            if image.is_dirty() and image.get_file():
                # prompt a dialog to save the image before closing, options are Yes, Discard Changes, Cancel
                dialog = Gtk.MessageDialog(
                    parent=self,
                    flags=0,
                    message_type=Gtk.MessageType.QUESTION,
                    buttons=Gtk.ButtonsType.NONE,
                    text=f"The image '{image.get_name()}' has unsaved changes. Do you want to save them before closing?",
                )
                dialog.add_button(Gtk.STOCK_YES, Gtk.ResponseType.YES)
                dialog.add_button(Gtk.STOCK_DISCARD, Gtk.ResponseType.NO)
                dialog.add_button(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL)

                dialog.set_keep_above(True)

                response = dialog.run()
                dialog.destroy()

                if response == Gtk.ResponseType.YES:
                    # Save the image
                    Gimp.file_save(Gimp.RunMode.INTERACTIVE, image, image.get_file(), None)
                    self.generate_preview_thumbnail_image(image)
                elif response == Gtk.ResponseType.CANCEL:
                    do_not_close = True
                else:
                    pass # Discard changes and close
            elif image.is_dirty() and not image.get_file():
                # weird but ok
                do_not_close = True

            # update the thumbnail if not dirty anyway just in case
            # maybe the user closed the image and saved it manually
            # so we want to be sure the thumbnail is up to date
            elif img["xcf"] is True:
                self.generate_preview_thumbnail_image(image)

            if not do_not_close:
                delete_succeeded = Gimp.Display.delete(img["display"])

                if delete_succeeded:
                    Gimp.Image.delete(img["image"])

        self.images_opened = []

    def cleanup(self):
        if threading.current_thread() is threading.main_thread():
            self.cleanup_opened_files()
        else:
            GLib.idle_add(self.cleanup_opened_files)