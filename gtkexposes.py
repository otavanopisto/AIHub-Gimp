import struct
import urllib
from label import AIHubLabel
from workspace import get_aihub_common_property_value, update_aihub_common_property_value
from gi.repository import Gimp, Gtk, GLib, Gio, Gdk # type: ignore
from gi.repository.GdkPixbuf import Pixbuf # type: ignore
from gi.repository.GdkPixbuf import InterpType # type: ignore
import hashlib
import random

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
		self.on_change_callback_hijack = False
		self.apinfo = None

		self.apinfo = apinfo
		self.data = data
		self.id = id
		self.workflow_context = workflow_context
		self.workflow_id = workflow_id
		self.initial_value = get_aihub_common_property_value(workflow_context, workflow_id, self.id, project_saved_path)
		self.workflow = workflow
		self.project_current_timeline_path = project_current_timeline_path
		self.project_saved_path = project_saved_path

		if (self.initial_value is None):
			self.set_initial_value()

	def set_initial_value(self):
		if ("value" in self.data and self.data["value"] is not None):
			self.initial_value = self.data["value"]

	def update_project_current_timeline_path_and_saved_path(self, new_timeline_path, new_saved_path):
		self.project_current_timeline_path = new_timeline_path
		self.project_saved_path = new_saved_path

	def read_project_config_json(self, key):
		if not self.projectname or self.projectname == "":
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

	def get_value(self):
		return None

	def get_widget(self):
		pass

	def upload_binary(self, ws, relegator=None):
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

		# add a timeout to stack and only do the change after 1s if the function isnt called continously
		# basically it waits 1s before calling the function but
		# if it is called a second time it will stop the first call
		if self._on_change_timeout_id is not None:
			GLib.source_remove(self._on_change_timeout_id)
			self._on_change_timeout_id = None

		self._on_change_timeout_id = GLib.timeout_add(300, self._on_change_timeout, value)

	def change_id(self, new_id):
		self.id = new_id

	def change_label(self, new_label):
		if hasattr(self, 'label') and self.label is not None:
			self.label.set_text(new_label)

	def _on_change_timeout(self, value):
		update_aihub_common_property_value(self.workflow_context, self.workflow_id, self.id, value, self.project_saved_path)
		GLib.source_remove(self._on_change_timeout_id)
		self._on_change_timeout_id = None

	def after_ui_built(self):
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

	def hook_on_change_fn_hijack(self, fn):
		self.on_change_callback = fn
		self.on_change_callback_hijack = True

	def get_ui_label_identifier(self):
		return self.data["label"]
	
	def get_special_priority(self):
		return 0

