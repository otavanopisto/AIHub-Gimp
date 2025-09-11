import os
import configparser
import json

CONFIG_FILE_NAME = "config.ini"
PROJECT_CONFIG_JSON_FILE_NAME = "config.json"
AI_HUB_FOLDER_NAME = "aihub"
home_directory = os.path.expanduser("~")
AI_HUB_FOLDER_PATH = os.path.join(home_directory, AI_HUB_FOLDER_NAME)

DEFAULT_CONFIG = configparser.ConfigParser()
DEFAULT_CONFIG["api"] = {
	"host": "127.0.0.1",
	"port": "8000",
	"protocol": "ws",
	"apikey": "YOUR_API_KEY",
}

def get_config_filepath():
	config_path = os.path.join(AI_HUB_FOLDER_PATH, CONFIG_FILE_NAME)

	return config_path

def get_project_config_filepath(projectname: str):
	config_path = os.path.join(AI_HUB_FOLDER_PATH, projectname, PROJECT_CONFIG_JSON_FILE_NAME)

	return config_path

def ensure_and_retrieve_aihub_config():
	config_path = get_config_filepath()

	current_config = configparser.ConfigParser()
	config_changed = False

	# 1. Check if the config file exists
	if not os.path.exists(config_path):
		print(f"'{CONFIG_FILE_NAME}' not found at '{config_path}'. Creating with default configuration.")
		current_config = DEFAULT_CONFIG
		config_changed = True
	else:
		# File exists, load its content
		try:
			current_config.read(config_path)
			print(f"config read from: {config_path}")
		except Exception as e:
			print(f"Error reading existing config file '{config_path}': {e}. Reverting to default configuration.")
			raise Exception("Failed to read config file")

	# 2. Check for missing sections and options and add them
	for section in DEFAULT_CONFIG.sections():
		if not current_config.has_section(section):
			current_config.add_section(section)
			print(f"Adding missing config section: [{section}]")
			config_changed = True

		for option, default_value in DEFAULT_CONFIG.items(section):
			if not current_config.has_option(section, option):
				current_config.set(section, option, default_value)
				print(f"Adding missing config option: [{section}]{option} = {default_value}")
				config_changed = True

	# 3. Save the file if any changes were made
	if config_changed:
		update_aihub_config(current_config)

	return current_config

def update_aihub_config(current_config: configparser.ConfigParser):
	home_directory = os.path.expanduser("~")
	aihub_folder_path = os.path.join(home_directory, AI_HUB_FOLDER_NAME)
	config_path = os.path.join(aihub_folder_path, CONFIG_FILE_NAME)

	print(f"Updating '{CONFIG_FILE_NAME}' at '{config_path}'")
	try:
		with open(config_path, 'w') as configfile:
			current_config.write(configfile)
		print("Configuration file updated successfully.")
	except IOError as e:
		print(f"Error saving updated config file '{config_path}': {e}")
		raise Exception("Error saving config file")

def ensure_aihub_folder():
	"""
	Checks for the 'aihub' folder in the user's home directory and creates it if it doesn't exist.
	Prints messages indicating the action taken.
	"""
	home_directory = os.path.expanduser("~")
	aihub_folder_path = os.path.join(home_directory, AI_HUB_FOLDER_NAME)

	if os.path.isdir(aihub_folder_path):
		pass
	else:
		try:
			os.makedirs(aihub_folder_path)
		except OSError as e:
			print(f"Error creating 'aihub' folder at {aihub_folder_path}: {e}")
			raise Exception("Error creating 'aihub' folder")
		
	return ensure_and_retrieve_aihub_config()

def update_aihub_common_property_value(workflow_context: str, workflow_id: str, property_id: str | list, value, project: str):
	"""
	Each property that is retreived from an AIHub workflow for a given id has a value,
	this key is used to identify the property in the workflow, this function will
	save in a saved.json file in the AIHub folder the value for the common property
	as it has been modified by the user
	"""

	folder_to_save = os.path.join(AI_HUB_FOLDER_PATH)
	if project is not None and project != "":
		folder_to_save = os.path.join(AI_HUB_FOLDER_PATH, "projects", project)

	if not os.path.exists(folder_to_save):
		os.makedirs(folder_to_save)

	file_to_save = os.path.join(folder_to_save, "saved.json")

	# Load existing saved properties
	saved_properties = {}
	if os.path.exists(file_to_save):
		with open(file_to_save, "r") as f:
			saved_properties = json.load(f)

	# Update the specific property value
	saved_properties[workflow_context] = saved_properties.get(workflow_context, {})
	saved_properties[workflow_context][workflow_id] = saved_properties.get(workflow_context, {}).get(workflow_id, {})
	if isinstance(property_id, list):
		# if property_id is a list, this is the path of the property in the json, so we need to traverse it, remember that numbers
		# represent indexes in lists
		current_level = saved_properties[workflow_context][workflow_id]
		# we don't want to traverse the last element, because that is the one we want to set
		for key in property_id[:-1]:
			if isinstance(key, int) and isinstance(current_level, list) and 0 <= key < len(current_level):
				current_level = current_level[key]
			elif isinstance(key, str) and isinstance(current_level, dict) and key in current_level:
				current_level = current_level[key]
			else:
				current_level = None
				break
		if current_level is not None:
			last_key = property_id[-1]
			if isinstance(last_key, int) and isinstance(current_level, list) and last_key >= 0:
				# if the index is out of range, we need to extend the list
				while len(current_level) <= last_key:
					current_level.append(None)
				current_level[last_key] = value
			elif isinstance(last_key, str) and isinstance(current_level, dict):
				current_level[last_key] = value
			else:
				return None
	else:
		saved_properties[workflow_context][workflow_id][property_id] = value

	# Save the updated properties back to the file
	with open(file_to_save, "w") as f:
		json.dump(saved_properties, f, indent=4)

def get_aihub_common_property_value(workflow_context: str, workflow_id: str, property_id: str | list, project: str):
	"""
	Retrieves the value of a common property for a given workflow type and property ID.
	"""
	folder_to_read = os.path.join(AI_HUB_FOLDER_PATH)
	if project is not None and project != "":
		folder_to_read = os.path.join(AI_HUB_FOLDER_PATH, "projects", project)

	if not os.path.exists(folder_to_read):
		os.makedirs(folder_to_read)

	file_to_read = os.path.join(folder_to_read, "saved.json")

	if os.path.exists(file_to_read):
		with open(file_to_read, "r") as f:
			saved_properties = json.load(f)
			if isinstance(property_id, list):
				# if property_id is a list, this is the path of the property in the json, so we need to traverse it, remember that numbers
				# represent indexes in lists
				current_level = saved_properties.get(workflow_context, {}).get(workflow_id, {})
				for key in property_id:
					if isinstance(key, int) and isinstance(current_level, list) and 0 <= key < len(current_level):
						current_level = current_level[key]
					elif isinstance(key, str) and isinstance(current_level, dict) and key in current_level:
						current_level = current_level[key]
					else:
						current_level = None
						break
				return current_level
			return saved_properties.get(workflow_context, {}).get(workflow_id, {}).get(property_id, None)
	return None