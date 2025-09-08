from workspace import get_aihub_common_property_value, get_project_config_filepath, update_aihub_common_property_value
from gi.repository import Gimp, Gtk, GLib # type: ignore
from gi.repository.GdkPixbuf import Pixbuf # type: ignore
from gi.repository.GdkPixbuf import InterpType # type: ignore
from gi.repository import Gio # type: ignore

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

	def upload_binary(self, ws):
		# upload a binary before getting the value, if any this function is called
		# when the value is requested by the run function
		pass

	def is_default_value(self):
		return self.get_value() == self.data["value"]
	
	def is_advanced(self):
		return False if "advanced" not in self.data or self.data["advanced"] is None else self.data["advanced"]

	def get_index(self):
		return 0 if "index" not in self.data or self.data["index"] is None else self.data["index"]
	
	def on_change(self, value):
		# add a timeout to stack and only do the change after 1s if the function isnt called continously
		# basically it waits 1s before calling the function but
		# if it is called a second time it will stop the first call
		if self._on_change_timeout_id is not None:
			GLib.source_remove(self._on_change_timeout_id)
			self._on_change_timeout_id = None

		self._on_change_timeout_id = GLib.timeout_add(1000, self._on_change_timeout, value)

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

	def can_run(self):
		# by default all exposes can run
		return True

