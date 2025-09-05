#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import gi

gi.require_version('Gimp', '3.0')
gi.require_version('GimpUi', '3.0')
gi.require_version('Gtk', '3.0')

from image import runImageProcedure

from gi.repository import Gimp #type: ignore

import gettext
textdomain = "gimp30-python"

class AiHub(Gimp.PlugIn):
	def do_set_i18n(self, name):
		gettext.bindtextdomain(textdomain, Gimp.locale_directory())
		return True, 'gimp30-python', None

	def do_query_procedures(self):
		return [
			"ai-hub-image-procedure"
		]
	
	def do_create_procedure(self, name):
		if name == "ai-hub-image-procedure":
			procedure = Gimp.ImageProcedure.new(
				self,
				"ai-hub-image-procedure",  # Unique PDB procedure name
				Gimp.PDBProcType.PLUGIN,         # It's a standard plugin
				runImageProcedure,                     # Function to call when run
				None,
			)
			procedure.set_menu_label("Image Tools")
			procedure.add_menu_path("<Image>/AI Hub")
			procedure.set_sensitivity_mask(
				Gimp.ProcedureSensitivityMask.ALWAYS
			)
			return procedure
		return None

Gimp.main(AiHub.__gtype__, sys.argv)