class AIHubExposeImage(AIHubExposeBase):
	def get_special_priority(self):
		return 100
	
	def __init__(self, id, data, workflow_context, workflow_id, workflow, project_current_timeline_path, project_saved_path, apinfo):
		super().__init__(id, data, workflow_context, workflow_id, workflow, project_current_timeline_path, project_saved_path, apinfo)

		self.label: Gtk.Label = None
		self.error_label: AIHubLabel = None
		self.success_label: AIHubLabel = None
		self.namelabel: Gtk.Label = None
		self.select_button: Gtk.Button = None
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

		known_tooltip = None

		if ("tooltip" in self.data and self.data["tooltip"] is not None and self.data["tooltip"] != ""):
			known_tooltip = self.data["tooltip"]

		if (not self.is_using_internal_file()):
			#first let's build a file selector
			self.select_button = Gtk.Button(label=_("Select an image from a file"), xalign=0)
			self.select_button.connect("clicked", self.on_file_chooser_clicked)

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

			if self.image_model is not None:
				self.select_combo.set_model(self.image_model)
				if self.image_model is not None and len(self.image_model) > 0:
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

	def upload_binary(self, ws, relegator=None):
		self.uploaded_file_path = None

		if (self.info_only_mode):
			return
		
		# first lets get the file that we are going to upload
		file_to_upload = None
		if (not self.is_using_internal_file()):
			if (self.selected_filename is not None and not os.path.exists(self.selected_filename)):
				file_to_upload = self.selected_filename
			elif (self.select_combo.get_active() != -1 and self.select_combo.get_model() is not None):
				tree_iter = self.select_combo.get_active_iter()
				if tree_iter is not None:
					id_of_image = self.select_combo.get_model()[tree_iter][0]
					gimp_image = Gimp.Image.get_by_id(id_of_image)
					if gimp_image is not None:
						# save the image to a temporary file
						file_to_upload = os.path.join(GLib.get_tmp_dir(), f"aihub_temp_image_{id_of_image}.png")
						# create a new gfile to save the image
						gfile = Gio.File.new_for_path(file_to_upload)
						Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, gimp_image, gfile, None)
			else:
				# nothing selected
				return
		else:
			load_type = self.data["type"]
			# an image has been selected but not a layer
			if self.selected_image is not None and self.selected_layer is None:
				# save the image to a temporary file
				id_of_image = self.selected_image.get_id()
				file_to_upload = os.path.join(GLib.get_tmp_dir(), f"aihub_temp_image_{id_of_image}.webp")
				# create a new gfile to save the image
				gfile = Gio.File.new_for_path(file_to_upload)
				Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, self.selected_image, gfile, None)
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
				Gimp.displays_flush()
				try:
					Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, new_image, gfile, None)
					Gimp.displays_flush()
				except Exception as e:
					raise e
				finally:
					new_image.delete()
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
				# create a new gfile to save the image
				gfile = Gio.File.new_for_path(file_to_upload)

				# hide the layer if not already visible
				was_visible = False
				if self.selected_layer.get_visible():
					was_visible = True
					self.selected_layer.set_visible(False)
				
				try:
					Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, self.selected_image, gfile, None)
				except Exception as e:
					raise e
				finally:
					# restore the visibility
					if was_visible:
						self.selected_layer.set_visible(True)
			else:
				# no image selected
				return
			
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

			self.uploaded_file_path = upload_file_hash
			return True

		return False

	def load_image_data_for_internal(self):
		load_type = self.data["type"]
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

	def on_file_chooser_clicked(self, widget):
		self.uploaded_file_path = None
		if (self.selected_filename is not None):
			# clear the selection
			self.selected_filename = None
			self.select_button.set_label(_("Select an image from a file"))
			self.select_combo.show()
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
		dialog.add_filter(file_filter)
		# Do not add any other filters

		response = dialog.run()
		if response == Gtk.ResponseType.OK:
			filename = dialog.get_filename()
			self.select_button.set_label(os.path.basename(filename) + " (" + _("Click to clear") + ")")
			self.selected_filename = filename
			self.on_file_selected()
		dialog.destroy()

		self.select_combo.hide()

	def get_widget(self):
		return self.box
	
	def is_using_internal_file(self):
		if (self.data["type"] == "upload"):
			return False
		return True

	def set_initial_value(self):
		# no initial value by default
		# either it loads from the saved.json file
		# or it is empty because a default cannot be set
		return
	
	def on_file_selected(self):
		self.on_change(self.get_value_base())
		self.load_image_preview()
		self.error_label.hide()
		self.success_label.hide()

	def load_image_preview(self):
		if self.is_using_internal_file():
			load_type = self.data["type"]
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
		if (self.selected_filename is not None and os.path.exists(self.selected_filename)):
			return {
				"_local_file": self.selected_filename,
				"local_file": self.uploaded_file_path,
				"pos_x": self.value_pos_x,
				"pos_y": self.value_pos_y,
				"layer_id": self.value_layer_id
			}
		elif (self.uploaded_file_path is not None):
			return {
				"local_file": self.uploaded_file_path,
				"pos_x": self.value_pos_x,
				"pos_y": self.value_pos_y,
				"layer_id": self.value_layer_id
			}
		return None
	
	def get_value(self):
		base_value = self.get_value_base()
		# remove _local_file from the value
		if base_value is not None and "_local_file" in base_value:
			del base_value["_local_file"]
		if base_value is not None and self.info_only_mode:
			del base_value["local_file"]
		return base_value
	
	def current_image_changed(self, image, model):
		super().current_image_changed(image, model)

		if not self.is_using_internal_file():
			# update the model of the select combo
			# if the model is different from the current one
			if (self.select_combo.get_model() != model and model is not None):
				self.select_combo.set_model(model)
				if model is not None and len(model) > 0:
					self.select_combo.set_active(0)
		else:
			self.load_image_data_for_internal()

		self.check_validity(self.get_value())

	def after_ui_built(self):
		self.check_validity(self.get_value())
		if (self.is_using_internal_file()):
			pass
		else:
			if self.selected_filename is not None:
				self.select_combo.hide()
			else:
				self.select_combo.show()
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
			elif (self.value_width == 0 or self.value_height == 0):
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
			elif (self.value_width == 0 or self.value_height == 0):
				self.error_label.show()
				self.success_label.hide()
				self.error_label.set_text(_("The selected image has no width or height"))
			else:
				self.error_label.hide()
				self.success_label.hide()

	def can_run(self):
		value_width_and_height_valid = self.value_width > 0 and self.value_height > 0
		if not value_width_and_height_valid:
			return False
		if (not self.is_using_internal_file()):
			return self.selected_filename is not None or self.select_combo.get_active() != -1
		else:
			return self.selected_image is not None

