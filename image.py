from websocket._app import WebSocketApp
from workspace import ensure_aihub_folder, get_aihub_common_property_value, get_project_config_filepath, update_aihub_common_property_value
from gi.repository import Gimp, GimpUi, Gtk, GLib # type: ignore
import json
import os
import websocket
import socket

import threading

import gettext
textdomain = "gimp30-python"
gettext.textdomain(textdomain)
_ = gettext.gettext

import sys
sys.stderr = open('err.txt', 'a')
sys.stdout = open('log.txt', 'a')

PROC_NAME = "AI Hub"

def getAllAvailableContextFromWorkflows(workflows):
	return list(set(workflow["context"] for workflow in workflows.values()))

def getAvailableCategoriesFromWorkflows(workflows, contexts):
	"""
	Returns a dictionary where the key are the workflow context and the values
	are a list that represent the given categories for that workflow context.
	"""
	return {context: [workflow["category"] for workflow in workflows.values() if workflow["context"] == context]
			for context in contexts}

class AIHubExposeBase:
	data = None
	id = None
	initial_value = None
	workflow = None
	projectname = None
	workflow_context = None
	workflow_id = None
	_on_change_timeout_id = None
	def __init__(self, id, data, workflow_context, workflow_id, workflow, projectname):
		self.data = data
		self.id = id
		self.workflow_context = workflow_context
		self.workflow_id = workflow_id
		self.initial_value = get_aihub_common_property_value(workflow_context, workflow_id, self.id, projectname)
		self.workflow = workflow
		self.projectname = projectname
		if (self.initial_value is None and data["value"] is not None):
			self.initial_value = data["value"]

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
		pass

	def is_default_value(self):
		return self.get_value() == self.data["value"]
	
	def is_advanced(self):
		return self.data["advanced"]

	def get_index(self):
		return self.data["index"]
	
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

	def get_value(self):
		return self.widget.get_active_id()

	def get_widget(self):
		return self.widget
	
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

	# TODO fix these with actual values
	"AIHubExposeImage": None,
	"AIHubExposeImageInfoOnly": None,
	"AIHubExposeImageBatch": None,
	"AIHubExposeSeed": None,

	# TODO fix these with actual values
	"AIHubExposeSampler": AIHubExposeString,
	"AIHubExposeScheduler": AIHubExposeString
}

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

