from websocket._app import WebSocketApp
from workspace import ensure_aihub_folder, get_aihub_common_property_value, get_project_config_filepath, update_aihub_common_property_value
from gi.repository import Gimp, GimpUi, Gtk, GLib # type: ignore
from gi.repository.GdkPixbuf import Pixbuf # type: ignore
from gi.repository.GdkPixbuf import InterpType # type: ignore
from gi.repository import Gio # type: ignore
from gtkexposes import EXPOSES

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
sys.stderr = open('err.txt', 'a')
sys.stdout = open('log.txt', 'a')

PROC_NAME = "AI Hub"

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

def getAvailableCategoriesFromWorkflows(workflows, contexts):
	"""
	Returns a dictionary where the key are the workflow context and the values
	are a list that represent the given categories for that workflow context.
	"""
	return {context: [workflow["category"] for workflow in workflows.values() if workflow["context"] == context]
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
		samplers = []
		schedulers = []

		main_box: Gtk.Box

		selected_image = None

		# elements of the main UI
		image_selector: Gtk.ComboBox
		image_model: Gtk.ListStore
		context_selector: Gtk.ComboBoxText
		category_selector: Gtk.ComboBoxText
		workflow_selector: Gtk.ComboBoxText
		description_label: Gtk.TextView
		run_button: Gtk.Button

		# elements of a project type UI

		# generics
		workflow_image: Gtk.Image
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
						self.samplers = message_parsed.get("samplers", [])
						self.schedulers = message_parsed.get("schedulers", [])
						self.setStatus("Status: Processing workflows, models and loras")

						if (len(self.workflow_contexts) == 0 or len(self.workflow_categories) == 0):
							self.setStatus("Status: No valid workflows or categories found.")
							self.setErrored()
							return
						
						try:
							self.setStatus("Status: Ready")
							self.build_ui_base()
						except Exception as e:
							self.setStatus(f"Status: Error building UI: {e}")
							self.setErrored()
					else:
						self.setStatus(f"Status: Unknown message type received: {message_parsed['type']}")
			except Exception as e:
				self.setStatus("Status: Received invalid message from server.")

		def refresh_image_list(self, recreate_list: bool):
			if self.errored:
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

			self.on_context_selected(self.context_selector)

		def on_context_selected(self, combo):
			try:
				selected_context = combo.get_active_id()

				update_aihub_common_property_value("", "", "default_context", selected_context, None)
				
				# remove all workflows and categories in their respective comboboxes that have been
				# previously selected
				self.workflow_selector.remove_all()
				self.category_selector.remove_all()

				# now start by adding the categories for that specific context that was selected
				for category in self.workflow_categories.get(selected_context, []):
					self.category_selector.append(category, category.upper())

				self.main_box.show_all()

				default_category = get_aihub_common_property_value("", selected_context, "default_category", None)
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

				update_aihub_common_property_value("", selected_context, "default_category", selected_category, None)

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

				default_workflow = get_aihub_common_property_value("", selected_context + "/" + selected_category, "default_workflow", None)
				if default_workflow is None or not self.workflow_categories[selected_context].count(default_workflow):
					default_workflow = first_workflow

				self.main_box.show_all()

				# we are going to make the default selected to be the first one in our list of workflows in workflows
				self.workflow_selector.set_active_id(default_workflow)

			#self.on_workflow_selected(self.workflow_selector)
			except Exception as e:
				self.setStatus(f"Error: {str(e)}")
				self.setErrored()

		def on_workflow_selected(self, combo):
			try:
				selected_context = self.context_selector.get_active_id()
				selected_workflow = combo.get_active_id()
				workflow = self.workflows.get(selected_workflow)

				if not workflow or not workflow.get("description", None):
					self.description_label.get_buffer().set_text(workflow.get("description", "No description available."))
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

					ExposeClass = EXPOSES.get(type, None)

					instance = ExposeClass(expose_id, data, selected_context, selected_workflow, workflow, None) if ExposeClass else None
					if instance:
						if self.selected_image:
							instance.current_image_changed(self.selected_image, self.image_selector.get_model())
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

				# add a horizontal separator
				separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
				self.workflow_elements.pack_start(separator, False, False, 12)

				self.run_button = Gtk.Button(label="Run Workflow")
				self.run_button.connect("clicked", self.on_run_workflow)
				#align the run button to the right
				self.run_button.set_halign(Gtk.Align.END)
				self.run_button.set_hexpand(False)
				#add margin top to the button
				self.run_button.set_margin_top(12)

				self.workflow_elements.pack_start(self.run_button, False, False, 0)

				self.run_button.set_tooltip_text("Run the selected workflow with the selected options")
				self.run_button.show()

				for element in self.workflow_elements_all:
					if element.get_widget():
						element.after_ui_built()
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
						dialog.format_secondary_text("Please check the input values and try again.")
						dialog.show()
						# make the dialog on top of everything
						dialog.set_keep_above(True)
						# make it close once you click ok, and also call mark_as_running(False)
						dialog.connect("response", lambda d, r: self.mark_as_running(False) or d.destroy())
						return

				# we are going to gather all the values
				values = {}
				for element in self.workflow_elements_all:
					element.upload_binary(self.websocket)
					values[element.id] = element.get_value()

			except Exception as e:
				self.setStatus(f"Error: {str(e)}")
				self.setErrored()
				return

			return
		
		def mark_as_running(self, running: bool):
			# disable all the elements in the UI if running is true, otherwise enable them
			self.image_selector.set_sensitive(not running)
			self.context_selector.set_sensitive(not running)
			self.category_selector.set_sensitive(not running)
			self.workflow_selector.set_sensitive(not running)
			# make the run button disabled or enabled
			self.run_button.set_sensitive(not running)

			for element in self.workflow_elements_all:
				if element.get_widget():
					element.get_widget().set_sensitive(not running)

			if running:
				self.setStatus("Status: Running workflow...")
			else:
				self.setStatus("Status: Ready")

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

			# add on dialog focus event
			Gtk.Window.connect(self, "focus-in-event", self.on_dialog_focus)

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

			self.message_label.set_tooltip_text("Shows the current status of the plugin as it communicates with the server and operates")

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

		def on_dialog_focus(self, widget, event):
			# call the function in all the workflow_elements_all to notify them that the dialog has been focused
			self.refresh_image_list(True)
			for element in self.workflow_elements_all:
				element.on_refresh()

	ImageDialog().run()

	return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())