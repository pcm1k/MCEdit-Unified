# id_definitions.py
#
# D.C.-G. (LaChal) 2016
#
# Load the data according to the game version from the versioned resources.
#
"""
The logic here is to load the JSON definitions for blocks, entities and tile entities for a given game version.

Data for each game platform is contained in subfolders of the 'mcver' one and subsequent subfolders for each game version number and namespace:

mcver/
  + Alpha/
    + 1.2/
      + minecraft/
        - blocks.json
        - entities.json
        - tileentities.json
    + 1.2.3/
      + minecraft/
        - blocks.json
        - entities.json
        - tileentities.json
  + Pocket/
    + 1.2/
      + minecraft/
        - blocks.json
        - entities.json
        - tileentities.json
    + 1.4/
      + minecraft/
        - blocks.json
        - entities.json
        - tileentities.json
[etc.]

The JSON files can contain all the definitions for a version, or partial ones.
If definitions are partial, other game version files can be loaded by referencing this version in a "load" object like this:

'''
{
    "load": "1.2",
    "blocks": [snip...]
}
'''

Using the directory structure above, and assuming the code snippet comes from the 'block.json' file in the 'Alpha/1.2.3/minecraft' subfolder,
the data in 'blocks.json' in the 'Alpha/1.2/minecraft' subfolder will be loaded before the data in 'blocks.json' in 'Alpha/1.2.3/minecraft'.
So the '1.2.3' data will override the '1.2' data.
"""

import os
import json
from logging import getLogger
import pymclevel
import re
import collections
import sys
from distutils.version import LooseVersion
import pkg_resources

PLATFORM_UNKNOWN = "Unknown"
PLATFORM_ALPHA = "Alpha"
PLATFORM_CLASSIC = "Classic"
PLATFORM_INDEV = "Indev"
PLATFORM_POCKET = "Pocket"

VERSION_UNKNOWN = "Unknown"
VERSION_LATEST = "Latest"

log = getLogger(__name__)

def updateRecursive(orig_dict, new_dict):
    for key, val in new_dict.iteritems():
        if isinstance(val, collections.Mapping):
            if orig_dict.get(key, {}) == val:
                continue
            tmp = updateRecursive(orig_dict.get(key, {}), val)
            orig_dict[key] = tmp
        elif isinstance(val, list):
            if orig_dict.get(key, []) == val:
                continue
            orig_dict[key] = (orig_dict.get(key, []) + val)
        else:
            if orig_dict.get(key, None) == new_dict[key]:
                continue
            orig_dict[key] = new_dict[key]
    return orig_dict

def _parseAutobuilds(data, prefix):
    autobuilds = data.get("autobuild", {})
    for a_name, a_value in autobuilds.iteritems():
        p = re.findall(r"(^|[ ])%s\['(\w+)'" % prefix, a_value)
        if p:
            for a in p[0][1:]:
                if a not in data:
                    log.error("Found wrong reference while parsing autobuilds for %s: %s" % (prefix, a))
                    autobuilds.pop(a_name)
                else:
                    autobuilds[a_name] = a_value.replace("%s[" % prefix, "data[")
        else:
            # Just remove stuff which is not related to data internal stuff
            autobuilds.pop(a_name)
    return autobuilds

def _resolveType(actorTypes, name, actorType, visited):
    if name in visited:
        return 0
    if isinstance(actorType, int):
        # already resolved to an int
        return actorType
    if isinstance(actorType, basestring):
        # resolve the reference recursively
        visited.add(name)
        result = _resolveType(actorTypes, actorType, actorTypes[actorType], visited)
        visited.remove(name)
        return result
    result = 0
    for num in actorType:
        result |= _resolveType(actorTypes, name, num, visited)
    return result

def _resolveTypes(actorTypes):
    result = {}
    for name, actorType in actorTypes.iteritems():
        actorTypeNew = _resolveType(actorTypes, name, actorType, set())
        result[name] = actorTypeNew
    return result