def runImageProcedure(procedure, run_mode, image, drawables, config, run_data):
	GimpUi.init("AIHub.py")

	lock_socket = acquire_process_lock()
	if (not lock_socket):
		return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())

	class ImageDialog(GimpUi.Dialog):
		message_label: Gtk.TextView
		websocket: WebSocketApp
		errored: bool = False
		expecting_next_binary: bool = False

		workflows = {}
		workflow_contexts = []
		workflow_categories = []
		models = []
		loras = []

		main_box: Gtk.Box

		# elements of the main UI
		context_selector: Gtk.ComboBoxText
		category_selector: Gtk.ComboBoxText
		workflow_selector: Gtk.ComboBoxText
		description_label: Gtk.TextView

		# elements of a project type UI

		# generics
		workflow_elements: Gtk.Box
		workflow_elements_all = []

		def setStatus(self, v: str):
			buffer = self.message_label.get_buffer()
			buffer.set_text(v)

		def setErrored(self):
			self.errored = True

		def on_message(self, ws, msg):
			if self.errored:
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
						self.setStatus("Status: Processing workflows, models and loras")

						if (len(self.workflow_contexts) == 0 or len(self.workflow_categories) == 0):
							self.setStatus("Status: No valid workflows or categories found.")
							self.setErrored()
							return
						
						try:
							self.build_ui_base()
							self.setStatus("Status: Ready")
						except Exception as e:
							self.setStatus(f"Status: Error building UI: {e}")
							self.setErrored()
					else:
						self.setStatus(f"Status: Unknown message type received: {message_parsed['type']}")
			except Exception as e:
				self.setStatus("Status: Received invalid message from server.")

		def build_ui_base(self):
			if self.errored:
				return
			
			# lets start with the basics and make a selector for the contexts
			self.context_selector = Gtk.ComboBoxText()
			for context in self.workflow_contexts:
				self.context_selector.append(context, context.upper())
			self.main_box.pack_start(self.context_selector, False, False, 0)

			self.category_selector = Gtk.ComboBoxText()
			self.main_box.pack_start(self.category_selector, False, False, 0)

			self.workflow_selector = Gtk.ComboBoxText()
			self.main_box.pack_start(self.workflow_selector, False, False, 0)

			# we are also going to make some label text display to display
			# the description
			self.description_label = Gtk.TextView()
			self.description_label.set_editable(False)
			self.description_label.set_cursor_visible(False)
			self.description_label.set_wrap_mode(Gtk.WrapMode.WORD)
			self.description_label.set_size_request(400, -1)

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

			# add the listener for the a context is selected by the user
			self.context_selector.connect("changed", self.on_context_selected)
			# trigger it by hand because we want to set the initial status
			self.main_box.show_all()

			self.on_context_selected(self.context_selector)

		def on_context_selected(self, combo):
			selected_context = combo.get_active_id()
			
			# remove all workflows and categories in their respective comboboxes that have been
			# previously selected
			self.workflow_selector.remove_all()
			self.category_selector.remove_all()

			# now start by adding the categories for that specific context that was selected
			for category in self.workflow_categories.get(selected_context, []):
				self.category_selector.append(category, category.upper())

			# we are going to make the default selected to be the first one in our list of categories in workflow_categories
			self.category_selector.set_active_id(self.workflow_categories[selected_context][0])

			self.main_box.show_all()

			self.on_category_selected(self.category_selector)

		def on_category_selected(self, combo):
			selected_context = self.context_selector.get_active_id()
			selected_category = combo.get_active_id()

			# remove all workflows in their respective comboboxes that have been previously selected
			self.workflow_selector.remove_all()

			# now start by adding the workflows for that specific category that was selected
			# the workflows have to be filtered by hand because they are a dictionary of key values and we must check
			# by the context and the category that they match
			first_workflow = None
			for workflow in self.workflows.values():
				if workflow["context"] == selected_context and workflow["category"] == selected_category:
					self.workflow_selector.append(workflow["id"], workflow["label"])
					if not first_workflow:
						first_workflow = workflow["id"]

			# we are going to make the default selected to be the first one in our list of workflows in workflows
			self.workflow_selector.set_active_id(first_workflow)

			self.main_box.show_all()

			self.on_workflow_selected(self.workflow_selector)

		def on_workflow_selected(self, combo):
			selected_context = self.context_selector.get_active_id()
			selected_workflow = combo.get_active_id()
			workflow = self.workflows.get(selected_workflow)

			if not workflow or not workflow.get("description", None):
				self.description_label.get_buffer().set_text(workflow.get("description", "No description available."))
			else:
				self.description_label.get_buffer().set_text(workflow["description"])

			# now let's clear the workflow box
			self.workflow_elements.foreach(Gtk.Widget.destroy)
			self.workflow_elements_all = []

			# and let's find our exposes for that let's get the key value for each expose
			exposes = workflow.get("expose", {})

			for expose_id, widget in exposes.items():
				global EXPOSES
				type = widget.get("type", None)
				data = widget.get("data", None)
				ExposeClass = EXPOSES.get(type, None)

				instance = ExposeClass(expose_id, data, selected_context, selected_workflow, workflow, None) if ExposeClass else None
				if instance:
					self.workflow_elements_all.append(instance)
			
			# now we have to sort self.workflow_elements_all by the get_index function that returns a number
			self.workflow_elements_all.sort(key=lambda x: x.get_index())

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
			else:
				self.main_box.show_all()

		def on_toggle_advanced_options(self, button, advanced_options_box):
			if advanced_options_box.is_visible():
				advanced_options_box.hide()
				button.set_label("Show Advanced Options")
			else:
				advanced_options_box.show()
				button.set_label("Hide Advanced Options")

		def on_open(self, ws):
			self.setStatus("Status: Connected to server, waiting for workflows information")

		def on_close(self, ws):
			self.setStatus("Status: Disconnected from server.")
			self.setErrored()

		def start_websocket(self):
			try:
				self.websocket = websocket.WebSocketApp(
					f"{self.apiprotocol}://{self.apihost}:{self.apiport}/ws",
					on_message=self.on_message,
					on_open=self.on_open,
					header={"api-key": self.apikey}
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

			GimpUi.Dialog.__init__(self, decorated=True, modal=False)
			Gtk.Window.set_title(self, _("AI Hub Image Tools"))
			Gtk.Window.set_role(self, PROC_NAME)
			Gtk.Window.set_resizable(self, False)

			Gtk.Window.set_keep_above(self, True)

			Gtk.Window.connect(self, "delete-event", self.on_delete_event)

			Gtk.Window.set_default_size(self, 400, 600)

			# make the dialog always be as small as it can be
			Gtk.Window.set_size_request(self, 400, 600)

			# Make the dialog dockable and persistent.
			# This is how you make it behave like GIMP's native dialogs.
			self.set_role("ai-hub-image-procedure") # A unique role string

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

			buffer = self.message_label.get_buffer()
			buffer.set_text("Status: Connecting to server...")

			self.main_box.pack_start(self.message_label, False, False, 0)

			contents_area = Gtk.Dialog.get_content_area(self)
			contents_area.pack_start(self.main_box, True, True, 0)

			try:
				config = ensure_aihub_folder()

				self.apihost = config.get("api", "host")
				self.apiport = config.get("api", "port")
				self.apiprotocol = config.get("api", "protocol")
				self.apikey = config.get("api", "apikey")

				self.setStatus(f"Status: Communicating at {self.apiprotocol}://{self.apihost}:{self.apiport}")

				threading.Thread(target=self.start_websocket, daemon=True).start()
			except Exception as e:
				self.setStatus(f"Error: {str(e)}")
				self.setErrored()

		def on_delete_event(self, widget, event):
			self.destroy()
			Gtk.main_quit()
			lock_socket.close()
			return True
		
		def run(self):
			Gtk.Widget.show_all(self)
			Gtk.main()

	ImageDialog().run()

	return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())