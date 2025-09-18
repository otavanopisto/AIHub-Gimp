import struct
from label import AIHubLabel
from workspace import get_aihub_common_property_value, get_project_config_filepath, update_aihub_common_property_value
from gi.repository import Gimp, Gtk, GLib, Gio # type: ignore
from gi.repository.GdkPixbuf import Pixbuf # type: ignore
from gi.repository.GdkPixbuf import InterpType # type: ignore
import hashlib

import json
import os

class AIHubExposeBase:
	data = None
	id = None
	initial_value = None
	workflow = None
	projectname = None
	workflow_context = None
	workflow_id = None
	_on_change_timeout_id = None
	current_image = None
	image_model = None
	
	def __init__(self, id, data, workflow_context, workflow_id, workflow, projectname):
		self.data = data
		self.id = id
		self.workflow_context = workflow_context
		self.workflow_id = workflow_id
		self.initial_value = get_aihub_common_property_value(workflow_context, workflow_id, self.id, projectname)
		self.workflow = workflow
		self.projectname = projectname

		if (self.initial_value is None):
			self.set_initial_value()

	def set_initial_value(self):
		if (self.data["value"] is not None):
			self.initial_value = self.data["value"]

	def read_config_json(self, key):
		if not self.projectname or self.projectname == "":
			return None
		
		config_path = get_project_config_filepath(self.projectname)

		if not os.path.exists(config_path):
			return None

		with open(config_path, "r") as f:
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
		# add a timeout to stack and only do the change after 1s if the function isnt called continously
		# basically it waits 1s before calling the function but
		# if it is called a second time it will stop the first call
		if self._on_change_timeout_id is not None:
			GLib.source_remove(self._on_change_timeout_id)
			self._on_change_timeout_id = None

		self._on_change_timeout_id = GLib.timeout_add(1000, self._on_change_timeout, value)

	def change_id(self, new_id):
		self.id = new_id

	def change_label(self, new_label):
		if hasattr(self, 'label') and self.label is not None:
			self.label.set_text(new_label)

	def _on_change_timeout(self, value):
		update_aihub_common_property_value(self.workflow_context, self.workflow_id, self.id, value, self.projectname)
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
		# this function is called when the refresh button is clicked
		pass

	def check_validity(self, value):
		# this function should be used to override and check the validity
		# of the current value, and just mark the UI as invalid if so
		# and specify why
		pass

	def can_run(self):
		# by default all exposes can run
		return True