class AIHubExposeImageInfoOnly(AIHubExposeImage):
	def __init__(self, id, data, workflow_context, workflow_id, workflow, project_current_timeline_path, project_saved_path, apinfo):
		super().__init__(id, data, workflow_context, workflow_id, workflow, project_current_timeline_path, project_saved_path, apinfo)

		self.info_only_mode = True

class AIHubExposeImageBatch(AIHubExposeBase):
	def get_special_priority(self):
		return 100
	
	def get_widget_for_expose(self, expose):
		usual_widget = expose.get_widget()

		# now we need to extend this widget with a delete button on the right
		delete_button = Gtk.Button(label="Delete")
		delete_button.connect("clicked", self.on_delete_expose, expose)
		# add the delete button to the right of the usual widget
		vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
		vbox.pack_start(usual_widget, True, True, 0)
		vbox.pack_start(delete_button, False, False, 0)

		return vbox

	def __init__(self, id, data, workflow_context, workflow_id, workflow, project_current_timeline_path, project_saved_path, apinfo):
		super().__init__(id, data, workflow_context, workflow_id, workflow, project_current_timeline_path, project_saved_path, apinfo)

		self.label: Gtk.Label = None
		self.box: Gtk.Box = None
		self.innerbox: Gtk.Box = None

		self.list_of_exposes = []
		self.list_of_expose_widgets = []

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
				expose = AIHubExposeImage([self.id, i], {
					"label": _("Image {}").format(i+1),
					"type": "upload",
					"tooltip": self.data["tooltip"] if "tooltip" in self.data else None,
				}, self.workflow_context, self.workflow_id, self.workflow, self.projectname)

				self.list_of_exposes.append(expose)
				new_widget = self.get_widget_for_expose(expose)
				self.list_of_expose_widgets.append(new_widget)

				self.innerbox.pack_start(new_widget, True, True, 0)

	def on_delete_expose(self, expose):
		widget_of_expose = None
		for i in range(0, len(self.list_of_exposes)):
			if self.list_of_exposes[i] == expose:
				widget_of_expose = self.list_of_expose_widgets[i]
				self.list_of_expose_widgets.pop(i)
				break
	
		self.list_of_exposes.remove(expose)
		# remove the widget from the Gtk box
		self.innerbox.remove(widget_of_expose)

		for i in range(0, len(self.list_of_exposes)):
			expose = self.list_of_exposes[i]
			expose.change_id([self.id, i])
			expose.change_label(_("Image {}").format(i+1))

	def on_add_expose(self):
		new_expose = AIHubExposeImage([self.id, len(self.list_of_exposes)], {
			"label": _("Image {}").format(len(self.list_of_exposes)+1),
			"type": "upload",
			"tooltip": self.data["tooltip"] if "tooltip" in self.data else None,
		}, self.workflow_context, self.workflow_id, self.workflow, self.projectname)
		self.list_of_exposes.append(new_expose)
		self.innerbox.pack_start(new_expose.get_widget(), True, True, 0)

	def get_widget(self):
		return self.box

	def get_value(self):
		return self.value
	
	def can_run(self):
		return self.data["maxlen"] >= len(self.list_of_exposes) >= self.data["minlen"] and all([expose.can_run() for expose in self.list_of_exposes])

