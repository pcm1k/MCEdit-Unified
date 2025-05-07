import tempfile
import shutil
import zipfile
import atexit
import os
import glob

DO_REMOVE = True

def trim_any_leftovers():
    print tempfile.gettempdir()
    leftovers = glob.glob(os.path.join(tempfile.gettempdir(), 'mcworld_*', ''))
    for d in leftovers:
        print "Found left over directory: {}".format(d)
        if DO_REMOVE:
            shutil.rmtree(d, ignore_errors=True)

def close_all_temp_dirs():
    for d in glob.glob(os.path.join(tempfile.gettempdir(), 'mcworld_*', '')):
        #print d
        #print os.path.dirname(d)
        #print '====='
        print "Found temp directory to cleanup: {}".format(d)
        if DO_REMOVE:
            shutil.rmtree(d, ignore_errors=True)
        #shutil.rmtree(os.path.dirname(os.path.dirname(d)), ignore_errors=True)

def _find_level_dat(directory):
    for root, dirs, files in os.walk(directory):
        if 'level.dat' in files and 'db' in dirs:
            return os.path.join(root, 'level.dat')

def open_world(file_path):
    temp_dir = tempfile.mkdtemp(prefix="mcworld_")
    zip_fd = zipfile.ZipFile(file_path, 'r')
    zip_fd.extractall(temp_dir)
    zip_fd.close()

    return _find_level_dat(temp_dir)

def save_world(world_path, dest_path):
    zip_fd = zipfile.ZipFile(dest_path, 'w')
    for root, dirs, files in os.walk(world_path):
        for f in files:
            result = os.path.join(root, f)
            result = result.replace(world_path, '')[1:]
            fp = open(os.path.join(root, f), 'rb')
            zip_fd.writestr(result, fp.read())
            fp.close()
    zip_fd.close()

    return os.path.basename(dest_path)

atexit.register(close_all_temp_dirs)
trim_any_leftovers()