class AIHubExposeImage(AIHubExposeBase):
	label: Gtk.Label = None
	error_label: AIHubLabel = None
	success_label: AIHubLabel = None
	namelabel: Gtk.Label = None
	select_button: Gtk.Button = None
	select_combo: Gtk.ComboBox = None
	image_preview: Gtk.Image = None
	selected_filename: str = None
	selected_image = None
	selected_layer = None
	selected_layername = None
	box: Gtk.Box
	info_only_mode: bool = False

	uploaded_file_path: str = None
	value_pos_x: int = 0
	value_pos_y: int = 0
	value_width: int = 0
	value_height: int = 0
	value_layer_id: str = ""

	def __init__(self, id, data, workflow_context, workflow_id, workflow, projectname):
		super().__init__(id, data, workflow_context, workflow_id, workflow, projectname)

		known_tooltip = None

		if ("tooltip" in self.data and self.data["tooltip"] is not None and self.data["tooltip"] != ""):
			known_tooltip = self.data["tooltip"]

		if (not self.is_using_internal_file()):
			#first let's build a file selector
			self.select_button = Gtk.Button(label="Select an image from a file", xalign=0)
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

				self.select_button.set_label(os.path.basename(self.selected_filename) + " (Click to clear)")

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
				file_to_upload = os.path.join(GLib.get_tmp_dir(), f"aihub_temp_image_{id_of_image}.png")
				# create a new gfile to save the image
				gfile = Gio.File.new_for_path(file_to_upload)
				Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, self.selected_image, gfile, None)
			# an image and a layer have been selected
			elif self.selected_image is not None and self.selected_layer is not None and load_type == "current_layer":
				# save the layer to a temporary file
				id_of_image = self.selected_image.get_id()
				file_to_upload = os.path.join(GLib.get_tmp_dir(), f"aihub_temp_layer_{id_of_image}_{self.selected_layer.get_id()}.png")
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
				try:
					Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, new_image, gfile, None)
				except Exception as e:
					raise e
				finally:
					new_image.delete()
			elif self.selected_image is not None and self.selected_layer is not None and load_type == "merged_image_without_current_layer":
				# save the layer to a temporary file
				id_of_image = self.selected_image.get_id()
				file_to_upload = os.path.join(GLib.get_tmp_dir(), f"aihub_temp_layer_{id_of_image}_no_{self.selected_layer.get_id()}.png")
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

			if not data.startswith(b'\x89PNG\r\n\x1a\n'):
				hash_md5.update(data)
			else:
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
		upload_file_hash = hash_md5.hexdigest()

		# now we can upload the file, using that hash as filename, if the file does not exist
		binary_header = {
			"type": "FILE_UPLOAD",
			"filename": upload_file_hash,
			"workflow_id": self.workflow_id,
			"if_not_exists": True
		}

		print("Uploading file", file_to_upload, "with hash", upload_file_hash)

		relegator.reset()

		ws.send(json.dumps(binary_header))

		if not relegator.wait(10):
			self.error_label.show()
			self.success_label.hide()
			self.error_label.set_text("Error uploading file: Timeout waiting for server response.")
			return False
		
		response_data = relegator.last_response

		if (response_data["type"] == "ERROR"):
			self.error_label.show()
			self.success_label.hide()
			self.error_label.set_text(f"Error uploading file: {response_data.get('message', 'Unknown error')}")
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
					self.error_label.set_text("Error uploading file: Timeout waiting for server response after sending file data.")
					return False

				response_data = relegator.last_response

				if (response_data["type"] == "ERROR"):
					self.error_label.show()
					self.success_label.hide()
					self.error_label.set_text(f"Error uploading file: {response_data.get('message', 'Unknown error')}")
					return False
				elif (response_data["type"] == "FILE_UPLOAD_SUCCESS"):
					filename = response_data.get("file", None)
					self.uploaded_file_path = filename

					if self.uploaded_file_path is None:
						self.error_label.show()
						self.success_label.hide()
						self.error_label.set_text("Error uploading file: No file path returned by server.")
						return False

					self.success_label.show()
					self.error_label.hide()
					self.success_label.set_text("File uploaded successfully.")

					# upload successful
					return True
				# unexpected response
				self.error_label.show()
				self.success_label.hide()
				self.error_label.set_text(f"Unexpected response from server: {response_data.get('message', 'Unknown error')}")
				return False
			except Exception as e:
				self.error_label.show()
				self.success_label.hide()
				self.error_label.set_text(f"Error sending file data: {str(e)}")
				return False
		elif (response_data["type"] == "FILE_UPLOAD_SKIP"):
			self.error_label.hide()
			self.success_label.show()
			self.success_label.set_text("File already exists on server, upload skipped.")

			self.uploaded_file_path = upload_file_hash
			return True

		return False

	def load_image_data_for_internal(self):
		load_type = self.data["type"]
		# load types are ["current_layer","merged_image", "merged_image_without_current_layer","upload",]
		if (
			load_type == "current_layer" or
			load_type == "merged_image_without_current_layer"
		):
			# this is our current GIMP image
			image_selected = self.current_image
			print(image_selected)
			if image_selected is not None:
				layers = image_selected.get_selected_layers()
				current_layer = None
				if layers is not None and len(layers) > 0:
					current_layer = layers[0]

				layer = None
				if current_layer is not None and (load_type == "current_layer" or load_type == "merged_image_without_current_layer"):
					layer = current_layer

				if layer is not None:
					self.selected_layer = layer
					self.selected_image = image_selected
					self.selected_layername = layer.get_name()

					if layer is not None and load_type == "current_layer":
						offsets = layer.get_offsets()
						self.value_pos_x = offsets.offset_x
						self.value_pos_y =  offsets.offset_y
						self.value_layer_id = str(layer.get_id())
						self.value_width = layer.get_width()
						self.value_height = layer.get_height()
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
			self.select_button.set_label("Select an image from a file")
			self.select_combo.show()
			self.on_file_selected()
			return
		
		dialog = Gtk.FileChooserDialog(
			title="Select an image file",
			parent=None,
			action=Gtk.FileChooserAction.OPEN,
			buttons=(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
		)
		Gtk.Window.set_keep_above(dialog, True)
		file_filter = Gtk.FileFilter()
		file_filter.set_name("Image files")
		file_filter.add_pattern("*.png")
		file_filter.add_pattern("*.jpg")
		file_filter.add_pattern("*.jpeg")
		dialog.add_filter(file_filter)
		# Do not add any other filters

		response = dialog.run()
		if response == Gtk.ResponseType.OK:
			filename = dialog.get_filename()
			self.select_button.set_label(os.path.basename(filename) + " (Click to clear)")
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
					self.error_label.set_text("Failed to load image.")
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
				self.error_label.set_text("Please select a valid image.")
			else:
				self.success_label.hide()
				self.error_label.hide()
		else:
			if (self.selected_image is None):
				self.error_label.show()
				self.success_label.hide()
				self.error_label.set_text("Please create and select an active image from the dropdown that is not empty.")
			else:
				self.error_label.hide()
				self.success_label.hide()

	def can_run(self):
		if (not self.is_using_internal_file()):
			return self.selected_filename is not None or self.select_combo.get_active() != -1
		else:
			return self.selected_image is not None

class AIHubExposeImageInfoOnly(AIHubExposeImage):
	def __init__(self, id, data, workflow_context, workflow_id, workflow, projectname):
		super().__init__(id, data, workflow_context, workflow_id, workflow, projectname)

		self.info_only_mode = True

class AIHubExposeImageBatch(AIHubExposeBase):
	label: Gtk.Label = None
	box: Gtk.Box = None
	innerbox: Gtk.Box = None

	list_of_exposes = []
	list_of_expose_widgets = []

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

	def __init__(self, id, data, workflow_context, workflow_id, workflow, projectname):
		super().__init__(id, data, workflow_context, workflow_id, workflow, projectname)

		if self.initial_value is None:
			# we will store this immediately
			# so that the children have something where to store their values
			self.on_change([])

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
					"label": f"Image {i+1}",
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
			expose.change_label(f"Image {i+1}")

	def on_add_expose(self):
		new_expose = AIHubExposeImage([self.id, len(self.list_of_exposes)], {
			"label": f"Image {len(self.list_of_exposes)+1}",
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
	label: Gtk.Label = None
	error_label: AIHubLabel = None
	widget: Gtk.SpinButton 
	box: Gtk.Box

	def __init__(self, id, data, workflow_context, workflow_id, workflow, projectname):
		super().__init__(id, data, workflow_context, workflow_id, workflow, projectname)

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
		if not isinstance(value, int):
			self.error_label.show()
			self.error_label.set_text("Value must be an integer.")
		elif not (self.data["min"] <= value <= self.data["max"]):
			self.error_label.show()
			self.error_label.set_text(f"Value must be between {self.data['min']} and {self.data['max']}.")
		else:
			self.error_label.hide()

	def after_ui_built(self):
		self.check_validity(self.get_value())

	def can_run(self):
		return self.data["min"] <= self.get_value() <= self.data["max"]

class AIHubExposeSeed(AIHubExposeBase):
	label: Gtk.Label = None
	error_label: AIHubLabel = None
	widget_value_fixed: Gtk.SpinButton
	widget_value: Gtk.ComboBoxText
	box: Gtk.Box

	def __init__(self, id, data, workflow_context, workflow_id, workflow, projectname):
		super().__init__(id, data, workflow_context, workflow_id, workflow, projectname)

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
			self.widget_value_fixed.set_tooltip_text("Set a fixed seed value to get the same results every time.")

		self.widget_value = Gtk.ComboBoxText()
		self.widget_value.set_entry_text_column(0)
		self.widget_value.append("random", "Random")
		self.widget_value.append("fixed", "Fixed")

		self.widget_value_fixed.connect("changed", self.on_change_value)
		self.widget_value.connect("changed", self.on_change_value)

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

		self.ensure_value_fixed_visibility_state()

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

	def set_initial_value_from_default(self):
		if (self.data["value"] is not None):
			self.initial_value = {
				"value": self.data["value"],
				"value_fixed": self.data["value_fixed"] if "value_fixed" in self.data else 0
			}

	def get_value(self):
		return {
			"value_fixed": self.widget_value_fixed.get_value_as_int(),
			"value": self.widget_value.get_active_id()
		}

	def get_widget(self):
		return self.box
	
	def ensure_value_fixed_visibility_state(self):
		if self.widget_value.get_active_id() == "fixed":
			self.widget_value_fixed.show()
		else:
			self.widget_value_fixed.hide()

	def on_change_value(self, widget):
		self.ensure_value_fixed_visibility_state()
		self.on_change(self.get_value())

	def can_run(self):
		value = self.get_value()
		return isinstance(value, dict) and "value" in value and value["value"] in ["random", "fixed"] and isinstance(value["value_fixed"], int)
	
	def check_validity(self, value):
		if not self.can_run():
			self.error_label.show()
			self.error_label.set_text("Value must be a valid object with 'value' as 'random' or 'fixed' and 'value_fixed' as an integer.")
		else:
			self.error_label.hide()

	def after_ui_built(self):
		self.ensure_value_fixed_visibility_state()
		self.check_validity(self.get_value())

class AIHubExposeFloat(AIHubExposeBase):
	label: Gtk.Label = None
	widget: Gtk.SpinButton
	box: Gtk.Box

	def __init__(self, id, data, workflow_context, workflow_id, workflow, projectname):
		super().__init__(id, data, workflow_context, workflow_id, workflow, projectname)

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

		# add on change event
		self.widget.connect("value-changed", self.on_change_value)

		if (self.initial_value is not None):
			self.widget.set_value(float(self.initial_value))

		# add a tooltip with the description if any available
		if "tooltip" in data and data["tooltip"] is not None and data["tooltip"] != "":
			self.widget.set_tooltip_text(data["tooltip"])

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

	def can_run(self):
		return self.data["min"] <= self.get_value() <= self.data["max"]
	
	def check_validity(self, value):
		if not isinstance(value, float):
			self.error_label.show()
			self.error_label.set_text("Value must be an float.")
		elif not (self.data["min"] <= value <= self.data["max"]):
			self.error_label.show()
			self.error_label.set_text(f"Value must be between {self.data['min']} and {self.data['max']}.")
		else:
			self.error_label.hide()

	def after_ui_built(self):
		self.check_validity(self.get_value())

class AIHubExposeBoolean(AIHubExposeBase):
	label: Gtk.Label = None
	error_label: AIHubLabel = None
	widget: Gtk.CheckButton
	box: Gtk.Box

	def __init__(self, id, data, workflow_context, workflow_id, workflow, projectname):
		super().__init__(id, data, workflow_context, workflow_id, workflow, projectname)

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
			self.error_label.set_text("Value must be a boolean.")
		else:
			self.error_label.hide()

	def after_ui_built(self):
		self.check_validity(self.get_value())

	def can_run(self):
		return not isinstance(self.get_value(), bool)

class AIHubExposeString(AIHubExposeBase):
	label: Gtk.Label = None
	error_label: AIHubLabel = None
	widget: Gtk.Entry | Gtk.TextView
	box: Gtk.Box
	is_multiline: bool = False

	def __init__(self, id, data, workflow_context, workflow_id, workflow, projectname):
		super().__init__(id, data, workflow_context, workflow_id, workflow, projectname)

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
			self.error_label.set_text("Value must be a string.")
		elif len(value) > self.data["maxlen"]:
			self.error_label.show()
			self.error_label.set_text(f"Value must be at most {self.data['maxlen']} characters long.")
		elif len(value) < self.data["minlen"]:
			self.error_label.show()
			self.error_label.set_text(f"Value must be at least {self.data['minlen']} characters long.")
		else:
			self.error_label.hide()

	def can_run(self):
		return len(self.get_value()) <= self.data["maxlen"] and len(self.get_value()) >= self.data["minlen"]

class AIHubExposeStringSelection(AIHubExposeBase):
	label: Gtk.Label = None
	error_label: AIHubLabel = None
	widget: Gtk.ComboBoxText
	box: Gtk.Box
	options: list = []
	labels: list = []

	def __init__(self, id, data, workflow_context, workflow_id, workflow, projectname):
		super().__init__(id, data, workflow_context, workflow_id, workflow, projectname)

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
			self.error_label.set_text("Value must be a string.")
		elif value not in self.options:
			self.error_label.show()
			self.error_label.set_text(f"Value must be one of the allowed options.")
		else:
			self.error_label.hide()

class AIHubExposeConfigBase(AIHubExposeBase):
	def get_value(self):
		value = self.read_config_json(self.data["field"])
		if value is None:
			value = self.data["default"]
		return value
	
class AIHubExposeConfigString(AIHubExposeBase):
	def get_value(self):
		parent_value = super().get_value()
		if not isinstance(parent_value, str):
			return self.data["default"]
		return parent_value
	
class AIHubExposeConfigInteger(AIHubExposeBase):
	def get_value(self):
		parent_value = super().get_value()
		if not isinstance(parent_value, int):
			return self.data["default"]
		return parent_value
	
class AIHubExposeConfigBoolean(AIHubExposeBase):
	def get_value(self):
		parent_value = super().get_value()
		if not isinstance(parent_value, bool):
			return self.data["default"]
		return parent_value
	
class AIHubExposeConfigFloat(AIHubExposeBase):
	def get_value(self):
		parent_value = super().get_value()
		if not isinstance(parent_value, float):
			return self.data["default"]
		return parent_value

EXPOSES = {
	"AIHubExposeInteger": AIHubExposeInteger,
	"AIHubExposeSteps": AIHubExposeInteger,
	"AIHubExposeCfg": AIHubExposeFloat,
	"AIHubExposeConfigInteger": AIHubExposeConfigInteger,
	"AIHubExposeConfigString": AIHubExposeConfigString,
	"AIHubExposeConfigBoolean": AIHubExposeConfigBoolean,
	"AIHubExposeConfigFloat": AIHubExposeConfigFloat,
	"AIHubExposeFloat": AIHubExposeFloat,
	"AIHubExposeBoolean": AIHubExposeBoolean,
	"AIHubExposeString": AIHubExposeString,
	"AIHubExposeStringSelection": AIHubExposeStringSelection,
	"AIHubExposeImage": AIHubExposeImage,
	"AIHubExposeImageInfoOnly": AIHubExposeImageInfoOnly,
	"AIHubExposeImageBatch": AIHubExposeImageBatch,
	"AIHubExposeSeed": AIHubExposeSeed,
	"AIHubExposeSampler": AIHubExposeStringSelection,
	"AIHubExposeScheduler": AIHubExposeStringSelection
}