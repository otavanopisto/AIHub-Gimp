import shutil
import ssl
from about import AboutDialog
from settings import SettingsDialog
from update import UpdateDialog
from websocket._app import WebSocketApp
from workspace import AI_HUB_FOLDER_PATH, AI_HUB_SAVED_PATH, ensure_aihub_folder, get_aihub_common_property_value, update_aihub_common_property_value
from gi.repository import Gimp, GimpUi, Gtk, GLib, Gdk # type: ignore
from gi.repository.GdkPixbuf import Pixbuf # type: ignore
from gi.repository.GdkPixbuf import InterpType # type: ignore
from gi.repository import Gio # type: ignore
import threading
from gtkexposes import EXPOSES
import uuid
from project import ProjectDialog

import json
import os
import websocket
import socket

import threading

import urllib.request

import gettext
textdomain = "gimp30-python"
gettext.textdomain(textdomain)
_ = gettext.gettext

import sys
#sys.stderr = open('err.txt', 'a')
#sys.stdout = open('log.txt', 'a')

PROC_NAME = "AI Hub"

VERSION = None
try:
	with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "VERSION"), "r") as f:
		VERSION = f.read().strip()
except Exception as e:
	VERSION = "unknown"

def get_active_image_id(combobox):
	model = combobox.get_model()
	active_iter = combobox.get_active_iter()
	if active_iter is not None:
		image_id = model[active_iter][0]  # Column 0 holds the ID
		return image_id
	return None

def set_active_image_id(combobox, image_id):
	model = combobox.get_model()
	for row in model:
		if row[0] == image_id:
			combobox.set_active_iter(row.iter)
			return

def getAllAvailableContextFromWorkflows(workflows):
	return list(set(workflow["context"] for workflow in workflows.values()))

def removeDuplicatesFromList(lst):
	seen = set()
	result = []
	for item in lst:
		if item not in seen:
			seen.add(item)
			result.append(item)
	return result

def getAvailableCategoriesFromWorkflows(workflows, contexts):
	"""
	Returns a dictionary where the key are the workflow context and the values
	are a list that represent the given categories for that workflow context.
	"""
	return {context: removeDuplicatesFromList([workflow["category"] for workflow in workflows.values() if workflow["context"] == context])
			for context in contexts}

def acquire_process_lock(port=54321):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(('127.0.0.1', port))
        s.listen(1)
        return s  # Keep this socket open for the process lifetime
    except OSError:
        s.close()
        return None

def is_port_open(port, host='127.0.0.1'):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        result = sock.connect_ex((host, port))
        return result == 0  # 0 means the port is open
	
class WsRelegator:
	def __init__(self):
		self.event = None
		self.last_response = None
		self.is_awaiting = False

	def wait(self, timeout=None):
		return self.event.wait(timeout)

	def set(self, last_response):
		self.last_response = last_response
		self.is_awaiting = False
		self.event.set()

	def reset(self):
		self.event = threading.Event()
		self.last_response = None
		self.is_awaiting = True

MESSAGE_LOCK = threading.Lock()

def get_project_folder_in_timeline(timeline_path, project_is_real):
	if not project_is_real:
		base_folder = GLib.get_tmp_dir()
		project_folder = os.path.join(base_folder, "ai_hub_temp_project_" + timeline_path)
	else:
		project_folder = timeline_path
	
	if not os.path.exists(project_folder):
		os.makedirs(project_folder, exist_ok=True)

	return project_folder

def store_project_file(timeline_path, project_is_real, filename, file_action, bytes, separator=b""):
	# first lets get the folder for the project files
	project_folder = get_project_folder_in_timeline(timeline_path, project_is_real)
	if not os.path.exists(project_folder):
		os.makedirs(project_folder, exist_ok=True)
	files_folder = os.path.join(project_folder, "files")
	if not os.path.exists(files_folder):
		os.makedirs(files_folder, exist_ok=True)
	filepath = os.path.join(files_folder, filename)
	if file_action == "REPLACE":
		with open(filepath, "wb") as f:
			f.write(bytes)
		return filepath
	elif file_action == "APPEND":
		# we want to get the filename with a number appended to it before the extension
		base, ext = os.path.splitext(filename)
		# now in the directory we are supposed to store we are going to try to see which one
		# is the filename with the highest number
		i = 1
		while os.path.exists(os.path.join(files_folder, f"{base}_{i}{ext}")):
			i += 1
		finalpath = os.path.join(files_folder, f"{base}_{i}{ext}")
		with open(finalpath, "wb") as f:
			f.write(bytes)
		return finalpath
	elif file_action == "JOIN":
		# we are going to append to the file if it exists, using the separator if provided
		# to separate the chunks
		with open(filepath, "ab") as f:
			if os.path.exists(filepath) and separator:
				f.write(separator)
			f.write(bytes)
	else:
		raise ValueError(f"Invalid file_action {file_action}, must be REPLACE or APPEND")
	
def open_project_file_as_image(finalpath):
	# now try to open it in gimp if it is an image

	loaded_image = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(finalpath))
	if loaded_image:
		Gimp.Display.new(loaded_image)
		# if we loaded the image successfully, then we return it
		return loaded_image
	
	return None

def handle_project_file(
	timeline_path,
	project_is_real,
	bytes,
	action,
	current_image,
):
	file_name = action.get("file_name", "unnamed") if action else "unnamed"
	file_action = action.get("file_action", "REPLACE") if action else "REPLACE"
	separator = action.get("file_separator", b"") if action else b""
	finalpath = store_project_file(timeline_path, project_is_real, file_name, file_action, bytes, separator)
	if action is not None:
		if action["action"] == "NEW_IMAGE" or (action["action"] == "NEW_LAYER" and current_image is None):
			# when real projects we do not open the image automatically
			if not project_is_real:
				open_project_file_as_image(finalpath)
		elif action["action"] == "NEW_LAYER":
			pos_x = action.get("pos_x", 0)
			pos_y = action.get("pos_y", 0)
			# we are going to add a new layer to the current image
			# first lets make a pixbuf from the file at finalpath
			pixbuf = Pixbuf.new_from_file(finalpath)
			new_name = action.get("name", "AI Hub Layer")
			layer = Gimp.Layer.new_from_pixbuf(current_image, new_name, pixbuf, 100, Gimp.LayerMode.NORMAL, 0, 100)
			reference_layer_raw = action.get("reference_layer_id", None)
			reference_layer_id = int(reference_layer_raw) if reference_layer_raw is not None and reference_layer_raw.isdigit() else None
			reference_layer = None if reference_layer_id is None else Gimp.Layer.get_by_id(reference_layer_id)

			if reference_layer is None and reference_layer_raw == "__first__":
				reference_layer = current_image.get_layers()[0] if len(current_image.get_layers()) > 0 else None
			elif reference_layer is None and reference_layer_raw == "__last__":
				layers = current_image.get_layers()
				reference_layer = layers[-1] if len(layers) > 0 else None
			
			# get the selected layers before we insert the new one
			selectedlayers = current_image.get_selected_layers()
			if reference_layer is None:
				current_image.insert_layer(layer, None, 0)
				layer.set_offsets(pos_x, pos_y)
			else:
				# can be NEW_BEFORE, NEW_AFTER and REPLACE
				reference_layer_action = action.get("reference_layer_action", "NEW_AFTER")
				parent_layer = reference_layer.get_parent()
				sibling_layers = current_image.get_layers() if parent_layer is None else parent_layer.get_children()
				reference_layer_index = sibling_layers.index(reference_layer)
				if reference_layer_action == "NEW_BEFORE":
					current_image.insert_layer(layer, parent_layer, reference_layer_index + 1)
				elif reference_layer_action == "NEW_AFTER":
					current_image.insert_layer(layer, parent_layer, reference_layer_index)
				elif reference_layer_action == "REPLACE":
					# in order to avoid destructive actions, we are going to insted
					# hide it and set it before the new layer
					reference_layer.set_visible(False)
					current_image.insert_layer(layer, parent_layer, reference_layer_index + 1)
				layer.set_offsets(pos_x, pos_y)
			# go back to the previously selected layers
			# so the user doesnt suddenly lose their selection
			current_image.set_selected_layers(selectedlayers)

			# bug in GIMP 3.0.10 where the image is not updated if the layer is made visible again
			img_width = current_image.get_width()
			img_height = current_image.get_height()
			# make a thumbnail starting at 400px with the ratio for the given height
			height_from_ratio = int(400 * img_height / img_width)
			pixbuf2 = current_image.get_thumbnail(400,height_from_ratio,Gimp.PixbufTransparency.KEEP_ALPHA)

			layer.set_visible(False)
			Gimp.displays_flush()
			layer.set_visible(True)
			Gimp.displays_flush()

			# do it again for good measure
			pixbuf3 = current_image.get_thumbnail(400,height_from_ratio,Gimp.PixbufTransparency.KEEP_ALPHA)




