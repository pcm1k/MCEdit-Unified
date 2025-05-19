from logging import getLogger
import json
import directories
import os
import shutil
import types
from id_definitions import get_defs_ids, BaseDefs, getBaseDefs, PLATFORM_ALPHA, VERSION_LATEST

logger = getLogger(__name__)


class ItemType(object):
    def __init__(self, id, name, maxdamage=0, damagevalue=0, stacksize=64):
        self.id = id
        self.name = name
        self.maxdamage = maxdamage
        self.damagevalue = damagevalue
        self.stacksize = stacksize

    def __repr__(self):
        return "ItemType({0}, '{1}')".format(self.id, self.name)

    def __str__(self):
        return "ItemType {0}: {1}".format(self.id, self.name)


class Items(BaseDefs):
    def __init__(self, defsIds):
        super(Items, self).__init__(defsIds)

        self.items = {}

        def addItem(idStr, item):
            if not isinstance(idStr, basestring):
                return
            if "stacksize" not in item:
                item["stacksize"] = 64
            if "maxdamage" not in item:
                if "data" in item and len(item["data"]) > 0:
                    item["maxdamage"] = len(item["data"]) - 1
                else:
                    item["maxdamage"] = 0
            if "name" not in item:
                lowestData = None
                for dataKey in item["data"]:
                    dataNum = int(dataKey)
                    if lowestData is None or dataNum < lowestData:
                        lowestData = dataNum
                item["name"] = item["data"][str(lowestData)]["name"]
            self.items[idStr] = item

        for idStr, defId in defsIds.mcedit_ids["items"].iteritems():
            addItem(idStr, defsIds.mcedit_defs[defId])
        for idStr, defId in defsIds.mcedit_ids["blocks"].iteritems():
            addItem(idStr, defsIds.mcedit_defs[defId])

    def findItem(self, id=0, damage=0):
        try:
            item = self.items[id]
        except:
            item = self.findItemID(id)
        if damage <= item["maxdamage"]:
            # pcm1k - this should use the new "data" field
            if isinstance(item["name"], basestring):
                return ItemType(id, item["name"], item["maxdamage"], damage, item["stacksize"])
            else:
                if isinstance(item["name"][damage], basestring):
                    return ItemType(id, item["name"][damage], item["maxdamage"], damage, item["stacksize"])
                else:
                    raise ItemNotFound()
        else:
            raise ItemNotFound()

    def findItemID(self, id):
        for item in self.items:
            itemTemp = self.items[item]
            if not isinstance(itemTemp, types.UnicodeType):
                if itemTemp["id"] == id:
                    return self.items[item]
        raise ItemNotFound()


class ItemNotFound(KeyError):
    pass


class _Items(object):
    def __init__(self, itemDefs=None):
        self._itemDefs = itemDefs

    def __getattr__(self, name):
        return getattr(self._itemDefs, name)

# trying to keep backwards compatibility
items = _Items(Items(get_defs_ids(PLATFORM_ALPHA, VERSION_LATEST)))

del _Items

_itemsCache = {}

def getItemDefs(defsIds, forceNew=False):
    itemDefs = getBaseDefs(defsIds, Items, items._itemDefs, _itemsCache, forceNew)
    # update global
    items._itemDefs = itemDefs
    return itemDefs