class AIHubExposeInteger(AIHubExposeBase):
	def __init__(self, id, data, workflow_context, workflow_id, workflow, project_current_timeline_path, project_saved_path, apinfo):
		super().__init__(id, data, workflow_context, workflow_id, workflow, project_current_timeline_path, project_saved_path, apinfo)

		self.label: Gtk.Label = None
		self.error_label: AIHubLabel = None
		self.widget: Gtk.SpinButton = None
		self.box: Gtk.Box = None

		# make a numeric entry that only allows for integer values
		expected_step = data["step"] if "step" in data else 1
		adjustment = Gtk.Adjustment(
			value=self.initial_value,
			lower=data["min"] if "min" in data else 0,
			upper=data["max"] if "max" in data else 100,
			step_increment=expected_step,
		)
		self.widget = Gtk.SpinButton(adjustment=adjustment, climb_rate=1, digits=0, numeric=True)
		self.widget.set_input_purpose(Gtk.InputPurpose.NUMBER)

		# add on change event
		self.widget.connect("value-changed", self.on_change_value)

		if (self.initial_value is not None):
			self.widget.set_value(int(self.initial_value))

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

	def get_value(self):
		return self.widget.get_value_as_int()

	def get_widget(self):
		return self.box

	def on_change_value(self, widget):
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
		else:
			self.error_label.hide()

	def after_ui_built(self):
		self.check_validity(self.get_value())

	def can_run(self):
		min = self.data["min"] if "min" in self.data else None
		max = self.data["max"] if "max" in self.data else None
		value = self.get_value()
		return (min is None or value >= min) and (max is None or value <= max)

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
	
	def get_value(self):
		current_selection = self.widget_value.get_active_id()
		if current_selection == "random":
			return random.randint(0, 0xffffffffffffffff)
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

	def after_ui_built(self):
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
		adjustment = Gtk.Adjustment(
			value=self.initial_value,
			lower=data["min"] if "min" in data else 0,
			upper=data["max"] if "max" in data else 100,
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
			self.widget.set_value(float(self.initial_value))

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

	def get_value(self):
		return self.widget.get_value()

	def get_widget(self):
		return self.box
	
	def on_change_value(self, widget):
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
		else:
			self.error_label.hide()

	def after_ui_built(self):
		self.check_validity(self.get_value())

	def can_run(self):
		min = self.data["min"] if "min" in self.data else None
		max = self.data["max"] if "max" in self.data else None
		value = self.get_value()
		return (min is None or value >= min) and (max is None or value <= max)

	def after_ui_built(self):
		self.check_validity(self.get_value())

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
		self.error_label = AIHubLabel("", "color: red;")
		self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
		self.box.pack_start(self.label, False, False, 0)
		self.box.pack_start(self.error_label.get_widget(), False, False, 0)
		self.box.pack_start(self.widget, True, True, 0)

		# add on change event
		self.widget.connect("toggled", self.on_change_value)

		# ensure to add spacing from the top some margin top
		self.box.set_margin_top(10)

	def get_value(self):
		return self.widget.get_active()

	def get_widget(self):
		return self.box
	
	def on_change_value(self, widget):
		self.on_change(widget.get_value())

	def check_validity(self, value):
		if not isinstance(value, bool):
			self.error_label.show()
			self.error_label.set_text(_("Value must be a boolean"))
		else:
			self.error_label.hide()

	def after_ui_built(self):
		self.check_validity(self.get_value())

	def can_run(self):
		return not isinstance(self.get_value(), bool)

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
			buffer.set_text(self.initial_value)

			# prevent the text view from growing horizontally
			self.widget.set_size_request(400, 100)
			self.widget.set_wrap_mode(Gtk.WrapMode.WORD)

			# add onchange event
			buffer.connect("changed", self.on_change_value)
		else:
			self.widget.set_text(self.initial_value)
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

	def get_value(self):
		if (self.is_multiline):
			return self.widget.get_buffer().get_text(
				self.widget.get_buffer().get_start_iter(),
				self.widget.get_buffer().get_end_iter(),
				True,
			)
		return self.widget.get_text()

	def get_widget(self):
		return self.box

	def on_change_value(self, widget):
		self.on_change(self.get_value())

	def after_ui_built(self):
		self.check_validity(self.get_value())

	def check_validity(self, value):
		if not isinstance(value, str):
			self.error_label.show()
			self.error_label.set_text(_("Value must be a string"))
		elif len(value) > self.data["maxlen"]:
			self.error_label.show()
			self.error_label.set_text(_("Value must be at most {} characters long").format(self.data['maxlen']))
		elif len(value) < self.data["minlen"]:
			self.error_label.show()
			self.error_label.set_text(_("Value must be at least {} characters long").format(self.data['minlen']))
		else:
			self.error_label.hide()

	def can_run(self):
		return len(self.get_value()) <= self.data["maxlen"] and len(self.get_value()) >= self.data["minlen"]

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

	def get_value(self):
		return self.widget.get_active_id()

	def get_widget(self):
		return self.box
	
	def on_change_value(self, widget):
		self.on_change(self.widget.get_active_id())

	def can_run(self):
		return self.get_value() in self.options
	
	def after_ui_built(self):
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

class AIHubExposeProjectConfigBase(AIHubExposeBase):
	def get_value(self):
		value = self.read_project_config_json(self.data["field"])
		if value is None:
			value = self.data["default"]
		return value

class AIHubExposeProjectConfigString(AIHubExposeProjectConfigBase):
	def get_value(self):
		parent_value = super().get_value()
		if not isinstance(parent_value, str):
			return self.data["default"]
		return parent_value
	
class AIHubExposeProjectConfigInteger(AIHubExposeProjectConfigBase):
	def get_value(self):
		parent_value = super().get_value()
		if not isinstance(parent_value, int):
			return self.data["default"]
		return parent_value
	
class AIHubExposeProjectConfigBoolean(AIHubExposeProjectConfigBase):
	def get_value(self):
		parent_value = super().get_value()
		if not isinstance(parent_value, bool):
			return self.data["default"]
		return parent_value
	
class AIHubExposeProjectConfigFloat(AIHubExposeProjectConfigBase):
	def get_value(self):
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
		self.name_label = AIHubLabel(lora_data["name"], b"font-weight: bold;")
		self.name_label.set_size_request(-1, -1)
		right_box.pack_start(self.name_label.get_widget(), False, False, 0)
		self.description_label = AIHubLabel(lora_data["description"], b"font-style: italic;")
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
		try:
			response = urllib.request.urlopen(image_url)
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

	def get_value(self):
		return {
			"strength": self.slider.get_value(),
			"enabled": self.enabled,
		}
	
	def set_enabled(self, enabled: bool):
		self.enabled = enabled
		if self.enabled:
			self.box.show()
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

	def after_ui_built(self):
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

		for model in data["filtered_models"]:
			self.options.append(model["id"])
			self.labels.append(model["name"])
				

		for i in range(len(self.options)):
			self.widget.append(self.options[i], self.labels[i])

		# set the initial value if available
		if self.initial_value is not None and self.initial_value["_id"] in self.options and self.data.get("disable_model_selection", False):
			self.widget.set_active_id(self.initial_value["_id"])
			self.model = next((m for m in data["filtered_models"] if m["id"] == self.initial_value["_id"]), None)
		elif "model" in data and data["model"] is not None and data["model"] in self.options:
			self.widget.set_active_id(data["model"])
			self.model = next((m for m in data["filtered_models"] if m["id"] == data["model"]), None)
		else:
			self.widget.set_active(0)
			self.model = next((m for m in data["filtered_models"] if m["id"] == self.widget.get_active_id()), None)

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
		try:
			response = urllib.request.urlopen(image_url)
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
			if lora["limit_to_model"] is None or lora["limit_to_model"] == self.model["id"]:
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
		
	def get_value(self):
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

		self.on_change(self.get_value())

	def can_run(self):
		if self.data.get("disable_model_selection", False):
			if self.data["model"] is None or not self.data["model"]:
				return False
			if not self.data["model"] in self.options:
				return False
		return self.model is not None
	
	def after_ui_built(self):
		for lora in self.lorasobjects.values():
			lora.after_ui_built()

		if self.data.get("disable_model_selection", False):
			if self.data["model"] is None or not self.data["model"]:
				self.error_label.show()
				self.error_label.set_text(_("The model selection is disabled but no model is set"))
				return
			if not self.data["model"] in self.options:
				self.error_label.show()
				self.error_label.set_text(_("The model selection is disabled but the set model {} is not available").format(self.data['model']))
				return

		if self.model is None:
			self.error_label.show()
			self.error_label.set_text(_("There are no models available for this workflow"))
		else:
			self.error_label.hide()

EXPOSES = {
	"AIHubExposeInteger": AIHubExposeInteger,
	"AIHubExposeSteps": AIHubExposeSteps,
	"AIHubExposeCfg": AIHubExposeCfg,
	"AIHubExposeProjectConfigInteger": AIHubExposeProjectConfigInteger,
	"AIHubExposeProjectConfigString": AIHubExposeProjectConfigString,
	"AIHubExposeProjectConfigBoolean": AIHubExposeProjectConfigBoolean,
	"AIHubExposeProjectConfigFloat": AIHubExposeProjectConfigFloat,
	"AIHubExposeFloat": AIHubExposeFloat,
	"AIHubExposeBoolean": AIHubExposeBoolean,
	"AIHubExposeString": AIHubExposeString,
	"AIHubExposeStringSelection": AIHubExposeStringSelection,
	"AIHubExposeImage": AIHubExposeImage,
	"AIHubExposeImageInfoOnly": AIHubExposeImageInfoOnly,
	"AIHubExposeImageBatch": AIHubExposeImageBatch,
	"AIHubExposeSeed": AIHubExposeSeed,
	"AIHubExposeSampler": AIHubExposeSampler,
	"AIHubExposeScheduler": AIHubExposeScheduler,
	"AIHubExposeExtendableScheduler": AIHubExposeExtendableScheduler,
	"AIHubExposeModel": AIHubExposeModel,
	# the simple uses the same as the standard on the display, since it only differs on how
	# it is configured in the backend
	"AIHubExposeModelSimple": AIHubExposeModel,
}