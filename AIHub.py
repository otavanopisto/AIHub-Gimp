#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import gi

gi.require_version('Gimp', '3.0')
gi.require_version('GimpUi', '3.0')
gi.require_version('Gtk', '3.0')

from tools import runToolsProcedure

from gi.repository import Gimp #type: ignore

import gettext
_ = gettext.gettext
#textdomain = "gimp30-python"

class AiHub(Gimp.PlugIn):
	#def do_set_i18n(self, name):
	#	gettext.bindtextdomain(textdomain, Gimp.locale_directory())
	#	return True, 'gimp30-python', None

	def do_query_procedures(self):
		return [
			"ai-hub-tools-procedure"
		]
	
	def do_create_procedure(self, name):
		if name == "ai-hub-tools-procedure":
			procedure = Gimp.ImageProcedure.new(
				self,
				"ai-hub-tools-procedure",  # Unique PDB procedure name
				Gimp.PDBProcType.PLUGIN,         # It's a standard plugin
				runToolsProcedure,                     # Function to call when run
				None,
			)
			procedure.set_menu_label(_("Launch AIHub"))
			procedure.add_menu_path("<Image>/AI Hub")
			procedure.set_sensitivity_mask(
				Gimp.ProcedureSensitivityMask.ALWAYS
			)
			return procedure
		return None

Gimp.main(AiHub.__gtype__, sys.argv)