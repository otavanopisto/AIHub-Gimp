import os
import ssl
import threading
from gi.repository import Gimp, Gtk, GLib, Gdk # type: ignore
from gi.repository.GdkPixbuf import Pixbuf # type: ignore
from gi.repository import Gio # type: ignore
import sys
import urllib.request
import zipfile
import subprocess
from shutil import copyfile

import gettext
_ = gettext.gettext

FFMPEG_SOURCES = {
    "windows": {
        "url_zip": "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
        "bin_paths": [
            "ffmpeg",
            "ffmpeg.exe",
            "C:\\ffmpeg\\bin\\ffmpeg.exe",
            "C:\\ProgramData\\chocolatey\\lib\\ffmpeg\\tools\\ffmpeg\\bin\\ffmpeg.exe",
        ],
    },
    "linux": {      
        "bin_paths": ["ffmpeg"],
    },
    "mac": {      
        "bin_paths": ["ffmpeg"],
    },
    "unknown": {      
        "bin_paths": ["ffmpeg"],
    },
}

class FrameByFrameVideoVideoViewer(Gtk.Dialog):
    def __init__(self, file_path, parent, project_files_path, project_type, tools_object):
        title = os.path.basename(file_path)
        super().__init__(title=title, transient_for=parent, flags=0)

        self.set_default_size(800, 600)
        self.set_keep_above(True)
        self.set_border_width(10)
        self.set_resizable(True)
        self.set_deletable(True)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.parent = parent

        self.project_type = project_type
        self.tools_object = tools_object

        self.calculate_workflows_with_frame_input()

        self.project_files_path = project_files_path

        self.file_path = file_path
        self.images_path = None

        self.current_frame = 0
        self.has_next_frame = False
        self.total_frames = 0
        self.has_set_event_listeners = False
        self.fps = None

        self.message_label = Gtk.TextView()
        self.message_label.set_editable(False)
        self.message_label.set_cursor_visible(False)
        self.message_label.set_wrap_mode(Gtk.WrapMode.WORD)
        # make it as wide as the window
        self.message_label.set_size_request(800, -1)

        css = b"""
            .textview, textview, textview text, textview view {
            background-color: transparent;
            border: none;
        }
        """
        style_provider = Gtk.CssProvider()
        style_provider.load_from_data(css)
        self.message_label.get_style_context().add_provider(
            style_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        self.message_label.get_style_context().add_class("textview")

        self.message_label.set_tooltip_text(_("Shows the status of the frame by frame viewer"))

        message_label_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        message_label_box.set_halign(Gtk.Align.START)
        #add padding to the message label box
        message_label_box.set_margin_start(12)
        message_label_box.set_margin_end(12)
        # add horizontal padding too
        message_label_box.set_margin_top(12)
        message_label_box.set_margin_bottom(12)
        message_label_box.set_size_request(800, -1)

        buffer = self.message_label.get_buffer()
        buffer.set_text(_("Status: Loading frame by frame viewer..."))

        message_label_box.pack_start(self.message_label, False, False, 0)

        self.main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        contents_area = self.get_content_area()
        contents_area.pack_start(message_label_box, False, False, 0)
        contents_area.pack_start(self.main_box, True, True, 0)

        self.ffmpeg_bin_path = self.check_for_ffmpeg()

        if self.ffmpeg_bin_path is None:
            return

        self.main_box.show_all()

        self.setStatus(_("Starting processing..."))

        # somehow force the UI to update before starting processing
        # because of a weird bug in Gtk, we need to process the UI events
        while Gtk.events_pending():
            Gtk.main_iteration()

        self.process_images()

    def setStatus(self, v: str):
        def do_set():
            buffer = self.message_label.get_buffer()
            buffer.set_text(v)
            return False  # Stop idle handler
            # Only update directly if in main thread
        if threading.current_thread() is threading.main_thread():
            do_set()
        else:
            GLib.idle_add(do_set)

    def process_images(self):
        if not hasattr(self, "image"):
            self.image = Gtk.Image()
            self.main_box.pack_start(self.image, True, True, 0)
            self.image.show()

        self.call_ffmpeg_process()

    def calculate_total_frames(self):
        # just count the number of files in the images path directory
        self.total_frames = len(os.listdir(self.images_path))
        return self.total_frames
    
    def move_frame(self, direction=1):
        new_frame = self.current_frame + direction
        if new_frame < 0:
            new_frame = 0
        if new_frame >= self.total_frames:
            new_frame = self.total_frames - 1
        if new_frame != self.current_frame:
            self.current_frame = new_frame
            self.display_current_frame()

    def display_current_frame(self):
        current_frame_path = os.path.join(self.images_path, f"frame_{(self.current_frame + 1):08d}.png")
        if os.path.exists(current_frame_path):
            pixbuf = Pixbuf.new_from_file(current_frame_path)
            self.image.set_from_pixbuf(pixbuf)
            self.setStatus(_("Displaying frame {}").format(self.current_frame + 1))
            self.has_next_frame = self.total_frames > (self.current_frame + 1)
        else:
            self.setStatus(_("Frame {} not found").format(current_frame_path))
            self.has_next_frame = False

        if not self.has_set_event_listeners:
            self.setup_event_listeners()

    def setup_event_listeners(self):
        def on_key_press(widget, event):
            key = Gdk.keyval_name(event.keyval)
            if key in ["Right", "Page_Down", "space"]:
                self.move_frame(1)
            elif key in ["Left", "Page_Up"]:
                self.move_frame(-1)
            elif key in ["Home"]:
                self.current_frame = 0
                self.display_current_frame()
            elif key in ["End"]:
                self.current_frame = self.total_frames - 1
                self.display_current_frame()
            elif key in ["Escape"]:
                self.response(Gtk.ResponseType.CLOSE)
            return True  # Stop further handling

        self.connect("key-press-event", on_key_press)

        # add a second click menu for custom actions
        self.image.set_tooltip_text(_("Right-click for options"))
        def on_button_press(widget, event):
            if event.type == Gdk.EventType.BUTTON_PRESS and event.button == Gdk.BUTTON_SECONDARY:
                menu = Gtk.Menu()

                export_video_item = Gtk.MenuItem(label=_("Export Video"))
                export_video_item.connect("activate", lambda x: self.export_video())
                menu.append(export_video_item)

                # add a divider
                separator = Gtk.SeparatorMenuItem()
                menu.append(separator)

                edit_item = Gtk.MenuItem(label=_("Edit in Gimp"))
                edit_item.connect("activate", lambda x: self.edit_in_gimp())
                menu.append(edit_item)

                replace_item = Gtk.MenuItem(label=_("Replace from Gimp Frame"))
                replace_item.connect("activate", lambda x: self.replace_from_gimp_frame())
                menu.append(replace_item)

                # add a divider
                separator = Gtk.SeparatorMenuItem()
                menu.append(separator)

                for workflow_object in self.workflows_with_frame_input:
                    workflow = workflow_object["workflow"]
                    workflow_name = workflow.get("label", "Unnamed Workflow")
                    item = Gtk.MenuItem(label=_("Apply Workflow: {}").format(workflow_name))
                    def on_workflow_activate(x, workflow=workflow):
                        expose_values = {}
                        for expose_id, widget in workflow.get("expose", {}).items():
                            if widget.get("type") == "AIHubExposeFrame":
                                offset = widget.get("data", {}).get("frame_index", 0)
                                if widget.get("data", {}).get("frame_index_type") == "relative_to_current":
                                    frame_to_use = self.current_frame + offset
                                else:
                                    frame_to_use = offset
                                if frame_to_use < 0 or frame_to_use >= self.total_frames:
                                    self.setStatus(_("Cannot apply workflow {}, frame {} is out of bounds.").format(workflow_name, frame_to_use))
                                    return
                                frame_path = os.path.join(self.images_path, f"frame_{(frame_to_use + 1):08d}.png")
                                expose_values[expose_id] = {"path": frame_path, "frame": frame_to_use, "total_frames": self.total_frames}
                        self.tools_object.select_workflow_for_frames(workflow, expose_values, self.on_frames_callback)
                    item.connect("activate", on_workflow_activate)
                    menu.append(item)

                    # need to check whether the item should be enabled or disabled
                    min_offset = workflow_object["min_offset"]
                    max_offset = workflow_object["max_offset"]
                    specific_frames = workflow_object["specific_frames"]
                    can_apply = True
                    if self.current_frame + min_offset < 0:
                        can_apply = False
                    if self.current_frame + max_offset >= self.total_frames:
                        can_apply = False
                    for specific_frame in specific_frames:
                        if specific_frame < 0 or specific_frame >= self.total_frames:
                            can_apply = False
                    if not can_apply:
                        item.set_sensitive(False)
                    
                menu.show_all()
                menu.popup_at_pointer(event)
                return True  # Stop further handling
            return False
        self.connect("button-press-event", on_button_press)
        self.has_set_event_listeners = True

    def edit_in_gimp(self):
        current_frame_path = os.path.join(self.images_path, f"frame_{(self.current_frame + 1):08d}.png")
        if os.path.exists(current_frame_path):
            self.parent.on_import_file(current_frame_path)
        else:
            self.setStatus(_("Frame {} not found").format(current_frame_path))

    def on_frames_callback(self, paths, last_use_as_frames_action):
        if last_use_as_frames_action["insert_action"] == "REPLACE":
            # easiest to do we will be replacing the frames given at the given index with the new frames given
            start_index = int(last_use_as_frames_action.get("insert_index", 0))
            for i, path in enumerate(paths):
                frame_index = start_index + i
                dest_path = os.path.join(self.images_path, f"frame_{(frame_index + 1):08d}.png")
                copyfile(path, dest_path)
            # nothing changes we must just refresh the current frame
            self.display_current_frame()
        else:
            # more difficult we need to insert the frames at the given index and shift the rest forward
            insert_index = int(last_use_as_frames_action.get("insert_index", 0))
            num_new_frames = len(paths)
            # shift existing frames forward
            for frame_num in range(self.total_frames - 1, insert_index - 1, -1):
                old_path = os.path.join(self.images_path, f"frame_{(frame_num + 1):08d}.png")
                new_path = os.path.join(self.images_path, f"frame_{(frame_num + 1 + num_new_frames):08d}.png")
                if os.path.exists(old_path):
                    os.rename(old_path, new_path)
            # now copy the new frames in
            for i, path in enumerate(paths):
                dest_path = os.path.join(self.images_path, f"frame_{(insert_index + i + 1):08d}.png")
                copyfile(path, dest_path)
            # update total frames
            self.total_frames += num_new_frames
            self.current_frame += num_new_frames
            # refresh the current frame
            self.display_current_frame()
        return True

    def replace_from_gimp_frame(self):
        # get the current width and height of the current frame
        image_pixbuf = self.image.get_pixbuf()
        width = image_pixbuf.get_width()
        height = image_pixbuf.get_height()

        # now we need to get all the images in gimp that match this size
        valid_images = []
        for img in Gimp.get_images():
            if img.get_width() == width and img.get_height() == height:
                valid_images.append(img)
        if len(valid_images) == 0:
            self.setStatus(_("No open images in Gimp match the size of the current frame ({}x{}).").format(width, height))
            return
        
        # now we will make a dialog to select which image to use
        dialog = Gtk.Dialog(title=_("Select Image to Replace Frame"), transient_for=self, flags=0)
        dialog.set_default_size(400, 300)
        dialog.set_border_width(10)
        dialog.set_modal(True)
        dialog.set_keep_above(True)
        content_area = dialog.get_content_area()
        listbox = Gtk.ListBox()
        listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        for img in valid_images:
            row = Gtk.ListBoxRow()
            hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            label = Gtk.Label(label=img.get_name(), xalign=0)
            height_from_ratio = int((200 / img.get_width()) * img.get_height())
            image_pixbuf = img.get_thumbnail(200,height_from_ratio,Gimp.PixbufTransparency.KEEP_ALPHA)
            image = Gtk.Image.new_from_pixbuf(image_pixbuf)
            hbox.pack_start(image, False, False, 0)
            hbox.pack_start(label, True, True, 0)
            row.add(hbox)
            listbox.add(row)
        content_area.pack_start(listbox, True, True, 0)
        dialog.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
        dialog.add_button(_("Replace Frame"), Gtk.ResponseType.OK)
        dialog.show_all()
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            selected_row = listbox.get_selected_row()
            if selected_row is not None:
                index = selected_row.get_index()
                selected_image = valid_images[index]
                dest_path = os.path.join(self.images_path, f"frame_{(self.current_frame + 1):08d}.png")

                # create a new gfile to save the image
                gfile = Gio.File.new_for_path(dest_path)
                Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, selected_image, gfile, None)

                self.display_current_frame()
        dialog.destroy()


    def export_video(self):
        # call ffmpeg to export the frames as a video
        self.setStatus(_("Exporting video..."))
        def run():
            try:
                basename = os.path.splitext(os.path.basename(self.file_path))[0]
                output_video_path = os.path.join(self.project_files_path, f"{basename}_export.mp4")
                n = 1
                while os.path.exists(output_video_path):
                    output_video_path = os.path.join(self.project_files_path, f"{basename}_export_{n}.mp4")
                    n += 1
                thumbnail_path = os.path.splitext(output_video_path)[0] + ".thumbnail"
                process = subprocess.Popen(
                    [self.ffmpeg_bin_path, "-framerate", self.fps, "-i", os.path.join(self.images_path, "frame_%08d.png"), "-c:v", "libx264", "-pix_fmt", "yuv420p", output_video_path],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    universal_newlines=True,
                )
                stdout, stderr = process.communicate()
                return_code = process.returncode
                if return_code != 0:
                    self.setStatus(_("ffmpeg export failed with return code {}: {}").format(return_code, stderr.strip()))
                    self.setStatus(" ".join([self.ffmpeg_bin_path, "-framerate", self.fps, "-i", os.path.join(self.images_path, "frame_%08d.png"), "-c:v", "libx264", "-pix_fmt", "yuv420p", output_video_path]))
                else:
                    self.setStatus(_("ffmpeg export completed successfully. Video saved to {}").format(output_video_path))

                # copy the first frame as thumbnail
                first_frame_path = os.path.join(self.images_path, "frame_00000001.png")
                if os.path.exists(first_frame_path):
                    copyfile(first_frame_path, thumbnail_path)

                if threading.current_thread() is threading.main_thread():
                    self.parent.update_project_file_list([output_video_path])
                else:
                    GLib.idle_add(self.parent.update_project_file_list, [output_video_path])
            except Exception as e:
                self.setStatus(_("ffmpeg export failed: {}").format(str(e)))
        threading.Thread(target=run).start()

    def call_ffmpeg_process(self):
        def run():
            try:
                # clean up any existing files in the images_path
                if self.images_path is not None and os.path.exists(self.images_path):
                    for f in os.listdir(self.images_path):
                        os.remove(os.path.join(self.images_path, f))
                if self.images_path is None:
                    # make a temporary folder in a temp directory
                    self.images_path = os.path.join(GLib.get_tmp_dir(), f"{os.path.basename(self.file_path)}_frames")
                # make the images path if it doesn't exist
                if not os.path.exists(self.images_path):
                    os.makedirs(self.images_path, exist_ok=True)

                # now we will call ffmpeg to extract frames as png files
                process = subprocess.Popen(
                    [self.ffmpeg_bin_path, "-i", self.file_path, os.path.join(self.images_path, "frame_%08d.png")],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    universal_newlines=True,
                )
                stdout, stderr = process.communicate()
                return_code = process.returncode
                if return_code != 0:
                    self.setStatus(_("ffmpeg processing failed with return code {}: {}").format(return_code, stderr.strip()))
                    return
                
                # calculate the fps from the ffmpeg output
                fps = None

                for line in stderr.splitlines():
                    if "Stream #" in line and "Video:" in line:
                        # Look for fps patterns like "25 fps", "29.97 fps", "30000/1001 fps"
                        if " fps" in line:
                            parts = line.split()
                            for i, part in enumerate(parts):
                                if part.replace(",", "").strip() == "fps" and i > 0:
                                    try:
                                        fps_str = parts[i-1]
                                        fps = fps_str.strip()
                                    except ValueError:
                                        continue
                        if fps:
                            break
                    
                if fps is None:
                    self.setStatus(_("Could not determine fps from ffmpeg output."))
                    return

                self.fps = fps
                self.setStatus(_("ffmpeg processing completed successfully at {} fps.").format(fps))
                self.calculate_total_frames()
                if threading.current_thread() is threading.main_thread():
                    self.display_current_frame()
                else:
                    GLib.idle_add(self.display_current_frame)
            except Exception as e:
                self.setStatus(_("ffmpeg processing failed: {}").format(str(e)))

        threading.Thread(target=run).start()

    def get_local_ffmpeg(self):
        local_ffmpeg_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ffmpeg")
        if os.path.exists(local_ffmpeg_dir):
            # search for ffmpeg binary in the extracted folder
            for root, dirs, files in os.walk(local_ffmpeg_dir):
                # check if it is a directory named bin
                if os.path.basename(root) == "bin":
                    for file in files:
                        if file.startswith("ffmpeg"):
                            ffmpeg_path = os.path.join(root, file)
                            if os.path.exists(ffmpeg_path):
                                return ffmpeg_path
        return None
    
    def downloaded_ffmpeg_success(self):
        try:
            local_ffmpeg_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ffmpeg")
            zip_path = os.path.join(local_ffmpeg_dir, "ffmpeg.zip")
            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                zip_ref.extractall(local_ffmpeg_dir)

            self.ffmpeg_bin_path = self.get_local_ffmpeg()
            def do_action():
                if self.ffmpeg_bin_path is not None:
                    self.setStatus(_("ffmpeg download successful, starting processing..."))
                    self.process_images()
                else:
                    self.setStatus(_("ffmpeg not found after download, please install ffmpeg and make sure it is in your PATH"))
            if threading.current_thread() is threading.main_thread():
                do_action()
            else:
                GLib.idle_add(do_action)

        except Exception as e:
            self.setStatus(_("Failed to extract ffmpeg: {}").format(str(e)))
    
    def download_ffmpeg(self, url):
        local_ffmpeg_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ffmpeg")
        zip_path = os.path.join(local_ffmpeg_dir, "ffmpeg.zip")
        if os.path.exists(zip_path):
            self.downloaded_ffmpeg_success()
            return
        try:
            self.setStatus(_("Downloading ffmpeg..."))
            context = ssl._create_unverified_context()
            response = urllib.request.urlopen(url, context=context)
            with open(zip_path, "wb") as f:
                f.write(response.read())
            self.downloaded_ffmpeg_success()
        except Exception as e:
            self.setStatus(_("Failed to download ffmpeg: {}").format(str(e)))

    def check_for_ffmpeg(self):
        system = sys.platform
        if system.startswith("win"):
            system = "windows"
        elif system.startswith("linux"):
            system = "linux"
        elif system.startswith("darwin"):
            system = "mac"
        else:
            system = "unknown"
            
        for bin_path in FFMPEG_SOURCES[system]["bin_paths"]:
            if os.path.exists(bin_path):
                return bin_path
            
        local_ffmpeg = self.get_local_ffmpeg()
        if local_ffmpeg is not None:
            return local_ffmpeg
        
        local_ffmpeg_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ffmpeg")
            
        if FFMPEG_SOURCES[system].get("url_zip"):
            # make directory ffmpeg in the current directory if it does not exist
            os.makedirs(local_ffmpeg_dir, exist_ok=True)
            # in another thread we download the ffmpeg zip file
            threading.Thread(target=self.download_ffmpeg, args=(FFMPEG_SOURCES[system]["url_zip"],)).start()
            return None

        local_ffmpeg = self.get_local_ffmpeg()
        if local_ffmpeg is not None:
            return local_ffmpeg

        self.setStatus(_("ffmpeg not found, please install ffmpeg and make sure it is in your PATH"))
        return None
    
    def cleanup_tmp(self):
        if self.images_path is not None and os.path.exists(self.images_path):
            for f in os.listdir(self.images_path):
                os.remove(os.path.join(self.images_path, f))
            try:
                os.rmdir(self.images_path)
            except OSError:
                pass

    def on_close(self, callback):
        self.connect("response", lambda dialog, response: callback() or self.destroy() or self.cleanup_tmp())

    def calculate_workflows_with_frame_input(self):
        workflows = self.tools_object.get_workflows()
        self.workflows_with_frame_input = []
        for workflow in workflows.values():
            compatible_project_type = workflow.get("project_type", "") == self.project_type or workflow.get("project_type", "") == ""
            if not compatible_project_type:
                continue
            exposes = workflow.get("expose", {})
            min_offset = 0
            max_offset = 0
            specific_frames = []
            contains_frames = False
            for expose_id, widget in exposes.items():
                if widget.get("type") == "AIHubExposeFrame":
                    contains_frames = True
                    offset = widget.get("data", {}).get("frame_index", 0)
                    if widget.get("data", {}).get("frame_index_type") == "relative_to_current":
                        if offset < min_offset:
                            min_offset = offset
                        if offset > max_offset:
                            max_offset = offset
                    else:
                        specific_frames.append(offset)
            if contains_frames:
                self.workflows_with_frame_input.append({"workflow": workflow, "name": workflow.get("name", "Unnamed Workflow"), "min_offset": min_offset, "max_offset": max_offset, "specific_frames": specific_frames})