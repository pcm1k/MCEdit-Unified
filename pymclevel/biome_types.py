from id_definitions import BaseTypeSet
from numpy import array

class Biome(object):
    def __init__(self, biomeTypes, biomeID):
        self.biomeTypes = biomeTypes
        self.ID = biomeID

    def __str__(self):
        return "<Biome {name} ({id})>".format(
            name=self.name, id=self.ID)

    def __repr__(self):
        return str(self)

    def __cmp__(self, other):
        if not isinstance(other, Biome):
            return -1
        # pcm1k TODO - compare biomeTypes?
        key = lambda a: a and a.ID
        return cmp(key(self), key(other))

    def __hash__(self):
        return hash(self.ID)

    @property
    def stringID(self):
        biomeData = self.biomeTypes._biomeDataByID.get(self.ID)
        if biomeData is None:
            return "mcedit:unknown_%s" % self.ID
        return biomeData.stringID

    @property
    def name(self):
        biomeData = self.biomeTypes._biomeDataByID.get(self.ID)
        if biomeData is None:
            return "Unknown Biome"
        return biomeData.name


class _BiomeData(object):
    def __init__(self, biomeID, stringID, name):
        self.ID = biomeID
        self.stringID = stringID
        self.name = name


# these are exclusive
id_limit = 256

id_limit_mask = 0xFF


class BiomeTypeSet(BaseTypeSet):
    _typeSetCache = {}

    def __init__(self, defsIds):
        super(BiomeTypeSet, self).__init__(defsIds)

        self.allBiomes = []
        self._biomesByID = {}
        self._biomesByName = {}
        self._biomesByStringID = {}
        self._biomesByDefID = {}

        self._biomeDataByID = {}

        self.topBiomeID = 0

        if defsIds is None:
            return

        for defId, item in defsIds.mcedit_defs.iteritems():
            if not defId.startswith("DEF_BIOMES_"):
                continue
            self._addJsonBiome(item, defId=defId)

    @classmethod
    def getTypeSet(cls, defsIds, forceNew=False):
        return cls._getTypeSet(defsIds, cls._typeSetCache, forceNew=forceNew)

    def biomeWithID(self, biomeID):
        biome = self._biomesByID.get(biomeID)
        if biome is None:
            biome = Biome(self, biomeID)
        return biome

    def biomeWithStringID(self, stringID, create=False):
        stringID = stringID.lower()
        if stringID.startswith("mcedit:unknown_"):
            try:
                biomeID = int(stringID[15:])
            except ValueError:
                return None
            return self.biomeWithID(biomeID)

        if ":" not in stringID:
            stringID = "minecraft:" + stringID

        biome = self._biomesByStringID.get(stringID)
        if biome is not None or not create or self.locked:
            return biome

        biome = self._addDummyBiome(stringID)
        return biome

    def _addDummyBiome(self, stringID, biomeID=None, **kwargs):
        if biomeID is None:
            biomeID = max(self.topBiomeID + 1, id_limit)
        return self._addBiome(biomeID, stringID, stringID, invalid=True, **kwargs)

    def _addJsonBiome(self, jsonDict, defId=None):
        biomeID = jsonDict["id"] & id_limit_mask
        stringID = "%s:%s" % (jsonDict["namespace"], jsonDict["idStr"])
        name = jsonDict["name"]
        self._addBiome(biomeID, stringID, name, defId=defId)

    def _addBiome(self, biomeID, stringID, name, defId=None, invalid=False):
        biomeData = _BiomeData(biomeID, stringID, name)
        biome = Biome(self, biomeID)
        self._biomeDataByID[biomeID] = biomeData
        if not invalid and biomeID not in self._biomesByID:
            self.allBiomes.append(biome)
        self._biomesByID[biomeID] = biome
        self._biomesByName[name] = biome
        self._biomesByStringID[stringID.lower()] = biome
        if bool(defId):
            self._biomesByDefID[defId] = biome

        if biomeID > self.topBiomeID:
            self.topBiomeID = biomeID

        return biome


_nullConversion = lambda b, d: (b, d)


def _convertNoLimit(biomes, destDefs, sourceDefs):
    biomeWithID = sourceDefs.biomeWithID
    biomeWithStringID = destDefs.biomeWithStringID

    biomesNew = array(biomes)
    for pos in zip(*(biomes >= id_limit).nonzero()):
        biome = biomeWithID(biomes[pos])
        biomeNew = biomeWithStringID(biome.stringID, create=True)
        if biomeNew is None:
            continue
        biomesNew[pos] = biomeNew.ID
    return biomesNew


def conversionFunc(destDefs, sourceDefs):
    if destDefs is sourceDefs:
        return _nullConversion
#    destName = destMats.name
#    sourceName = sourceMats.name
#    func = _conversionFuncs.get((destName, sourceName))
#    if func is not None:
#        return func

#    destMats = namedMaterials.get(destName, destMats)
#    sourceMats = namedMaterials.get(sourceName, sourceMats)
#    filters, unavailable = guessFilterTable(sourceMats, destMats)
#    log.debug("")
#    log.debug("%s %s %s", sourceName, "=>", destName)
#    for a, b in [(sourceMats.blockWithID(*a), destMats.blockWithID(*b)) for a, b in filters]:
#        log.debug("{0:20}: \"{1}\"".format('"' + a.name + '"', b.name))

#    log.debug("")
#    log.debug("Missing blocks: %s", [sourceMats.blockWithID(*a).name for a in unavailable])

#    table = _createFilterTable(filters, unavailable, (35, 0))
    func = lambda biomes: _convertNoLimit(biomes, destDefs, sourceDefs)
#    _conversionFuncs[destName, sourceName] = func
    return func


def convertBiomes(destDefs, sourceDefs, biomes):
    if sourceDefs is destDefs:
        return biomes

    return conversionFunc(destDefs, sourceDefs)(biomes)


getBiomeTypes = BiomeTypeSet.getTypeSet