def runToolsProcedure(procedure, run_mode, image, drawables, config, run_data):
	GimpUi.init("AIHub.py")

	lock_socket = acquire_process_lock()
	if (not lock_socket):
		return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())

	class ImageDialog(GimpUi.Dialog):
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

		def setErrored(self):
			if threading.current_thread() is threading.main_thread():
				self.errored = True
				self.menu_item_open_project.set_sensitive(False)

				if hasattr(self, "image_selector") and self.image_selector is not None:
					self.image_selector.set_sensitive(False)
				if hasattr(self, "context_selector") and self.context_selector is not None:
					self.context_selector.set_sensitive(False)
				if hasattr(self, "category_selector") and self.category_selector is not None:
					self.category_selector.set_sensitive(False)
				if hasattr(self, "workflow_selector") and self.workflow_selector is not None:
					self.workflow_selector.set_sensitive(False)
				# make the run button disabled or enabled
				if hasattr(self, "run_button") and self.run_button is not None:
					self.run_button.set_sensitive(False)

				if hasattr(self, "workflow_elements_all") and self.workflow_elements_all is not None:
					for element in self.workflow_elements_all:
						if element.get_widget():
							element.get_widget().set_sensitive(False)
			else:
				GLib.idle_add(self.setErrored)

		def on_message(self, ws, msg):
			if self.errored:
				return
			
			if self.websocket_relegator and self.websocket_relegator.is_awaiting and isinstance(msg, str):
				try:
					self.websocket_relegator.set(json.loads(msg))
				except Exception as e:
					print("Error setting websocket_relegator:", e)
				return
			
			MESSAGE_LOCK.acquire()
			
			# we are expecting a binary file
			try:
				if len(self.next_file_info) > 0 and isinstance(msg, bytes):
					next_file_info = self.next_file_info.pop(0)
					# we are expecting a binary file to be received next
					try:
						file_data = msg
						# write the file to a temporary location
						handle_project_file(
							self.project_current_timeline_folder,
							self.project_is_real,
							file_data,
							next_file_info.get("action", None),
							self.selected_image,
						)
						MESSAGE_LOCK.release()
						return
					except Exception as e:
						if self.is_running:
							self.mark_as_running(False, "Error: Failed to write received file from server " + str(e))
						else:
							self.setStatus("Error: Failed to write received file from server " + str(e))
						MESSAGE_LOCK.release()
						return
				elif isinstance(msg, bytes):
					self.next_file.append(msg)
					MESSAGE_LOCK.release()
					return
			except Exception as e:
				if self.is_running:
					self.mark_as_running(False, "Error: Failed to process received file from server " + str(e))
				else:
					self.setStatus("Error: Failed to process received file from server " + str(e))
				MESSAGE_LOCK.release()
				return

			try:
				message_parsed = json.loads(msg)
				if "type" in message_parsed:
					if message_parsed["type"] == "INFO_LIST":
						self.workflows = message_parsed.get("workflows", {})
						self.workflow_contexts = getAllAvailableContextFromWorkflows(self.workflows)
						self.workflow_categories = getAvailableCategoriesFromWorkflows(self.workflows, self.workflow_contexts)
						self.models = message_parsed.get("models", [])
						self.loras = message_parsed.get("loras", [])
						self.samplers = message_parsed.get("samplers", [])
						self.schedulers = message_parsed.get("schedulers", [])
						self.setStatus("Status: Processing workflows, models and loras")

						if (len(self.workflow_contexts) == 0 or len(self.workflow_categories) == 0):
							self.setStatus("Status: No valid workflows or categories found.")
							self.setErrored()
							MESSAGE_LOCK.release()
							return
						
						try:
							self.setStatus("Status: Ready")
							if threading.current_thread() is threading.main_thread():
								self.build_ui_base()
							else:
								GLib.idle_add(self.build_ui_base)
						except Exception as e:
							self.setStatus(f"Status: Error building UI: {e}")
							self.setErrored()
					elif message_parsed["type"] == "ERROR":
						if self.is_running:
							self.mark_as_running(False, f"Status: Error received from server \"{message_parsed.get('message', 'Unknown error')}\"")
						else:
							self.setStatus(f"Status: Error received from server \"{message_parsed.get('message', 'Unknown error')}\"")
					elif message_parsed["type"] == "STATUS":
						self.setStatus(f"Status: {message_parsed.get('message', 'Unknown status')}")
					elif message_parsed["type"] == "WORKFLOW_AWAIT":
						# waiting for the workflow with id, there are "before_this" users before you
						self.setStatus(f"Status: Waiting for workflow {message_parsed.get('workflow_id', 'unknown')} to start, there are {message_parsed.get('before_this', 0)} users before you.")
						self.current_run_id = message_parsed.get('id', None)
					elif message_parsed["type"] == "WORKFLOW_START":
						self.setStatus(f"Status: Workflow {message_parsed.get('workflow_id', 'unknown')} has started.")
						self.current_run_id = message_parsed.get('id', None)
					elif message_parsed["type"] == "FILE":
						if len(self.next_file) > 0:
							file_it_describes = self.next_file.pop(0)
							try:
								handle_project_file(
									self.project_current_timeline_folder,
									self.project_is_real,
									file_it_describes,
									message_parsed.get("action", None),
									self.selected_image,
								)
							except Exception as e:
								if self.is_running:
									self.mark_as_running(False, "Error: Failed to write received file from server " + str(e))
								else:
									self.setStatus("Error: Failed to write received file from server " + str(e))
								MESSAGE_LOCK.release()
								return
						else:
							self.next_file_info.append(message_parsed)
					elif message_parsed["type"] == "PREPARE_BATCH":
						if message_parsed.get("file_action", "APPEND") == "REPLACE":
							# we need to remove all the potentially existing files in the batch
							# TODO: implement removing existing files in the batch
							filename = message_parsed.get("file_name", "new batch")
					elif message_parsed["type"] == "WORKFLOW_FINISHED":
						self.current_run_id = None
						if self.is_running:
							if message_parsed["error"]:
								self.mark_as_running(False, f"Status: Workflow finished with error: {message_parsed.get('error_message', 'No message provided')}")
							else:
								self.mark_as_running(False, f"Status: Workflow finished successfully; ready for another run.")

							if self.started_new_project_last_run:
								self.complete_steps_after_new_empty_project(message_parsed["error"])

					elif message_parsed["type"] == "WORKFLOW_STATUS":
						if self.is_running:
							node_name = message_parsed.get("node_name", "unknown")
							progress = message_parsed.get("progress", 0)
							total = message_parsed.get("total", 1)

							# we are not sure the value may be integer or float, but we want to display with the least amount of decimals
							# regardless of which type it is, a float with no decimals should be displayed same as integer
							if isinstance(progress, float):
								if progress.is_integer():
									progress = int(progress)
							if isinstance(total, float):
								if total.is_integer():
									total = int(total)

							self.setStatus(f"Status: Running {node_name} ({progress}/{total})")
					elif message_parsed["type"] == "SET_CONFIG_VALUE":
						field = message_parsed.get("field", None)
						value = message_parsed.get("value", None)
						if field is not None and self.project_is_real:
							timeline_config_path = os.path.join(self.project_current_timeline_folder, "config.json")

							current_config = {}
							if os.path.exists(timeline_config_path):
								with open(timeline_config_path, "r") as f:
									try:
										current_config = json.load(f)
									except json.JSONDecodeError:
										current_config = {}
							
							current_config_working_with = current_config
							splitted = field.split(".")
							for i in range(0, len(splitted)):
								if i == len(splitted) - 1:
									current_config_working_with[splitted[i]] = value
									break

								part = splitted[i]
								next_config = current_config_working_with.get(part, None)
								if next_config is None:
									current_config_working_with[part] = {}
									current_config_working_with = current_config_working_with[part]
								else:
									current_config_working_with = next_config

							with open(timeline_config_path, "w") as f:
								json.dump(current_config, f, indent=4)
					else:
						if self.is_running:
							self.mark_as_running(False, f"Status: Unknown message type received: {message_parsed['type']}")
						else:
							self.setStatus(f"Status: Unknown message type received: {message_parsed['type']}")
						
			except Exception as e:
				if self.is_running:
					self.mark_as_running(False, "Status: Received invalid message from server.")
				else:
					self.setStatus("Status: Received invalid message from server.")

			MESSAGE_LOCK.release()

		def refresh_image_list(self, recreate_list: bool):
			if self.errored:
				return
			
			if not hasattr(self, "image_selector") or self.image_selector is None:
				return
			
			current_image_id = get_active_image_id(self.image_selector)

			if (recreate_list):
				# we are going to recreate the list of images available in GIMP
				#self.image_selector.remove_all()
				available_ids = []
				# the store is a list of string, string, and a pixbuf for the image
				self.image_model = self.image_selector.get_model() or Gtk.ListStore(int, str, Pixbuf)  # ID, Name, Preview
				for img in Gimp.get_images():
					available_ids.append(img.get_id())
					option_id = img.get_id()
					
					# check if the image_selector_model already has this id
					# if not, then we add it, otherwise we will update the preview
					modified = False
					for row in self.image_model:
						if row[0] == option_id:
							# update the preview
							image_preview = img.get_thumbnail(128,128,Gimp.PixbufTransparency.KEEP_ALPHA)
							row[2] = image_preview
							modified = True
							break
					if not modified:
						name_id = img.get_name()
						image_preview = img.get_thumbnail(128,128,Gimp.PixbufTransparency.KEEP_ALPHA)
						self.image_model.append([option_id, name_id, image_preview])

				# find if there are images that are no longer available and remove them from the list
				rows_to_remove = [row.iter for row in self.image_model if row[0] not in available_ids]
				for row_iter in rows_to_remove:
					self.image_model.remove(row_iter)

				if (not self.image_selector.get_model()):
					self.image_selector.set_model(self.image_model)

					renderer_pixbuf = Gtk.CellRendererPixbuf()
					renderer_text = Gtk.CellRendererText()

					self.image_selector.pack_start(renderer_pixbuf, False)
					self.image_selector.add_attribute(renderer_pixbuf, "pixbuf", 2)
					self.image_selector.pack_start(renderer_text, True)
					self.image_selector.add_attribute(renderer_text, "text", 1)

				if not available_ids.count(current_image_id):
					current_image_id = available_ids[0] if len(available_ids) > 0 else None
			
			if current_image_id and get_active_image_id(self.image_selector) != current_image_id:
				set_active_image_id(self.image_selector, current_image_id)

			if current_image_id:
				new_selected_image = Gimp.Image.get_by_id(current_image_id)

				if new_selected_image != self.selected_image:
					self.selected_image = new_selected_image
					for element in self.workflow_elements_all:
						element.current_image_changed(self.selected_image, self.image_selector.get_model())
			else:
				self.selected_image = None
				for element in self.workflow_elements_all:
					element.current_image_changed(self.selected_image, self.image_selector.get_model())

		def build_ui_base(self):
			if self.errored:
				return
			
			self.image_selector = Gtk.ComboBox()
			self.refresh_image_list(True)
			self.image_selector.connect("changed", lambda combo: self.refresh_image_list(False))
			self.main_box.pack_start(self.image_selector, False, False, 0)

			self.image_selector.set_tooltip_text("Select the image to work with")
			
			# lets start with the basics and make a selector for the contexts
			self.context_selector = Gtk.ComboBoxText()
			for context in self.workflow_contexts:
				self.context_selector.append(context, context.capitalize())
			self.main_box.pack_start(self.context_selector, False, False, 0)

			self.context_selector.set_tooltip_text("Select the context that you are working with, normally depends on the type of file you are" + 
										  " dealing with; in the case of gimp it would be more commonly 'image'")

			self.category_selector = Gtk.ComboBoxText()
			self.main_box.pack_start(self.category_selector, False, False, 0)

			self.category_selector.set_tooltip_text("Select the category of the workflow that you want to use, each category brings their own set of workflows")

			self.workflow_selector = Gtk.ComboBoxText()
			self.main_box.pack_start(self.workflow_selector, False, False, 0)

			self.workflow_selector.set_tooltip_text("Select the workflow that you want to use, each workflow has their own set of options and parameters")

			# we are also going to make some label text display to display
			# the description
			self.description_label = Gtk.TextView()
			self.description_label.set_editable(False)
			self.description_label.set_cursor_visible(False)
			self.description_label.set_wrap_mode(Gtk.WrapMode.WORD)
			self.description_label.set_size_request(400, -1)

			self.description_label.set_tooltip_text("Description of the selected workflow")

			css = b"""
			.textview, textview, textview text, textview view {
				background-color: transparent;
				border: none;
			}
			"""
			style_provider = Gtk.CssProvider()
			style_provider.load_from_data(css)
			self.description_label.get_style_context().add_provider(
				style_provider,
				Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
			)
			self.description_label.get_style_context().add_class("textview")

			self.main_box.pack_start(self.description_label, False, False, 0)

			# lets add the workflow elements box
			self.workflow_elements = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
			self.main_box.pack_start(self.workflow_elements, True, True, 0)

			# try to force the selected value to image, and if it is not available, then
			# force the first one that is found
			if "image" in self.workflow_contexts:
				self.context_selector.set_active_id("image")
			else:
				self.context_selector.set_active_id(self.workflow_contexts[0])

			default_context = get_aihub_common_property_value("", "", "default_context", None)

			if default_context and default_context in self.workflow_contexts:
				self.context_selector.set_active_id(default_context)

			# add the listener for the a context is selected by the user
			self.context_selector.connect("changed", self.on_context_selected)
			self.category_selector.connect("changed", self.on_category_selected)
			self.workflow_selector.connect("changed", self.on_workflow_selected)
			# trigger it by hand because we want to set the initial status
			self.main_box.show_all()
			self.setup_project_ui()

			self.on_context_selected(self.context_selector)

		def setup_project_ui(self):
			if self.errored:
				return
			
			if not self.project_is_real:
				# change the name of the window to the default one
				self.set_title(_("AIHub Tools"))

				if hasattr(self, "project_dialog") and self.project_dialog is not None:
					self.project_dialog.close()
					self.project_dialog = None
			else:
				project_name = self.project_file_contents.get("project_name", "Unnamed Project")
				self.set_title(_("AIHub Tools - Project: ") + project_name)

				if not hasattr(self, "project_dialog") or self.project_dialog is None:
					self.project_dialog = ProjectDialog(
						project_name,
						self,
						self.project_file_contents,
						self.project_current_timeline_folder,
						self.project_folder,
						self.image_model,
						self.on_dialog_focus,
					)
					self.project_dialog.show_all()
					self.project_dialog.on_close(self.close_project)
					self.project_dialog.on_change_timeline(self.on_change_project_timeline)

		def on_context_selected(self, combo):
			try:
				selected_context = combo.get_active_id()

				update_aihub_common_property_value("", "", "default_context", selected_context, self.project_saved_config_json_file)
				
				# remove all workflows and categories in their respective comboboxes that have been
				# previously selected
				self.workflow_selector.remove_all()
				self.category_selector.remove_all()

				# now start by adding the categories for that specific context that was selected
				for category in self.workflow_categories.get(selected_context, []):
					# capitalize the first letter of each word in the category
					self.category_selector.append(category, category.capitalize())

				#self.main_box.show_all()

				default_category = get_aihub_common_property_value("", selected_context, "default_category", self.project_saved_config_json_file)
				if default_category is None or not self.workflow_categories[selected_context].count(default_category):
					default_category = self.workflow_categories[selected_context][0]

				# we are going to make the default selected to be the first one in our list of categories in workflow_categories
				self.category_selector.set_active_id(default_category)

				#self.on_category_selected(self.category_selector)
			except Exception as e:
				self.setStatus(f"Error: {str(e)}")
				self.setErrored()

		def on_category_selected(self, combo):
			try:
				selected_context = self.context_selector.get_active_id()
				selected_category = combo.get_active_id()

				update_aihub_common_property_value("", selected_context, "default_category", selected_category, self.project_saved_config_json_file)

				# remove all workflows in their respective comboboxes that have been previously selected
				self.workflow_selector.remove_all()

				# now start by adding the workflows for that specific category that was selected
				# the workflows have to be filtered by hand because they are a dictionary of key values and we must check
				# by the context and the category that they match
				workflows_for_category = []
				workflows_to_add = []
				for workflow in self.workflows.values():
					if workflow["context"] == selected_context and workflow["category"] == selected_category:

						workflow_project_type = workflow.get("project_type", None)
						if workflow_project_type is not None and workflow_project_type.strip() == "":
							workflow_project_type = None

						mark_as_special = False
						mark_as_project_init = False
						current_project_type = self.project_file_contents.get("project_type", None) if self.project_file_contents is not None else None

						if current_project_type is not None:
							# if we are ourselves within a project, that has a given type, all the workflows
							# that have a project type that matches ours, should be available first
							# and marked as special
							if workflow_project_type is not None and current_project_type != workflow_project_type:
								# we are not in the same project type, so we skip this workflow
								continue

							current_timeline_info = self.project_file_contents.get("timelines", {}).get(self.project_file_contents.get("current_timeline", ""), {})
							# if the current timeline we are in is the initial timeline we allow to recreate the timeline
							should_show_project_init = current_timeline_info.get("initial", False)

							# we are not showing project inits if we are outside of the initial timeline
							# as it would then make no sense and break things
							if not should_show_project_init and workflow.get("project_type_init", False):
								continue

							# if the workflow has a project type that matches ours, then we mark it as special
							# so that we can display it first
							if workflow_project_type is not None and current_project_type == workflow_project_type:
								mark_as_special = True
							# if the workflow has no project type, then it is a general workflow and we do not mark it as special
							# but it is also available
							else:
								mark_as_special = False

							if workflow.get("project_type_init", False):
								# if the workflow has a project type, and this is also an init, then we mark it, so that it
								# is clear that it will re-start the same project
								mark_as_project_init = True
						else:
							# if we are not within a project, then we can only show project_type_init workflows
							# if they have a project type
							if workflow_project_type is not None:
								if workflow.get("project_type_init", False):
									mark_as_project_init = True
								else:
									# we are not in a project, and the workflow has a project type, but is not a project_type_init
									# so we skip it
									continue
						
						workflows_for_category.append(workflow["id"])
						workflows_to_add.append((workflow["id"], workflow["label"], mark_as_special, mark_as_project_init))

				# we want to sort workflows_to_add so that init ones are first, then special ones, then general ones
				# and within each group, we sort alphabetically by the workflow label
				workflows_to_add.sort(key=lambda x: (not x[3], not x[2], x[1].lower()))

				first_workflow = None
				for workflow_id, workflow_label, special, init in workflows_to_add:
					if not first_workflow:
						first_workflow = workflow_id
					if init:
						# workflows that start a new project marked with <>
						self.workflow_selector.append(workflow_id, f"<{workflow_label}>")
					elif special:
						# wokflows that run actions within the current project marked with []
						self.workflow_selector.append(workflow_id, f"[{workflow_label}]")
					else:
						# general workflows with no special markings that are available anywhere
						self.workflow_selector.append(workflow_id, workflow_label)

				default_workflow = get_aihub_common_property_value("", selected_context + "/" + selected_category, "default_workflow", self.project_saved_config_json_file)
				if default_workflow is None or not workflows_for_category.count(default_workflow):
					default_workflow = first_workflow

				#self.main_box.show_all()

				# we are going to make the default selected to be the first one in our list of workflows in workflows
				self.workflow_selector.set_active_id(default_workflow)

			#self.on_workflow_selected(self.workflow_selector)
			except Exception as e:
				self.setStatus(f"Error: {str(e)}")
				self.setErrored()

		def on_model_changed(self, new_model_id):
			model_info = next((model for model in self.models if model["id"] == new_model_id), None)
			if not model_info:
				return
			# we are going to loop through all the workflow_elements_all
			# then we will update their current model
			for element in self.workflow_elements_all:
				element.on_model_changed(model_info)

		def on_workflow_selected(self, combo):
			try:
				selected_context = self.context_selector.get_active_id()
				selected_workflow = combo.get_active_id()
				workflow = self.workflows.get(selected_workflow)

				if workflow is None:
					# bug in GTK where the changed signal is called even if there are no items
					# in the combobox, so we just ignore it
					self.run_button.hide()
					self.cancel_run_button.hide()
					return

				if not workflow or workflow is None or not workflow.get("description", None):
					self.description_label.get_buffer().set_text("No description available.")
				else:
					self.description_label.get_buffer().set_text(workflow["description"])

				# Update the default workflow for the current context and category
				update_aihub_common_property_value("", selected_context + "/" + self.category_selector.get_active_id(), "default_workflow", selected_workflow, None)

				# now let's clear the workflow box
				self.workflow_elements.foreach(Gtk.Widget.destroy)
				self.workflow_elements_all = []

				image_url = f"{"http" if self.apiprotocol == "ws" else "https"}://{self.apihost}:{self.apiport}/workflows/{workflow['id']}.png"
				try:
					response = urllib.request.urlopen(image_url)
					input_stream = Gio.MemoryInputStream.new_from_data(response.read(), None)
					pixbuf = Pixbuf.new_from_stream(input_stream, None)

					width = 400
					height = int(pixbuf.get_height() * (width / pixbuf.get_width()))
					scaled_pixbuf = pixbuf.scale_simple(width, height, InterpType.BILINEAR)

					self.workflow_image = Gtk.Image()
					self.workflow_image.set_from_pixbuf(scaled_pixbuf)

					self.workflow_elements.pack_start(self.workflow_image, False, False, 0)
				except Exception as e:
					# if we fail to load the image, we just ignore it
					self.workflow_image = None


				# and let's find our exposes for that let's get the key value for each expose
				exposes = workflow.get("expose", {})

				apinfo = {
					"protocol": self.apiprotocol,
					"usehttps": self.apiprotocol == "wss",
					"host": self.apihost,
					"port": self.apiport,
				}

				for expose_id, widget in exposes.items():
					type = widget.get("type", None)
					data = widget.get("data", None)

					if type == "AIHubExposeSampler":
						# add the samplers to the options
						data["options"] = "\n".join(self.samplers)
						data["options_label"] = "\n".join(self.samplers)

					elif type == "AIHubExposeScheduler":
						# add the schedulers to the options
						data["options"] = "\n".join(self.schedulers)
						data["options_label"] = "\n".join(self.schedulers)

					elif type == "AIHubExposeExtendableScheduler":
						blacklist_raw = data.get("blacklist", "")
						blacklist_values = [b.strip() for b in blacklist_raw.split("\n") if b.strip() != ""]
						blacklist = blacklist_values if len(blacklist_values) > 0 else None
						blacklist_all = data.get("blacklist_all", False)
						extras_raw_splitted = data.get("extras", "").split("\n")
						extras = [e.strip() for e in extras_raw_splitted if e.strip() != ""]


						final_schedulers = [scheduler for scheduler in self.schedulers if
							(blacklist is None or scheduler not in blacklist) and
							(blacklist_all is False)
						]

						final_schedulers.extend(extras)

						# add the schedulers to the options
						data["options"] = "\n".join(final_schedulers)
						data["options_label"] = "\n".join(final_schedulers)

					elif type == "AIHubExposeModel" or type == "AIHubExposeModelSimple":
						# add the models to the options, models is a list and we need to get the id and name from each model
						# and join them with a newline
						# note that models have a context which should match the current context
						# note that the data may contain a limit_to_family field that we should filter by family
						# also has a limit_to_group field that we should filter by group
						limit_to_family = data.get("limit_to_family", None)
						limit_to_group = data.get("limit_to_group", None)

						if limit_to_family is not None:
							limit_to_family = limit_to_family.strip()
							if limit_to_family == "":
								limit_to_family = None

						if limit_to_group is not None:
							limit_to_group = limit_to_group.strip()
							if limit_to_group == "":
								limit_to_group = None

						filtered_models = [
							model for model in self.models if model["context"] == selected_context and
							(limit_to_family is None or model.get("family", None) == limit_to_family) and
							(limit_to_group is None or model.get("group", None) == limit_to_group)
						]
						data["filtered_models"] = filtered_models

						filtered_loras = [
							lora for lora in self.loras if lora["context"] == selected_context and
							(limit_to_family is None or lora.get("family", None) == limit_to_family) and
							(limit_to_group is None or lora.get("group", None) == limit_to_group)
						]

						data["filtered_loras"] = filtered_loras

					ExposeClass = EXPOSES.get(type, None)

					instance = ExposeClass(expose_id, data, selected_context, selected_workflow, workflow, self.project_current_timeline_folder, self.project_saved_config_json_file, apinfo) if ExposeClass else None
					if instance:
						if self.selected_image:
							instance.current_image_changed(self.selected_image, self.image_selector.get_model())
						self.workflow_elements_all.append(instance)

						if type == "AIHubExposeModel":
							instance.hook_on_change_fn(self.on_model_changed)
				
				# now we have to sort self.workflow_elements_all by the get_index function that returns a number
				# if two elements return the same number, then we sort them by their get_special_priority function that returns a number
				# the highest number goes first in the case of get_special_priority
				self.workflow_elements_all.sort(key=lambda x: (x.get_index(), -x.get_special_priority()))

				# now we will loop through all the workflow_elements_all that are not marked as advanced and append them to the self.workflow_elements box
				# provided that they return a widget
				for element in self.workflow_elements_all:
					if not element.is_advanced() and element.get_widget():
						self.workflow_elements.pack_start(element.get_widget(), False, False, 0)

				# lets check if we have advanced options within our list
				has_advanced = any(element.is_advanced() and element.get_widget() is not None for element in self.workflow_elements_all)

				if (has_advanced):
					# now we add a Gtk container for advanced options that is hidden by default
					advanced_options_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
					
					# now lets add some border and some padding to it
					
					css = b"""
					.advanced-border {
						border: 2px solid #888;
						border-radius: 8px;
						padding: 12px;
					}
					"""
					style_provider = Gtk.CssProvider()
					style_provider.load_from_data(css)

					advanced_options_box.get_style_context().add_provider(style_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

					advanced_options_box.get_style_context().add_class("advanced-border")
					advanced_options_box.set_margin_start(12)
					advanced_options_box.set_margin_end(12)
					advanced_options_box.set_margin_top(12)
					advanced_options_box.set_margin_bottom(12)

					# add a button to toggle advanced options
					toggle_button = Gtk.Button(label="Show Advanced Options")
					toggle_button.connect("clicked", self.on_toggle_advanced_options, advanced_options_box)

					# add some margin top to the button
					toggle_button.set_margin_top(12)

					self.workflow_elements.pack_start(toggle_button, False, False, 0)

					# make the button not grow and be left aligned
					toggle_button.set_hexpand(False)
					toggle_button.set_halign(Gtk.Align.START)
					self.workflow_elements.pack_start(advanced_options_box, False, False, 0)
					
					for element in self.workflow_elements_all:
						if element.is_advanced() and element.get_widget():
							advanced_options_box.pack_start(element.get_widget(), False, False, 0)

					self.main_box.show_all()
					advanced_options_box.hide()
					self.run_button.show()
					self.cancel_run_button.show()
				else:
					self.main_box.show_all()
					self.run_button.show()
					self.cancel_run_button.show()

				# add a horizontal separator
				separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
				self.workflow_elements.pack_start(separator, False, False, 12)

				for element in self.workflow_elements_all:
					if element.get_widget():
						element.after_ui_built()

				self.on_dialog_focus(None, None)
			except Exception as e:
				self.setStatus(f"Error: {str(e)}")
				self.setErrored()

		def on_toggle_advanced_options(self, button, advanced_options_box):
			if advanced_options_box.is_visible():
				advanced_options_box.hide()
				button.set_label("Show Advanced Options")
			else:
				advanced_options_box.show()
				button.set_label("Hide Advanced Options")
			
		def on_run_workflow(self, button):
			if self.errored:
				return
			
			self.mark_as_running(True)

			selected_workflow = self.workflow_selector.get_active_id()
			workflow = self.workflows.get(selected_workflow)

			workflow_is_init = workflow.get("project_type_init", False)

			self.started_new_project_last_run = False
			self.started_new_timeline_from_init_last_run = False

			# check if the workflow is project_type_init so then we have to request the user to create a new project
			# in that case we need to show a dialog asking the user to create a new project
			# the dialog should be to save a file dialog with a name for the project
			if workflow_is_init and not self.project_is_real:
				# we are going to show a dialog asking the user to save a file
				# the dialog should be a native file chooser dialog if possible
				dialog = Gtk.FileChooserNative(
					title="Select a file to save the new project at",
					action=Gtk.FileChooserAction.SAVE,
					transient_for=self,
					accept_label="Create Project",
					cancel_label="Cancel",
					#buttons=(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, "Create Project", Gtk.ResponseType.ACCEPT)
				)
				dialog.set_modal(True)
				#dialog.set_keep_above(True)
				response = dialog.run()
				if response == Gtk.ResponseType.ACCEPT:
					project_file = dialog.get_filename()
					if project_file is None or project_file.strip() == "":
						self.mark_as_running(False)
						return
					# remove potential extension from the file using os.path
					project_path = os.path.splitext(project_file)[0]
					workflow_name = workflow.get("label", "Unknown")
					self.start_empty_project(workflow.get("project_type", "Unknown"), project_path, workflow_name)
					self.started_new_project_last_run = True
					dialog.destroy()
				else:
					# user cancelled the dialog
					self.mark_as_running(False)
					dialog.destroy()
					return
			elif workflow_is_init:
				# we are already within a project, so we are going to create a new timeline within the current project
				self.branch_project_timeline("Alternative timeline", is_initial=True)
				# while this would make sense, we are commenting it out because it doesn't matter as it is used to refresh
				# the options for the workflow, which we don't need to do here
				# self.started_new_timeline_from_init_last_run = True
			elif self.project_is_real:
				workflow_name = workflow.get("label", "Unknown")
				self.branch_project_timeline(workflow_name, is_initial=False)

			try:
				# check if all the elements are can_run returns true
				for element in self.workflow_elements_all:
					if not element.can_run():
						# show a dialog specifiying that it is invalid
						dialog = Gtk.MessageDialog(
							transient_for=self,
							flags=0,
							message_type=Gtk.MessageType.ERROR,
							buttons=Gtk.ButtonsType.OK,
							text="Some input fields are invalid.",
						)
						dialog.format_secondary_text("Please check the value for \"" + element.get_ui_label_identifier() + "\" and try again.")
						dialog.show()
						# make the dialog on top of everything
						dialog.set_keep_above(True)
						# make it close once you click ok, and also call mark_as_running(False)
						dialog.connect("response", lambda d, r: self.mark_as_running(False) or d.destroy())
						return

				# we are going to gather all the values
				values = {}
				for element in self.workflow_elements_all:
					websocket_relegator = WsRelegator()
					self.websocket_relegator = websocket_relegator
					status = element.upload_binary(self.websocket, self.websocket_relegator)
					self.websocket_relegator = None
					if (status is False):
						self.mark_as_running(False)
						self.setStatus("Error: Failed to upload binary data.")
						return
					values[element.id] = element.get_value()

				workflow_operation = {
					"type": "WORKFLOW_OPERATION",
					"workflow_id": self.workflow_selector.get_active_id(),
					"expose": values
				}

				self.websocket.send(json.dumps(workflow_operation))
			except Exception as e:
				self.setStatus(f"Error: {str(e)}")
				self.setErrored()
				return

			return
		
		def on_cancel_run_workflow(self, button=None):
			if self.errored:
				return
			
			# literally not running or we haven't received a run id
			# either this is going slow or something odd is happening
			# either way without this id we can't really cancel anything
			running_id = self.current_run_id
			if running_id is None:
				return
			
			self.cancel_run_button.set_sensitive(False)
			#change the label of the cancel button to cancelling
			self.cancel_run_button.set_label("Cancelling...")

			cancel_operation = {
				"type": "WORKFLOW_OPERATION",
				"cancel": running_id
			}

			try:
				self.websocket.send(json.dumps(cancel_operation))
			except Exception as e:
				self.setStatus(f"Error: {str(e)}")
				self.setErrored()
				return
		
		def mark_as_running(self, running: bool, messageOverride: str = None):
			def do_action():
				self.is_running = running

				# disable all the elements in the UI if running is true, otherwise enable them
				self.image_selector.set_sensitive(not running)
				self.context_selector.set_sensitive(not running)
				self.category_selector.set_sensitive(not running)
				self.workflow_selector.set_sensitive(not running)
				# make the run button disabled or enabled
				self.run_button.set_sensitive(not running)
				self.cancel_run_button.set_sensitive(running)
				self.cancel_run_button.set_label("Cancel Run")

				for element in self.workflow_elements_all:
					if element.get_widget():
						element.get_widget().set_sensitive(not running)

				messageToShow = messageOverride if messageOverride is not None else ("Status: Running workflow..." if running else "Status: Ready")
				self.setStatus(messageToShow)
				#if not running:
					# the reason we force this focus is because the dialog remains static while it is running
					# and it may had been focused during that phase, so we force it to refocus once it is done
					# so that the user can see the updated status
					# disabled seems to cause crashes
					#self.on_dialog_focus(None, None)

				if hasattr(self, "project_dialog") and self.project_dialog is not None and self.project_is_real and not running:
					self.project_dialog.refresh(self.project_file_contents, self.project_current_timeline_folder)

			if threading.current_thread() is threading.main_thread():
				do_action()
			else:
				GLib.idle_add(do_action)

		def on_open(self, ws):
			self.connected = True
			self.setStatus("Status: Connected to server, waiting for workflows information")

		def on_close(self, ws, close_status_code, close_msg):
			if not self.connected:
				self.setStatus("Error: Could not connect to server " + self.apihost + ":" + str(self.apiport))
				self.setErrored()
				return
			self.setStatus("Error: Disconnected from server")
			self.setErrored()

		def on_error(self, ws, error):
			self.setStatus(f"Error: {str(error)}")
			self.setErrored()

		def start_websocket(self):
			try:
				self.websocket = websocket.WebSocketApp(
					f"{self.apiprotocol}://{self.apihost}:{self.apiport}/ws",
					on_message=self.on_message,
					on_open=self.on_open,
					on_close=self.on_close,
					on_error=self.on_error,
					header={"api-key": self.apikey},
					sslopt={"cert_reqs": ssl.CERT_NONE} if self.apiprotocol == "wss" else None,
				)
				self.websocket.run_forever()
			except Exception as e:
				self.setStatus(f"Error: {str(e)}")
				self.setErrored()
		"""
		The permanent GTK dialog for the AI Image Procedure
		"""
		def __init__(self):
			#use_header_bar = Gtk.Settings.get_default().get_property("gtk-dialogs-use-header")
			#GimpUi.Dialog.__init__(self, use_header_bar=use_header_bar)

			self.connected: bool = False

			self.message_label: Gtk.TextView
			self.websocket: WebSocketApp
			self.websocket_relegator: WsRelegator = None
			self.errored: bool = False

			self.current_run_id: str = None

			self.workflows = {}
			self.workflow_contexts = []
			self.workflow_categories = []
			self.models = []
			self.loras = []
			self.samplers = []
			self.schedulers = []

			self.main_box: Gtk.Box
			self.is_running: bool = False

			self.selected_image = None

			# elements of the main UI
			self.image_selector: Gtk.ComboBox
			self.image_model: Gtk.ListStore
			self.context_selector: Gtk.ComboBoxText
			self.category_selector: Gtk.ComboBoxText
			self.workflow_selector: Gtk.ComboBoxText
			self.description_label: Gtk.TextView
			self.run_button: Gtk.Button

			# elements of a project type UI

			# generics
			self.workflow_image: Gtk.Image
			self.workflow_elements: Gtk.Box
			self.workflow_elements_all = []

			self.next_file_info = []
			self.next_file = []

			# eg the ./myproject.aihubproj
			self.project_file = None
			# eg. ./myproject/
			self.project_folder = uuid.uuid4().hex
			self.project_is_real = False
			# eg. ./myproject/timelines/abcdef1234567890
			self.project_current_timeline_folder = uuid.uuid4().hex
			# eg. ./myproject/saved.json
			self.project_saved_config_json_file = None
			# the project info that exist within the project_file
			self.project_file_contents = {}

			self.started_new_project_last_run = False
			self.started_new_timeline_from_init_last_run = False

			GimpUi.Dialog.__init__(self, decorated=True, modal=False)
			Gtk.Window.set_title(self, _("AIHub Tools"))
			Gtk.Window.set_role(self, PROC_NAME)
			Gtk.Window.set_resizable(self, False)

			Gtk.Window.set_keep_above(self, True)

			Gtk.Window.connect(self, "delete-event", self.on_delete_event)

			Gtk.Window.set_default_size(self, 400, 600)

			# make the dialog always be as small as it can be
			Gtk.Window.set_size_request(self, 400, 600)

			# add on dialog focus event
			Gtk.Window.connect(self, "focus-in-event", self.on_dialog_focus)

			# Make the dialog dockable and persistent.
			# This is how you make it behave like GIMP's native dialogs.
			self.set_role("ai-hub-tools") # A unique role string

			# make a top bar with a File menu
			header_bar = Gtk.HeaderBar()
			header_bar.set_title("AIHub Tools")
			header_bar.set_show_close_button(True)
			Gtk.Window.set_titlebar(self, header_bar)
			menu_button = Gtk.MenuButton()
			menu_image = Gtk.Image.new_from_icon_name("open-menu-symbolic", Gtk.IconSize.BUTTON)
			menu_button.add(menu_image)
			header_bar.pack_start(menu_button)
			menu = Gtk.Menu()
			self.menu_item_open_project = Gtk.MenuItem(label="Open Project")
			self.menu_item_open_project.connect("activate", self.on_menu_open_project)
			menu.append(self.menu_item_open_project)

			# add a divider to the menu
			menu.append(Gtk.SeparatorMenuItem())

			# add a menu entry for settings
			self.menu_item_settings = Gtk.MenuItem(label="Settings")
			self.menu_item_settings.connect("activate", self.on_menu_settings)
			menu.append(self.menu_item_settings)

			# add a menu entry for updating
			self.menu_item_update = Gtk.MenuItem(label="Check for Updates")
			self.menu_item_update.connect("activate", self.on_menu_update)
			menu.append(self.menu_item_update)

			# add a menu entry for about
			self.menu_item_about = Gtk.MenuItem(label="About AIHub")
			self.menu_item_about.connect("activate", self.on_menu_about)
			menu.append(self.menu_item_about)

			menu_button.set_popup(menu)
			menu.show_all()

			# Create a vertical box to hold widgets
			self.main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
			self.main_box.set_margin_start(12)
			self.main_box.set_margin_end(12)
			self.main_box.set_margin_top(12)
			self.main_box.set_margin_bottom(12)

			self.message_label = Gtk.TextView()
			self.message_label.set_editable(False)
			self.message_label.set_cursor_visible(False)
			self.message_label.set_wrap_mode(Gtk.WrapMode.WORD)
			self.message_label.set_size_request(400, -1)

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

			self.message_label.set_tooltip_text("Shows the current status of the plugin as it communicates with the server and operates")

			message_label_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
			message_label_box.set_halign(Gtk.Align.START)
			#add padding to the message label box
			message_label_box.set_margin_start(12)
			message_label_box.set_margin_end(12)
			# add horizontal padding too
			message_label_box.set_margin_top(12)
			message_label_box.set_margin_bottom(12)

			buffer = self.message_label.get_buffer()
			buffer.set_text("Status: Connecting to server...")

			message_label_box.pack_start(self.message_label, False, False, 0)
			#self.main_box.pack_start(self.message_label, False, False, 0)

			contents_area = Gtk.Dialog.get_content_area(self)
			contents_area.pack_start(message_label_box, False, False, 0)
			#contents_area.pack_start(self.main_box, True, True, 0)

			# add a scrollbar if it overflows
			scrolled_window = Gtk.ScrolledWindow()
			scrolled_window.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
			# get screen height and set the max height to 80% of it
			screen = Gdk.Screen.get_default()
			screen_height = screen.get_height()
			scrolled_window.set_min_content_height(int(screen_height * 0.8))
			scrolled_window.add(self.main_box)
			contents_area.pack_start(scrolled_window, True, True, 0)

			button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
			button_box.set_hexpand(True)
			button_box.set_halign(Gtk.Align.END)

			self.run_button = Gtk.Button(label="Run Workflow")
			self.cancel_run_button = Gtk.Button(label="Cancel Run")
			self.cancel_run_button.connect("clicked", self.on_cancel_run_workflow)
			self.run_button.connect("clicked", self.on_run_workflow)
			#align the run button to the right
			self.run_button.set_halign(Gtk.Align.END)
			self.run_button.set_hexpand(False)
			self.cancel_run_button.set_halign(Gtk.Align.START)
			self.cancel_run_button.set_hexpand(False)
			#add margin top to the button
			self.run_button.set_margin_top(12)
			self.cancel_run_button.set_margin_top(12)
			self.cancel_run_button.set_sensitive(False)

			#self.workflow_elements.pack_start(self.run_button, False, False, 0)

			self.run_button.set_tooltip_text("Run the selected workflow with the selected options")
			self.cancel_run_button.set_tooltip_text("Cancel the running workflow")

			button_box.set_margin_start(12)
			button_box.set_margin_end(12)
			button_box.pack_start(self.cancel_run_button, False, False, 0)
			button_box.pack_start(self.run_button, False, False, 0)

			contents_area.pack_start(button_box, False, False, 0)

			try:
				config = ensure_aihub_folder()

				self.apihost = config.get("api", "host")
				self.apiport = config.get("api", "port")
				self.apiprotocol = config.get("api", "protocol")
				self.apikey = config.get("api", "apikey")

				self.setStatus(f"Status: Communicating at {self.apiprotocol}://{self.apihost}:{self.apiport}")

				last_opened_project = get_aihub_common_property_value("", "", "last_opened_project", None)
				if last_opened_project:
					# the ui is not ready yet, so we pass quiet=True
					# so it only updates the internal project information
					self.open_project(last_opened_project, quiet=True)

				threading.Thread(target=self.start_websocket, daemon=True).start()
			except Exception as e:
				self.setStatus(f"Error: {str(e)}")
				self.setErrored()

		def on_menu_settings(self, menu_item):
			if not hasattr(self, "settings_dialog") or self.settings_dialog is None:
				self.settings_dialog = SettingsDialog(
					self,
				)
				self.settings_dialog.show_all()
				self.settings_dialog.on_close(self.close_settings_dialog)

		def close_settings_dialog(self):
			if hasattr(self, "settings_dialog") and self.settings_dialog is not None:
				self.settings_dialog.destroy()
				self.settings_dialog = None

		def on_menu_update(self, menu_item):
			if not hasattr(self, "update_dialog") or self.update_dialog is None:
				global VERSION
				self.update_dialog = UpdateDialog(
					self,
					VERSION,
				)
				self.update_dialog.show_all()
				self.update_dialog.on_close(self.close_update_dialog)

		def close_update_dialog(self):
			if hasattr(self, "update_dialog") and self.update_dialog is not None:
				self.update_dialog.destroy()
				self.update_dialog = None

		def on_menu_about(self, menu_item):
			if not hasattr(self, "about_dialog") or self.about_dialog is None:
				global VERSION
				self.about_dialog = AboutDialog(
					self,
					VERSION,
				)
				self.about_dialog.show_all()
				self.about_dialog.on_close(self.close_about_dialog)

		def close_about_dialog(self):
			if hasattr(self, "about_dialog") and self.about_dialog is not None:
				self.about_dialog.destroy()
				self.about_dialog = None

		def on_delete_event(self, widget, event):
			# check for a potential project dialog to call its cleanup
			if hasattr(self, "project_dialog") and self.project_dialog is not None:
				self.project_dialog.cleanup()

			self.destroy()
			Gtk.main_quit()
			lock_socket.close()
			return True
		
		def run(self):
			Gtk.Widget.show_all(self)
			Gtk.main()

		def on_menu_open_project(self, menu_item):
			if self.errored or self.is_running:
				return
			aihubprojfilter = Gtk.FileFilter()
			aihubprojfilter.set_name("AIHub Project Files")
			aihubprojfilter.add_pattern("*.aihubproj")
			allfilter = Gtk.FileFilter()
			allfilter.set_name("All Files")
			allfilter.add_pattern("*")

			dialog = Gtk.FileChooserNative(
				title="Select a project file to open",
				action=Gtk.FileChooserAction.OPEN,
				transient_for=self,
				accept_label="Open Project",
				cancel_label="Cancel",
				#ensure the file extension is .aihubproj
			)
			dialog.add_filter(aihubprojfilter)
			dialog.add_filter(allfilter)
			dialog.set_modal(True)
			response = dialog.run()
			if response == Gtk.ResponseType.ACCEPT:
				project_file = dialog.get_filename()
				if project_file is None or project_file.strip() == "":
					dialog.destroy()
					return
				self.open_project(project_file)
				update_aihub_common_property_value("", "", "last_opened_project", project_file, None)
				dialog.destroy()
			else:
				# user cancelled the dialog
				dialog.destroy()
			return

		def open_project(self, project_file_path: str, quiet: bool = False):
			if self.errored or self.is_running:
				return
			if not os.path.isfile(project_file_path):
				self.showErrorDialog("Error", "Project file " + project_file_path + " does not exist.")
				update_aihub_common_property_value("", "", "last_opened_project", None, None)
				return
			
			# remove extension to get the project folder name
			# the project folder should contain all the subtree information
			project_folder = os.path.splitext(project_file_path)[0] + "_files"

			if not os.path.isdir(project_folder):
				self.showErrorDialog("Error", "Project folder " + project_folder + " does not exist.")
				return

			try:
				with open(project_file_path, "r") as f:
					project_absolute_config = json.load(f)
					if not isinstance(project_absolute_config, dict):
						raise Exception("Invalid project file format.")
					self.project_folder = project_folder
					self.project_is_real = True
					self.project_file = project_file_path
					self.project_file_contents = project_absolute_config
					self.project_current_timeline_folder = os.path.join(self.project_folder, "timelines", self.project_file_contents.get("current_timeline", ""))
					if not os.path.isdir(self.project_current_timeline_folder):
						raise Exception("Invalid project file format: current timeline folder does not exist.")
					self.project_saved_config_json_file = os.path.join(self.project_folder, "saved.json")
					# Ensure the saved config file exists
					if not os.path.isfile(self.project_saved_config_json_file):
						raise Exception("Invalid project file format: saved.json file does not exist.")
					
					# check that is is a valid json file
					with open(self.project_saved_config_json_file, "r") as sf:
						saved_config = json.load(sf)
						if not isinstance(saved_config, dict):
							raise Exception("Invalid saved.json file format.")

					self.setStatus(f"Status: Opened project {self.project_file_contents.get('project_name', 'Unknown')}")
					if hasattr(self, "category_selector") and self.category_selector is not None:
						self.on_category_selected(self.category_selector)
					if not quiet:
						self.on_project_opened()
			except Exception as e:
				self.showErrorDialog("Error", f"Failed to open project file: {str(e)}")
				self.close_project_cleanup_data()

		def close_project_cleanup_data(self):
			if self.errored:
				return
			self.project_file = None
			self.project_file_contents = None
			self.project_folder = uuid.uuid4().hex
			self.project_is_real = False
			self.project_current_timeline_folder = uuid.uuid4().hex
			self.project_saved_config_json_file = None

		def close_project(self):
			if self.errored:
				return
			if self.is_running:
				self.on_cancel_run_workflow()
			self.close_project_cleanup_data()
			self.setStatus("Status: Closed project")
			self.on_project_closed()

		def on_change_project_timeline(self, new_timeline_id: str):
			if self.errored:
				return
			
			if not self.project_is_real or self.project_file_contents is None:
				self.setStatus("Error: No project is currently opened.")
				return

			self.project_file_contents.current_timeline = new_timeline_id
			self.project_current_timeline_folder = os.path.join(self.project_folder, "timelines", new_timeline_id)

			with open(self.project_file, "w") as f:
				json.dump(self.project_file_contents, f, indent=4)

			if not os.path.isdir(self.project_current_timeline_folder):
				os.makedirs(self.project_current_timeline_folder)

			if hasattr(self, "project_dialog") and self.project_dialog is not None:
				if threading.current_thread() is threading.main_thread():
					self.project_dialog.refresh(self.project_file_contents, self.project_current_timeline_folder)
				else:
					GLib.idle_add(self.project_dialog.refresh, self.project_file_contents, self.project_current_timeline_folder)

		def start_empty_project(self, project_type: str, project_path: str, timeline_name: str):
			if self.errored:
				return
			
			self.project_folder = project_path + "_files"
			self.project_is_real = True
			self.project_file = project_path + ".aihubproj"
			initial_timeline_id = uuid.uuid4().hex
			project_name = os.path.basename(project_path)
			self.project_file_contents = {
				"version": 1,
				"timelines": {
					initial_timeline_id: {
						"id": initial_timeline_id,
						"name": timeline_name,
						"parent_id": None,
						"initial": True,
					}
				},
				"current_timeline": initial_timeline_id,
				"project_type": project_type,
				"project_name": project_name,
			}
			self.project_current_timeline_folder = os.path.join(self.project_folder, "timelines", initial_timeline_id)
			self.project_saved_config_json_file = os.path.join(self.project_folder, "saved.json")

			with open(self.project_file, "w") as f:
				json.dump(self.project_file_contents, f, indent=4)

			# make the directory for the project
			if not os.path.isdir(self.project_folder):
				os.makedirs(self.project_folder)

			# we want to copy our saved.json file to this project_saved_config_json_file
			# if it does not exist, we create an empty one copy from AI_HUB_SAVED_PATH to project_saved_config_json_file
			if not os.path.isfile(self.project_saved_config_json_file):
				# if the AI_HUB_SAVED_PATH exists, we copy it
				if os.path.isfile(AI_HUB_SAVED_PATH):
					shutil.copyfile(AI_HUB_SAVED_PATH, self.project_saved_config_json_file)
				else:
					with open(self.project_saved_config_json_file, "w") as f:
						json.dump({}, f, indent=4)

			if not os.path.isdir(self.project_current_timeline_folder):
				os.makedirs(self.project_current_timeline_folder)

			self.on_project_opened()

		def branch_project_timeline(self, new_timeline_name: str, is_initial: bool = False):
			if self.errored:
				return

			current_timeline_info = self.project_file_contents.get("timelines", {}).get(self.project_file_contents.get("current_timeline", ""), {})	
			if self.project_is_real and self.project_file_contents is not None:
				new_timeline_id = uuid.uuid4().hex
				self.project_file_contents["timelines"][new_timeline_id] = {
					"id": new_timeline_id,
					"name": new_timeline_name,
					"parent_id": None if is_initial else current_timeline_info.get("id", None),
					"initial": True if is_initial else False,
				}
				self.project_file_contents["current_timeline"] = new_timeline_id

				# update the project file
				try:
					with open(self.project_file, "w") as f:
						json.dump(self.project_file_contents, f, indent=4)
				except Exception as e:
					self.setStatus(f"Error: Failed to update project file: {str(e)}")
					self.setErrored()
					return

				# create the new timeline folder
				self.project_current_timeline_folder = os.path.join(self.project_folder, "timelines", new_timeline_id)
				if not os.path.isdir(self.project_current_timeline_folder):
					os.makedirs(self.project_current_timeline_folder)

				# now such timeline inherits everything from the previous timeline
				# so we copy the entire structure into our new timeline folder
				previous_timeline_folder = os.path.join(self.project_folder, "timelines", self.project_file_contents["timelines"][new_timeline_id]["parent_id"])
				if previous_timeline_folder is not None:
					try:
						if os.path.isdir(previous_timeline_folder):
							shutil.copytree(previous_timeline_folder, self.project_current_timeline_folder, dirs_exist_ok=True)
					except Exception as e:
						self.setStatus(f"Error: Failed to copy timeline data: {str(e)}")
						self.setErrored()
						return
				
				if is_initial:
					self.setStatus(f"Status: Created new alternate timeline '{new_timeline_name}'")
				else:
					self.setStatus(f"Status: Branched new timeline '{new_timeline_name}'")

				if self.is_running:
					self.started_new_timeline_from_init_last_run = current_timeline_info.get("initial", False)
			else:
				self.setStatus("Error: No project is currently opened.")
				self.setErrored()
				return
	
		def on_dialog_focus(self, widget, event):
			if self.errored or self.is_running:
				return
			# call the function in all the workflow_elements_all to notify them that the dialog has been focused
			self.refresh_image_list(True)
			for element in self.workflow_elements_all:
				element.on_refresh()

		def on_project_opened(self):
			update_aihub_common_property_value("", "", "last_opened_project", self.project_file, None)
			if (threading.current_thread() is threading.main_thread()):
				self.setup_project_ui()
			else:
				GLib.idle_add(self.setup_project_ui)

		def on_project_closed(self):
			# force a reset like this
			self.on_category_selected(self.category_selector)
			update_aihub_common_property_value("", "", "last_opened_project", None, None)
			if (threading.current_thread() is threading.main_thread()):
				self.setup_project_ui()
			else:
				GLib.idle_add(self.setup_project_ui)

		def complete_steps_after_new_empty_project(self, error):
			def do_action():
				if self.started_new_project_last_run or self.started_new_timeline_from_init_last_run:
					self.started_new_project_last_run = False
					self.started_new_timeline_from_init_last_run = False
					self.on_category_selected(self.category_selector)

			if threading.current_thread() is threading.main_thread():
				do_action()
			else:
				GLib.idle_add(do_action)

		def showErrorDialog(self, title: str, message: str):
			dialog = Gtk.MessageDialog(
				transient_for=self,
				flags=0,
				message_type=Gtk.MessageType.ERROR,
				buttons=Gtk.ButtonsType.OK,
				text=title,
			)
			dialog.format_secondary_text(message)
			dialog.set_keep_above(True)
			dialog.run()
			dialog.destroy()

	ImageDialog().run()

	return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())