class AIHubExposeImage(AIHubExposeBase):
	label: Gtk.Label = None
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

	refresh_amount = 0

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
			self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
			self.box.pack_start(self.label, False, False, 0)
			self.box.pack_start(self.select_button, True, True, 0)
			self.box.pack_start(self.select_combo, True, True, 0)

			self.image_preview = Gtk.Image()
			self.box.pack_start(self.image_preview, True, True, 0)

			self.load_image_preview()

			# ensure to add spacing from the top some margin top
			self.box.set_margin_top(10)
		else:
			self.label = Gtk.Label(self.data["label"], xalign=0)
			self.namelabel = Gtk.Label("", xalign=0)
			self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
			self.box.pack_start(self.label, False, False, 0)
			self.box.pack_start(self.namelabel, False, False, 0)
			self.box.set_margin_top(10)

			self.image_preview = Gtk.Image()
			self.box.pack_start(self.image_preview, True, True, 0)

			if known_tooltip is not None:
				self.label.set_tooltip_text(known_tooltip)
				self.namelabel.set_tooltip_text(known_tooltip)
				self.image_preview.set_tooltip_text(known_tooltip)

			self.load_image_data_for_internal()

	def load_image_data_for_internal(self):
		load_type = self.data["type"]
		# load types are ["current_layer","merged_image", "merged_image_without_current_layer","upload",]
		if (
			load_type == "current_layer" or
			load_type == "merged_image_without_current_layer"
		):
			# this is our current GIMP image
			image_selected = self.current_image
			if image_selected is not None:
				layers = image_selected.get_selected_layers()
				current_layer = None
				if layers is not None and len(layers) > 0:
					current_layer = layers[0]

				layer = None
				if current_layer is not None and (load_type == "current_layer" or load_type == "merged_image_without_current_layer"):
					layer = current_layer

				self.selected_layer = layer
				self.selected_image = image_selected
				self.selected_layername = layer.get_name()

				if layer is not None and load_type == "current_layer":
					offsets = layer.get_offsets()
					self.value_pos_x = offsets.offset_x
					self.value_pos_y =  offsets.offset_y
					self.value_layer_id = layer.get_id()
					self.value_width = layer.get_width()
					self.value_height = layer.get_height()
				else:
					self.value_pos_x = 0
					self.value_pos_y = 0
					self.value_layer_id = ""
					self.value_width = image_selected.get_width()
					self.value_height = image_selected.get_height()
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
		file_filter.add_pattern("*.webp")
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
					pixbuf = pixbuf.scale_simple(width, height, InterpType.BILINEAR)
					self.image_preview.set_from_pixbuf(pixbuf)
				except Exception as e:
					self.image_preview.clear()
			else:
				self.image_preview.clear()
	
	def get_value_base(self):
		if (self.selected_filename is not None and os.path.exists(self.selected_filename)):
			return {
				"_local_file": self.selected_filename,
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

	def after_ui_built(self):
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

class AIHubExposeImageInfoOnly(AIHubExposeImage):
	def __init__(self, id, data, workflow_context, workflow_id, workflow, projectname):
		super().__init__(id, data, workflow_context, workflow_id, workflow, projectname)

		self.info_only_mode = True

class AIHubExposeInteger(AIHubExposeBase):
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
		label = Gtk.Label(self.data["label"], xalign=0)
		self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
		self.box.pack_start(label, False, False, 0)
		self.box.pack_start(self.widget, True, True, 0)

		# ensure to add spacing from the top some margin top
		self.box.set_margin_top(10)

	def get_value(self):
		return self.widget.get_value_as_int()

	def get_widget(self):
		return self.box

	def on_change_value(self, widget):
		self.on_change(widget.get_value_as_int())

class AIHubExposeSeed(AIHubExposeBase):
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
		label = Gtk.Label(self.data["label"], xalign=0)
		self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
		self.box.pack_start(label, False, False, 0)

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

	def after_ui_built(self):
		self.ensure_value_fixed_visibility_state()

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

class AIHubExposeFloat(AIHubExposeBase):
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
		label = Gtk.Label(self.data["label"], xalign=0)
		label.set_size_request(400, -1)
		label.set_line_wrap(True)
		self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
		self.box.pack_start(label, False, False, 0)
		self.box.pack_start(self.widget, True, True, 0)

		# ensure to add spacing from the top some margin top
		self.box.set_margin_top(10)

	def get_value(self):
		return self.widget.get_value()

	def get_widget(self):
		return self.box
	
	def on_change_value(self, widget):
		self.on_change(widget.get_value())

class AIHubExposeBoolean(AIHubExposeBase):
	widget: Gtk.CheckButton
	box: Gtk.Box

	def __init__(self, id, data, workflow_context, workflow_id, workflow, projectname):
		super().__init__(id, data, workflow_context, workflow_id, workflow, projectname)

		self.widget = Gtk.CheckButton()
		self.widget.set_active(self.initial_value)

		# make a box to have the label and the field
		# make the label
		label = Gtk.Label(self.data["label"], xalign=0)
		label.set_size_request(400, -1)
		label.set_line_wrap(True)
		self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
		self.box.pack_start(label, False, False, 0)
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
	
class AIHubExposeString(AIHubExposeBase):
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
		label = Gtk.Label(self.data["label"], xalign=0)
		label.set_size_request(400, -1)
		label.set_line_wrap(True)
		self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
		self.box.pack_start(label, False, False, 0)
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

class AIHubExposeStringSelection(AIHubExposeBase):
	widget: Gtk.ComboBoxText
	box: Gtk.Box

	def __init__(self, id, data, workflow_context, workflow_id, workflow, projectname):
		super().__init__(id, data, workflow_context, workflow_id, workflow, projectname)

		self.widget = Gtk.ComboBoxText()
		self.widget.set_entry_text_column(0)

		# add the options to the combo box
		# options is actually just a string that is multiline separated, ignore empty lines
		# the label is optained from a similar field called options_label that works in the same way
		labels = []
		options = []
		for option in data["options"].splitlines():
			option = option.strip()
			if option:
				options.append(option)

		for label in data["options_label"].splitlines():
			label = label.strip()
			if label:
				labels.append(label)

		for i in range(len(options)):
			self.widget.append(options[i], labels[i])

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
		label = Gtk.Label(self.data["label"], xalign=0)
		label.set_size_request(400, -1)
		label.set_line_wrap(True)
		self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
		self.box.pack_start(label, False, False, 0)
		self.box.pack_start(self.widget, True, True, 0)

	def get_value(self):
		return self.widget.get_active_id()

	def get_widget(self):
		return self.box
	
	def on_change_value(self, widget):
		self.on_change(self.widget.get_active_id())

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
	"AIHubExposeImageBatch": None,
	"AIHubExposeSeed": AIHubExposeSeed,
	"AIHubExposeSampler": AIHubExposeStringSelection,
	"AIHubExposeScheduler": AIHubExposeStringSelection
}