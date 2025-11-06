import os
from gi.repository import Gimp, Gtk, GLib, Gdk # type: ignore
from gi.repository.GdkPixbuf import Pixbuf # type: ignore
from gi.repository import Gio # type: ignore
import threading
from frame_by_frame import FrameByFrameVideoVideoViewer
from shutil import copyfile, rmtree

import sys
import subprocess

import gettext
textdomain = "gimp30-python"
gettext.textdomain(textdomain)
_ = gettext.gettext

DEFAULT_THUMBNAIL = None
UNKNOWN_THUMBNAIL = None

import gettext
_ = gettext.gettext

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

SUPPORTED_VIDEO_EXTENSIONS = [
    ".mp4",
    ".avi",
    ".mkv",
    ".webm",
    ".flv"
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
        self.project_type = project_file_contents.get("project_type", "")

        self.images_opened = []

        self.custom_project_file_folder = os.path.join(self.project_folder, "project_files")

        self.tools_object = parent

        if not os.path.exists(self.custom_project_file_folder):
            os.makedirs(self.custom_project_file_folder)

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
        menu_item_new = Gtk.MenuItem(label=_("New empty image"))
        menu_item_new.connect("activate", self.on_menu_new_xcf_file)
        menu.append(menu_item_new)
        menu_item_add = Gtk.MenuItem(label=_("New image from open images"))
        menu_item_add.connect("activate", self.on_menu_add_xcf_files)
        menu.append(menu_item_add)
        menu_item_import = Gtk.MenuItem(label=_("Import image from file"))
        menu_item_import.connect("activate", self.on_menu_import_file)
        menu.append(menu_item_import)

        menu_button.set_popup(menu)
        menu.show_all()

        Gtk.Window.connect(self, "focus-in-event", on_focus_dialog)
        Gtk.Window.connect(self, "focus-in-event", self.refresh_non_dirty_images)

        self.set_keep_above(True)

        # Add more widgets to display and edit project data as needed
        self.rebuild_timeline_ui()
        self.update_project_file_list()
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
            column = Gtk.TreeViewColumn(_("Timelines"), renderer, text=0)
            self.timeline_tree_widget.append_column(column)
            self.timeline_tree_widget.set_headers_visible(False)
            self.timeline_tree_widget.set_size_request(200, 300)
            self.timeline_tree_widget.get_selection().set_mode(Gtk.SelectionMode.SINGLE)
            self.timeline_tree_widget.get_selection().connect("changed", self.on_timeline_selection_changed)
            timelines_label = Gtk.Label(label=_("Project Timelines:"))
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
                                menu_item_rename = Gtk.MenuItem(label=_("Rename Timeline"))
                                def on_rename_activate(menu_item):
                                    self.rename_timeline(timeline_id)
                                menu_item_rename.connect("activate", on_rename_activate)
                                menu.append(menu_item_rename)

                                menu_item_delete = Gtk.MenuItem(label=_("Delete Timeline"))
                                def on_delete_activate(menu_item):
                                    self.delete_timeline(timeline_id)
                                menu_item_delete.connect("activate", on_delete_activate)
                                menu.append(menu_item_delete)

                                menu_item_delete_keep_children = Gtk.MenuItem(label=_("Delete Timeline and Keep Children"))
                                def on_delete_keep_children_activate(menu_item):
                                    self.delete_timeline(timeline_id, keep_children=True)
                                menu_item_delete_keep_children.connect("activate", on_delete_keep_children_activate)
                                menu.append(menu_item_delete_keep_children)

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
        # NO you cannot do this because of GTK bugs with tree stores
        # for timeline_id in list(existing_timelines.keys()):
        #    found = False
        #    for timeline in timeline_values:
        #        if timeline.get("id", None) == timeline_id:
        #            found = True
        #            break
        #    if not found:
        #        self.timeline_tree_store.remove(existing_timelines[timeline_id])
        #        del existing_timelines[timeline_id]

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

    def save_file_as(self, timeline_file_path):
        dialog = Gtk.FileChooserDialog(
            title=_("Save File As"),
            parent=self,
            action=Gtk.FileChooserAction.SAVE,
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL,
            Gtk.ResponseType.CANCEL,
            Gtk.STOCK_SAVE,
            Gtk.ResponseType.OK,
        )
        dialog.set_default_size(600, 400)
        dialog.set_current_name(os.path.basename(timeline_file_path))
        dialog.set_keep_above(True)
        dialog.set_modal(True)

        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            destination_path = dialog.get_filename()
            try:
                copyfile(timeline_file_path, destination_path)
            except Exception as e:
                error_dialog = Gtk.MessageDialog(
                    parent=self,
                    flags=0,
                    message_type=Gtk.MessageType.ERROR,
                    buttons=Gtk.ButtonsType.CLOSE,
                    text=_("Error saving file: {}").format(str(e)),
                )
                error_dialog.set_keep_above(True)
                error_dialog.set_modal(True)
                error_dialog.run()
                error_dialog.destroy()
        dialog.destroy()

    def rebuild_timeline_files(self):
        # then we will create a Gtk FlowBox to show them with thumbnails if available
        if not hasattr(self, 'timeline_file_list_widget'):
            project_timeline_label = Gtk.Label(label=_("Timeline Files:"))
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

        if self.project_current_timeline_folder is None:
            return
        
        timeline_files_folder = os.path.join(self.project_current_timeline_folder, "files")
        timeline_files = []
        if os.path.exists(timeline_files_folder) and os.path.isdir(timeline_files_folder):
            timeline_files = [
                f for f in os.listdir(timeline_files_folder)
                if os.path.isfile(os.path.join(timeline_files_folder, f)) and
                not f.endswith(".thumbnail") and
                not f.startswith("_")
            ]

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
            elif os.path.exists(os.path.join(timeline_files_folder, os.path.splitext(timeline_file)[0] + ".thumbnail")):
                thumbnail_path = os.path.join(timeline_files_folder, os.path.splitext(timeline_file)[0] + ".thumbnail")
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
                        menu_item_open = Gtk.MenuItem(label=_("Open File"))
                        menu_item_open.connect("activate", lambda item: open_file_with_default_app(timeline_file_path))
                        menu.append(menu_item_open)

                        menu_item_save_as = Gtk.MenuItem(label=_("Save File As..."))
                        menu_item_save_as.connect("activate", lambda item: self.save_file_as(timeline_file_path))
                        menu.append(menu_item_save_as)

                        if extension_with_dot in SUPPORTED_GIMP_OPENABLE_IMAGE_EXTENSIONS:
                            # NOTE does not work due to GIMP not setting the overwrite path correctly
                            #menu_item_open_gimp = Gtk.MenuItem(label="Open in GIMP")
                            #menu_item_open_gimp.connect("activate", lambda item: self.open_timeline_file_as_image(timeline_file_path))
                            #menu.append(menu_item_open_gimp)

                            menu_item_overwrite = Gtk.MenuItem(label=_("Overwrite with Reference Image"))
                            menu_item_overwrite.connect("activate", lambda item: self.overwrite_timeline_file_with_reference_image(timeline_file_path))
                            menu.append(menu_item_overwrite)

                            menu_item_import = Gtk.MenuItem(label=_("Import as project XCF image"))
                            menu_item_import.connect("activate", lambda item: self.on_import_file(timeline_file_path))
                            menu.append(menu_item_import)

                        if extension_with_dot in SUPPORTED_VIDEO_EXTENSIONS:
                            menu_item_extract_frames = Gtk.MenuItem(label=_("Open in Frame by Frame Viewer"))
                            menu_item_extract_frames.connect("activate", lambda item: self.open_frame_by_frame_viewer(timeline_file_path))
                            menu.append(menu_item_extract_frames)

                        menu_item_add_to_project = Gtk.MenuItem(label=_("Add to Project Files"))
                        menu_item_add_to_project.connect("activate", lambda item: self.add_timeline_file_to_project(timeline_file_path))
                        menu.append(menu_item_add_to_project)

                        # add a horizontal separator
                        separator = Gtk.SeparatorMenuItem()
                        menu.append(separator)

                        menu_item_delete = Gtk.MenuItem(label=_("Delete File"))
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
        dialog = Gtk.Dialog(title=_("Rename Timeline"), parent=self, flags=0)
        dialog.set_keep_above(True)
        dialog.set_default_size(300, 100)
        content_area = dialog.get_content_area()
        content_area.set_spacing(10)
        content_area.set_border_width(10)
        entry = Gtk.Entry()
        entry.set_text(timeline_in_question.get("name", ""))
        content_area.pack_start(Gtk.Label(label=_("New name:")), False, False, 0)
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

    def actually_delete_timeline(self, timeline_id, keep_children=False, is_root_call=True):
        deleted_current_timeline = timeline_id == self.project_file_contents.get("current_timeline", None)
        own_timeline_object = self.project_file_contents.get("timelines", {}).pop(timeline_id, None)

        if not keep_children:
            for existing_timeline_element in self.project_file_contents.get("timelines", {}).copy().values():
                if existing_timeline_element.get("parent_id", None) == timeline_id:
                    that_deleted_current_timeline = self.actually_delete_timeline(existing_timeline_element.get("id", None), keep_children=keep_children, is_root_call=False)
                    if that_deleted_current_timeline:
                        deleted_current_timeline = True

            if is_root_call and deleted_current_timeline:
                new_current_timeline = own_timeline_object.get("parent_id", None)
                self.project_file_contents["current_timeline"] = new_current_timeline
        else:
            own_parent_id = own_timeline_object.get("parent_id", None)
            new_current_timeline = None
            # need to reparent children to the deleted timeline's parent
            for existing_timeline_element_key, existing_timeline_element in self.project_file_contents.get("timelines", {}).items():
                if existing_timeline_element.get("parent_id", None) == timeline_id:
                    if not new_current_timeline:
                        new_current_timeline = existing_timeline_element.get("id", None)
                    self.project_file_contents["timelines"] = self.project_file_contents["timelines"].copy()
                    self.project_file_contents["timelines"][existing_timeline_element_key] = self.project_file_contents["timelines"][existing_timeline_element_key].copy()
                    self.project_file_contents["timelines"][existing_timeline_element_key]["parent_id"] = own_parent_id
                    if own_parent_id is None:
                        self.project_file_contents["timelines"][existing_timeline_element_key]["initial"] = True

            if new_current_timeline is not None:
                self.project_file_contents["current_timeline"] = new_current_timeline

        if self.project_file_contents["current_timeline"] is None:
            # set to any existing initial timeline if available
            for existing_timeline_element in self.project_file_contents.get("timelines", {}).values():
                if existing_timeline_element.get("initial", False):
                    self.project_file_contents["current_timeline"] = existing_timeline_element.get("id", None)
                    break

        GTK_BUG_WORKAROUND = self.project_file_contents # workaround for GTK messing up with the data in the project file contents

        # delete from the tree store
        if keep_children:
            # still delete the children due to bugs in GTK we need to rebuild the entire timeline tree UI
            # delete everything in timeline_tree_store and rebuild from scratch
            self.timeline_tree_store.clear()
        else:
            # we need to delete all children from the tree store as well
            # we delete everything because GTK is a bit buggy with tree stores
            self.timeline_tree_store.clear()

        # delete the timeline directory and all its contents
        timeline_folder = os.path.join(self.project_folder, "timelines", timeline_id)
        if os.path.exists(timeline_folder) and os.path.isdir(timeline_folder):
            rmtree(timeline_folder)

        self.project_file_contents = GTK_BUG_WORKAROUND

        return deleted_current_timeline

    def delete_timeline(self, timeline_id, keep_children=False):
        timeline_in_question = self.project_file_contents.get("timelines", {}).get(timeline_id, None)
        if timeline_in_question is None:
            return
        # first we must ask for confirmation
        dialog = Gtk.MessageDialog(parent=self, flags=0, message_type=Gtk.MessageType.QUESTION,
                                   buttons=Gtk.ButtonsType.YES_NO, text=_("Are you sure you want to delete the timeline {}? this action cannot be reversed and will delete any timeline files associated with it").format(timeline_in_question.get('name', _('unknown'))))
        dialog.set_keep_above(True)
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.YES:
            # make a shallow copy of the project file contents and update the current timeline
            # that is because this is a dict and we want to avoid mutating the original one
            # that is a reference to the one in the tools.py
            self.project_file_contents = self.project_file_contents.copy()

            self.actually_delete_timeline(timeline_id, keep_children=keep_children)
            self.update_project_file(self.project_file_contents)
            self.rebuild_timeline_ui()
        
    def on_close(self, callback):
        self.connect("response", lambda dialog, response: callback() or self.destroy() or self.cleanup())

    def overwrite_timeline_file_with_reference_image(self, timeline_file):
        # first we set a dialog to select from the currently open images in GIMP
        dialog = Gtk.Dialog(title=_("Select Reference Image"), parent=self, flags=0)
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
        content_area.pack_start(Gtk.Label(label=_("Select an open image to use as reference:")), False, False, 0)
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
                    raise ValueError(_("Failed to get the selected image"))
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
                                                 buttons=Gtk.ButtonsType.OK, text=_("Cannot delete {} because it is currently open in GIMP.").format(timeline_file))
                error_dialog.set_keep_above(True)
                error_dialog.run()
                error_dialog.destroy()
                break

        # make a dialog asking the user to confirm deletion
        dialog = Gtk.MessageDialog(parent=self, flags=0, message_type=Gtk.MessageType.QUESTION,
                                   buttons=Gtk.ButtonsType.YES_NO, text=_("Are you sure you want to delete {}? this action cannot be reversed and may corrupt the timeline").format(timeline_file))
        dialog.set_keep_above(True)

        response = dialog.run()
        dialog.destroy()

        if response != Gtk.ResponseType.YES:
            return
        
        try:
            os.remove(timeline_file)
            thumbnail_path = os.path.splitext(timeline_file)[0] + ".thumbnail"
            if os.path.exists(thumbnail_path):
                os.remove(thumbnail_path)
            
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

    def rename_project_file(self, project_file):
        # before doing this check if the file is open in GIMP
        for opened in self.images_opened:
            if opened["file_path"] == project_file:
                # refuse to rename the file if it is open in GIMP
                error_dialog = Gtk.MessageDialog(parent=self, flags=0, message_type=Gtk.MessageType.ERROR,
                                                 buttons=Gtk.ButtonsType.OK, text=_("Cannot rename {} because it is currently open in GIMP.").format(project_file))
                error_dialog.set_keep_above(True)
                error_dialog.run()
                error_dialog.destroy()
                return

        # create a dialog to ask for the new name
        dialog = Gtk.Dialog(title=_("Rename Project File"), parent=self, flags=0)
        dialog.set_default_size(300, 100)
        content_area = dialog.get_content_area()
        content_area.set_spacing(10)
        content_area.set_border_width(10)
        entry = Gtk.Entry()
        entry.set_text(os.path.splitext(os.path.basename(project_file))[0])
        content_area.pack_start(Gtk.Label(label=_("New name:")), False, False, 0)
        content_area.pack_start(entry, False, False, 0)
        dialog.add_button(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL)
        dialog.add_button(Gtk.STOCK_OK, Gtk.ResponseType.OK)
        dialog.set_keep_above(True)
        dialog.set_modal(True)
        dialog.show_all()

        extension_with_dot = os.path.splitext(project_file)[1]

        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            new_name = entry.get_text().strip() + extension_with_dot
            if new_name != "":
                new_path = os.path.join(self.custom_project_file_folder, new_name)
                if new_path != project_file:
                    if os.path.exists(new_path):
                        error_dialog = Gtk.MessageDialog(parent=self, flags=0, message_type=Gtk.MessageType.ERROR,
                                                         buttons=Gtk.ButtonsType.OK, text=_("File {} already exists").format(new_path))
                        error_dialog.set_keep_above(True)
                        error_dialog.run()
                        error_dialog.destroy()
                    else:
                        try:
                            os.rename(project_file, new_path)
                            # also rename the thumbnail if it exists
                            old_thumbnail_path = os.path.splitext(project_file)[0] + "_thumbnail.png"
                            if os.path.exists(old_thumbnail_path):
                                new_thumbnail_path = os.path.splitext(new_path)[0] + "_thumbnail.png"
                                os.rename(old_thumbnail_path, new_thumbnail_path)

                            # update the project file list UI
                            for existing_file_element in self.project_files_list_widget.get_children():
                                existing_label = existing_file_element.get_child().get_child().get_children()[1]
                                if os.path.basename(project_file) == existing_label.get_text():
                                    existing_label.set_text(new_name)
                                    break

                        except Exception as e:
                            error_dialog = Gtk.MessageDialog(parent=self, flags=0, message_type=Gtk.MessageType.ERROR,
                                                             buttons=Gtk.ButtonsType.OK, text=str(e))
                            error_dialog.set_keep_above(True)
                            error_dialog.run()
                            error_dialog.destroy()
            else:
                error_dialog = Gtk.MessageDialog(parent=self, flags=0, message_type=Gtk.MessageType.ERROR,
                                                 buttons=Gtk.ButtonsType.OK, text=_("File name cannot be empty"))
                error_dialog.set_keep_above(True)
                error_dialog.run()
                error_dialog.destroy()

        dialog.destroy()

    def delete_project_file(self, project_file):
        # first let's check if the file is open in GIMP
        for opened in self.images_opened:
            if opened["file_path"] == project_file:
                # refuse to delete the file if it is open in GIMP
                error_dialog = Gtk.MessageDialog(parent=self, flags=0, message_type=Gtk.MessageType.ERROR,
                                                 buttons=Gtk.ButtonsType.OK, text=_("Cannot delete {} because it is currently open in GIMP.").format(project_file))
                error_dialog.set_keep_above(True)
                error_dialog.run()
                error_dialog.destroy()
                break

        # make a dialog asking the user to confirm deletion
        dialog = Gtk.MessageDialog(parent=self, flags=0, message_type=Gtk.MessageType.QUESTION,
                                   buttons=Gtk.ButtonsType.YES_NO, text=_("Are you sure you want to delete {}? this action cannot be reversed").format(project_file))
        dialog.set_keep_above(True)

        response = dialog.run()
        dialog.destroy()

        if response != Gtk.ResponseType.YES:
            return

        try:
            # send it to the recycling bin or whatever the OS uses
            os.remove(project_file)
            thumbnail_path = os.path.splitext(project_file)[0] + "_thumbnail.png"
            if os.path.exists(thumbnail_path):
                os.remove(thumbnail_path)
            
            for i, existing_file_element in enumerate(self.project_files_list_widget.get_children()):
                existing_label = existing_file_element.get_child().get_child().get_children()[1]
                if os.path.basename(project_file) == existing_label.get_text():
                    self.project_files_list_widget.remove(existing_file_element)
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
        dialog = Gtk.Dialog(title=_("New Image"), parent=self, flags=0)
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

        content_area.pack_start(Gtk.Label(label=_("Width:")), False, False, 0)
        content_area.pack_start(width_entry, False, False, 0)
        content_area.pack_start(Gtk.Label(label=_("Height:")), False, False, 0)
        content_area.pack_start(height_entry, False, False, 0)
        content_area.pack_start(Gtk.Label(label=_("File Name:")), False, False, 0)
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
                    raise ValueError(_("File name cannot be empty"))

                if not file_name.endswith(".xcf"):
                    file_name = file_name + ".xcf"

                if width <= 0 or height <= 0:
                    raise ValueError(_("Invalid width or height"))
                
                file_path = os.path.join(self.custom_project_file_folder, file_name)
                if os.path.exists(file_path):
                    raise ValueError(_("File {} already exists").format(file_path))

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
                    raise ValueError(_("Failed to create the new image file"))

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
                self.update_project_file_list()
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
        dialog = Gtk.Dialog(title=_("Add Open Image"), parent=self, flags=0)
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
        content_area.pack_start(Gtk.Label(label=_("Select an open image to add to the project:")), False, False, 0)
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
                    raise ValueError(_("File name cannot be empty"))

                if not file_name.endswith(".xcf"):
                    file_name = file_name + ".xcf"

                file_path = os.path.join(self.custom_project_file_folder, file_name)

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
                self.update_project_file_list([file_path])
            except ValueError as e:
                error_dialog = Gtk.MessageDialog(parent=self, flags=0, message_type=Gtk.MessageType.ERROR,
                                                 buttons=Gtk.ButtonsType.OK, text=str(e))
                error_dialog.set_keep_above(True)
                error_dialog.run()
                error_dialog.destroy()
                

    def on_menu_import_file(self, menu_item):
        # in this case we use a file chooser dialog to select an image file from disk
        dialog = Gtk.FileChooserNative(
            title=_("Import Image File"),
            action=Gtk.FileChooserAction.OPEN,
            transient_for=self,
            accept_label=_("Open"),
            cancel_label=_("Cancel"),
        )
        imagefilter = Gtk.FileFilter()
        imagefilter.set_name(_("Image files"))
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
        allfilter.set_name(_("All files"))
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

    def open_frame_by_frame_viewer(self, video_file_path):
        if not hasattr(self, 'open_viewers'):
            self.open_viewers = {}
        if video_file_path in self.open_viewers:
            existing_viewer = self.open_viewers[video_file_path]
            existing_viewer.present()
            return
        viewer = FrameByFrameVideoVideoViewer(video_file_path, parent=self, project_files_path=self.custom_project_file_folder, project_type=self.project_type, tools_object=self.tools_object)
        viewer.show_all()
        viewer.present()
        viewer.on_close(lambda: self.close_frame_by_frame_viewer(video_file_path, viewer))
        self.open_viewers[video_file_path] = viewer

    def close_frame_by_frame_viewer(self, video_file_path, viewer):
        if video_file_path in self.open_viewers:
            del self.open_viewers[video_file_path]

    def add_timeline_file_to_project(self, timeline_file):
        try:
            file_name = os.path.basename(timeline_file)
            dest_path = os.path.join(self.custom_project_file_folder, file_name)
            n = 2
            while os.path.exists(dest_path):
                dest_path = os.path.join(self.custom_project_file_folder, f"{os.path.splitext(file_name)[0]}_{n}{os.path.splitext(file_name)[1]}")
                n += 1
            copyfile(timeline_file, dest_path)
            thumbnail_path = os.path.splitext(timeline_file)[0] + ".thumbnail"
            if os.path.exists(thumbnail_path):
                copyfile(thumbnail_path, os.path.splitext(dest_path)[0] + ".thumbnail")
            self.update_project_file_list([dest_path])
        except Exception as e:
            error_dialog = Gtk.MessageDialog(parent=self, flags=0, message_type=Gtk.MessageType.ERROR,
                                             buttons=Gtk.ButtonsType.OK, text=str(e))
            error_dialog.set_keep_above(True)
            error_dialog.run()
            error_dialog.destroy()

    def on_import_file(self, file_path):
        try:
            file_name = os.path.basename(file_path)
            # remove existing extension if any
            file_name = os.path.splitext(file_name)[0]
            filename_base = file_name
            file_name = file_name + ".xcf"
            dest_path = os.path.join(self.custom_project_file_folder, file_name)
            n = 2
            while os.path.exists(dest_path):
                dest_path = os.path.join(self.custom_project_file_folder, f"{filename_base}_{n}.xcf")
                n += 1
            gfile = Gio.File.new_for_path(file_path)
            loaded_image = Gimp.file_load(Gimp.RunMode.INTERACTIVE, gfile)
            if loaded_image is None:
                raise ValueError(_("Failed to load the selected image file"))
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
            self.update_project_file_list([dest_path])
        except ValueError as e:
            error_dialog = Gtk.MessageDialog(parent=self, flags=0, message_type=Gtk.MessageType.ERROR,
                                                     buttons=Gtk.ButtonsType.OK, text=str(e))
            error_dialog.set_keep_above(True)
            error_dialog.run()
            error_dialog.destroy()

    def update_project_file_list(self, update_specifically=None):
        # first we are going to list all project files in the custom project file folder
        project_files_in_folder = [
            f for f in os.listdir(self.custom_project_file_folder)
            if os.path.isfile(os.path.join(self.custom_project_file_folder, f)) and
            not f.endswith(".thumbnail")
        ]
        project_files = project_files_in_folder if update_specifically is None else [os.path.basename(f) for f in update_specifically]
        # then we will create a Gtk FlowBox to show them with thumbnails if available
        if not hasattr(self, 'project_files_list_widget'):
            project_file_label = Gtk.Label(label=_("Project Files:"))
            project_file_label.set_margin_bottom(10)
            project_file_label.set_margin_top(20)
            #project_file_label.set_halign(Gtk.Align.START)
            # add a separator before the label
            self.internal_box.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0)
            self.internal_box.pack_start(project_file_label, False, False, 0)

            self.project_files_list_widget = Gtk.FlowBox()
            #ensure max width is only 600 pixels
            self.project_files_list_widget.set_column_spacing(10)
            self.project_files_list_widget.set_row_spacing(10)

            self.internal_box.pack_start(self.project_files_list_widget, True, True, 0)
            project_files = project_files_in_folder

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
        for project_file in project_files:
            thumbnail_path = os.path.splitext(os.path.join(self.custom_project_file_folder, project_file))[0] + ".thumbnail"
            thumbnail = UNKNOWN_THUMBNAIL
            extension_with_dot = os.path.splitext(project_file)[1].lower()
            if extension_with_dot in SUPPORTED_IMAGE_EXTENSIONS:
                thumbnail = Pixbuf.new_from_file_at_scale(os.path.join(self.custom_project_file_folder, project_file), 100, 100, True)
            elif os.path.exists(thumbnail_path):
                thumbnail = Pixbuf.new_from_file_at_scale(thumbnail_path, 100, 100, True)
            elif extension_with_dot in EXTENSIONS_THUMBNAILS_CACHE:
                thumbnail = EXTENSIONS_THUMBNAILS_CACHE[extension_with_dot]
            elif extension_with_dot in EXTENSIONS_THUMBNAILS:
                thumbnail = Pixbuf.new_from_file_at_scale(os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons", EXTENSIONS_THUMBNAILS[extension_with_dot]), 100, 100, True)
                EXTENSIONS_THUMBNAILS_CACHE[extension_with_dot] = thumbnail
                
            # first let's see if we already have this file in the list box
            existing_file_element = None
            for file_element in self.project_files_list_widget.get_children():
                label = file_element.get_child().get_child().get_children()[1]
                if label.get_text() == project_file:
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
                new_file_element.pack_start(Gtk.Label(label=project_file), False, False, 0)
                new_file_element_event_box.add(new_file_element)

                inserted = False
                for i, existing_file_element in enumerate(self.project_files_list_widget.get_children()):
                    existing_label = existing_file_element.get_child().get_child().get_children()[1]
                    if project_file < existing_label.get_text():
                        self.project_files_list_widget.insert(new_file_element_event_box, i)
                        inserted = True
                        break
                if not inserted:
                    self.project_files_list_widget.add(new_file_element_event_box)

                if project_file.endswith(".xcf"):
                    # add an event on double click to open the xcf file in GIMP
                    def on_xcf_file_double_click(widget, event, xcf_file=os.path.join(self.custom_project_file_folder, project_file)):
                        if event.type == Gdk.EventType._2BUTTON_PRESS and event.button == Gdk.BUTTON_PRIMARY:
                            self.open_xcf_file(xcf_file)
                        elif event.type == Gdk.EventType.BUTTON_PRESS and event.button == Gdk.BUTTON_SECONDARY:
                            # set the flowbox selection to this item
                            self.project_files_list_widget.select_child(widget.get_parent())
                            # Right-click detected, show context menu
                            menu = Gtk.Menu()

                            open_file_menu_item = Gtk.MenuItem(label=_("Open XCF File"))
                            open_file_menu_item.connect("activate", lambda item: self.open_xcf_file(xcf_file))
                            menu.append(open_file_menu_item)

                            # add a horizontal separator
                            separator = Gtk.SeparatorMenuItem()
                            menu.append(separator)

                            rename_file_menu_item = Gtk.MenuItem(label=_("Rename File"))
                            rename_file_menu_item.connect("activate", lambda item: self.rename_project_file(xcf_file))
                            menu.append(rename_file_menu_item)

                            # add a horizontal separator
                            separator = Gtk.SeparatorMenuItem()
                            menu.append(separator)

                            menu_item_delete = Gtk.MenuItem(label=_("Delete XCF File"))
                            menu_item_delete.connect("activate", lambda item: self.delete_project_file(xcf_file))
                            menu.append(menu_item_delete)
                            menu.show_all()
                            menu.popup_at_pointer(event)

                    new_file_element_event_box.connect("button-press-event", on_xcf_file_double_click)
                else:
                    def on_other_file_double_click(widget, event, file_path=os.path.join(self.custom_project_file_folder, project_file)):
                        extension_with_dot = os.path.splitext(file_path)[1].lower()
                        if event.type == Gdk.EventType._2BUTTON_PRESS and event.button == Gdk.BUTTON_PRIMARY:
                            open_file_with_default_app(file_path)
                        elif event.type == Gdk.EventType.BUTTON_PRESS and event.button == Gdk.BUTTON_SECONDARY:
                            # set the flowbox selection to this item
                            self.project_files_list_widget.select_child(widget.get_parent())
                            # Right-click detected, show context menu
                            menu = Gtk.Menu()
                            menu_item_open = Gtk.MenuItem(label=_("Open File"))
                            menu_item_open.connect("activate", lambda item: open_file_with_default_app(file_path))
                            menu.append(menu_item_open)
                            
                            if extension_with_dot in SUPPORTED_VIDEO_EXTENSIONS:
                                menu_item_open_in_viewer = Gtk.MenuItem(label=_("Open in Frame by Frame Viewer"))
                                menu_item_open_in_viewer.connect("activate", lambda item: self.open_frame_by_frame_viewer(file_path))
                                menu.append(menu_item_open_in_viewer)

                            if extension_with_dot in SUPPORTED_IMAGE_EXTENSIONS:
                                menu_item_import_as_xcf = Gtk.MenuItem(label=_("Create XCF Project File From this"))
                                menu_item_import_as_xcf.connect("activate", lambda item: self.on_import_file(file_path))
                                menu.append(menu_item_import_as_xcf)

                            # add a horizontal separator
                            separator = Gtk.SeparatorMenuItem()
                            menu.append(separator)

                            rename_file_menu_item = Gtk.MenuItem(label=_("Rename File"))
                            rename_file_menu_item.connect("activate", lambda item: self.rename_project_file(file_path))
                            menu.append(rename_file_menu_item)

                            # add a horizontal separator
                            separator = Gtk.SeparatorMenuItem()
                            menu.append(separator)

                            menu_item_delete = Gtk.MenuItem(label=_("Delete File"))
                            menu_item_delete.connect("activate", lambda item: self.delete_project_file(file_path))
                            menu.append(menu_item_delete)
                            menu.show_all()
                            menu.popup_at_pointer(event)
                    new_file_element_event_box.connect("button-press-event", on_other_file_double_click)

        self.project_files_list_widget.show_all()

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
        thumbnail_file_path = os.path.splitext(xcf_file_path)[0] + ".thumbnail"
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
            raise ValueError(_("File {} does not exist").format(timeline_file_path))
        gfile = Gio.File.new_for_path(timeline_file_path)
        loaded_image = Gimp.file_load(Gimp.RunMode.INTERACTIVE, gfile)
        if loaded_image is None:
            raise ValueError(_("Failed to load the image file {}").format(timeline_file_path))
        display = Gimp.Display.new(loaded_image)
        self.images_opened.append({
            "image": loaded_image,
            "display": display,
            "file_path": timeline_file_path,
            "xcf": False,
        })
    
    def open_xcf_file(self, xcf_file_path):
        if not os.path.exists(xcf_file_path):
            raise ValueError(_("File {} does not exist").format(xcf_file_path))
        gfile = Gio.File.new_for_path(xcf_file_path)
        loaded_image = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, gfile)
        if loaded_image is None:
            raise ValueError(_("Failed to load the image file {}").format(xcf_file_path))
        display = Gimp.Display.new(loaded_image)
        self.images_opened.append({
            "image": loaded_image,
            "display": display,
            "file_path": xcf_file_path,
            "xcf": True,
        })
        self.generate_preview_thumbnail_image(loaded_image)
        self.update_project_file_list([xcf_file_path])

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
            self.update_project_file_list(updated_xcf_files)

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
                    text=_("The image '{}' has unsaved changes. Do you want to save them before closing?").format(image.get_name()),
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