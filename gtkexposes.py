import struct
import urllib
from label import AIHubLabel
from workspace import get_aihub_common_property_value, update_aihub_common_property_value
from gi.repository import Gimp, Gtk, GLib, Gio, Gdk # type: ignore
from gi.repository.GdkPixbuf import Pixbuf # type: ignore
from gi.repository.GdkPixbuf import InterpType # type: ignore
import hashlib
import random
import ssl

import json
import os

import gettext
_ = gettext.gettext

class AIHubExposeBase:
	def __init__(self, id, data, workflow_context, workflow_id, workflow, project_current_timeline_path, project_saved_path, apinfo):
		self.data = None
		self.id = None
		self.initial_value = None
		self.workflow = None
		self.project_current_timeline_path = None
		self.project_saved_path = None
		self.workflow_context = None
		self.workflow_id = None
		self._on_change_timeout_id = None
		self.current_image = None
		self.image_model = None
		self.on_change_callback = None
		self.change_listeners = []
		self.on_change_callback_hijack = False
		self.apinfo = None
		self.siblings = []

		self.apinfo = apinfo
		self.data = data
		self.id = id
		self.workflow_context = workflow_context
		self.workflow_id = workflow_id
		self.initial_value = get_aihub_common_property_value(workflow_context, workflow_id, self.id, project_saved_path)
		self.had_initial_value_loaded_from_configfile = self.initial_value is not None
		self.workflow = workflow
		self.project_current_timeline_path = project_current_timeline_path
		self.project_saved_path = project_saved_path

		self.all_exposes_in_workflow = []

		if (self.initial_value is None):
			self.set_initial_value()

	def set_exposes_in_workflow(self, all_exposes):
		self.all_exposes_in_workflow = all_exposes

	def set_siblings(self, siblings):
		self.siblings = siblings

	def set_initial_value(self):
		if ("value" in self.data and self.data["value"] is not None):
			self.initial_value = self.data["value"]

	def update_project_current_timeline_path_and_saved_path(self, new_timeline_path, new_saved_path):
		self.project_current_timeline_path = new_timeline_path
		self.project_saved_path = new_saved_path

	def parse_index(self, index_str):
		try:
			return int(index_str)
		except:
			# we will try to see if it is a variable from the config
			stripped = index_str.strip()
			sign = ""
			if stripped.startswith("+") or stripped.startswith("-"):
				sign = stripped[0]
				stripped = stripped[1:].strip()
			value = self.read_project_config_json(stripped)
			if value is not None and isinstance(value, int):
				return value if sign == "" else (value if sign == "+" else -value)
			raise ValueError("Invalid index string for config file, could not find a valid integer: {}".format(index_str))

	def read_project_config_json(self, key):
		if not self.project_saved_path or self.project_saved_path == "":
			return None
		
		timeline_config_path = os.path.join(self.project_current_timeline_path, "config.json")

		if not os.path.exists(timeline_config_path):
			return None

		with open(timeline_config_path, "r") as f:
			config = json.load(f)
			# the key is dot separated and should go in a loop
			for part in key.split("."):
				config = config.get(part, None)
				if config is None:
					break
			return config

	def get_value(self, half_size=False, half_size_coords=False):
		return None

	def get_widget(self):
		pass

	def upload_binary(self, ws, relegator=None, half_size=False):
		# upload a binary before getting the value, if any this function is called
		# when the value is requested by the run function
		return True

	def is_default_value(self):
		return self.get_value() == self.data["value"]
	
	def is_advanced(self):
		return False if "advanced" not in self.data or self.data["advanced"] is None else self.data["advanced"]

	def get_index(self):
		return 0 if "index" not in self.data or self.data["index"] is None else self.data["index"]
	
	def on_change(self, value):
		self.check_validity(value)

		if self.on_change_callback is not None:
			self.on_change_callback(value)

			if self.on_change_callback_hijack:
				return
			
		for secondary_listener in self.change_listeners:
			secondary_listener(value)

		# add a timeout to stack and only do the change after 1s if the function isnt called continously
		# basically it waits 1s before calling the function but
		# if it is called a second time it will stop the first call
		if self._on_change_timeout_id is not None:
			GLib.source_remove(self._on_change_timeout_id)
			self._on_change_timeout_id = None

		self._on_change_timeout_id = GLib.timeout_add(300, self._on_change_timeout, value)

	def change_id(self, new_id):
		self.id = new_id

	def get_id(self):
		return self.id

	def change_label(self, new_label):
		if hasattr(self, 'label') and self.label is not None:
			self.label.set_text(new_label)

	def _on_change_timeout(self, value):
		update_aihub_common_property_value(self.workflow_context, self.workflow_id, self.id, value, self.project_saved_path)
		GLib.source_remove(self._on_change_timeout_id)
		self._on_change_timeout_id = None

	def after_ui_built(self, workflow_elements_all):
		# this function is called after the UI is built, it can be used to do any
		# additional setup that requires the UI to be fully built
		pass
	
	def current_image_changed(self, image, model):
		self.current_image = image
		self.image_model = model
		# this function is called when the current image in GIMP changes
		pass

	def on_refresh(self):
		# this function is called when the ui is refocused and images may have changed
		# in gimp
		pass

	def check_validity(self, value):
		# this function should be used to override and check the validity
		# of the current value, and just mark the UI as invalid if so
		# and specify why
		pass

	def can_run(self):
		# by default all exposes can run
		return True
	
	def on_model_changed(self, model):
		# this function is called when the model being used changes
		# it can be used to update the default values after initialization
		pass

	def hook_on_change_fn(self, fn):
		self.on_change_callback = fn

	def add_change_event_listener(self, fn):
		self.change_listeners.append(fn)

	def remove_change_event_listener(self, fn):
		if fn in self.change_listeners:
			self.change_listeners.remove(fn)

	def hook_on_change_fn_hijack(self, fn):
		self.on_change_callback = fn
		self.on_change_callback_hijack = True

	def get_ui_label_identifier(self):
		return self.data["label"]
	
	def get_special_priority(self):
		return 0
	
	def get_data(self):
		return self.data
	
	def destroy(self):
		pass
	
def save_image_file(gimp_image, file_path, half_size=False):
	if half_size:
		# we need to create a new image with half size
		new_image = Gimp.Image.new(gimp_image.get_width(), gimp_image.get_height(), gimp_image.get_base_type())

		# now we need to scale each layer and add it to the new image
		new_layer = Gimp.Layer.new_from_visible(gimp_image, new_image)
		new_image.insert_layer(new_layer, None, 0)

		new_width = gimp_image.get_width() // 2
		new_height = gimp_image.get_height() // 2

		new_image.scale(new_width, new_height)
	else:
		new_image = gimp_image

	gimp_image = new_image

	# create a new gfile to save the image
	gfile = Gio.File.new_for_path(file_path)
	Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, gimp_image, gfile, None)

	if half_size:
		gimp_image.delete()

	return (gfile, )