# We wouldn't need this if different entries could overwrite each other while loading each dependency. Since it is a list, rather than a dict, they currently can not
def _deleteOld(prefix, ids_dict, itemOld):
    del ids_dict[prefix][itemOld["id"]]
    idStr = itemOld.get("idStr")
    if not idStr:
        return
    if idStr in ids_dict[prefix]:
        del ids_dict[prefix][idStr]
    namespace = itemOld.get("namespace")
    if not namespace:
        return
    namespacedId = "%s:%s" % (namespace, idStr)
    if namespacedId in ids_dict[prefix]:
        del ids_dict[prefix][namespacedId]

def _addItem(data, prefix, namespace, defs_dict, ids_dict, autobuilds, item):
    # pcm1k - this should handle extra item in "data" like how MCMaterials does it
    _name = item.get("_name", item.get("idStr", str(item["id"])))
    entry_name = MCEditDefsIds.formatDefId(prefix, _name)

    itemOld = defs_dict.get(entry_name)
    if itemOld:
        _deleteOld(prefix, ids_dict, itemOld)

    defs_dict[entry_name] = item
    if prefix not in ids_dict:
        ids_dict[prefix] = {}
    # pcm1k - storing ids_dict[prefix][_name] kinda makes storing defs_dict[entry_name] redundant
#    ids_dict[prefix][item["id"]] = ids_dict[prefix][_name] = entry_name
    ids_dict[prefix][item["id"]] = entry_name
    idStr = item.get("idStr")
    if idStr:
        if namespace:
            namespacedId = "%s:%s" % (namespace, idStr)
            ids_dict[prefix][namespacedId] = entry_name
            item["namespace"] = namespace
        if not namespace or namespace == "minecraft":
            ids_dict[prefix][idStr] = entry_name

    if "_name" not in item:
        item["_name"] = _name
#    if "idStr" not in item:
#        item["idStr"] = _name

    fullid = item["id"]
    if "actorType" in item and "actorTypesRes" in defs_dict:
        fullid |= _resolveType(defs_dict["actorTypesRes"], "", item["actorType"], set())
    item["fullid"] = fullid

    for a_name, a_value in autobuilds.iteritems():
        try:
            # this uses "data", so don't remove it
            # pcm1k - I would rather not store code in JSON
            v = eval(a_value)
#                 print "###", a_name, a_value, v
            defs_dict[entry_name][a_name] = eval(a_value)
            ids_dict[v] = entry_name
        except Exception as e:
            log.error('An error occurred while autobuilding definitions %s (value: "%s": %s' % (a_name, a_value, e))

def _parseData(data, prefix, namespace, defs_dict, ids_dict):
    """Parse the JSON data and build objects accordingly.
    :data: JSON data.
    :prefix: unicode: the prefix to be used, basically 'blocks', 'entities' or 'tileentities'.
    :defs_dict: dict: the object to be populated with definitions; basically 'MCEDIT_DEFS' dict.
    :ids_dict: dict: the object to be populated with IDs; basically 'MCEDIT_IDS' dict."""
    # Find if "autobuild" items are defined
    autobuilds = _parseAutobuilds(data, prefix)

    for definition, value in data.iteritems():
        if definition == prefix:
            # We're parsing the block/entity/whatever data
            for item in value:
                _addItem(data, prefix, namespace, defs_dict, ids_dict, autobuilds, item)
        else:
            # Build extra info in other defs
            defs_dict[definition] = value
            # "actorTypes" taken from https://mojang.github.io/bedrock-protocol-docs/html/enums.html
            if definition == "actorTypes":
                defs_dict["actorTypesRes"] = _resolveTypes(value)

def _loadJsonData(jsonPath, fileFuncs, timestamps=None):
    data = None
    try:
        with fileFuncs.openRead(jsonPath) as fp:
            data = json.load(fp)
        if timestamps is not None:
            statResult = fileFuncs.stat(jsonPath)
            if statResult is not None:
                timestamps[jsonPath] = statResult.st_mtime
    except Exception as e:
        log.error("Could not load data from %s" % jsonPath)
        log.error("Error is: %s" % e)
        raise
    return data

