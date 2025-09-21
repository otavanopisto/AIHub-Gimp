from gi.repository import Gtk # type: ignore

class AIHubLabel:
	def __init__(self, text, css_extra: bytes = None):
		self.text = text
		self.widget = Gtk.TextView()
		self.widget.set_editable(False)
		self.widget.set_cursor_visible(False)
		self.widget.set_wrap_mode(Gtk.WrapMode.WORD)
		self.widget.set_size_request(400, -1)

		css = b"""
		.textview, textview, textview text, textview view {
			background-color: transparent;
			border: none;
		"""
		if css_extra is not None:
			css += css_extra
		css += b"}"

		style_provider = Gtk.CssProvider()
		style_provider.load_from_data(css)
		self.widget.get_style_context().add_provider(
			style_provider,
			Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
		)
		self.widget.get_style_context().add_class("textview")
		self.set_text(text)

	def get_widget(self):
		return self.widget
	
	def get_as_gtk_label(self):
		label = Gtk.Label()
		label.set_text(self.text)
		label.set_line_wrap(True)
		label.set_xalign(0)  # Align left
		return label
	
	def set_tooltip_text(self, text):
		self.widget.set_tooltip_text(text)

	def get_text(self):
		buffer = self.widget.get_buffer()
		start_iter = buffer.get_start_iter()
		end_iter = buffer.get_end_iter()
		return buffer.get_text(start_iter, end_iter, True)
	
	def set_text(self, text):
		buffer = self.widget.get_buffer()
		buffer.set_text(text)

	def show(self):
		self.widget.show()
	
	def hide(self):
		self.widget.hide()

	def set_size_request(self, width, height):
		self.widget.set_size_request(width, height)