class AIHubExposeImage(AIHubExposeBase):
	def get_special_priority(self):
		return 100
	
	def __init__(self, id, data, workflow_context, workflow_id, workflow, project_current_timeline_path, project_saved_path, apinfo, is_frame=False):
		super().__init__(id, data, workflow_context, workflow_id, workflow, project_current_timeline_path, project_saved_path, apinfo)

		self.label: Gtk.Label = None
		self.error_label: AIHubLabel = None
		self.success_label: AIHubLabel = None
		self.namelabel: Gtk.Label = None
		self.select_button: Gtk.Button = None
		self.select_from_layer_button = None
		self.select_combo: Gtk.ComboBox = None
		self.image_preview: Gtk.Image = None
		self.selected_filename: str = None
		self.selected_image = None
		self.selected_layer = None
		self.selected_layername = None
		self.box: Gtk.Box = None
		self.info_only_mode: bool = False

		self.uploaded_file_path: str = None
		self.value_pos_x: int = 0
		self.value_pos_y: int = 0
		self.value_width: int = 0
		self.value_height: int = 0
		self.value_layer_id: str = ""

		self.is_frame = is_frame

		known_tooltip = None

		if ("tooltip" in self.data and self.data["tooltip"] is not None and self.data["tooltip"] != ""):
			known_tooltip = self.data["tooltip"]

		if (not self.is_using_internal_file()):
			#first let's build a file selector
			self.select_button = Gtk.Button(label=_("Select a video frame from a file") if is_frame else _("Select an image from a file"), xalign=0)
			self.select_button.connect("clicked", self.on_file_chooser_clicked)

			self.select_from_layer_button = Gtk.Button(label=_("Use current layer intersection"), xalign=0)
			self.select_from_layer_button.connect("clicked", self.on_select_from_layer_button_clicked)

			self.select_combo = Gtk.ComboBox()

			renderer_pixbuf = Gtk.CellRendererPixbuf()
			renderer_text = Gtk.CellRendererText()

			self.select_combo.pack_start(renderer_pixbuf, False)
			self.select_combo.add_attribute(renderer_pixbuf, "pixbuf", 2)
			self.select_combo.pack_start(renderer_text, True)
			self.select_combo.add_attribute(renderer_text, "text", 1)

			if known_tooltip is not None:
				self.select_combo.set_tooltip_text(known_tooltip)
				self.select_button.set_tooltip_text(known_tooltip)
				self.select_from_layer_button.set_tooltip_text(known_tooltip)

			if self.image_model is not None:
				# we need to add the option for no selection, but make a copy of the model first
				# because we don't want to modify the original model
				model = self.image_model
				if self.data.get("optional", False):
					# Get column types from the original model
					n_columns = self.image_model.get_n_columns()
					column_types = [self.image_model.get_column_type(i) for i in range(n_columns)]
					new_model = Gtk.ListStore(*column_types)
					# Copy all rows from the original model
					for row in model:
						new_model.append(list(row))
					model = new_model
					# we want to insert at the top the none option
					model.insert(0, [ -1, _("No image selected"), None ])

				self.select_combo.set_model(model)
				if model is not None and len(model) > 0:
					self.select_combo.set_active(0)

			if (
				self.initial_value is not None and
				isinstance(self.initial_value, dict) and "_local_file" in self.initial_value and 
				os.path.exists(self.initial_value["_local_file"])
			):
				self.selected_filename = self.initial_value["_local_file"]

				self.select_button.set_label(os.path.basename(self.selected_filename) + " (" + _("Click to clear") + ")")

			# make a box to have the label and the field
			self.label = Gtk.Label(self.data["label"], xalign=0)
			self.error_label = AIHubLabel("", b"color: red;")
			self.success_label = AIHubLabel("", b"color: green;")
			self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
			self.box.pack_start(self.label, False, False, 0)
			self.box.pack_start(self.error_label.get_widget(), False, False, 0)
			self.box.pack_start(self.success_label.get_widget(), False, False, 0)
			self.box.pack_start(self.select_button, True, True, 0)
			self.box.pack_start(self.select_from_layer_button, True, True, 0)
			self.box.pack_start(self.select_combo, True, True, 0)

			self.image_preview = Gtk.Image()
			self.box.pack_start(self.image_preview, True, True, 0)

			self.load_image_preview()

			# ensure to add spacing from the top some margin top
			self.box.set_margin_top(10)
		else:
			self.label = Gtk.Label(self.data["label"], xalign=0)
			self.error_label = AIHubLabel("", b"color: red;")
			self.success_label = AIHubLabel("", b"color: green;")
			self.namelabel = Gtk.Label("", xalign=0)
			self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
			self.box.pack_start(self.label, False, False, 0)
			self.box.pack_start(self.namelabel, False, False, 0)
			self.box.pack_start(self.error_label.get_widget(), False, False, 0)
			self.box.pack_start(self.success_label.get_widget(), False, False, 0)
			self.box.set_margin_top(10)

			self.image_preview = Gtk.Image()
			self.box.pack_start(self.image_preview, True, True, 0)

			if known_tooltip is not None:
				self.label.set_tooltip_text(known_tooltip)
				self.namelabel.set_tooltip_text(known_tooltip)
				self.image_preview.set_tooltip_text(known_tooltip)

			self.load_image_data_for_internal()

		if self.is_frame:
			self.frame_widget_label = Gtk.Label(_("Frame index (zero indexed)"), xalign=0)

			initial_frame_number = self.initial_value.get("frame", 0) if self.initial_value is not None else 0
			frame_adjustment = Gtk.Adjustment(
				value=initial_frame_number,
				lower=0,
				upper=1000000,
				step_increment=1,
			)
			self.frame_widget = Gtk.SpinButton(adjustment=frame_adjustment, climb_rate=1, digits=0, numeric=True)
			self.frame_widget.set_input_purpose(Gtk.InputPurpose.NUMBER)

			self.total_frame_widget_label = Gtk.Label(_("Total frames in the video"), xalign=0)

			initial_total_frames = self.initial_value.get("total_frames", 1) if self.initial_value is not None else 1
			total_frames_adjustment = Gtk.Adjustment(
				value=initial_total_frames,
				lower=1,
				upper=1000000,
				step_increment=1,
			)
			self.total_frames_widget = Gtk.SpinButton(adjustment=total_frames_adjustment, climb_rate=1, digits=0, numeric=True)
			self.total_frames_widget.set_input_purpose(Gtk.InputPurpose.NUMBER)

			self.box.pack_start(self.frame_widget_label, False, False, 0)
			self.box.pack_start(self.frame_widget, False, False, 0)
			self.box.pack_start(self.total_frame_widget_label, False, False, 0)
			self.box.pack_start(self.total_frames_widget, False, False, 0)

	def upload_binary(self, ws, relegator=None, half_size=False):
		self.uploaded_file_path = None

		if (self.info_only_mode):
			return True
		
		# first lets get the file that we are going to upload
		file_to_upload = None
		if (not self.is_using_internal_file()):
			if (self.selected_filename is not None and os.path.exists(self.selected_filename)):
				file_to_upload = self.selected_filename

				if half_size:
					# we need to load the image and resize it to half size and save it to a temporary file
					# use gimp to resize
					loaded_image = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, Gio.File.new_for_path(self.selected_filename))
					new_width = loaded_image.get_width() // 2
					new_height = loaded_image.get_height() // 2
					loaded_image.scale(new_width, new_height)

					file_to_upload = os.path.join(GLib.get_tmp_dir(), f"aihub_temp_image_halfsize_{random.randint(0, 1000000)}.webp")

					Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, loaded_image, Gio.File.new_for_path(file_to_upload), None)
					loaded_image.delete()
						
			elif (self.select_combo.get_active() != -1 and self.select_combo.get_model() is not None):
				tree_iter = self.select_combo.get_active_iter()
				if tree_iter is not None:
					id_of_image = self.select_combo.get_model()[tree_iter][0]
					if id_of_image == -1:
						# no image selected
						if self.data.get("optional", False):
							# optional, so we can skip, mark it as successful
							return True
						return False
					gimp_image = Gimp.Image.get_by_id(id_of_image)
					if gimp_image is not None:
						# save the image to a temporary file
						file_to_upload = os.path.join(GLib.get_tmp_dir(), f"aihub_temp_image_{id_of_image}.webp")

						(gfile, ) = save_image_file(gimp_image, file_to_upload, half_size=half_size)
			else:
				# nothing selected
				if self.data.get("optional", False):
					# optional, so we can skip, mark it as successful
					return True
				return False
		else:
			load_type = self.data.get("type", "upload")
			# an image has been selected but not a layer
			if self.selected_image is not None and self.selected_layer is None:
				# save the image to a temporary file
				id_of_image = self.selected_image.get_id()
				file_to_upload = os.path.join(GLib.get_tmp_dir(), f"aihub_temp_image_{id_of_image}.webp")
				# create a new gfile to save the image
				(gfile, ) = save_image_file(self.selected_image, file_to_upload, half_size=half_size)
			# an image and a layer have been selected
			elif self.selected_image is not None and self.selected_layer is not None and load_type == "current_layer":
				# save the layer to a temporary file
				id_of_image = self.selected_image.get_id()
				# make a file to print the time for debugging
				file_to_upload = os.path.join(GLib.get_tmp_dir(), f"aihub_temp_layer_{id_of_image}_{self.selected_layer.get_id()}.webp")
				# create a new gfile to save the image
				gfile = Gio.File.new_for_path(file_to_upload)

				# Take the layer and only the layer and make a copy and save it to the new file
				# because Gimp.file_save needs an image, not a layer
				# first then we need to create a new image with the same dimensions and type as the layer
				new_image = Gimp.Image.new(self.selected_layer.get_width(), self.selected_layer.get_height(), self.selected_image.get_base_type())
				layer_to_work_on = self.selected_layer
				new_layer = Gimp.Layer.new_from_drawable(layer_to_work_on, new_image)
				new_image.insert_layer(new_layer, None, 0)
				new_layer.set_offsets(0,0)
				new_layer.set_opacity(100.0)
				new_layer.set_visible(True)

				if half_size:
					new_width = new_image.get_width() // 2
					new_height = new_image.get_height() // 2
					new_image.scale(new_width, new_height)

				Gimp.displays_flush()
				try:
					Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, new_image, gfile, None)
					Gimp.displays_flush()
				except Exception as e:
					raise e
				finally:
					new_image.delete()
					Gimp.displays_flush()
			elif self.selected_image is not None and self.selected_layer is not None and (
				load_type == "current_layer_at_image_intersection" or
				load_type == "merged_image_current_layer_intersection" or
				load_type == "merged_image_current_layer_intersection_without_current_layer"
			):
				id_of_image = self.selected_image.get_id()
				file_to_upload = os.path.join(GLib.get_tmp_dir(), f"aihub_temp_layer_{id_of_image}_{load_type}_{self.selected_layer.get_id()}.webp")
				gfile = Gio.File.new_for_path(file_to_upload)
				
				new_image = Gimp.Image.new(self.selected_image.get_width(), self.selected_image.get_height(), self.selected_image.get_base_type())
				new_layer = None
				was_visible = False
				if load_type == "current_layer_at_image_intersection":
					new_layer = Gimp.Layer.new_from_drawable(self.selected_layer, new_image)
					new_layer.set_visible(True)
					new_image.insert_layer(new_layer, None, 0)
					# we need to call the procedure gimp-layer-resize-to-image-size
					procedure = Gimp.get_pdb().lookup_procedure("gimp-layer-resize-to-image-size")
					config = procedure.create_config()
					config.set_property('layer', new_layer)
					procedure.run(config)
				elif load_type == "merged_image_current_layer_intersection":
					new_layer = Gimp.Layer.new_from_visible(self.selected_image, new_image)
					new_image.insert_layer(new_layer, None, 0)
				elif load_type == "merged_image_current_layer_intersection_without_current_layer":
					if self.selected_layer.get_visible():
						was_visible = True
						self.selected_layer.set_visible(False)
					new_layer = Gimp.Layer.new_from_visible(self.selected_image, new_image)
					new_image.insert_layer(new_layer, None, 0)

				new_layer.set_offsets(0,0)
				new_layer.set_opacity(100.0)
				new_layer.set_visible(True)

				# now we need to calculate the intersection of the current layer with the image
				layer_offsets = self.selected_layer.get_offsets()
				x1 = max(0, layer_offsets.offset_x)
				y1 = max(0, layer_offsets.offset_y)
				x2 = min(self.selected_image.get_width(), layer_offsets.offset_x + self.selected_layer.get_width())
				y2 = min(self.selected_image.get_height(), layer_offsets.offset_y + self.selected_layer.get_height())

				# now we need to crop the new layer to the intersection
				new_width = x2 - x1
				new_height = y2 - y1
				# for some reason the resize function takes negative offsets
				offset_x = -x1
				offset_y = -y1

				new_image.resize(new_width, new_height, offset_x, offset_y)

				if half_size:
					new_width = new_image.get_width() // 2
					new_height = new_image.get_height() // 2
					new_image.scale(new_width, new_height)

				try:
					Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, new_image, gfile, None)
				except Exception as e:
					raise e
				finally:
					if was_visible and load_type == "merged_image_current_layer_intersection_without_current_layer":
						self.selected_layer.set_visible(True)
					new_image.remove_layer(new_layer)
					new_layer.delete()
					new_image.delete()

			elif self.selected_image is not None and self.selected_layer is not None and load_type == "merged_image_without_current_layer":
				# save the layer to a temporary file
				id_of_image = self.selected_image.get_id()
				file_to_upload = os.path.join(GLib.get_tmp_dir(), f"aihub_temp_layer_{id_of_image}_{load_type}_{self.selected_layer.get_id()}.webp")

				# hide the layer if not already visible
				was_visible = False
				if self.selected_layer.get_visible():
					was_visible = True
					self.selected_layer.set_visible(False)
				
				try:
					(gfile, ) = save_image_file(self.selected_image, file_to_upload, half_size=half_size)
				except Exception as e:
					raise e
				finally:
					# restore the visibility
					if was_visible:
						self.selected_layer.set_visible(True)
						Gimp.displays_flush()
			else:
				# no image selected
				if self.data.get("optional", False):
					# optional, so we can skip, mark it as successful
					return True
				return False
			
		# now we need to make a calculation for a hash of the file to upload
		hash_md5 = hashlib.md5()
		# make a new binary data to upload
		file_data = b""
		with open(file_to_upload, "rb") as f:
			data = f.read()  # read whole thing
			file_data = data

			if data.startswith(b'\x89PNG\r\n\x1a\n'):
				pos = 8
				while pos < len(data):
					if pos + 8 > len(data):
						break
					length = struct.unpack(">I", data[pos:pos+4])[0]
					chunk_type = data[pos+4:pos+8]
					chunk_data = data[pos+8:pos+8+length]
					if chunk_type in [b'IHDR', b'IDAT', b'IEND']:
						hash_md5.update(chunk_type)
						hash_md5.update(chunk_data)
					pos += 8 + length + 4
			else:
				hash_md5.update(data)
				
		upload_file_hash = hash_md5.hexdigest()

		# now we can upload the file, using that hash as filename, if the file does not exist
		binary_header = {
			"type": "FILE_UPLOAD",
			"filename": upload_file_hash,
			"workflow_id": self.workflow_id,
			"if_not_exists": True
		}

		relegator.reset()

		ws.send(json.dumps(binary_header))

		if not relegator.wait(10):
			self.error_label.show()
			self.success_label.hide()
			self.error_label.set_text(_("Error uploading file: Timeout waiting for server response"))
			return False
		
		response_data = relegator.last_response

		if (response_data["type"] == "ERROR"):
			self.error_label.show()
			self.success_label.hide()
			self.error_label.set_text(_("Error uploading file: {}").format(response_data.get('message', _('Unknown error'))))
		elif (response_data["type"] == "UPLOAD_ACK"):
			# we can now send the file data
			self.error_label.hide()
			self.success_label.hide()
			try:
				relegator.reset()
				ws.send_bytes(file_data)
				
				# wait for the upload ack
				if not relegator.wait(10):
					self.error_label.show()
					self.success_label.hide()
					self.error_label.set_text("Error uploading file: Timeout waiting for server response after sending file data")
					return False

				response_data = relegator.last_response

				if (response_data["type"] == "ERROR"):
					self.error_label.show()
					self.success_label.hide()
					self.error_label.set_text(_("Error uploading file: {}").format(response_data.get('message', _('Unknown error'))))
					return False
				elif (response_data["type"] == "FILE_UPLOAD_SUCCESS"):
					filename = response_data.get("file", None)
					self.uploaded_file_path = filename

					if self.uploaded_file_path is None:
						self.error_label.show()
						self.success_label.hide()
						self.error_label.set_text("Error uploading file: No file path returned by server")
						return False

					self.success_label.show()
					self.error_label.hide()
					self.success_label.set_text("File uploaded successfully")

					# upload successful
					return True
				# unexpected response
				self.error_label.show()
				self.success_label.hide()
				self.error_label.set_text(_("Unexpected response from server: {}").format(response_data.get('message', _('Unknown error'))))
				return False
			except Exception as e:
				self.error_label.show()
				self.success_label.hide()
				self.error_label.set_text(_("Error sending file data: {}").format(str(e)))
				return False
		elif (response_data["type"] == "FILE_UPLOAD_SKIP"):
			self.error_label.hide()
			self.success_label.show()
			self.success_label.set_text(_("File already exists on server, upload skipped"))

			filename = response_data.get("file", None)
			self.uploaded_file_path = filename

			if self.uploaded_file_path is None:
				self.error_label.show()
				self.success_label.hide()
				self.error_label.set_text("Error uploading file: No file path returned by server")
				return False
			
			return True

		return False

	def load_image_data_for_internal(self):
		load_type = self.data.get("type", "upload")
		# load types are ["current_layer","merged_image",
		# "merged_image_without_current_layer","merged_image_current_layer_intersection",
		# "merged_image_current_layer_intersection_without_current_layer",
		# "current_layer_at_image_intersection", "upload",]
		if (
			load_type == "current_layer" or
			load_type == "merged_image_without_current_layer" or
			load_type == "merged_image_current_layer_intersection" or
			load_type == "merged_image_current_layer_intersection_without_current_layer" or
			load_type == "current_layer_at_image_intersection"
		):
			# this is our current GIMP image
			image_selected = self.current_image
			if image_selected is not None:
				layers = image_selected.get_selected_layers()
				current_layer = None
				if layers is not None and len(layers) > 0:
					current_layer = layers[0]

				layer = None
				if current_layer is not None and (
					load_type == "current_layer" or
					load_type == "merged_image_without_current_layer" or
					load_type == "merged_image_current_layer_intersection" or
					load_type == "merged_image_current_layer_intersection_without_current_layer" or
					load_type == "current_layer_at_image_intersection"
				):
					layer = current_layer

				if layer is not None:
					self.selected_layer = layer
					self.selected_image = image_selected
					self.selected_layername = layer.get_name()

					if layer is not None and (
						load_type == "current_layer" or
						load_type == "current_layer_at_image_intersection" or
						load_type == "merged_image_current_layer_intersection" or
						load_type == "merged_image_current_layer_intersection_without_current_layer"
					):
						offsets = layer.get_offsets()
						self.value_pos_x = offsets.offset_x
						self.value_pos_y =  offsets.offset_y
						self.value_layer_id = str(layer.get_id())
						if load_type == "current_layer":
							self.value_width = layer.get_width()
							self.value_height = layer.get_height()
						else:
							# for intersection types we need to calculate the intersection
							x1 = max(0, offsets.offset_x)
							y1 = max(0, offsets.offset_y)
							x2 = min(image_selected.get_width(), offsets.offset_x + layer.get_width())
							y2 = min(image_selected.get_height(), offsets.offset_y + layer.get_height())
							self.value_width = x2 - x1
							self.value_height = y2 - y1
							if self.value_width < 0:
								self.value_width = 0
							if self.value_height < 0:
								self.value_height = 0
							self.value_pos_x = x1
							self.value_pos_y = y1
					else:
						self.value_pos_x = 0
						self.value_pos_y = 0
						self.value_layer_id = ""
						self.value_width = image_selected.get_width()
						self.value_height = image_selected.get_height()
				else:
					self.selected_image = None
					self.selected_layer = None
					self.value_pos_x = 0
					self.value_pos_y = 0
					self.value_layer_id = ""
					self.value_width = 0
					self.value_height = 9
		else:
			self.selected_image = self.current_image
			self.selected_layer = None
			self.value_pos_x = 0
			self.value_pos_y = 0
			self.value_layer_id = ""
			self.value_width = self.selected_image.get_width() if self.selected_image is not None else 0
			self.value_height = self.selected_image.get_height() if self.selected_image is not None else 0

		self.load_image_preview()

	def on_select_from_layer_button_clicked(self, widget):
		# first thing we are simply going to do is to is the same process as merged_image_current_layer_intersection
		# to export this image to a file
		if self.current_image is not None:
			selected_layers = self.current_image.get_selected_layers()
			if selected_layers is not None and len(selected_layers) > 0:
				selected_layer = selected_layers[0]
				id_of_image = self.current_image.get_id()
				id_of_layer = selected_layer.get_id()
				random_number = random.randint(1000, 9999)
				file_to_upload = os.path.join(GLib.get_tmp_dir(), f"aihub_temp_file_{id_of_image}_layer_extract_{id_of_layer}_{random_number}.webp")
				gfile = Gio.File.new_for_path(file_to_upload)
				
				new_image = Gimp.Image.new(self.current_image.get_width(), self.current_image.get_height(), self.current_image.get_base_type())
				new_layer = Gimp.Layer.new_from_visible(self.current_image, new_image)
				new_image.insert_layer(new_layer, None, 0)

				new_layer.set_offsets(0,0)
				new_layer.set_opacity(100.0)
				new_layer.set_visible(True)

				# now we need to calculate the intersection of the current layer with the image
				layer_offsets = selected_layer.get_offsets()
				x1 = max(0, layer_offsets.offset_x)
				y1 = max(0, layer_offsets.offset_y)
				x2 = min(self.current_image.get_width(), layer_offsets.offset_x + selected_layer.get_width())
				y2 = min(self.current_image.get_height(), layer_offsets.offset_y + selected_layer.get_height())

				# now we need to crop the new layer to the intersection
				new_width = x2 - x1
				new_height = y2 - y1
				# for some reason the resize function takes negative offsets
				offset_x = -x1
				offset_y = -y1

				new_image.resize(new_width, new_height, offset_x, offset_y)

				try:
					Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, new_image, gfile, None)
				except Exception as e:
					raise e
				finally:
					new_image.remove_layer(new_layer)
					new_layer.delete()
					new_image.delete()

					self.selected_filename = file_to_upload
					self.select_button.set_label(os.path.basename(self.selected_filename) + " (" + _("Click to clear") + ")")
					self.on_file_selected()
					self.select_combo.hide()
					self.select_from_layer_button.hide()

	def on_file_chooser_clicked(self, widget):
		self.uploaded_file_path = None
		if (self.selected_filename is not None):
			# clear the selection
			self.selected_filename = None
			if self.is_frame:
				self.select_button.set_label(_("Select a frame from the video"))
			else:
				self.select_button.set_label(_("Select an image from a file"))
			self.select_combo.show()
			self.select_from_layer_button.show()
			self.image_preview.clear()
			self.on_file_selected()
			return
		
		dialog = Gtk.FileChooserDialog(
			title=_("Select an image file"),
			parent=None,
			action=Gtk.FileChooserAction.OPEN,
			buttons=(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
		)
		Gtk.Window.set_keep_above(dialog, True)
		file_filter = Gtk.FileFilter()
		file_filter.set_name(_("Image files"))
		file_filter.add_pattern("*.png")
		file_filter.add_pattern("*.jpg")
		file_filter.add_pattern("*.jpeg")
		file_filter.add_pattern("*.webp")
		dialog.add_filter(file_filter)
		# Do not add any other filters

		response = dialog.run()
		if response == Gtk.ResponseType.OK:
			filename = dialog.get_filename()
			self.select_button.set_label(os.path.basename(filename) + " (" + _("Click to clear") + ")")
			self.selected_filename = filename
			self.on_file_selected()
			self.select_combo.hide()
			self.select_from_layer_button.hide()
		dialog.destroy()

	def get_widget(self):
		return self.box
	
	def is_using_internal_file(self):
		if (self.data.get("type", "upload") == "upload" or self.is_frame):
			return False
		return True

	def set_initial_value(self):
		# no initial value by default
		# either it loads from the saved.json file
		# or it is empty because a default cannot be set
		return
	
	def on_file_selected(self):
		self.on_change(self.get_value_base())
		self.error_label.hide()
		self.success_label.hide()
		self.load_image_preview()

	def load_image_preview(self):
		if self.is_using_internal_file():
			load_type = self.data.get("type", "upload")
			if self.selected_image is not None:
				try:
					height_from_ratio = int(self.value_height * (400 / self.value_width))
					pixbuf = None
					if load_type == "merged_image":
						pixbuf = self.selected_image.get_thumbnail(400,height_from_ratio,Gimp.PixbufTransparency.KEEP_ALPHA)
						self.namelabel.set_text(self.selected_image.get_name())
					elif load_type == "current_layer":
						pixbuf = self.selected_layer.get_thumbnail(400,height_from_ratio,Gimp.PixbufTransparency.KEEP_ALPHA)
						self.namelabel.set_text(self.selected_layer.get_name())
					elif (
						load_type == "merged_image_current_layer_intersection" or
						load_type == "merged_image_current_layer_intersection_without_current_layer" or
						load_type == "current_layer_at_image_intersection"
					):
						# first we need to calculate the intersection of the current layer with the image
						# to get x1, y1, x2, y2
						if self.selected_layer is not None:
							should_toggle_visibility = load_type == "merged_image_current_layer_intersection_without_current_layer"
							original_visible_state = self.selected_layer.get_visible()

							if should_toggle_visibility and original_visible_state:
								self.selected_layer.set_visible(False)

							# now we need to calculate x1, y1, x2, y2
							layer_offsets = self.selected_layer.get_offsets()
							x1 = max(0, layer_offsets.offset_x)
							y1 = max(0, layer_offsets.offset_y)
							x2 = min(self.selected_image.get_width(), layer_offsets.offset_x + self.selected_layer.get_width())
							y2 = min(self.selected_image.get_height(), layer_offsets.offset_y + self.selected_layer.get_height())
							# now we need to crop the new layer to the intersection
							new_width = x2 - x1
							new_height = y2 - y1
							# for some reason the resize function takes negative offsets
							offset_x = -x1
							offset_y = -y1

							if new_width <= 0 or new_height <= 0 or offset_x > 0 or offset_y > 0:
								# no intersection
								self.image_preview.clear()
								return
							
							new_image = Gimp.Image.new(self.selected_image.get_width(), self.selected_image.get_height(), self.selected_image.get_base_type())

							# first we must create a new layer from visible
							new_layer = None
							if load_type == "current_layer_at_image_intersection":
								new_layer = Gimp.Layer.new_from_drawable(self.selected_layer, new_image)
								new_image.insert_layer(new_layer, None, 0)
								#copy the same offsets
								original_offsets = self.selected_layer.get_offsets()
								new_layer.set_offsets(original_offsets.offset_x, original_offsets.offset_y)
								new_layer.set_opacity(100.0)
								new_layer.set_visible(True)

								# we need to call the procedure gimp-layer-resize-to-image-size
								procedure = Gimp.get_pdb().lookup_procedure('gimp-layer-resize-to-image-size')
								config = procedure.create_config()
								config.set_property('layer', new_layer)
								procedure.run(config)
							else:
								new_layer = Gimp.Layer.new_from_visible(self.selected_image, new_image)
								new_image.insert_layer(new_layer, None, 0)
								new_layer.set_offsets(0,0)
								new_layer.set_opacity(100.0)
								new_layer.set_visible(True)
							
							new_layer.resize(new_width, new_height, offset_x, offset_y)
							pixbuf = new_layer.get_thumbnail(400,height_from_ratio,Gimp.PixbufTransparency.KEEP_ALPHA)
							new_image.remove_layer(new_layer)
							new_layer.delete()
							new_image.delete()

							if should_toggle_visibility and original_visible_state:
								self.selected_layer.set_visible(True)

							if load_type == "current_layer_at_image_intersection":
								self.namelabel.set_text(self.selected_layer.get_name())
							else:
								self.namelabel.set_text(self.selected_image.get_name())
					elif load_type == "merged_image_without_current_layer":
						# hide the layer if not already visible
						was_visible = False
						if self.selected_layer is not None and self.selected_layer.get_visible():
							was_visible = True
							self.selected_layer.set_visible(False)
						pixbuf = self.selected_image.get_thumbnail(400,height_from_ratio,Gimp.PixbufTransparency.KEEP_ALPHA)
						# restore the visibility
						if self.selected_layer is not None and was_visible:
							self.selected_layer.set_visible(True)
							# bug in GIMP 3.0.10 where the thumbnail is not updated if the layer is made visible again
							pixbuf2 = self.selected_image.get_thumbnail(400,height_from_ratio,Gimp.PixbufTransparency.KEEP_ALPHA)
						self.namelabel.set_text(self.selected_image.get_name())
					self.image_preview.set_from_pixbuf(pixbuf)
				except Exception as e:
					self.image_preview.clear()
			else:
				self.image_preview.clear()
		else:
			if (self.selected_filename is not None and os.path.exists(self.selected_filename)):
				try:
					pixbuf = Pixbuf.new_from_file(self.selected_filename)
					width = 400
					height = int(pixbuf.get_height() * (width / pixbuf.get_width()))
					self.value_height = pixbuf.get_height()
					self.value_width = pixbuf.get_width()
					self.value_layer_id = ""
					self.value_pos_x = 0
					self.value_pos_y = 0
					pixbuf = pixbuf.scale_simple(width, height, InterpType.BILINEAR)
					self.image_preview.set_from_pixbuf(pixbuf)
				except Exception as e:
					# try to load the image using GIMP
					try:
						gfile = Gio.File.new_for_path(self.selected_filename)
						loaded_image = Gimp.file_load(Gimp.RunMode.NONINTERACTIVE, gfile)
						pixbuf = loaded_image.get_thumbnail(400, int(loaded_image.get_height() * (400 / loaded_image.get_width())), Gimp.PixbufTransparency.KEEP_ALPHA)
						self.value_height = loaded_image.get_height()
						self.value_width = loaded_image.get_width()
						self.value_layer_id = ""
						self.value_pos_x = 0
						self.value_pos_y = 0
						self.image_preview.set_from_pixbuf(pixbuf)
						loaded_image.delete()
					except Exception as e:
						self.image_preview.clear()
						self.value_height = 0
						self.value_width = 0
						self.value_layer_id = ""
						self.value_pos_x = 0
						self.value_pos_y = 0

						self.error_label.show()
						self.success_label.hide()
						self.error_label.set_text(_("Failed to load image"))
			elif (self.select_combo.get_active() != -1 and self.select_combo.get_model() is not None):
				tree_iter = self.select_combo.get_active_iter()
				if tree_iter is not None:
					id_of_image = self.select_combo.get_model()[tree_iter][0]
					if id_of_image == -1:
						# no image selected
						self.value_height = 0
						self.value_width = 0
						self.value_layer_id = ""
						self.value_pos_x = 0
						self.value_pos_y = 0
						return
					gimp_image = Gimp.Image.get_by_id(id_of_image)
					if gimp_image is not None:
						self.value_height = gimp_image.get_height()
						self.value_width = gimp_image.get_width()
						self.value_layer_id = ""
						self.value_pos_x = 0
						self.value_pos_y = 0
			else:
				self.image_preview.clear()
				self.value_height = 0
				self.value_width = 0
				self.value_layer_id = ""
				self.value_pos_x = 0
				self.value_pos_y = 0
	
	def get_value_base(self):
		dictValue = None
		if (self.selected_filename is not None and os.path.exists(self.selected_filename)):
			dictValue = {
				"_local_file": self.selected_filename,
				"local_file": self.uploaded_file_path,
				"pos_x": self.value_pos_x,
				"pos_y": self.value_pos_y,
				"layer_id": self.value_layer_id
			}
		else:
			dictValue = {
				"local_file": self.uploaded_file_path,
				"pos_x": self.value_pos_x,
				"pos_y": self.value_pos_y,
				"layer_id": self.value_layer_id
			}
		if self.info_only_mode:
			dictValue["value_width"] = self.value_width
			dictValue["value_height"] = self.value_height
		if self.is_frame:
			del dictValue["layer_id"]
			del dictValue["pos_x"]
			del dictValue["pos_y"]
			dictValue["frame"] = self.frame_widget.get_value_as_int()
			dictValue["total_frames"] = self.total_frames_widget.get_value_as_int()
		return dictValue
	
	def get_value(self, half_size=False, half_size_coords=False):
		base_value = self.get_value_base()
		# remove _local_file from the value
		if base_value is not None and "_local_file" in base_value:
			del base_value["_local_file"]
		if base_value is not None and self.info_only_mode:
			del base_value["local_file"]

		if half_size:
			if "pos_x" in base_value and half_size_coords:
				base_value["pos_x"] = base_value["pos_x"] // 2
			if "pos_y" in base_value and half_size_coords:
				base_value["pos_y"] = base_value["pos_y"] // 2
			if "value_width" in base_value:
				base_value["value_width"] = base_value["value_width"] // 2
			if "value_height" in base_value:
				base_value["value_height"] = base_value["value_height"] // 2

		return base_value
	
	def current_image_changed(self, image, model):
		super().current_image_changed(image, model)

		if not self.is_using_internal_file():
			# update the model of the select combo
			# if the model is different from the current one
			if (self.select_combo.get_model() != model and model is not None):
				if self.data.get("optional", False):
					# Get column types from the original model
					n_columns = model.get_n_columns()
					column_types = [model.get_column_type(i) for i in range(n_columns)]
					new_model = Gtk.ListStore(*column_types)

					# Copy all rows from the original model
					for row in model:
						new_model.append(list(row))
					# we want to insert at the top the none option
					new_model.insert(0, [ -1, _("No image selected"), None ])
					model = new_model
					
				self.select_combo.set_model(model)
				if model is not None and len(model) > 0:
					self.select_combo.set_active(0)
			self.load_image_preview()
		else:
			self.load_image_data_for_internal()

		self.check_validity(self.get_value())

	def after_ui_built(self, workflow_elements_all):
		self.check_validity(self.get_value())
		if (self.is_using_internal_file()):
			pass
		else:
			if self.selected_filename is not None:
				self.select_combo.hide()
				self.select_from_layer_button.hide()
			else:
				self.select_combo.show()
				self.select_from_layer_button.show()
			self.select_button.show()

	def on_refresh(self):
		# check that the select combo has something selected that actually exists in the model
		# this is because the model can change when the current image changes
		if self.select_combo is not None and self.select_combo.get_active() == -1 and self.select_combo.get_model() is not None and len(self.select_combo.get_model()) > 0:
			self.select_combo.set_active(0)

		self.load_image_data_for_internal()
		self.check_validity(self.get_value())

	def check_validity(self, value):
		if (not self.is_using_internal_file()):
			if (self.selected_filename is None and self.select_combo.get_active() == -1):
				self.error_label.show()
				self.success_label.hide()
				self.error_label.set_text(_("Please select a valid image"))
			elif (self.value_width == 0 or self.value_height == 0) and not self.data.get("optional", False):
				self.error_label.show()
				self.success_label.hide()
				self.error_label.set_text(_("The selected image has no width or height"))
			else:
				self.success_label.hide()
				self.error_label.hide()
		else:
			if (self.selected_image is None):
				self.error_label.show()
				self.success_label.hide()
				self.error_label.set_text(_("There is no active image/layer in GIMP"))
			elif ((self.value_width == 0 or self.value_height == 0) and not self.data.get("optional", False)):
				self.error_label.show()
				self.success_label.hide()
				self.error_label.set_text(_("The selected image has no width or height"))
			else:
				self.error_label.hide()
				self.success_label.hide()

	def can_run(self):
		if self.data.get("optional", False):
			return True
		if (not self.is_using_internal_file()):
			return self.selected_filename is not None or self.select_combo.get_active() != -1
		else:
			return self.selected_image is not None
		
	def force_select(self, path_value, frame_value=None, total_frames_value=None):
		# set the uploaded_file_path to the given path_value
		if (not self.is_using_internal_file()):
			self.selected_filename = path_value
			self.select_button.set_label(os.path.basename(self.selected_filename) + " (" + _("Click to clear") + ")")
			if self.is_frame and frame_value is not None and total_frames_value is not None:
				self.frame_widget.set_value(frame_value)
				self.total_frames_widget.set_value(total_frames_value)
			self.on_file_selected()

class AIHubExposeImageInfoOnly(AIHubExposeImage):
	def __init__(self, id, data, workflow_context, workflow_id, workflow, project_current_timeline_path, project_saved_path, apinfo):
		super().__init__(id, data, workflow_context, workflow_id, workflow, project_current_timeline_path, project_saved_path, apinfo)

		self.info_only_mode = True

class AIHubExposeFrame(AIHubExposeImage):
	def __init__(self, id, data, workflow_context, workflow_id, workflow, project_current_timeline_path, project_saved_path, apinfo):
		super().__init__(id, data, workflow_context, workflow_id, workflow, project_current_timeline_path, project_saved_path, apinfo, is_frame=True)

class AIHubExposeFileBase(AIHubExposeBase):
	def __init__(self, id, data, workflow_context, workflow_id, workflow, project_current_timeline_path, project_saved_path, apinfo, select_button_label=None, file_types=None, file_types_label=None):
		super().__init__(id, data, workflow_context, workflow_id, workflow, project_current_timeline_path, project_saved_path, apinfo)

		self.file_types = file_types if file_types is not None else ["*"]
		self.file_types_label = file_types_label if file_types_label is not None else _("Allowed files")
		self.selected_filename = None
		self.uploaded_file_path = None

		self.label: Gtk.Label = None
		self.error_label: AIHubLabel = None
		
		self.select_button = Gtk.Button(label=select_button_label, xalign=0)
		self.select_button.connect("clicked", self.on_file_chooser_clicked)

		known_tooltip = None

		if ("tooltip" in self.data and self.data["tooltip"] is not None and self.data["tooltip"] != ""):
			known_tooltip = self.data["tooltip"]

		if known_tooltip is not None:
			self.select_button.set_tooltip_text(known_tooltip)

		if (
			self.initial_value is not None and
			isinstance(self.initial_value, dict) and "_local_file" in self.initial_value and 
			os.path.exists(self.initial_value["_local_file"])
		):
			self.selected_filename = self.initial_value["_local_file"]

			self.select_button.set_label(os.path.basename(self.selected_filename) + " (" + _("Click to clear") + ")")

		self.box: Gtk.Box = None

		self.select_from_timeline_files_button: Gtk.Button = None
		self.select_from_timeline_files_button = Gtk.Button(label=_("Select from Timeline Files"), xalign=0)
		self.select_from_timeline_files_button.connect("clicked", self.on_select_from_timeline_files_clicked)

		self.select_from_project_files_button: Gtk.Button = None
		self.select_from_project_files_button = Gtk.Button(label=_("Select from Project Files"), xalign=0)
		self.select_from_project_files_button.connect("clicked", self.on_select_from_project_files_clicked)

		self.label = Gtk.Label(self.data["label"], xalign=0)
		self.label.set_size_request(400, -1)
		self.label.set_line_wrap(True)
		self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
		self.box.pack_start(self.label, False, False, 0)
		self.box.pack_start(self.select_button, False, False, 0)
		self.box.pack_start(self.select_from_timeline_files_button, False, False, 0)
		self.box.pack_start(self.select_from_project_files_button, False, False, 0)
		self.error_label = AIHubLabel("", b"color: red;")
		self.success_label = AIHubLabel("", b"color: green;")
		self.box.pack_start(self.success_label.get_widget(), False, False, 0)
		self.box.pack_start(self.error_label.get_widget(), False, False, 0)
		self.error_label.hide()
		self.success_label.hide()

	def on_file_chooser_clicked(self, widget):
		dialog = Gtk.FileChooserDialog(
			title=self.data["label"],
			parent=None,
			action=Gtk.FileChooserAction.OPEN,
			buttons=(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
		)
		Gtk.Window.set_keep_above(dialog, True)

		file_filter = Gtk.FileFilter()
		file_filter.set_name(self.file_types_label)
		for pattern in self.file_types:
			file_filter.add_pattern(pattern)
		dialog.add_filter(file_filter)

		response = dialog.run()
		if response == Gtk.ResponseType.OK:
			filename = dialog.get_filename()
			self.select_button.set_label(os.path.basename(filename) + " (" + _("Click to change") + ")")
			self.selected_filename = filename
			self.on_file_selected()
		dialog.destroy()

	def on_file_selected(self):
		self.on_change(self.get_value_base())
		self.error_label.hide()
		self.success_label.hide()

	def get_widget(self):
		return self.box

	def get_value_base(self):
		return {
			"_local_file": self.selected_filename,
			"local_file": self.uploaded_file_path,
		}
	
	def get_value(self, half_size=False, half_size_coords=False):
		base_value = self.get_value_base()
		# remove _local_file from the value
		if base_value is not None and "_local_file" in base_value:
			del base_value["_local_file"]
		return base_value
	
	def check_validity(self, value):
		if (self.selected_filename is None or not os.path.exists(self.selected_filename)):
			self.error_label.show()
			self.success_label.hide()
			self.error_label.set_text(_("Please select a valid file"))
		else:
			self.success_label.hide()
			self.error_label.hide()

	def can_run(self):
		if self.data.get("optional", False):
			return True
		return self.selected_filename is not None and os.path.exists(self.selected_filename)
	
	def upload_binary(self, ws, relegator=None, half_size=False):
		self.uploaded_file_path = None

		if self.selected_filename is None and self.data.get("optional", False):
			# optional file, no file selected
			return True

		# now we need to make a calculation for a hash of the file to upload
		hash_md5 = hashlib.md5()
		# make a new binary data to upload
		file_data = b""
		with open(self.selected_filename, "rb") as f:
			data = f.read()  # read whole thing
			file_data = data
			hash_md5.update(data)
				
		upload_file_hash = hash_md5.hexdigest()

		# now we can upload the file, using that hash as filename, if the file does not exist
		binary_header = {
			"type": "FILE_UPLOAD",
			"filename": upload_file_hash,
			"workflow_id": self.workflow_id,
			"if_not_exists": True
		}

		relegator.reset()

		ws.send(json.dumps(binary_header))

		if not relegator.wait(10):
			return _("Error uploading file {}: Timeout waiting for server response").format(self.selected_filename)
		
		response_data = relegator.last_response

		if (response_data["type"] == "ERROR"):
			return _("Error uploading file {}: {}").format(self.selected_filename, response_data.get('message', _('Unknown error')))
		elif (response_data["type"] == "UPLOAD_ACK"):
			try:
				relegator.reset()
				ws.send_bytes(file_data)
				
				# wait for the upload ack
				if not relegator.wait(10):
					return _("Error uploading file {}: Timeout waiting for server response after sending data").format(self.selected_filename)

				response_data = relegator.last_response

				if (response_data["type"] == "ERROR"):
					return _("Error uploading file {}: {}").format(self.selected_filename, response_data.get('message', _('Unknown error')))
				elif (response_data["type"] == "FILE_UPLOAD_SUCCESS"):
					filename = response_data.get("file", None)
					self.uploaded_file_path = filename

					if self.uploaded_file_path is None:
						return _("Error uploading file {}: Server did not return uploaded file path").format(self.selected_filename)

					# upload successful
					return True
				# unexpected response
				return _("Error uploading file {}: Unexpected server response").format(self.selected_filename)
			except Exception as e:
				return _("Error uploading file {}: {}").format(self.selected_filename, str(e))
		elif (response_data["type"] == "FILE_UPLOAD_SKIP"):
			# file already exists on server
			filename = response_data.get("file", None)
			self.uploaded_file_path = filename
			if self.uploaded_file_path is None:
				return _("Error uploading file {}: Server did not return uploaded file path").format(self.selected_filename)
			return True

		return _("Error uploading file {}: Unexpected server response").format(self.selected_filename)
	
	def update_project_current_timeline_path_and_saved_path(self, project_current_timeline_path, project_saved_path):
		super().update_project_current_timeline_path_and_saved_path(project_current_timeline_path, project_saved_path)

		# we will use this to know the project has updated
		if (project_saved_path is not None):
			self.select_from_timeline_files_button.show()
			self.select_from_project_files_button.show()
		else:
			self.select_from_timeline_files_button.hide()
			self.select_from_project_files_button.hide()

	def on_select_from_timeline_files_clicked(self, widget):
		if self.project_saved_path is None:
			return
		
		dialog = Gtk.FileChooserDialog(
			title=self.data["label"],
			parent=None,
			action=Gtk.FileChooserAction.OPEN,
			buttons=(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
		)
		Gtk.Window.set_keep_above(dialog, True)

		dialog.set_current_folder(os.path.join(self.project_current_timeline_path, "files"))

		file_filter = Gtk.FileFilter()
		file_filter.set_name(self.file_types_label)
		for pattern in self.file_types:
			file_filter.add_pattern(pattern)
		dialog.add_filter(file_filter)

		response = dialog.run()
		if response == Gtk.ResponseType.OK:
			filename = dialog.get_filename()
			self.select_button.set_label(os.path.basename(filename) + " (" + _("Click to change") + ")")
			self.selected_filename = filename
			self.on_file_selected()
		dialog.destroy()

	def on_select_from_project_files_clicked(self, widget):
		if self.project_saved_path is None:
			return
		
		dialog = Gtk.FileChooserDialog(
			title=self.data["label"],
			parent=None,
			action=Gtk.FileChooserAction.OPEN,
			buttons=(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
		)
		Gtk.Window.set_keep_above(dialog, True)

		# path to project files
		dialog.set_current_folder(os.path.join(os.path.dirname(self.project_saved_path), "project_files"))

		file_filter = Gtk.FileFilter()
		file_filter.set_name(self.file_types_label)
		for pattern in self.file_types:
			file_filter.add_pattern(pattern)
		dialog.add_filter(file_filter)

		response = dialog.run()
		if response == Gtk.ResponseType.OK:
			filename = dialog.get_filename()
			self.select_button.set_label(os.path.basename(filename) + " (" + _("Click to change") + ")")
			self.selected_filename = filename
			self.on_file_selected()
		dialog.destroy()

	def after_ui_built(self, workflow_elements_all):
		super().after_ui_built(workflow_elements_all)
	
		if (self.project_saved_path is not None):
			self.select_from_timeline_files_button.show()
			self.select_from_project_files_button.show()
		else:
			self.select_from_timeline_files_button.hide()
			self.select_from_project_files_button.hide()
	
class AIHubExposeAudio(AIHubExposeFileBase):
	def __init__(self, id, data, workflow_context, workflow_id, workflow, project_current_timeline_path, project_saved_path, apinfo):
		super().__init__(id, data, workflow_context, workflow_id, workflow, project_current_timeline_path, project_saved_path, apinfo,
			select_button_label=_("Select an audio file"),
			file_types=["*.mp3", "*.wav", "*.flac", "*.ogg"],
			file_types_label=_("Audio files")
		)

class AIHubExposeVideo(AIHubExposeFileBase):
	def __init__(self, id, data, workflow_context, workflow_id, workflow, project_current_timeline_path, project_saved_path, apinfo):
		super().__init__(id, data, workflow_context, workflow_id, workflow, project_current_timeline_path, project_saved_path, apinfo,
			select_button_label=_("Select a video file"),
			file_types=["*.mp4", "*.mov", "*.avi", "*.mkv"],
			file_types_label=_("Video files")
		)

class AIHubExposeLatent(AIHubExposeFileBase):
	def __init__(self, id, data, workflow_context, workflow_id, workflow, project_current_timeline_path, project_saved_path, apinfo):
		super().__init__(id, data, workflow_context, workflow_id, workflow, project_current_timeline_path, project_saved_path, apinfo,
			select_button_label=_("Select a latent file"),
			file_types=["*.safetensors"],
			file_types_label=_("Latent files")
		)

class AIHubExposeInteger(AIHubExposeBase):
	def __init__(self, id, data, workflow_context, workflow_id, workflow, project_current_timeline_path, project_saved_path, apinfo):
		super().__init__(id, data, workflow_context, workflow_id, workflow, project_current_timeline_path, project_saved_path, apinfo)

		self.label: Gtk.Label = None
		self.error_label: AIHubLabel = None
		self.widget: Gtk.SpinButton = None
		self.box: Gtk.Box = None

		# make a numeric entry that only allows for integer values
		expected_step = data["step"] if "step" in data else 1

		initial_value_int = 0
		try:
			initial_value_int = int(self.initial_value)
		except:
			initial_value_int = 0
			print("Warning: initial value for integer expose is not a valid integer: {}".format(self.initial_value))
		
		self.adjustment = Gtk.Adjustment(
			value=initial_value_int if self.initial_value is not None else (data["min"] if "min" in data else 0),
			lower=data["min"] if "min" in data and (not "min_expose_id" in data or not data["min_expose_id"]) else -0x8000000000000000,
			upper=data["max"] if "max" in data and (not "max_expose_id" in data or not data["max_expose_id"]) else 0xffffffffffffffff,
			step_increment=expected_step,
		)
		self.widget = Gtk.SpinButton(adjustment=self.adjustment, climb_rate=1, digits=0, numeric=True)
		self.widget.set_input_purpose(Gtk.InputPurpose.NUMBER)

		# add on change event
		self.widget.connect("value-changed", self.on_change_value)

		if (self.initial_value is not None):
			self.widget.set_value(initial_value_int)

		# add a tooltip with the description if any available
		if "tooltip" in data and data["tooltip"] is not None and data["tooltip"] != "":
			self.widget.set_tooltip_text(data["tooltip"])

		# make a box to have the label and the field
		# make the label
		self.label = Gtk.Label(self.data["label"], xalign=0)
		self.error_label = AIHubLabel("", b"color: red;")
		self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
		self.box.pack_start(self.label, False, False, 0)
		self.box.pack_start(self.error_label.get_widget(), False, False, 0)
		self.box.pack_start(self.widget, True, True, 0)

		# ensure to add spacing from the top some margin top
		self.box.set_margin_top(10)

	def get_value(self, half_size=False, half_size_coords=False):
		return self.widget.get_value_as_int()

	def get_widget(self):
		return self.box

	def on_change_value(self, widget):
		for sibling in self.siblings:
			sibling.check_validity(sibling.get_value())

		self.on_change(widget.get_value_as_int())

	def check_validity(self, value):
		min = self.data["min"] if "min" in self.data else None
		max = self.data["max"] if "max" in self.data else None
		if not isinstance(value, int):
			self.error_label.show()
			self.error_label.set_text(_("Value must be an integer"))
		elif not (min is None or value >= min) or not (max is None or value <= max):
			self.error_label.show()
			smallest_possible_integer = -0x8000000000000000
			largest_possible_integer = 0x7FFFFFFFFFFFFFFF
			self.error_label.set_text(_("Value must be between {} and {}").format(min or smallest_possible_integer, max or largest_possible_integer))
		elif not self.check_for_unique_valid(value):
			self.error_label.show()
			self.error_label.set_text(_("Value must be unique among siblings"))
		elif not self.check_for_sorted_valid(value):
			self.error_label.show()
			self.error_label.set_text(_("Value must be greater than the previous sibling"))
		else:
			self.error_label.hide()

	def after_ui_built(self, workflow_elements_all):
		self.check_validity(self.get_value())

		if "max_expose_id" in self.data:
			max_expose_id_id = self.data["max_expose_id"]
			for expose in workflow_elements_all:
				if expose.get_id() == max_expose_id_id and isinstance(expose, (AIHubExposeInteger, AIHubExposeFloat, AIHubExposeProjectConfigInteger, AIHubExposeProjectConfigFloat)):
					expose.add_change_event_listener(self.on_max_widget_change)
					self.on_max_widget_change(expose.get_value())
					self.max_widget = expose

		if "min_expose_id" in self.data:
			min_expose_id_id = self.data["min_expose_id"]
			for expose in workflow_elements_all:
				if expose.get_id() == min_expose_id_id and isinstance(expose, (AIHubExposeInteger, AIHubExposeFloat, AIHubExposeProjectConfigInteger, AIHubExposeProjectConfigFloat)):
					expose.add_change_event_listener(self.on_min_widget_change)
					self.on_min_widget_change(expose.get_value())
					self.min_widget = expose

	def check_for_unique_valid(self, value):
		if not self.data.get("unique", False):
			return True
		
		for sibling in self.siblings:
			if sibling.get_value() == value and sibling != self:
				return False
			
		return True
	
	def check_for_sorted_valid(self, value):
		if not self.data.get("sorted", False):
			return True
		
		previous_sibling = None
		for sibling in self.siblings:
			if sibling == self:
				break
			previous_sibling = sibling
		
		if previous_sibling is not None:
			previous_value = previous_sibling.get_value()
			if value <= previous_value:
				return False
		
		return True

	def can_run(self):
		min = self.data["min"] if "min" in self.data else None
		max = self.data["max"] if "max" in self.data else None
		value = self.get_value()
		return (min is None or value >= min) and (max is None or value <= max) and self.check_for_unique_valid(value) and self.check_for_sorted_valid(value)
	
	def on_max_widget_change(self, value):
		value_with_offset = int(value) + self.data.get("max_expose_offset", 0)
		adjustment: Gtk.Adjustment = self.widget.get_adjustment()
		adjustment.set_upper(value_with_offset)
		self.data["max"] = value_with_offset
		# if current value is greater than new max, set it to new max
		if self.widget.get_value_as_int() > value_with_offset:
			self.widget.set_value(value_with_offset)
		self.check_validity(self.get_value())

	def on_min_widget_change(self, value):
		value_with_offset = int(value) + self.data.get("min_expose_offset", 0)
		adjustment: Gtk.Adjustment = self.widget.get_adjustment()
		adjustment.set_lower(value_with_offset)
		self.data["min"] = value_with_offset
		# if current value is less than new min, set it to new min
		if self.widget.get_value_as_int() < value_with_offset:
			self.widget.set_value(value_with_offset)
		self.check_validity(self.get_value())

	def destroy(self):
		if hasattr(self, 'max_widget'):
			self.max_widget.remove_change_event_listener(self.on_max_widget_change)
		if hasattr(self, 'min_widget'):
			self.min_widget.remove_change_event_listener(self.on_min_widget_change)

class AIHubExposeSeed(AIHubExposeBase):
	def __init__(self, id, data, workflow_context, workflow_id, workflow, project_current_timeline_path, project_saved_path, apinfo):
		super().__init__(id, data, workflow_context, workflow_id, workflow, project_current_timeline_path, project_saved_path, apinfo)

		self.label: Gtk.Label = None
		self.error_label: AIHubLabel = None
		self.widget_value_fixed: Gtk.SpinButton = None
		self.widget_value: Gtk.ComboBoxText = None
		self.box: Gtk.Box = None

		initial_value_fixed = 0
		if (
			isinstance(self.initial_value, dict) and
			"value_fixed" in self.initial_value and
			self.initial_value["value_fixed"] is not None and
			isinstance(self.initial_value["value_fixed"], int)
		):
			initial_value_fixed = self.initial_value["value_fixed"]

		# make a numeric entry that only allows for integer values
		adjustment = Gtk.Adjustment(
			value=initial_value_fixed,
			lower=data["min"] if "min" in data else 0,
			upper=data["max"] if "max" in data else 0xffffffffffffffff,
			step_increment=1,
		)
		self.widget_value_fixed = Gtk.SpinButton(adjustment=adjustment, climb_rate=1, digits=0, numeric=True)
		self.widget_value_fixed.set_input_purpose(Gtk.InputPurpose.NUMBER)

		# add on change event
		self.widget_value_fixed.connect("value-changed", self.on_change_value)

		# add a tooltip with the description if any available
		if "tooltip" in data and data["tooltip"] is not None and data["tooltip"] != "":
			self.widget_value_fixed.set_tooltip_text(data["tooltip"])
		else:
			self.widget_value_fixed.set_tooltip_text(_("Set a fixed seed value to get the same results every time"))

		self.widget_value = Gtk.ComboBoxText()
		self.widget_value.set_entry_text_column(0)
		self.widget_value.append("random", "Random")
		self.widget_value.append("fixed", "Fixed")

		# set the initial value if available
		if (
			isinstance(self.initial_value, dict) and
			"value" in self.initial_value and
			self.initial_value["value"] is not None and
			self.initial_value["value"] in ["random", "fixed"]
		):
			self.widget_value.set_active_id(self.initial_value["value"])
		else:
			self.widget_value.set_active_id("random")

		# make a box to have the label and the field
		# make the label
		self.label = Gtk.Label(self.data["label"], xalign=0)
		self.error_label = AIHubLabel("", b"color: red;")
		self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
		self.box.pack_start(self.label, False, False, 0)
		self.box.pack_start(self.error_label.get_widget(), False, False, 0)

		box_for_inputs = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
		box_for_inputs.pack_start(self.widget_value, True, True, 0)
		box_for_inputs.pack_start(self.widget_value_fixed, True, True, 0)
		self.box.pack_start(box_for_inputs, True, True, 0)

		# ensure to add spacing from the top some margin top
		self.box.set_margin_top(10)

		self.ensure_value_fixed_visibility_state()

		self.widget_value_fixed.connect("changed", self.on_change_value)
		self.widget_value.connect("changed", self.on_change_value)

	def get_value_internal(self):
		return {
			"value_fixed": self.widget_value_fixed.get_value_as_int(),
			"value": self.widget_value.get_active_id()
		}
	
	def get_value(self, half_size=False, half_size_coords=False):
		current_selection = self.widget_value.get_active_id()
		if current_selection == "random":
			random_value = random.randint(0, (2**32) - 1)
			return random_value
		else:
			return self.widget_value_fixed.get_value_as_int()

	def get_widget(self):
		return self.box
	
	def ensure_value_fixed_visibility_state(self):
		if self.widget_value.get_active_id() == "fixed":
			self.widget_value_fixed.show()
		else:
			self.widget_value_fixed.hide()

	def on_change_value(self, widget):
		self.ensure_value_fixed_visibility_state()
		self.on_change(self.get_value_internal())

	def can_run(self):
		value = self.get_value_internal()
		return isinstance(value, dict) and "value" in value and value["value"] in ["random", "fixed"] and isinstance(value["value_fixed"], int)
	
	def check_validity(self, value):
		if not self.can_run():
			self.error_label.show()
			self.error_label.set_text(_("Value must be a valid object with 'value' as 'random' or 'fixed' and 'value_fixed' as an integer"))
		else:
			self.error_label.hide()

	def after_ui_built(self, workflow_elements_all):
		self.ensure_value_fixed_visibility_state()
		self.check_validity(self.get_value_internal())

class AIHubExposeFloat(AIHubExposeBase):
	def __init__(self, id, data, workflow_context, workflow_id, workflow, project_current_timeline_path, project_saved_path, apinfo):
		super().__init__(id, data, workflow_context, workflow_id, workflow, project_current_timeline_path, project_saved_path, apinfo)

		self.label: Gtk.Label = None
		self.widget: Gtk.SpinButton = None
		self.box: Gtk.Box = None

		# make a numeric entry that only allows for float values
		expected_step = data["step"] if "step" in data else 0.1
		initial_value_float = 0.0
		try:
			initial_value_float = float(self.initial_value)
		except:
			initial_value_float = 0.0
			print("Warning: initial value for float expose is not a valid float: {}".format(self.initial_value))

		adjustment = Gtk.Adjustment(
			value=initial_value_float if self.initial_value is not None else (data["min"] if "min" in data else 0.0),
			lower=data["min"] if "min" in data and (not "min_expose_id" in data or not data["min_expose_id"]) else -1e10,
			upper=data["max"] if "max" in data and (not "max_expose_id" in data or not data["max_expose_id"]) else 1e10,
			step_increment=expected_step,
		)
		# check how many decimal places are in expected_step
		step_digits = 0
		if isinstance(expected_step, float):
			step_str = str(expected_step)
			if '.' in step_str:
				step_digits = len(step_str.split('.')[1])
		self.widget = Gtk.SpinButton(adjustment=adjustment, climb_rate=1, digits=step_digits, numeric=True)
		self.widget.set_input_purpose(Gtk.InputPurpose.NUMBER)

		if (self.initial_value is not None):
			self.widget.set_value(initial_value_float)

		# add a tooltip with the description if any available
		if "tooltip" in data and data["tooltip"] is not None and data["tooltip"] != "":
			self.widget.set_tooltip_text(data["tooltip"])

		# add on change event
		self.widget.connect("value-changed", self.on_change_value)

		# make a box to have the label and the field
		# make the label, set a max width for 400 and make it wrap if it goes over
		self.label = Gtk.Label(self.data["label"], xalign=0)
		self.label.set_size_request(400, -1)
		self.label.set_line_wrap(True)
		self.error_label = AIHubLabel("", b"color: red;")
		self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
		self.box.pack_start(self.label, False, False, 0)
		self.box.pack_start(self.error_label.get_widget(), False, False, 0)
		self.box.pack_start(self.widget, True, True, 0)

		# ensure to add spacing from the top some margin top
		self.box.set_margin_top(10)

	def check_for_unique_valid(self, value):
		if not self.data.get("unique", False):
			return True
		
		for sibling in self.siblings:
			if sibling.get_value() == value and sibling != self:
				return False
			
		return True
	
	def check_for_sorted_valid(self, value):
		if not self.data.get("sorted", False):
			return True
		
		previous_sibling = None
		for sibling in self.siblings:
			if sibling == self:
				break
			previous_sibling = sibling
		
		if previous_sibling is not None:
			previous_value = previous_sibling.get_value()
			if value <= previous_value:
				return False
		
		return True

	def get_value(self, half_size=False, half_size_coords=False):
		return self.widget.get_value()

	def get_widget(self):
		return self.box
	
	def on_change_value(self, widget):
		for sibling in self.siblings:
			sibling.check_validity(sibling.get_value())
		self.on_change(widget.get_value())

	def check_validity(self, value):
		min = self.data["min"] if "min" in self.data else None
		max = self.data["max"] if "max" in self.data else None
		if not isinstance(value, float):
			self.error_label.show()
			self.error_label.set_text("Value must be a float")
		elif not (min is None or value >= min) or not (max is None or value <= max):
			self.error_label.show()
			self.error_label.set_text(_("Value must be between {} and {}").format(min or '-Infinity', max or 'Infinity'))
		elif not self.check_for_unique_valid(value):
			self.error_label.show()
			self.error_label.set_text(_("Value must be unique among siblings"))
		elif not self.check_for_sorted_valid(value):
			self.error_label.show()
			self.error_label.set_text(_("Value must be greater than the previous sibling"))
		else:
			self.error_label.hide()

	def after_ui_built(self, workflow_elements_all):
		self.check_validity(self.get_value())

		if "max_expose_id" in self.data:
			max_expose_id_id = self.data["max_expose_id"]
			for expose in workflow_elements_all:
				if expose.get_id() == max_expose_id_id and isinstance(expose, (AIHubExposeInteger, AIHubExposeFloat, AIHubExposeProjectConfigInteger, AIHubExposeProjectConfigFloat)):
					expose.add_change_event_listener(self.on_max_widget_change)
					self.on_max_widget_change(expose.get_value())
					self.max_widget = expose

		if "min_expose_id" in self.data:
			min_expose_id_id = self.data["min_expose_id"]
			for expose in workflow_elements_all:
				if expose.get_id() == min_expose_id_id and isinstance(expose, (AIHubExposeInteger, AIHubExposeFloat, AIHubExposeProjectConfigInteger, AIHubExposeProjectConfigFloat)):
					expose.add_change_event_listener(self.on_min_widget_change)
					self.on_min_widget_change(expose.get_value())
					self.min_widget = expose

	def can_run(self):
		min = self.data["min"] if "min" in self.data else None
		max = self.data["max"] if "max" in self.data else None
		value = self.get_value()
		return (min is None or value >= min) and (max is None or value <= max) and self.check_for_unique_valid(value) and self.check_for_sorted_valid(value)

	def after_ui_built(self, workflow_elements_all):
		self.check_validity(self.get_value())

	def on_max_widget_change(self, value):
		value_with_offset = float(value) + self.data.get("max_expose_offset", 0.0)
		adjustment: Gtk.Adjustment = self.widget.get_adjustment()
		adjustment.set_upper(value_with_offset)
		self.data["max"] = value_with_offset
		# if current value is greater than new max, set it to new max
		if self.widget.get_value() > value_with_offset:
			self.widget.set_value(value_with_offset)
		self.check_validity(self.get_value())

	def on_min_widget_change(self, value):
		value_with_offset = float(value) + self.data.get("min_expose_offset", 0.0)
		adjustment: Gtk.Adjustment = self.widget.get_adjustment()
		adjustment.set_lower(value_with_offset)
		self.data["min"] = value_with_offset
		# if current value is less than new min, set it to new min
		if self.widget.get_value() < value_with_offset:
			self.widget.set_value(value_with_offset)
		self.check_validity(self.get_value())

	def destroy(self):
		if hasattr(self, 'max_widget'):
			self.max_widget.remove_change_event_listener(self.on_max_widget_change)
		if hasattr(self, 'min_widget'):
			self.min_widget.remove_change_event_listener(self.on_min_widget_change)

class AIHubExposeCfg(AIHubExposeFloat):
	def on_model_changed(self, model):
		if self.data.get("unaffected_by_model_cfg", False):
			return
		default_cfg = model.get("default_cfg", None)
		if default_cfg is not None and isinstance(default_cfg, (int, float)):
			self.widget.set_value(float(default_cfg))
			self.on_change(self.get_value())
			self.check_validity(self.get_value())

class AIHubExposeSteps(AIHubExposeInteger):
	def on_model_changed(self, model):
		if self.data.get("unaffected_by_model_steps", False):
			return
		default_steps = model.get("default_steps", None)
		if default_steps is not None and isinstance(default_steps, int):
			self.widget.set_value(int(default_steps))
			self.on_change(self.get_value())
			self.check_validity(self.get_value())

class AIHubExposeBoolean(AIHubExposeBase):
	def __init__(self, id, data, workflow_context, workflow_id, workflow, project_current_timeline_path, project_saved_path, apinfo):
		super().__init__(id, data, workflow_context, workflow_id, workflow, project_current_timeline_path, project_saved_path, apinfo)

		self.label: Gtk.Label = None
		self.error_label: AIHubLabel = None
		self.widget: Gtk.CheckButton = None
		self.box: Gtk.Box = None

		self.widget = Gtk.CheckButton()
		self.widget.set_active(self.initial_value)

		# make a box to have the label and the field
		# make the label
		self.label = Gtk.Label(self.data["label"], xalign=0)
		self.label.set_size_request(400, -1)
		self.label.set_line_wrap(True)
		self.error_label = AIHubLabel("", b"color: red;")
		self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
		self.box.pack_start(self.label, False, False, 0)
		self.box.pack_start(self.error_label.get_widget(), False, False, 0)
		self.box.pack_start(self.widget, True, True, 0)

		# add on change event
		self.widget.connect("toggled", self.on_change_value)

		# ensure to add spacing from the top some margin top
		self.box.set_margin_top(10)

	def get_value(self, half_size=False, half_size_coords=False):
		return self.widget.get_active()

	def get_widget(self):
		return self.box
	
	def on_change_value(self, widget):
		self.on_change(widget.get_active())

		for sibling in self.siblings:
			if "one_true" in self.data and self.data["one_true"] and self.get_value():
				sibling.widget.set_active(False)
			if self.data["one_false"] and not self.get_value():
				sibling.widget.set_active(True)

	def check_validity(self, value):
		if not isinstance(value, bool):
			self.error_label.show()
			self.error_label.set_text(_("Value must be a boolean"))
		else:
			self.error_label.hide()

	def after_ui_built(self, workflow_elements_all):
		self.check_validity(self.get_value())

	def can_run(self):
		return not isinstance(self.get_value(), bool)
	
	def add_interacting_sibling(self, sibling):
		self.siblings.append(sibling)

class AIHubExposeString(AIHubExposeBase):
	def get_special_priority(self):
		if self.data.get("multiline", False):
			return 50
		return 0
	
	def __init__(self, id, data, workflow_context, workflow_id, workflow, project_current_timeline_path, project_saved_path, apinfo):
		super().__init__(id, data, workflow_context, workflow_id, workflow, project_current_timeline_path, project_saved_path, apinfo)

		self.label: Gtk.Label = None
		self.error_label: AIHubLabel = None
		self.widget: Gtk.Entry | Gtk.TextView = None
		self.box: Gtk.Box = None
		self.is_multiline: bool = False

		self.is_multiline = "multiline" in data and data["multiline"]
		self.widget = Gtk.TextView() if self.is_multiline else Gtk.Entry()

		if self.is_multiline:
			buffer = self.widget.get_buffer()
			buffer.set_text(self.initial_value or "")

			# prevent the text view from growing horizontally
			self.widget.set_size_request(400, 100)
			self.widget.set_wrap_mode(Gtk.WrapMode.WORD)

			# add onchange event
			buffer.connect("changed", self.on_change_value)
		else:
			self.widget.set_text(self.initial_value or "")
			# add on change event
			self.widget.connect("changed", self.on_change_value)

		# add a tooltip with the description if any available
		if "tooltip" in data and data["tooltip"] is not None and data["tooltip"] != "":
			self.widget.set_tooltip_text(data["tooltip"])

		# make a box to have the label and the field
		# make the label
		self.label = Gtk.Label(self.data["label"], xalign=0)
		self.label.set_size_request(400, -1)
		self.label.set_line_wrap(True)
		self.error_label = AIHubLabel("", b"color: red;")
		self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
		self.box.pack_start(self.label, False, False, 0)
		self.box.pack_start(self.error_label.get_widget(), False, False, 0)
		self.box.pack_start(self.widget, True, True, 0)

		# ensure to add spacing from the top some margin top
		self.box.set_margin_top(10)

	def get_value(self, half_size=False, half_size_coords=False):
		if (self.is_multiline):
			return self.widget.get_buffer().get_text(
				self.widget.get_buffer().get_start_iter(),
				self.widget.get_buffer().get_end_iter(),
				True,
			)
		return self.widget.get_text()
	
	def check_for_unique_valid(self, value):
		if not self.data.get("unique", False):
			return True
		
		for sibling in self.siblings:
			if sibling.get_value() == value and sibling != self:
				return False
			
		return True

	def get_widget(self):
		return self.box

	def on_change_value(self, widget):
		for sibling in self.siblings:
			sibling.check_validity(sibling.get_value())

		self.on_change(self.get_value())

	def after_ui_built(self, workflow_elements_all):
		self.check_validity(self.get_value())

		if "maxlen_expose_id" in self.data:
			maxlen_expose_id_id = self.data["maxlen_expose_id"]
			for expose in workflow_elements_all:
				if expose.get_id() == maxlen_expose_id_id and isinstance(expose, (AIHubExposeInteger, AIHubExposeFloat, AIHubExposeProjectConfigInteger, AIHubExposeProjectConfigFloat)):
					expose.add_change_event_listener(self.on_maxlen_widget_change)
					self.on_maxlen_widget_change(expose.get_value())
					self.maxlen_widget = expose

		if "minlen_expose_id" in self.data:
			minlen_expose_id_id = self.data["minlen_expose_id"]
			for expose in workflow_elements_all:
				if expose.get_id() == minlen_expose_id_id and isinstance(expose, (AIHubExposeInteger, AIHubExposeFloat, AIHubExposeProjectConfigInteger, AIHubExposeProjectConfigFloat)):
					expose.add_change_event_listener(self.on_minlen_widget_change)
					self.on_minlen_widget_change(expose.get_value())
					self.minlen_widget = expose

	def check_validity(self, value):
		if not isinstance(value, str):
			self.error_label.show()
			self.error_label.set_text(_("Value must be a string"))
		elif "maxlen" in self.data and len(value) > self.data["maxlen"]:
			self.error_label.show()
			self.error_label.set_text(_("Value must be at most {} characters long").format(self.data['maxlen']))
		elif "minlen" in self.data and len(value) < self.data["minlen"]:
			self.error_label.show()
			self.error_label.set_text(_("Value must be at least {} characters long").format(self.data['minlen']))
		elif not self.check_for_unique_valid(value):
			self.error_label.show()
			self.error_label.set_text(_("Value must be unique among siblings"))
		else:
			self.error_label.hide()

	def can_run(self):
		value = self.get_value()
		if "maxlen" in self.data and len(value) > self.data["maxlen"]:
			return False
		if "minlen" in self.data and len(value) < self.data["minlen"]:
			return False
		return self.check_for_unique_valid(value)
	
	def on_maxlen_widget_change(self, value):
		self.data["maxlen"] = int(value) + self.data.get("maxlen_expose_offset", 0)
		self.check_validity(self.get_value())

	def on_minlen_widget_change(self, value):
		self.data["minlen"] = int(value) + self.data.get("minlen_expose_offset", 0)
		self.check_validity(self.get_value())

	def destroy(self):
		if hasattr(self, "maxlen_widget"):
			self.maxlen_widget.remove_change_event_listener(self.on_maxlen_widget_change)
		if hasattr(self, "minlen_widget"):
			self.minlen_widget.remove_change_event_listener(self.on_minlen_widget_change)

class AIHubExposeStringSelection(AIHubExposeBase):
	def __init__(self, id, data, workflow_context, workflow_id, workflow, project_current_timeline_path, project_saved_path, apinfo):
		super().__init__(id, data, workflow_context, workflow_id, workflow, project_current_timeline_path, project_saved_path, apinfo)

		self.label: Gtk.Label = None
		self.error_label: AIHubLabel = None
		self.widget: Gtk.ComboBoxText = None
		self.box: Gtk.Box = None
		self.options: list = []
		self.labels: list = []

		self.widget = Gtk.ComboBoxText()
		self.widget.set_entry_text_column(0)

		# add the options to the combo box
		# options is actually just a string that is multiline separated, ignore empty lines
		# the label is optained from a similar field called options_label that works in the same way
		self.labels = []
		self.options = []
		for option in data["options"].splitlines():
			option = option.strip()
			if option:
				self.options.append(option)

		for label in data["options_label"].splitlines():
			label = label.strip()
			if label:
				self.labels.append(label)

		for i in range(len(self.options)):
			self.widget.append(self.options[i], self.labels[i])

		# set the initial value if available
		if self.initial_value is not None:
			self.widget.set_active_id(self.initial_value)

		# add on change event
		self.widget.connect("changed", self.on_change_value)

		# add a tooltip with the description if any available
		if "tooltip" in data and data["tooltip"] is not None and data["tooltip"] != "":
			self.widget.set_tooltip_text(data["tooltip"])

		# make a box to have the label and the field
		# make the label
		self.label = Gtk.Label(self.data["label"], xalign=0)
		self.label.set_size_request(400, -1)
		self.label.set_line_wrap(True)
		self.error_label = AIHubLabel("", b"color: red;")
		self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
		self.box.pack_start(self.label, False, False, 0)
		self.box.pack_start(self.error_label.get_widget(), False, False, 0)
		self.box.pack_start(self.widget, True, True, 0)

	def get_value(self, half_size=False, half_size_coords=False):
		return self.widget.get_active_id()

	def get_widget(self):
		return self.box
	
	def on_change_value(self, widget):
		self.on_change(self.widget.get_active_id())

	def can_run(self):
		return self.get_value() in self.options
	
	def after_ui_built(self, workflow_elements_all):
		self.check_validity(self.get_value())

	def check_validity(self, value):
		if not isinstance(value, str):
			self.error_label.show()
			self.error_label.set_text(_("Value must be a string"))
		elif value not in self.options:
			self.error_label.show()
			self.error_label.set_text(_("Value must be one of the allowed options"))
		else:
			self.error_label.hide()

class AIHubExposeScheduler(AIHubExposeStringSelection):
	def on_model_changed(self, model):
		if self.data.get("unaffected_by_model_scheduler", False):
			return
		default_scheduler = model.get("default_scheduler", None)
		if default_scheduler is not None and isinstance(default_scheduler, str):
			self.widget.set_value(default_scheduler)
			self.on_change(self.get_value())
			self.check_validity(self.get_value())

class AIHubExposeExtendableScheduler(AIHubExposeStringSelection):
	def on_model_changed(self, model):
		if self.data.get("unaffected_by_model_scheduler", False):
			return
		default_scheduler = model.get("default_scheduler", None)
		if default_scheduler is not None and isinstance(default_scheduler, str):
			self.widget.set_value(default_scheduler)
			self.on_change(self.get_value())
			self.check_validity(self.get_value())

class AIHubExposeSampler(AIHubExposeStringSelection):
	def on_model_changed(self, model):
		if self.data.get("unaffected_by_model_sampler", False):
			return
		default_sampler = model.get("default_sampler", None)
		if default_sampler is not None and isinstance(default_sampler, str):
			self.widget.set_value(default_sampler)
			self.on_change(self.get_value())
			self.check_validity(self.get_value())

class AIHubExposeProjectFileBase(AIHubExposeBase):
	def __init__(self, id, data, workflow_context, workflow_id, workflow, project_current_timeline_path, project_saved_path, apinfo):
		super().__init__(id, data, workflow_context, workflow_id, workflow, project_current_timeline_path, project_saved_path, apinfo)

		self.uploaded_file_path: str = None

	def upload_binary(self, ws, relegator=None, half_size=False):
		self.uploaded_file_path = None

		file_name = self.data.get("file_name", None)
		batch_index = self.data.get("batch_index", "")
		file_to_upload = os.path.join(self.project_current_timeline_path, "files", file_name)
		if batch_index.strip() != "":
			batch_index_as_int = 0
			try:
				batch_index_as_int = self.parse_index(batch_index)
			except:
				batch_index_as_int = 0
			# however there may be gaps in the numbering, due to potentially deleted files
			# also negative indexes should count from the end so we need to get all files that match the pattern
			matching_files = []
			prefix = os.path.splitext(file_name)[0] + "_"
			extension = os.path.splitext(file_name)[1]
			for f in os.listdir(os.path.join(self.project_current_timeline_path, "files")):
				if f.startswith(prefix) and f.endswith(extension):
					# check if the middle part is an integer
					middle_part = f[len(prefix):-len(extension)]
					try:
						matching_files.append({"file": f, "index": int(middle_part)})
					except:
						# maybe not an integer, skip
						continue
			# sort the matching files by index
			matching_files = sorted(matching_files, key=lambda x: x["index"])
			if batch_index_as_int < 0:
				batch_index_as_int = len(matching_files) + batch_index_as_int
			if batch_index_as_int < 0 or batch_index_as_int >= len(matching_files):
				if self.data.get("optional", False):
					return True  # skip upload if optional
				return _("The specified batch index {} is out of range for files matching {}").format(batch_index, file_name)
			file_to_upload = os.path.join(self.project_current_timeline_path, "files", matching_files[batch_index_as_int]["file"])

		if not os.path.isfile(file_to_upload):
			if self.data.get("optional", False):
				return True  # skip upload if optional
			return _("File to upload does not exist: {}").format(file_to_upload)

		# now we need to make a calculation for a hash of the file to upload
		hash_md5 = hashlib.md5()
		# make a new binary data to upload
		file_data = b""
		with open(file_to_upload, "rb") as f:
			data = f.read()  # read whole thing
			file_data = data
			hash_md5.update(data)
				
		upload_file_hash = hash_md5.hexdigest()

		# now we can upload the file, using that hash as filename, if the file does not exist
		binary_header = {
			"type": "FILE_UPLOAD",
			"filename": upload_file_hash,
			"workflow_id": self.workflow_id,
			"if_not_exists": True
		}

		relegator.reset()

		ws.send(json.dumps(binary_header))

		if not relegator.wait(10):
			return _("Error uploading file {}: Timeout waiting for server response").format(file_to_upload)
		
		response_data = relegator.last_response

		if (response_data["type"] == "ERROR"):
			return _("Error uploading file {}: {}").format(file_to_upload, response_data.get('message', _('Unknown error')))
		elif (response_data["type"] == "UPLOAD_ACK"):
			try:
				relegator.reset()
				ws.send_bytes(file_data)
				
				# wait for the upload ack
				if not relegator.wait(10):
					return _("Error uploading file {}: Timeout waiting for server response after sending data").format(file_to_upload)

				response_data = relegator.last_response

				if (response_data["type"] == "ERROR"):
					return _("Error uploading file {}: {}").format(file_to_upload, response_data.get('message', _('Unknown error')))
				elif (response_data["type"] == "FILE_UPLOAD_SUCCESS"):
					filename = response_data.get("file", None)
					self.uploaded_file_path = filename

					if self.uploaded_file_path is None:
						return _("Error uploading file {}: Server did not return uploaded file path").format(file_to_upload)

					# upload successful
					return True
				# unexpected response
				return _("Error uploading file {}: Unexpected server response").format(file_to_upload)
			except Exception as e:
				return _("Error uploading file {}: {}").format(file_to_upload, str(e))
		elif (response_data["type"] == "FILE_UPLOAD_SKIP"):
			# file already exists on server
			filename = response_data.get("file", None)
			self.uploaded_file_path = filename
			if self.uploaded_file_path is None:
				return _("Error uploading file {}: Server did not return uploaded file path").format(file_to_upload)
			return True

		return _("Error uploading file {}: Unexpected server response").format(file_to_upload)
	
	def get_value(self, half_size=False, half_size_coords=False):
		return {
			"local_file": self.uploaded_file_path,
		}
	
class AIHubExposeProjectFilesBase(AIHubExposeBase):
	def __init__(self, id, data, workflow_context, workflow_id, workflow, project_current_timeline_path, project_saved_path, apinfo):
		super().__init__(id, data, workflow_context, workflow_id, workflow, project_current_timeline_path, project_saved_path, apinfo)

		self.uploaded_file_paths: list[str] = []

	def upload_binary(self, ws, relegator=None, half_size=False):
		file_name = self.data.get("file_name", None)
		indexes = self.data.get("indexes", "")
		files_to_upload = []

		self.uploaded_file_paths = []

		files_path = os.path.join(self.project_current_timeline_path, "files")

		matching_files = []
		prefix = os.path.splitext(file_name)[0] + "_"
		extension = os.path.splitext(file_name)[1]
		for f in os.listdir(files_path):
			if f.startswith(prefix) and f.endswith(extension):
				# check if the middle part is an integer
				middle_part = f[len(prefix):-len(extension)]
				try:
					matching_files.append({"file": f, "index": int(middle_part)})
				except:
					# maybe not an integer, skip
					continue

		# sort the matching files by index
		matching_files = sorted(matching_files, key=lambda x: x["index"])

		if indexes.strip() == "":
			# upload all matching files
			for match in matching_files:
				files_to_upload.append(os.path.join(self.project_current_timeline_path, "files", match["file"]))
		elif "," in indexes:
			# multiple indexes specified
			for index_part in indexes.split(","):
				index_part = index_part.strip()
				if index_part != "":
					batch_index_as_int = 0
					try:
						batch_index_as_int = self.parse_index(index_part)
					except:
						batch_index_as_int = 0
					if batch_index_as_int < 0:
						batch_index_as_int = len(matching_files) + batch_index_as_int
					if batch_index_as_int < 0 or batch_index_as_int >= len(matching_files):
						return _("The specified batch index {} is out of range for files matching {}").format(batch_index_as_int, file_name)
					files_to_upload.append(os.path.join(self.project_current_timeline_path, "files", matching_files[batch_index_as_int]["file"]))
		elif ":" in indexes:
			# range of indexes specified
			parts = indexes.split(":")
			if len(parts) != 2:
				return _("The specified indexes {} are invalid for files matching {}").format(indexes, file_name)
			start_index = 0
			end_index = 0
			try:
				start_index = self.parse_index(parts[0].strip())
			except:
				start_index = 0
			try:
				end_index = self.parse_index(parts[1].strip())
			except:
				end_index = -1
			if start_index < 0:
				start_index = len(matching_files) + start_index
			if end_index < 0:
				end_index = len(matching_files) + end_index
			if start_index < 0 or end_index >= len(matching_files) or start_index > end_index:
				return _("The specified batch index range {} is out of range for files matching {}").format(indexes, file_name)
			for i in range(start_index, end_index + 1):
				files_to_upload.append(os.path.join(self.project_current_timeline_path, "files", matching_files[i]["file"]))

		for file_to_upload in files_to_upload:
			# now we need to make a calculation for a hash of the file to upload
			hash_md5 = hashlib.md5()
			# make a new binary data to upload
			file_data = b""
			with open(file_to_upload, "rb") as f:
				data = f.read()  # read whole thing
				file_data = data
				hash_md5.update(data)
					
			upload_file_hash = hash_md5.hexdigest()

			# now we can upload the file, using that hash as filename, if the file does not exist
			binary_header = {
				"type": "FILE_UPLOAD",
				"filename": upload_file_hash,
				"workflow_id": self.workflow_id,
				"if_not_exists": True
			}

			relegator.reset()

			ws.send(json.dumps(binary_header))

			if not relegator.wait(10):
				return _("Error uploading file {}: Timeout waiting for server response").format(file_to_upload)
			
			response_data = relegator.last_response

			if (response_data["type"] == "ERROR"):
				return _("Error uploading file {}: {}").format(file_to_upload, response_data.get('message', _('Unknown error')))
			elif (response_data["type"] == "UPLOAD_ACK"):
				try:
					relegator.reset()
					ws.send_bytes(file_data)
					
					# wait for the upload ack
					if not relegator.wait(10):
						return _("Error uploading file {}: Timeout waiting for server response after sending data").format(file_to_upload)

					response_data = relegator.last_response

					if (response_data["type"] == "ERROR"):
						return _("Error uploading file {}: {}").format(file_to_upload, response_data.get('message', _('Unknown error')))
					elif (response_data["type"] == "FILE_UPLOAD_SUCCESS"):
						filename = response_data.get("file", None)
						uploaded_file_path = filename

						if uploaded_file_path is None:
							return _("Error uploading file {}: Server did not return uploaded file path").format(file_to_upload)
						
						self.uploaded_file_paths.append(uploaded_file_path)

						# upload successful
						continue
					# unexpected response
					return _("Error uploading file {}: Unexpected server response").format(file_to_upload)
				except Exception as e:
					return _("Error uploading file {}: {}").format(file_to_upload, str(e))
			elif (response_data["type"] == "FILE_UPLOAD_SKIP"):
				# file already exists on server
				filename = response_data.get("file", None)
				if filename is None:
					return _("Error uploading file {}: Server did not return uploaded file path").format(file_to_upload)
				self.uploaded_file_paths.append(filename)
				continue

			return _("Error uploading file {}: Unexpected server response").format(file_to_upload)
	
	def get_value(self, half_size=False, half_size_coords=False):
		return {
			# server expects a comma separated list of file paths
			"local_files": self.uploaded_file_paths,
		}

class AIHubExposeProjectConfigBase(AIHubExposeBase):
	def get_value(self, half_size=False, half_size_coords=False):
		value = self.read_project_config_json(self.data["field"])
		if value is None:
			value = self.data["default"]
		return value

class AIHubExposeProjectConfigString(AIHubExposeProjectConfigBase):
	def get_value(self, half_size=False, half_size_coords=False):
		parent_value = super().get_value()
		if not isinstance(parent_value, str):
			return self.data["default"]
		return parent_value
	
class AIHubExposeProjectConfigInteger(AIHubExposeProjectConfigBase):
	def get_value(self, half_size=False, half_size_coords=False):
		parent_value = super().get_value()
		if not isinstance(parent_value, int):
			return self.data["default"]
		return parent_value
	
class AIHubExposeProjectConfigBoolean(AIHubExposeProjectConfigBase):
	def get_value(self, half_size=False, half_size_coords=False):
		parent_value = super().get_value()
		if not isinstance(parent_value, bool):
			return self.data["default"]
		return parent_value
	
class AIHubExposeProjectConfigFloat(AIHubExposeProjectConfigBase):
	def get_value(self, half_size=False, half_size_coords=False):
		parent_value = super().get_value()
		if not isinstance(parent_value, float):
			return self.data["default"]
		return parent_value
	
class AIHubExposeLora(AIHubExposeBase):
	def __init__(self, id, data, workflow_context, workflow_id, workflow, project_current_timeline_path, project_saved_path, apinfo):
		super().__init__(id, data, workflow_context, workflow_id, workflow, project_current_timeline_path, project_saved_path, apinfo)

		self.box: Gtk.Box = None
		self.image: Gtk.Image = None
		self.slider: Gtk.Scale = None
		self.name_label: AIHubLabel = None
		self.description_label: AIHubLabel = None
		self.strength: float = 1.0
		self.enabled: bool = False
		self.delete_button: Gtk.Button = None

		self.no_image = False

		lora_data = data["lora"]

		if "default_strength" in lora_data and lora_data["default_strength"] is not None and isinstance(lora_data["default_strength"], (int, float)):
			self.strength = lora_data["default_strength"]
		else:
			self.strength = 1.0

		self.enabled = False
		if self.initial_value is not None and isinstance(self.initial_value, dict):
			self.strength = self.initial_value["strength"]
			self.enabled = self.initial_value["enabled"]

		# we want the UI to be a card where an image exist to the left side and the name and description to the right side
		# as well as a widget under it of a slider 0 to 1 with step 0.05 to determine the strength of the lora
		self.box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
		self.box.set_size_request(400, 150)

		# time to add the image to the box in the left side
		self.image = Gtk.Image()
		self.image.set_size_request(150, 150)
		self.box.pack_start(self.image, False, False, 0)
		self.load_image()

		# now to the right side we want a vertical box with the name, description and slider
		right_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
		self.box.pack_start(right_box, True, True, 0)
		self.name_label = AIHubLabel(lora_data["name"] or lora_data["id"], b"font-weight: bold;")
		self.name_label.set_size_request(-1, -1)
		right_box.pack_start(self.name_label.get_widget(), False, False, 0)
		self.description_label = AIHubLabel(lora_data["description"] or "", b"font-style: italic;")
		self.description_label.set_size_request(-1, -1)
		right_box.pack_start(self.description_label.get_widget(), False, False, 0)
		self.slider = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 1, 0.05)
		self.slider.set_value(self.strength)
		right_box.pack_start(self.slider, True, True, 0)

		self.slider.connect("value-changed", self.on_change_value)
		self.slider.set_tooltip_text(_("Set the strength of the LORA model to apply. 0 means no effect, 1 means full effect"))

		self.delete_button = Gtk.Button(label=_("Remove"))
		self.delete_button.set_tooltip_text(_("Remove this LORA from the list"))
		self.delete_button.connect("clicked", self.on_delete)
		right_box.pack_start(self.delete_button, False, False, 0)

	def load_image(self):
		lora_id = self.data.get("lora", {}).get("id", None)
		image_url = f"{"https" if self.apinfo["usehttps"] else "http"}://{self.apinfo["host"]}:{self.apinfo["port"]}/loras/{lora_id}.png"
		context = None
		if self.apinfo["usehttps"]:
			context = ssl._create_unverified_context()
		try:
			response = None
			if context is None:
				response = urllib.request.urlopen(image_url)
			else:
				response = urllib.request.urlopen(image_url, context=context)
			input_stream = Gio.MemoryInputStream.new_from_data(response.read(), None)
			pixbuf = Pixbuf.new_from_stream(input_stream, None)

			width = 150
			# maintain aspect ratio
			height = int(pixbuf.get_height() * (width / pixbuf.get_width()))
			scaled_pixbuf = pixbuf.scale_simple(width, height, InterpType.BILINEAR)

			self.image.set_from_pixbuf(scaled_pixbuf)
			#ensure the image is centered since the aspect ratio might make it smaller
			self.image.set_halign(Gtk.Align.CENTER)
			self.image.set_valign(Gtk.Align.CENTER)

		except Exception as e:
			# if we fail to load the image, we just ignore it
			self.image.clear()
			self.no_image = True

	def get_widget(self):
		return self.box
	
	def on_change_value(self, widget):
		self.strength = widget.get_value()
		self.on_change(self.get_value())

	def get_value(self, half_size=False, half_size_coords=False):
		return {
			"strength": self.slider.get_value(),
			"enabled": self.enabled,
		}
	
	def set_enabled(self, enabled: bool):
		self.enabled = enabled
		if self.enabled:
			self.box.show_all()
			if self.no_image:
				self.image.hide()
		else:
			self.box.hide()
		self.on_change(self.get_value())

	def on_delete(self, widget):
		self.set_enabled(False)

	def is_enabled(self):
		return self.enabled
	
	def set_strength(self, strength: float):
		self.strength = strength
		self.slider.set_value(strength)
		self.on_change(self.get_value())

	def get_file(self):
		lora_data = self.data["lora"]
		return lora_data.get("file", None)
	
	def get_strength(self):
		return self.strength
	
	def get_use_loader_model_only(self):
		lora_data = self.data["lora"]
		return lora_data.get("use_loader_model_only", False)

	def after_ui_built(self, workflow_elements_all):
		if self.no_image:
			self.image.hide()
		else:
			self.image.show()
		
		if not self.enabled:
			self.box.hide()
		else:
			self.box.show()

	def get_list_row(self):
		row = Gtk.ListBoxRow()

		hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
		row.add(hbox)
		if not self.no_image:
			# make a copy of the image
			new_image = Gtk.Image()
			new_image.set_from_pixbuf(self.image.get_pixbuf())
			new_image.set_halign(Gtk.Align.CENTER)
			new_image.set_valign(Gtk.Align.CENTER)
			hbox.pack_start(new_image, False, False, 0)

		right_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
		hbox.pack_start(right_box, True, True, 0)
		right_box.pack_start(self.name_label.get_as_gtk_label(), True, True, 0)
		right_box.pack_start(self.description_label.get_as_gtk_label(), True, True, 0)

		return row

class AIHubExposeModel(AIHubExposeBase):
	def get_special_priority(self):
		return 1000
	def __init__(self, id, data, workflow_context, workflow_id, workflow, project_current_timeline_path, project_saved_path, apinfo):
		super().__init__(id, data, workflow_context, workflow_id, workflow, project_current_timeline_path, project_saved_path, apinfo)

		self.label: Gtk.Label = None
		self.error_label: AIHubLabel = None
		self.widget: Gtk.ComboBoxText = None
		self.box: Gtk.Box = None
		self.options: list = []
		self.labels: list = []
		self.options_file: list = []
		self.model: dict = None
		self.model_image: Gtk.Image = None
		self.model_description: AIHubLabel = None

		self.loras_add_button: Gtk.Button = None
		self.loras_box: Gtk.Box = None
		self.loras_label: Gtk.Label = None

		self.lorasobjects = {}

		self.widget = Gtk.ComboBoxText()
		self.widget.set_entry_text_column(0)

		# add the options to the combo box
		# options is actually just a string that is multiline separated, ignore empty lines
		# the label is optained from a similar field called options_label that works in the same way
		self.labels = []
		self.options = []
		self.options_file = []

		for model in data["filtered_models"]:
			self.options.append(model["id"])
			self.labels.append(model["name"])
			self.options_file.append(model.get("file", None))
				

		for i in range(len(self.options)):
			self.widget.append(self.options[i], self.labels[i])

		# set the initial value if available
		if self.initial_value is not None and self.initial_value["_id"] in self.options and not self.data.get("disable_model_selection", False):
			self.widget.set_active_id(self.initial_value["_id"])
			self.model = next((m for m in data["filtered_models"] if m["id"] == self.initial_value["_id"]), None)
		elif "model" in data and data["model"] is not None and data["model"] in self.options_file:
			# get the id of the model with that file
			model_id = None
			for m in data["filtered_models"]:
				if m.get("file", None) == data["model"]:
					model_id = m["id"]
					break
			self.widget.set_active_id(model_id)
			self.model = next((m for m in data["filtered_models"] if m["id"] == model_id), None)
		else:
			self.widget.set_active(0)
			self.model = next((m for m in data["filtered_models"] if m["id"] == self.widget.get_active_id()), None)

		if self.data.get("disable_model_selection", False):
			self.widget.set_sensitive(False)

		# add on change event
		self.widget.connect("changed", self.on_change_value)

		# add a tooltip with the description if any available
		if "tooltip" in data and data["tooltip"] is not None and data["tooltip"] != "":
			self.widget.set_tooltip_text(data["tooltip"])

		# make a box to have the label and the field
		# make the label
		self.label = Gtk.Label(self.data["label"], xalign=0)
		self.label.set_size_request(400, -1)
		self.label.set_line_wrap(True)
		self.error_label = AIHubLabel("", b"color: red;")
		self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
		self.box.pack_start(self.label, False, False, 0)
		self.box.pack_start(self.error_label.get_widget(), False, False, 0)
		self.box.pack_start(self.widget, True, True, 0)

		# add an image to the right of the combo box to show the model preview
		if not self.data.get("disable_model_selection", False):
			self.model_image = Gtk.Image()
			self.model_description = AIHubLabel("", b"font-style: italic;")
			self.box.pack_start(self.model_image, False, False, 10)
			self.box.pack_start(self.model_description.get_widget(), False, False, 10)

		if not self.data.get("disable_loras_selection", False):
			self.loras_label = Gtk.Label(_("LORAs"), xalign=0)
			self.loras_label.set_size_request(400, -1)
			self.loras_label.set_line_wrap(True)
			self.box.pack_start(self.loras_label, False, False, 10)

			# show the loras label for this model, lets make a box to show them
			self.loras_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
			self.box.pack_start(self.loras_box, True, True, 0)

			css = b"""
			.loras-border {
				border: 2px solid #ccc;
				border-radius: 8px;
				padding: 12px;
			}
			"""
			style_provider = Gtk.CssProvider()
			style_provider.load_from_data(css)

			self.loras_box.get_style_context().add_provider(style_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
			self.loras_box.get_style_context().add_class("loras-border")

			self.loras_add_button = Gtk.Button(label=_("Add LORA"))
			self.loras_add_button.set_tooltip_text(_("Add a LORA to this model"))

			self.loras_add_button.connect("clicked", self.on_add_lora_clicked)
			self.box.pack_start(self.loras_add_button, False, False, 10)

		if self.model is not None:
			if not self.data.get("disable_model_selection", False):
				self.load_model_image_and_description()
			if not self.data.get("disable_loras_selection", False):
				self.recalculate_loras()

	def load_model_image_and_description(self):
		model_id = self.widget.get_active_id()

		image_url = f"{"https" if self.apinfo["usehttps"] else "http"}://{self.apinfo["host"]}:{self.apinfo["port"]}/models/{model_id}.png"
		context = None
		if self.apinfo["usehttps"]:
			context = ssl._create_unverified_context()
		try:
			response = None
			if context is None:
				response = urllib.request.urlopen(image_url)
			else:
				response = urllib.request.urlopen(image_url, context=context)
			input_stream = Gio.MemoryInputStream.new_from_data(response.read(), None)
			pixbuf = Pixbuf.new_from_stream(input_stream, None)

			width = 400
			height = int(pixbuf.get_height() * (width / pixbuf.get_width()))
			scaled_pixbuf = pixbuf.scale_simple(width, height, InterpType.BILINEAR)

			self.model_image.set_from_pixbuf(scaled_pixbuf)
		except Exception as e:
			# if we fail to load the image, we just ignore it
			self.model_image.clear()

		# also the description if available, we just set it
		if "description" in self.model and self.model["description"] is not None and self.model["description"] != "":
			self.model_description.set_text(self.model['description'])
		else:
			self.model_description.set_text(_("No description provided"))

	def recalculate_loras(self):
		new_loras = []
		for lora in self.data["filtered_loras"]:
			if (
				("limit_to_model" not in lora or lora["limit_to_model"] is None or lora["limit_to_model"] == self.model["id"]) and
				("limit_to_group" not in lora or lora["limit_to_group"] is None or "group" not in self.model or self.model["group"] == lora["limit_to_group"])
			):
				new_loras.append(lora)

		new_loras_ids = [l["id"] for l in new_loras]

		# check our lorasobjects and remove the ones that are not in new_loras
		for lora_id in list(self.lorasobjects.keys()):
			if lora_id not in new_loras_ids:
				# remove the widget from the box
				self.loras_box.remove(self.lorasobjects[lora_id].get_widget())
				del self.lorasobjects[lora_id]

		# add the new loras that are not in lorasobjects
		splitted_loras = []
		splitted_strengths = []

		if "loras" in self.data and self.data["loras"] is not None and self.data["loras"] != "":
			splitted_loras = [lora.strip() for lora in self.data["loras"].split(",")]

		if "loras_strengths" in self.data and self.data["loras_strengths"] is not None and self.data["loras_strengths"] != "":
			splitted_strengths = [s.strip() for s in self.data["loras_strengths"].split(",")]

		for lora in new_loras:
			if lora["id"] not in self.lorasobjects:
				newinstance = AIHubExposeLora([self.id, "_loras", lora["id"]], {
					"lora": lora,
				}, self.workflow_context, self.workflow_id, self.workflow, self.project_current_timeline_path, self.project_saved_path, self.apinfo)
				self.lorasobjects[lora["id"]] = newinstance
				newinstance.hook_on_change_fn_hijack(self.on_lora_changed)
				
				# this means no value was loaded also for the lora either
				# so we don't need to override the strength or enabled state
				# since the lora will load from the same data
				if self.initial_value is None:
					# check if the lora is in splitted_loras and if so, set the strength and enabled state
					if lora["id"] in splitted_loras:
						index = splitted_loras.index(lora["id"])
						if index < len(splitted_strengths):
							try:
								strength = float(splitted_strengths[index])
								self.lorasobjects[lora["id"]].set_strength(strength)
								self.lorasobjects[lora["id"]].set_enabled(True)
							except:
								pass

				# add the widget to the box
				self.loras_box.pack_start(self.lorasobjects[lora["id"]].get_widget(), False, False, 0)

	def on_listbox_button_press(self, widget, event):
		# ensure only to happen on left click
		if event.type != Gdk.EventType.BUTTON_PRESS or event.button != 1:
			return False
		
		y = int(event.y)
		row = widget.get_row_at_y(y)
		if row:
			if row.get_style_context().has_class("selected"):
				row.get_style_context().remove_class("selected")
			else:
				row.get_style_context().add_class("selected")
			return True
		return False

	def on_add_lora_clicked(self, widget):
		# we are going to create a dialog to select the lora to add from all our list of loras
		dialog = Gtk.Dialog(title="Select LORA to add", transient_for=None, flags=0)
		# make the dialog be on top of everything
		dialog.set_modal(True)
		dialog.set_keep_above(True)
		# add a cancel and add button
		dialog.add_button("Add", Gtk.ResponseType.OK)
		dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)

		# make the dialog close when the user presses escape or clicks outside
		dialog.set_deletable(True)

		dialog.set_default_size(600, 600)
		#make it so it has a scrollbar and a list of loras to select from
		content_area = dialog.get_content_area()
		scrolled_window = Gtk.ScrolledWindow()
		scrolled_window.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
		content_area.pack_start(scrolled_window, True, True, 0)
		listbox = Gtk.ListBox()
		scrolled_window.add(listbox)
		listbox.set_selection_mode(Gtk.SelectionMode.NONE)

		listbox.connect("button-press-event", self.on_listbox_button_press)

		for lora_id, lora in self.lorasobjects.items():
			if not lora.is_enabled():
				row = lora.get_list_row()

				# set an id to the row so we can identify it later
				row.set_name(lora_id)

				# make the row change color when selected
				# remember to add the color to the Gtk.Label as well
				css = b"""
				row.selected {
					background-color: #007acc;
					border: 2px solid #005f99;
					border-radius: 8px;
					padding: 12px;
					color: white;
				}
				row:not(.selected) {
					background-color: transparent;
					border: 2px solid #ccc;
					border-radius: 8px;
					padding: 12px;
					color: white;
				}
				"""
				style_provider = Gtk.CssProvider()
				style_provider.load_from_data(css)

				row.get_style_context().add_provider(style_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
				listbox.add(row)

		dialog.show_all()
		# run the dialog and get the response
		response = dialog.run()

		if response == Gtk.ResponseType.OK:
			dialog.destroy()
			# we need to get all rows and filter the selected ones based on the class
			selected_rows = [row for row in listbox.get_children() if row.get_style_context().has_class("selected")]
			for row in selected_rows:
				lora_id = row.get_name()
				if lora_id is not None:
					self.lorasobjects[lora_id].set_enabled(True)
		else:
			# cancel pressed destroy the dialog
			dialog.destroy()
		
	def get_value(self, half_size=False, half_size_coords=False):
		if self.model is None:
			return None
		
		_loras = {}
		enabled_loras_list = []
		for lora_id, lora_value in self.lorasobjects.items():
			if lora_value.is_enabled() and lora_value.get_strength() > 0:
				_loras[lora_id] = lora_value.get_value()
				enabled_loras_list.append(lora_value)

		return {
			"_id": self.model.get("id", None),
			"_loras": _loras,

			"model": self.model.get("file", "") or "",
			"is_diffusion_model": self.model.get("is_diffusion_model", False) or False,
			"diffusion_model_weight_dtype": self.model.get("diffusion_model_weight_dtype", 0) or 0,
			"optional_vae": self.model.get("vae_file", "") or "",
			"optional_clip": self.model.get("clip_file", "") or "",
			"optional_clip_type": self.model.get("clip_type", "") or "",

			"loras": ",".join([l.get_file() for l in enabled_loras_list]),
			"loras_strengths": ",".join([str(l.get_strength()) for l in enabled_loras_list]),
			"loras_use_loader_model_only": ",".join([("t" if l.get_use_loader_model_only() else "f") for l in enabled_loras_list])
		}

	def get_widget(self):
		return self.box
	
	def on_lora_changed(self, value):
		self.on_change(self.get_value())
	
	def on_change_value(self, widget):
		self.model = next((m for m in self.data["filtered_models"] if m["id"] == self.widget.get_active_id()), None)
		if self.model is None:
			self.error_label.show()
			self.error_label.set_text(_("Selected model is not valid"))
			return
		else:
			self.error_label.hide()
		
		# the model is ours, we need to update the image
		self.load_model_image_and_description()
		# also recalculate the loras
		if not self.data.get("disable_loras_selection", False):
			self.recalculate_loras()
		self.on_change(self.get_value())

	def can_run(self):
		if self.data.get("disable_model_selection", False):
			if self.data["model"] is None or not self.data["model"]:
				return False
			if not self.data["model"] in self.options_file:
				return False
		return self.model is not None
	
	def after_ui_built(self, workflow_elements_all):
		for lora in self.lorasobjects.values():
			lora.after_ui_built(workflow_elements_all)

		if self.data.get("disable_model_selection", False):
			if self.data["model"] is None or not self.data["model"]:
				self.error_label.show()
				self.error_label.set_text(_("The model selection is disabled but no model is set"))
				return
			if not self.data["model"] in self.options_file:
				self.error_label.show()
				self.error_label.set_text(_("The model selection is disabled but the set model {} is not available").format(self.data['model']))
				return

		if self.model is None:
			self.error_label.show()
			self.error_label.set_text(_("There are no models available for this workflow"))
		else:
			self.error_label.hide()

BATCH_EXPOSE_METADATA_TYPE_TO_EXPOSE_CLASS = {
	"INT": AIHubExposeInteger,
	"FLOAT": AIHubExposeFloat,
	"STRING": AIHubExposeString,
	"BOOLEAN": AIHubExposeBoolean,
}

class AIHubExposeImageBatch(AIHubExposeBase):
	def get_special_priority(self):
		return 100
	
	def create_widget_for_expose(self, expose):
		usual_widget = expose.get_widget()

		# now we need to extend this widget with a delete button on the right
		delete_button = Gtk.Button(label="Delete")
		delete_button.connect("clicked", self.on_delete_expose, expose)

		move_up_button = Gtk.Button(label="↑")
		move_up_button.connect("clicked", self.on_move_expose, -1, expose)
		
		move_down_button = Gtk.Button(label="↓")
		move_down_button.connect("clicked", self.on_move_expose, +1, expose)

		box_for_move_buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
		box_for_move_buttons.pack_start(move_up_button, True, True, 0)
		box_for_move_buttons.pack_start(move_down_button, True, True, 0)

		# add the delete button to the right of the usual widget
		vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
		vbox.pack_start(usual_widget, True, True, 0)
		vbox.pack_start(box_for_move_buttons, False, False, 0)


		metadata_fields_text = self.data.get("metadata_fields", "")
		if metadata_fields_text is None or metadata_fields_text.strip() == "":
			return vbox
		metadata_fields_splitted = [field.strip() for field in metadata_fields_text.split("\n")]
		metadata_fields_label_text = self.data.get("metadata_fields_label", "")
		metadata_fields_label_splitted = [label.strip() for label in metadata_fields_label_text.split("\n")]
		
		if metadata_fields_label_text is not None and metadata_fields_label_text.strip() != "":
			expose_metadata_list = []
			for field in range(0, len(metadata_fields_splitted)):
				field_label = metadata_fields_label_splitted[field] if field < len(metadata_fields_label_splitted) else ""
				field_structure_splitted = [f.strip() for f in metadata_fields_splitted[field].split(" ") if f.strip() != ""]

				type_of_field = field_structure_splitted[1] if len(field_structure_splitted) >= 2 else "INT"
				global BATCH_EXPOSE_METADATA_TYPE_TO_EXPOSE_CLASS
				ExposeClass = BATCH_EXPOSE_METADATA_TYPE_TO_EXPOSE_CLASS.get(type_of_field, "AIHubExposeString")
				data = {
					"label": field_label,
					"metadata_id": field_structure_splitted[0],
					"tooltip": None,
				}
				for extra_param in field_structure_splitted[2:]:
					if extra_param.startswith("MAX:"):
						default_value = extra_param[len("MAX:"):].strip()
						try:
							value = int(default_value) if type_of_field == "INT" else float(default_value)
							if "max" in data:
								data["max"] = data["max"] + value
							else:
								data["max"] = value
						except ValueError:
							data["max_expose_id"] = default_value
					elif extra_param.startswith("MAXOFFSET:"):
						default_value = extra_param[len("MAXOFFSET:"):].strip()
						try:
							value = int(default_value) if type_of_field == "INT" else float(default_value)
							data["max_expose_offset"] = value
							if "max" in data:
								data["max"] = data["max"] + value
							else:
								data["max"] = value
						except ValueError:
							pass
					elif extra_param.startswith("MIN:"):
						default_value = extra_param[len("MIN:"):].strip()
						try:
							value = int(default_value) if type_of_field == "INT" else float(default_value)
							if "min" in data:
								data["min"] = data["min"] + value
							else:
								data["min"] = value
						except ValueError:
							data["min_expose_id"] = default_value
					elif extra_param.startswith("MINOFFSET:"):
						default_value = extra_param[len("MINOFFSET:"):].strip()
						try:
							value = int(default_value) if type_of_field == "INT" else float(default_value)
							data["min_expose_offset"] = value
							if "min" in data:
								data["min"] = data["min"] + value
							else:
								data["min"] = value
						except ValueError:
							pass
					elif extra_param.startswith("MAXLEN:"):
						default_value = extra_param[len("MAXLEN:"):].strip()
						try:
							if "maxlen" in data:
								data["maxlen"] = data["maxlen"] + int(default_value)
							else:
								data["maxlen"] = int(default_value)
						except ValueError:
							data["maxlen_expose_id"] = default_value
					elif extra_param.startswith("MAXLENOFFSET:"):
						default_value = extra_param[len("MAXLENOFFSET:"):].strip()
						try:
							data["maxlen_expose_offset"] = int(default_value)
							if "maxlen" in data:
								data["maxlen"] = data["maxlen"] + int(default_value)
							else:
								data["maxlen"] = int(default_value)
						except ValueError:
							pass
					elif extra_param.startswith("MINLEN:"):
						default_value = extra_param[len("MINLEN:"):].strip()
						try:
							if "minlen" in data:
								data["minlen"] = data["minlen"] + int(default_value)
							else:
								data["minlen"] = int(default_value)
						except ValueError:
							data["minlen_expose_id"] = default_value
					elif extra_param.startswith("MINLENOFFSET:"):
						default_value = extra_param[len("MINLENOFFSET:"):].strip()
						try:
							data["minlen_expose_offset"] = int(default_value)
							if "minlen" in data:
								data["minlen"] = data["minlen"] + int(default_value)
							else:
								data["minlen"] = int(default_value)
						except ValueError:
							pass
					elif extra_param.startswith("DEFAULT:"):
						default_value = extra_param[len("DEFAULT:"):].strip()
						if type_of_field == "INT":
							try:
								data["value"] = int(default_value)
							except ValueError:
								pass
						elif type_of_field == "FLOAT":
							try:
								data["value"] = float(default_value)
							except ValueError:
								pass
						elif type_of_field == "BOOLEAN":
							if default_value.lower() in ["true", "1", "t", "yes", "y"]:
								data["value"] = True
							else:
								data["value"] = False
						else:
							data["value"] = default_value
					elif extra_param == "MULTILINE":
						data["multiline"] = True
					elif extra_param == "ONE_TRUE":
						data["one_true"] = True
					elif extra_param == "ONE_FALSE":
						data["one_false"] = True
					elif extra_param == "UNIQUE":
						data["unique"] = True
					elif extra_param == "SORTED":
						data["sorted"] = True
			
				metadata_expose = ExposeClass([self.id, len(self.list_of_expose_metadata_subexposes), "metadata", field_structure_splitted[0]], data, self.workflow_context, self.workflow_id, self.workflow, self.project_current_timeline_path, self.project_saved_path, self.apinfo)
				metadata_expose.set_exposes_in_workflow(self.all_exposes_in_workflow)
				expose_metadata_list.append(metadata_expose)
				metadata_widget = metadata_expose.get_widget()
				vbox.pack_start(metadata_widget, False, False, 0)
			self.list_of_expose_metadata_subexposes.append(expose_metadata_list)

			for field in range(0, len(metadata_fields_splitted)):
				siblings_list = []
				for expose_metadata_list in self.list_of_expose_metadata_subexposes:
					subexpose_in_question = expose_metadata_list[field]
					siblings_list.append(subexpose_in_question)
				for expose_metadata_list in self.list_of_expose_metadata_subexposes:
					subexpose_in_question = expose_metadata_list[field]
					subexpose_in_question.set_siblings(siblings_list)

		vbox.pack_start(delete_button, False, False, 0)
		return vbox

	def __init__(self, id, data, workflow_context, workflow_id, workflow, project_current_timeline_path, project_saved_path, apinfo):
		super().__init__(id, data, workflow_context, workflow_id, workflow, project_current_timeline_path, project_saved_path, apinfo)

		self.label: Gtk.Label = None
		self.box: Gtk.Box = None
		self.innerbox: Gtk.Box = None

		self.list_of_exposes = []
		self.list_of_expose_widgets = []
		self.list_of_expose_metadata_subexposes = []

		self.label = Gtk.Label(self.data["label"], xalign=0)
		self.label.set_size_request(400, -1)
		self.label.set_line_wrap(True)
		self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
		self.box.pack_start(self.label, False, False, 0)

		self.innerbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
		self.box.pack_start(self.innerbox, True, True, 0)

		# ensure to add spacing from the top some margin top
		self.box.set_margin_top(10)

		if self.initial_value is not None and isinstance(self.initial_value, list):
			# we do not need to read this value because the children will do it
			# straight from the file
			for i in range(0, len(self.initial_value)):
				expose = AIHubExposeImage([self.id, i, "value"], {
					"label": _("Image {}").format(i+1),
					"type": "upload",
					"tooltip": self.data["tooltip"] if "tooltip" in self.data else None,
				}, self.workflow_context, self.workflow_id, self.workflow, self.project_current_timeline_path, self.project_saved_path, self.apinfo)

				self.list_of_exposes.append(expose)
				new_widget = self.create_widget_for_expose(expose)
				self.list_of_expose_widgets.append(new_widget)

				self.innerbox.pack_start(new_widget, True, True, 0)

		# add a spacer
		spacer = Gtk.Label("", xalign=0)
		spacer.set_size_request(400, 10)
		self.box.pack_start(spacer, False, False, 0)

		add_button = Gtk.Button(label=_("Add Image"))
		add_button.connect("clicked", self.on_add_expose)
		self.box.pack_start(add_button, False, False, 0)

	def set_exposes_in_workflow(self, all_exposes):
		super().set_exposes_in_workflow(all_exposes)

		for expose in self.list_of_exposes:
			expose.set_exposes_in_workflow(all_exposes)

		for expose_list in self.list_of_expose_metadata_subexposes:
			for expose in expose_list:
				expose.set_exposes_in_workflow(all_exposes)

	def on_delete_expose(self, widget, expose):
		widget_of_expose = None
		for i in range(0, len(self.list_of_exposes)):
			if self.list_of_exposes[i] == expose:
				widget_of_expose = self.list_of_expose_widgets[i]
				self.list_of_expose_widgets.pop(i)
				expose.destroy()
				subexposes = self.list_of_expose_metadata_subexposes.pop(i)
				for subexpose in subexposes:
					subexpose.destroy()
				break

		if not widget_of_expose:
			return
	
		self.list_of_exposes.remove(expose)
		# remove the widget from the Gtk box
		self.innerbox.remove(widget_of_expose)
		# we clear it up, we call onchange later anyway
		self.on_change([])

		metadata_fields_text = self.data.get("metadata_fields", "")
		if metadata_fields_text is None or metadata_fields_text.strip() == "":
			pass
		else:
			metadata_fields_splitted = [field.strip() for field in metadata_fields_text.split("\n")]
			for field in range(0, len(metadata_fields_splitted)):
				siblings_list = []
				for expose_metadata_list in self.list_of_expose_metadata_subexposes:
					subexpose_in_question = expose_metadata_list[field]
					siblings_list.append(subexpose_in_question)
				for expose_metadata_list in self.list_of_expose_metadata_subexposes:
					subexpose_in_question = expose_metadata_list[field]
					subexpose_in_question.set_siblings(siblings_list)

		for i in range(0, len(self.list_of_exposes)):
			expose = self.list_of_exposes[i]
			expose.change_id([self.id, i, "value"])
			expose.change_label(_("Image {}").format(i+1))
			# specific to image expose
			expose.on_change(expose.get_value_base())

			metadata_fields_elements = self.list_of_expose_metadata_subexposes[i]
			for element in metadata_fields_elements:
				current_id = element.get_id()
				element.change_id([self.id, i, "metadata", current_id[-1]])
				element.on_change(element.get_value())
 
	def on_add_expose(self, widget):
		new_expose = AIHubExposeImage([self.id, len(self.list_of_exposes), "value"], {
			"label": _("Image {}").format(len(self.list_of_exposes)+1),
			"type": "upload",
			"tooltip": self.data["tooltip"] if "tooltip" in self.data else None,
		}, self.workflow_context, self.workflow_id, self.workflow, self.project_current_timeline_path, self.project_saved_path, self.apinfo)
		new_expose.set_exposes_in_workflow(self.all_exposes_in_workflow)
		self.list_of_exposes.append(new_expose)
		new_widget = self.create_widget_for_expose(new_expose)
		self.list_of_expose_widgets.append(new_widget)
		self.innerbox.pack_start(new_widget, True, True, 0)
		new_widget.show_all()
		new_expose.current_image_changed(self.current_image, self.image_model)
		new_expose.after_ui_built(self.all_exposes_in_workflow)
		for element in self.list_of_expose_metadata_subexposes[-1]:
			element.get_widget().show_all()
			element.current_image_changed(self.current_image, self.image_model)
			element.after_ui_built(self.all_exposes_in_workflow)

	def on_move_expose(self, widget, direction, expose):
		index = self.list_of_exposes.index(expose)
		if index > 0 and direction == -1 or index < len(self.list_of_exposes)-1 and direction == +1:
			# swap in the list
			self.list_of_exposes[index], self.list_of_exposes[index+direction] = self.list_of_exposes[index+direction], self.list_of_exposes[index]
			self.list_of_expose_widgets[index], self.list_of_expose_widgets[index+direction] = self.list_of_expose_widgets[index+direction], self.list_of_expose_widgets[index]
			self.list_of_expose_metadata_subexposes[index], self.list_of_expose_metadata_subexposes[index+direction] = self.list_of_expose_metadata_subexposes[index+direction], self.list_of_expose_metadata_subexposes[index]
			# remove all widgets and re-add them in order
			for child in self.innerbox.get_children():
				self.innerbox.remove(child)
			for widget in self.list_of_expose_widgets:
				self.innerbox.pack_start(widget, True, True, 0)
			# we clear it up, we call onchange later anyway
			self.on_change([])

			metadata_fields_text = self.data.get("metadata_fields", "")
			if metadata_fields_text is None or metadata_fields_text.strip() == "":
				pass
			else:
				metadata_fields_splitted = [field.strip() for field in metadata_fields_text.split("\n")]
				for field in range(0, len(metadata_fields_splitted)):
					siblings_list = []
					for expose_metadata_list in self.list_of_expose_metadata_subexposes:
						subexpose_in_question = expose_metadata_list[field]
						siblings_list.append(subexpose_in_question)
					for expose_metadata_list in self.list_of_expose_metadata_subexposes:
						subexpose_in_question = expose_metadata_list[field]
						subexpose_in_question.set_siblings(siblings_list)

			for i in range(0, len(self.list_of_exposes)):
				expose = self.list_of_exposes[i]
				expose.change_id([self.id, i, "value"])
				expose.change_label(_("Image {}").format(i+1))
				# specific to image expose
				expose.on_change(expose.get_value_base())

				metadata_fields_elements = self.list_of_expose_metadata_subexposes[i]
				for element in metadata_fields_elements:
					current_id = element.get_id()
					element.change_id([self.id, i, "metadata", current_id[-1]])
					element.on_change(element.get_value())

	def get_widget(self):
		return self.box

	def get_value(self, half_size=False, half_size_coords=False):
		return {
			"local_files": [expose.get_value().get("local_file", None) for expose in self.list_of_exposes],
			"metadata": json.dumps(self.get_metadata())
		}
	
	def get_metadata(self):
		metadata = []
		for expose_metadata_list in self.list_of_expose_metadata_subexposes:
			metadata_entry = {}
			for expose_element in expose_metadata_list:
				metadata_entry[expose_element.data.get("metadata_id", "")] = expose_element.get_value()
			metadata.append(metadata_entry)
		return metadata
	
	def upload_binary(self, ws, relegator=None, half_size=False):
		for expose in self.list_of_exposes:
			result = expose.upload_binary(ws, relegator, half_size=half_size)
			if result is not True:
				return result
		return True
	
	def can_run(self):
		return self.data["maxlen"] >= len(self.list_of_exposes) >= self.data["minlen"] and all([expose.can_run() for expose in self.list_of_exposes])
	
	def after_ui_built(self, workflow_elements_all):
		super().after_ui_built(workflow_elements_all)

		for expose in self.list_of_exposes:
			expose.after_ui_built(workflow_elements_all)

		for expose_list in self.list_of_expose_metadata_subexposes:
			for expose in expose_list:
				expose.after_ui_built(workflow_elements_all)

	def current_image_changed(self, image, model):
		super().current_image_changed(image, model)

		for expose in self.list_of_exposes:
			expose.current_image_changed(image, model)

		for expose_list in self.list_of_expose_metadata_subexposes:
			for expose in expose_list:
				expose.current_image_changed(image, model)

EXPOSES = {
	"AIHubExposeInteger": AIHubExposeInteger,
	"AIHubExposeFloat": AIHubExposeFloat,
	"AIHubExposeBoolean": AIHubExposeBoolean,
	"AIHubExposeString": AIHubExposeString,
	"AIHubExposeStringSelection": AIHubExposeStringSelection,
	"AIHubExposeSeed": AIHubExposeSeed,

	"AIHubExposeImage": AIHubExposeImage,
	"AIHubExposeImageInfoOnly": AIHubExposeImageInfoOnly,
	"AIHubExposeImageBatch": AIHubExposeImageBatch,

	"AIHubExposeScheduler": AIHubExposeScheduler,
	"AIHubExposeExtendableScheduler": AIHubExposeExtendableScheduler,
	"AIHubExposeSampler": AIHubExposeSampler,
	"AIHubExposeCfg": AIHubExposeCfg,
	"AIHubExposeSteps": AIHubExposeSteps,

	"AIHubExposeModel": AIHubExposeModel,
	# the simple uses the same as the standard on the display, since it only differs on how
	# it is configured in the backend
	"AIHubExposeModelSimple": AIHubExposeModel,

	"AIHubExposeAudio": AIHubExposeAudio,
	"AIHubExposeVideo": AIHubExposeVideo,
	"AIHubExposeFrame": AIHubExposeFrame,
	"AIHubExposeLatent": AIHubExposeLatent,

	"AIHubExposeProjectAudio": AIHubExposeProjectFileBase,
	"AIHubExposeProjectVideo": AIHubExposeProjectFileBase,
	"AIHubExposeProjectImage": AIHubExposeProjectFileBase,
	"AIHubExposeProjectText": AIHubExposeProjectFileBase,
	"AIHubExposeProjectImageBatch": AIHubExposeProjectFilesBase,
	"AIHubExposeProjectLatent": AIHubExposeProjectFileBase,

	"AIHubExposeProjectConfigInteger": AIHubExposeProjectConfigInteger,
	"AIHubExposeProjectConfigString": AIHubExposeProjectConfigString,
	"AIHubExposeProjectConfigBoolean": AIHubExposeProjectConfigBoolean,
	"AIHubExposeProjectConfigFloat": AIHubExposeProjectConfigFloat,
}