def _loadDeps(jsonName, namespace, platformDir, defsIds, fileFuncs, data, prefix):
    deps = [data]
    depData = data
    ver = defsIds.version
    while "load" in depData:
        log.info('Found dependency for %s %s "%s"' % (defsIds.platform, ver, prefix))
        ver = depData["load"]
        # don't actually include the "load"
        del depData["load"]

        jsonPath2 = fileFuncs.join(platformDir, ver, namespace, jsonName)
        if not fileFuncs.isfile(jsonPath2):
            log.error("Could not find %s" % jsonPath2)
            return deps
        depData = _loadJsonData(jsonPath2, fileFuncs, timestamps=defsIds.timestamps)
        deps.append(depData)
    return deps

def _handleJson(jsonName, namespace, platformDir, defsIds, fileFuncs):
    log.info("Found %s" % jsonName)
    jsonPath = fileFuncs.join(platformDir, defsIds.version, namespace, jsonName)
    data = _loadJsonData(jsonPath, fileFuncs, timestamps=defsIds.timestamps)
    # We use here names coming from the 'minecraft:name_of_the_stuff' ids
    # The second part of the name is present in the first file used (for MC 1.11) in the 'idStr' value).
    # The keys of MCEDIT_DEFS are built by concatenating the file base name and the idStr
    # References to MCEDIT_DEFS elements are stored in MCEDIT_IDS dict.
    # If an element "load" is defined in the JSON data, it must be a string corresponding to another game version.
    # The corresponding file will be loaded before parsing the data.
    log.info("Loading...")
    prefix = os.path.splitext(jsonName)[0]
    deps = _loadDeps(jsonName, namespace, platformDir, defsIds, fileFuncs, data, prefix)
    allData = {}
    if len(deps) > 0:
        log.info("Loading definitions dependencies")
    for depData in reversed(deps):
        #allData.update(depData)
        updateRecursive(allData, depData)
    #allData.update(data)
    if namespace.startswith("_"):
        namespace = ""
    _parseData(allData, prefix, namespace, defsIds.mcedit_defs, defsIds.mcedit_ids)
    defsIds.jsonDict.update(allData)
    log.info("Done")

NAMESPACE_FILTER = re.compile("[^-.0-9_a-z]")

def _loadDefsIds(platformDir, platform, version, fileFuncs, timestamps=False):
    """Load the whole files from mcver directory.
    :version: str/unicode: the game version for which the resources will be loaded.
    :timestamps: bool: whether to also return the loaded file timestamp."""
    log.info("Loading resources for MC {} {}".format(platform, version))
    if timestamps:
        timestampsDict = {}
    else:
        timestampsDict = None

    verDir = fileFuncs.join(platformDir, version)

    defsIds = MCEditDefsIds(platform, version, timestamps=timestampsDict)
    filesLoaded = 0
    if fileFuncs.isdir(verDir):
        for namespace in fileFuncs.listdir(verDir):
            if NAMESPACE_FILTER.search(namespace) is not None:
                continue
            namespaceDir = fileFuncs.join(verDir, namespace)
            if not fileFuncs.isdir(namespaceDir):
                continue
            for jsonName in fileFuncs.listdir(namespaceDir):
                if not jsonName.lower().endswith('.json') or not fileFuncs.isfile(fileFuncs.join(namespaceDir, jsonName)):
                    continue
                _handleJson(jsonName, namespace, platformDir, defsIds, fileFuncs)
                filesLoaded += 1

    if filesLoaded > 0:
        # pcm1k - this actually reports the wrong amount of ids, but who cares
        log.info("Loaded %s defs and %s ids" % (len(defsIds.mcedit_defs), len(defsIds.mcedit_ids)))
    else:
        log.info("MC {} {} resources not found.".format(platform, version))

    if '--dump-defs' in sys.argv:
        dump_f_name = 'defs_ids-{}-{}.json'.format(platform, version)
        log.info("Dumping definitions as JSON data in '%s'." % dump_f_name)
        with open(dump_f_name, 'w') as f:
            f.write("#" * 80)
            f.write("\nDEFS\n")
            f.write(json.dumps(defsIds.mcedit_defs, indent=4))
            f.write("\n\n" + "#" * 80)
            f.write("\nIDS\n")
            f.write(json.dumps(defsIds.mcedit_ids, indent=4))

    return defsIds

