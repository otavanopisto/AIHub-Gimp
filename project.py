import os
from gi.repository import Gimp, GimpUi, Gtk, GLib, Gdk # type: ignore
from gi.repository.GdkPixbuf import Pixbuf # type: ignore
from gi.repository.GdkPixbuf import InterpType # type: ignore
from gi.repository import Gio # type: ignore
import threading

import gettext
textdomain = "gimp30-python"
gettext.textdomain(textdomain)
_ = gettext.gettext

DEFAULT_THUMBNAIL = None

EXTENSIONS_THUMBAILS = {
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
        self.set_default_size(600, 400)
        self.project_file_contents = project_file_contents
        self.project_current_timeline_folder = project_current_timeline_folder
        self.project_folder = project_folder
        self.update_project_timeline = None
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
        self.update_xcf_file_list()
        self.rebuild_timeline_ui()
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
        pass

    def on_close(self, callback):
        self.connect("response", lambda dialog, response: callback() or self.destroy() or self.cleanup())

    def on_change_timeline(self, callback):
        self.update_project_timeline = callback

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

                id_of_image = self.image_model[selected_iter][0]
                gimp_image = Gimp.Image.get_by_id(id_of_image)
                gfile = Gio.File.new_for_path(file_name)
                Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, gimp_image, gfile, None)

                # Open the newly created image in GIMP and display it
                loaded_image = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, gfile)
                display = Gimp.Display.new(loaded_image)

                self.images_opened.append({
                    "image": loaded_image,
                    "display": display,
                })
                self.generate_preview_thumbnail_image(loaded_image)
                self.update_xcf_file_list()
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
                    loaded_image = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, gfile)
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
                    })
                    self.generate_preview_thumbnail_image(loaded_image_final)
                    self.update_xcf_file_list([dest_path])
                except ValueError as e:
                    error_dialog = Gtk.MessageDialog(parent=self, flags=0, message_type=Gtk.MessageType.ERROR,
                                                     buttons=Gtk.ButtonsType.OK, text=str(e))
                    error_dialog.set_keep_above(True)
                    error_dialog.run()
                    error_dialog.destroy()

        dialog.destroy()

    def update_xcf_file_list(self, update_specifically=None):
        # first we are going to list all xcf files in the custom xcf file folder
        xcf_files_in_folder = [f for f in os.listdir(self.custom_xcf_file_folder) if f.endswith(".xcf")]
        xcf_files = xcf_files_in_folder if update_specifically is None else [os.path.basename(f) for f in update_specifically]
        # then we will create a Gtk FlowBox to show them with thumbnails if available
        if not hasattr(self, 'xcf_file_list_widget'):
            project_file_label = Gtk.Label(label="XCF Files in Project:")
            project_file_label.set_halign(Gtk.Align.START)
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
                label = file_element.get_child().get_children()[1]
                if label.get_text() == xcf_file:
                    existing_file_element = file_element
                    break
            if existing_file_element is not None:
                # If we found an existing file element, we can update it
                existing_file_element.get_child().get_children()[0].set_from_pixbuf(thumbnail)
            else:
                # If not, we need to create a new row
                # we need to be sure it is added in alphabetical order
                new_file_element = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
                new_file_element.set_margin_top(10)
                new_file_element.set_margin_bottom(10)
                new_file_element.set_margin_start(10)
                new_file_element.set_margin_end(10)
                new_file_element.pack_start(Gtk.Image.new_from_pixbuf(thumbnail), False, False, 0)
                new_file_element.pack_start(Gtk.Label(label=xcf_file), False, False, 0)

                inserted = False
                for i, existing_file_element in enumerate(self.xcf_file_list_widget.get_children()):
                    existing_label = existing_file_element.get_child().get_children()[1]
                    if xcf_file < existing_label.get_text():
                        self.xcf_file_list_widget.insert(new_file_element, i)
                        inserted = True
                        break
                if not inserted:
                    self.xcf_file_list_widget.add(new_file_element)

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
        })

    def refresh_non_dirty_images(self, widget=None, event=None):
        clean_images = [img for img in self.images_opened if not img["image"].is_dirty()]
        updated_files = []
        for img in clean_images:
            updated = self.generate_preview_thumbnail_image(img["image"])
            if updated:
                updated_files.append(img["image"].get_xcf_file().get_path())
        if len(updated_files) > 0:
            self.update_xcf_file_list(updated_files)

    def cleanup_opened_xcf_files(self):
        for img in self.images_opened:
            image = img["image"]
            do_not_close = False
            if image.is_dirty():
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
                    Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, image, image.get_xcf_file(), None)
                    self.generate_preview_thumbnail_image(image)
                elif response == Gtk.ResponseType.CANCEL:
                    do_not_close = True
                else:
                    pass # Discard changes and close

            if not do_not_close:
                delete_succeeded = Gimp.Display.delete(img["display"])

                if delete_succeeded:
                    Gimp.Image.delete(img["image"])

        self.images_opened = []

    def cleanup(self):
        if threading.current_thread() is threading.main_thread():
            self.cleanup_opened_xcf_files()
        else:
            GLib.idle_add(self.cleanup_opened_xcf_files)