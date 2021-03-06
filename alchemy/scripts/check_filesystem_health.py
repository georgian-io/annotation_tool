from alchemy.db.fs import raw_data_dir, models_dir, training_data_dir
from alchemy.shared import health_check

# Make sure that the directories exist
raw_data_dir(as_path=True).mkdir(parents=True, exist_ok=True)
models_dir(as_path=True).mkdir(parents=True, exist_ok=True)
training_data_dir(as_path=True).mkdir(parents=True, exist_ok=True)

# Check if they're read and writable
if health_check.check_file_system():
    print("File system is operational and healthy")
else:
    print("ERROR: file system is either not readable or mounted as read only")
    exit(1)