class _FileFuncsPkg(object):
    def __init__(self, rootDir):
        self.rootDir = rootDir

    def join(self, a, *p):
        path = a
        for b in p:
            if b.startswith("/"):
                path = b
            elif path == "" or path.endswith("/"):
                path += b
            else:
                path += "/" + b
        return path

    def isfile(self, path):
        return pkg_resources.resource_exists(__name__, path) and not self.isdir(path)

    def isdir(self, s):
        return pkg_resources.resource_isdir(__name__, s)

    def listdir(self, path):
        return pkg_resources.resource_listdir(__name__, path)

    def openRead(self, name):
        return pkg_resources.resource_stream(__name__, name)

    def stat(self, path):
        return None

class _FileFuncsFs(object):
    def __init__(self, rootDir):
        self.rootDir = rootDir

    def join(self, a, *p):
        return os.path.join(a, *p)

    def isfile(self, path):
        return os.path.isfile(path)

    def isdir(self, s):
        return os.path.isfile(s)

    def listdir(self, path):
        return os.listdir(path)

    def openRead(self, name):
        return open(name)

    def stat(self, path):
        return os.stat(path)

_fileFuncs = None

def _getFileFuncs():
    global _fileFuncs
    if _fileFuncs is not None:
        return _fileFuncs
    if pkg_resources.resource_exists(__name__, "mcver"):
        # We're running from source or on Windows using the executable (<<== Not sure...)
        _fileFuncs = _FileFuncsPkg("")
    else:
        # In all other cases, retrieve the file directly from the file system.
        _fileFuncs = _FileFuncsFs(os.environ.get("PYMCLEVEL_YAML_ROOT", "pymclevel"))
    return _fileFuncs

version_defs_ids = {}

class MCEditDefsIds(object):
    """Class to handle MCEDIT_DEFS and MCEDIT_IDS dicts."""

    def __init__(self, platform, version, mcedit_defs=None, mcedit_ids=None, jsonDict=None, timestamps=None):
        self.platform = platform
        self.version = version

        self.mcedit_defs = mcedit_defs if mcedit_defs is not None else {}
        self.mcedit_ids = mcedit_ids if mcedit_ids is not None else {}
        self.jsonDict = jsonDict if jsonDict is not None else {}
        self.timestamps = timestamps if timestamps is not None else {}

        # ensure these are present
        if "blocks" not in self.mcedit_ids:
            self.mcedit_ids["blocks"] = {}
        if "entities" not in self.mcedit_ids:
            self.mcedit_ids["entities"] = {}
        if "items" not in self.mcedit_ids:
            self.mcedit_ids["items"] = {}
        if "tileentities" not in self.mcedit_ids:
            self.mcedit_ids["tileentities"] = {}

    # pcm1k - this works inconsistently and probably not worth it, may remove
    def check_timestamps(self, fileFuncs):
        """Compare the stored and current modification time stamp of files.
        :timestamps: dict: {"file_path": <modification timestamp>}
        Returns a list of files which don't have the same timestamp as stored."""
        result = []
        if not self.timestamps or fileFuncs.stat is None:
            return result
        for file_name, ts in self.timestamps.iteritems():
            statResult = fileFuncs.stat(file_name)
            if statResult is not None and statResult.st_mtime > ts:
                result.append(file_name)
        return result

    def get_id(self, prefix, obj_id, default=None, resolve=False):
        """Retrieves a "defId" from mcedit_ids and then optionally resolves it using mcedit_defs"""
        if obj_id.startswith(self.formatDefId(prefix, "")):
            # it's actually a defId
            if not resolve:
                return obj_id
            return self.get_def(obj_id, default)

        if prefix not in self.mcedit_ids:
            return default
        if obj_id not in self.mcedit_ids[prefix]:
            return default
        defId = self.mcedit_ids[prefix][obj_id]
        if not resolve:
            return defId
        return self.get_def(defId, default)

    def get_def(self, def_id, default=None):
        """Acts like mcedit_defs.get(def_id, default)"""
        return self.mcedit_defs.get(def_id, default)

    @property
    def isEmpty(self):
        return not self.mcedit_defs or not self.mcedit_defs

    @classmethod
    def formatDefId(cls, prefix, defName):
        return "DEF_%s_%s" % (prefix.upper(), defName.upper())

def _findVersionDir(platformDir, platform, version, fileFuncs):
    verDir = fileFuncs.join(platformDir, version)
    if fileFuncs.isdir(verDir):
        return version

    # If version 1.2.4 files are not found, try to load the one for the closest
    # lower version (like 1.2.3 or 1.2).
    log.info("No definitions found for MC {} {}. Trying to find ones for the closest lower version.".format(platform, version))
    verDirs = [entry for entry in fileFuncs.listdir(platformDir) if fileFuncs.isdir(fileFuncs.join(platformDir, entry))]
    if version == VERSION_UNKNOWN:
        # old versions will likely return an unknown version, so it makes sense just to choose the earliest one
        verDirs.sort(key=LooseVersion)
        return verDirs[0]
    elif version == VERSION_LATEST:
        verDirs.sort(key=LooseVersion)
        return verDirs[-1]
    verDirs.append(version)
    verDirs.sort(key=LooseVersion)
    idx = verDirs.index(version) - 1
    if idx < 0:
        # choose the next highest version instead
        idx = 1
    ver = verDirs[idx]
    log.info("Closest lower version found is MC {} {}.".format(platform, ver))
    return ver

def _checkCache(platform, version, checkTimes, fileFuncs):
    if platform not in version_defs_ids or version not in version_defs_ids[platform]:
        return None
    defsIds = version_defs_ids[platform][version]
    while isinstance(defsIds, basestring):
        # resolve pointer to other version
        if defsIds not in version_defs_ids[platform]:
            return None
        defsIds = version_defs_ids[platform][defsIds]
    if checkTimes and defsIds.check_timestamps(fileFuncs):
        return None
    return defsIds

def get_defs_ids(platform, version, checkTimes=True):
    """Create a MCEditDefsIds instance only if one for the game version does not already exists, or a definition file has been changed.
    See MCEditDefsIds doc.
    Returns a MCEditDefsIds instance."""
    fileFuncs = _getFileFuncs()
    defsIds = _checkCache(platform, version, checkTimes, fileFuncs)
    if defsIds is not None:
        return defsIds

    platformDir = fileFuncs.join(fileFuncs.rootDir, "mcver", platform)
    realVersion = _findVersionDir(platformDir, platform, version, fileFuncs)
    if realVersion is None:
        # could not find platformDir at all, create an empty MCEditDefsIds
        defsIds = MCEditDefsIds(platform, version)
        if platform not in version_defs_ids:
            version_defs_ids[platform] = {}
        version_defs_ids[platform][version] = defsIds
        return defsIds

    defsIds = _checkCache(platform, realVersion, checkTimes, fileFuncs)
    if defsIds is not None:
        version_defs_ids[platform][version] = realVersion
        return defsIds

    defsIds = _loadDefsIds(platformDir, platform, realVersion, fileFuncs, timestamps=True)

    if platform not in version_defs_ids:
        version_defs_ids[platform] = {}
    version_defs_ids[platform][realVersion] = defsIds
    version_defs_ids[platform][version] = realVersion

    return defsIds
