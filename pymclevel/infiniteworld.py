'''
Created on Jul 22, 2011

@author: Rio
'''
import collections

from datetime import datetime
import itertools
from logging import getLogger
from math import floor
from operator import mul
import os
import random
import shutil
import struct
import time
import traceback
import weakref
import sys

from box import BoundingBox
from entity import Entity, TileEntity, TileTick
from faces import FaceXDecreasing, FaceXIncreasing, FaceZDecreasing, FaceZIncreasing
from level import LightedChunk, EntityLevel, computeChunkHeightMap, MCLevel, ChunkBase, FakeChunk, GAME_PLATFORM_JAVA
from mclevelbase import ChunkMalformed, ChunkNotPresent, ChunkAccessDenied,ChunkConcurrentException,exhaust, PlayerNotFound
import nbt
from numpy import array, clip, maximum, ndenumerate, packbits, pad, unpackbits, zeros
from regionfile import MCRegionFile, ChunkTooBig, ExternalChunk
import logging
from uuid import UUID
from id_definitions import PLATFORM_ALPHA, VERSION_UNKNOWN

log = getLogger(__name__)

DIM_NETHER = -1
DIM_OVERWORLD = 0
DIM_END = 1

__all__ = ["ZeroChunk", "AnvilChunk", "ChunkedLevelMixin", "MCInfdevOldLevel", "MCAlphaDimension"]
_zeros = {}


class SessionLockLost(IOError):
    pass


def ZeroChunk(height=512):
    z = _zeros.get(height)
    if z is None:
        z = _zeros[height] = _ZeroChunk(height)
    return z


class _ZeroChunk(ChunkBase):
    " a placebo for neighboring-chunk routines "

    def __init__(self, height=512):
        zeroChunk = zeros((16, 16, height), 'uint8')
        whiteLight = zeroChunk + 15
        self.Blocks = zeroChunk
        self.BlockLight = whiteLight
        self.SkyLight = whiteLight
        self.Data = zeroChunk


def unpackNibbleArray(dataArray):
    s = dataArray.shape
    unpackedData = zeros((s[0], s[1], s[2] * 2), dtype='uint8')

    unpackedData[:, :, ::2] = dataArray
    unpackedData[:, :, ::2] &= 0xf
    unpackedData[:, :, 1::2] = dataArray
    unpackedData[:, :, 1::2] >>= 4
    return unpackedData


def packNibbleArray(unpackedData):
    packedData = array(unpackedData.reshape(16, 16, unpackedData.shape[2] / 2, 2))
    packedData[..., 1] <<= 4
    packedData[..., 1] |= packedData[..., 0]
    return array(packedData[:, :, :, 1])


def _bitLen(value):
    length = 0
    while value > 0:
        value >>= 1
        length += 1
    return length


def _unpackBlockstates(blockstates, paletteLen, padded=False, minBits=4, shape=(16, 16, 16)):
    # inspiration from https://github.com/MestreLion/mcworldlib/blob/d7e376d78dd8c6952e9450d59dc831daffe134f9/mcworldlib/chunk.py#L160-L188
    bitsPerEntry = max(_bitLen(paletteLen - 1), minBits)
    # convert the array into a bunch of binary values
    result = unpackbits(blockstates[::-1].astype(">i8").view("uint8"))
    if padded:
        # format used in 1.16 and later
        paddingPerEntry = 64 % bitsPerEntry
        # reshape and remove the padding
        result = result.reshape(-1, 64)[:, paddingPerEntry:]
    # reshape to separate each entry
    result = result.reshape(-1, bitsPerEntry)
    # convert the binary values back into integers and reshape it
    result = pad(result, ((0, 0), (64 - bitsPerEntry, 0)), "constant")
    result = packbits(result).view(">i8")[::-1][:reduce(mul, shape, 1)].reshape(shape)
    return result


def _packBlockstates(blockstates, paletteLen, padded=False, minBits=4):
    bitsPerEntry = max(_bitLen(paletteLen - 1), minBits)
    # convert the array into a bunch of binary values
    result = unpackbits(blockstates.ravel()[::-1].astype(">i8").view("uint8")).reshape(-1, 64)
    # remove the bits that are not needed
    result = result[:, -bitsPerEntry:]
    if padded:
        # format used in 1.16 and later
        paddingPerEntry = 64 % bitsPerEntry
        # the number of entries must be divisible by this number
        entriesPerLong = 64 // bitsPerEntry
        paddingEntries = entriesPerLong - len(result) % entriesPerLong
        if paddingEntries > 0:
            result = pad(result, ((paddingEntries, 0), (0, 0)), "constant")
        # reshape without the padding
        result = result.reshape(-1, 64 - paddingPerEntry)
        # add the padding
        result = pad(result, ((0, 0), (paddingPerEntry, 0)), "constant")
    # convert the binary values back into integers
    result = packbits(result).view(">i8")[::-1]
    return result


def _decodeBlockstateNbt(state):
    propertiesTag = state.get("Properties")
    if propertiesTag is not None:
        properties = {key: value.value for key, value in propertiesTag.iteritems()}
    else:
        properties = {}
    return state["Name"].value, properties


def _encodeBlockstateNbt(name, properties):
    result = nbt.TAG_Compound()
    result["Name"] = nbt.TAG_String(name)

    if bool(properties):
        result["Properties"] = propsTag = nbt.TAG_Compound()
        for key, value in properties.iteritems():
            propsTag[key] = nbt.TAG_String(value)
    return result


def _getBlockPaletteTable(palette, mats):
    blockstateToID = mats.blockstate_api.blockstateToID

    # pcm1k TODO - Check to make sure the entry actually get referenced in the block data? Only matters for suboptimal data which probably would not normally happen anyways
    table = zeros((len(palette), 2), dtype="uint16")
    for paletteI, entry in enumerate(palette):
        name, properties = _decodeBlockstateNbt(entry)
        blockID, blockData = blockstateToID(name, properties, create=True)
        if blockID == -1 or blockData == -1:
            continue
        table[paletteI] = (blockID, blockData)
    return table


def _createPaletteBlocks(blocks, data, mats):
    idToBlockstate = mats.blockstate_api.idToBlockstate

    unpackedBlocks = zeros(blocks.shape, dtype="uint16")
    paletteTag = nbt.TAG_List()
    stateCache = {}
    cacheGet = stateCache.get
    for pos, blockID in ndenumerate(blocks):
        blockData = data[pos]
        paletteIndex = cacheGet((blockID, blockData))
        # pcm1k TODO - It may be possible for different blockID, blockData combinations to resolve to the same blockstate. This will result in duplicate entries in the palette. This is probably not super important, however
        if paletteIndex is None:
            stateCache[blockID, blockData] = paletteIndex = len(paletteTag)
            name, properties = idToBlockstate(blockID, blockData)
            paletteTag.append(_encodeBlockstateNbt(name, properties))

        unpackedBlocks[pos] = paletteIndex
    return unpackedBlocks, paletteTag

def _getBiomePaletteTable(palette, biomeTypes):
    biomeWithStringID = biomeTypes.biomeWithStringID

    # pcm1k TODO - Check to make sure the entry actually get referenced in the biome data? Only matters for suboptimal data which probably would not normally happen anyways
    table = zeros(len(palette), dtype="uint16")
    for paletteI, entry in enumerate(palette):
        biome = biomeWithStringID(entry.value, create=True)
        if biome is None:
            continue
        table[paletteI] = biome.ID
    return table


def _createPaletteBiomes(biomes, biomeTypes):
    biomeWithID = biomeTypes.biomeWithID
    TAG_String = nbt.TAG_String

    unpackedBiomes = zeros(biomes.shape, dtype="uint16")
    paletteTag = nbt.TAG_List()
    stateCache = {}
    cacheGet = stateCache.get
    for pos, biomeID in ndenumerate(biomes):
        paletteIndex = cacheGet(biomeID)
        if paletteIndex is None:
            stateCache[biomeID] = paletteIndex = len(paletteTag)
            biome = biomeWithID(biomeID)
            paletteTag.append(TAG_String(biome.stringID))

        unpackedBiomes[pos] = paletteIndex
    return unpackedBiomes, paletteTag


def sanitizeBlocks(chunk):
    # change grass to dirt where needed so Minecraft doesn't flip out and die
    grass = chunk.Blocks == chunk.materials.Grass.ID
    grass |= chunk.Blocks == chunk.materials.Dirt.ID
    badgrass = grass[:, :, 1:] & grass[:, :, :-1]

    chunk.Blocks[:, :, :-1][badgrass] = chunk.materials.Dirt.ID

    # remove any thin snow layers immediately above other thin snow layers.
    # minecraft doesn't flip out, but it's almost never intended
    if hasattr(chunk.materials, "SnowLayer"):
        snowlayer = chunk.Blocks == chunk.materials.SnowLayer.ID
        badsnow = snowlayer[:, :, 1:] & snowlayer[:, :, :-1]

        chunk.Blocks[:, :, 1:][badsnow] = chunk.materials.Air.ID


class BaseChunkData(object):
    def __init__(self, world, chunkPosition, root_tag=None):
        self.chunkPosition = chunkPosition
        self.world = world
        self.root_tag = root_tag
        self.dirty = False


class AnvilChunkData(BaseChunkData):
    """ This is the chunk data backing an AnvilChunk. Chunk data is retained by the MCInfdevOldLevel until its
    AnvilChunk is no longer used, then it is either cached in memory, discarded, or written to disk according to
    resource limits.

    AnvilChunks are stored in a WeakValueDictionary so we can find out when they are no longer used by clients. The
    AnvilChunkData for an unused chunk may safely be discarded or written out to disk. The client should probably
     not keep references to a whole lot of chunks or else it will run out of memory.
    """

    def __init__(self, world, chunkPosition, root_tag=None, create=False):
        super(AnvilChunkData, self).__init__(world, chunkPosition, root_tag=None)

        self.Blocks = zeros((16, 16, world.Height), dtype="uint16")
        self.Data = None
        self.BlockLight = zeros((16, 16, world.Height), dtype="uint8")
        self.SkyLight = zeros((16, 16, world.Height), dtype="uint8")
        self.SkyLight[:] = 15
        self.Biomes = None

        if create:
            self._create()
        else:
            self._load(root_tag)

    def _createAnvilBase(self, entities):
        self.root_tag["Level"] = levelTag = nbt.TAG_Compound()

        cx, cz = self.chunkPosition
        levelTag["xPos"] = nbt.TAG_Int(cx)
        levelTag["zPos"] = nbt.TAG_Int(cz)

        levelTag["LastUpdate"] = nbt.TAG_Long(0)

        if entities:
            levelTag["Entities"] = nbt.TAG_List()
        levelTag["TileEntities"] = nbt.TAG_List()
        levelTag["TileTicks"] = nbt.TAG_List()

    def _createAnvil(self):
        self._createAnvilBase(True)
        levelTag = self.root_tag["Level"]
        levelTag["HeightMap"] = nbt.TAG_Int_Array(zeros((16, 16), dtype=">u4"))
        levelTag["TerrainPopulated"] = nbt.TAG_Byte(1)

        self.Data = zeros((16, 16, self.world.Height), dtype="uint8")
        self.Biomes = zeros((16, 16), dtype="uint8")

    def _createFlat13(self):
        self._createAnvilBase(True)

        self.Data = zeros((16, 16, self.world.Height), dtype="uint16")
        self.Biomes = zeros((16, 16), dtype="uint32")

    def _createFlat15(self, dataVersion):
        self._createAnvilBase(dataVersion < MCInfdevOldLevel.DATA_VERSION_FLAT17)

        self.Data = zeros((16, 16, self.world.Height), dtype="uint16")
        self.Biomes = zeros((16 // 4, 16 // 4, self.world.Height // 4), dtype="uint32")

    def _createFlat18(self):
        levelTag = self.root_tag

        cx, cz = self.chunkPosition
        levelTag["xPos"] = nbt.TAG_Int(cx)
        levelTag["zPos"] = nbt.TAG_Int(cz)
        levelTag["yPos"] = nbt.TAG_Int(self.world.minY // 16)

        levelTag["LastUpdate"] = nbt.TAG_Long(0)

        levelTag["block_entities"] = nbt.TAG_List()
        levelTag["block_ticks"] = nbt.TAG_List()

        self.Data = zeros((16, 16, self.world.Height), dtype="uint16")
        self.Biomes = zeros((16 // 4, 16 // 4, self.world.Height // 4), dtype="uint32")

    def _create(self):
        self.root_tag = chunkTag = nbt.TAG_Compound()

        dataVersion = self.world.dataVersion
        if dataVersion is not None:
            chunkTag["DataVersion"] = nbt.TAG_Int(dataVersion)

        if dataVersion is None:
            self._createAnvil()
        elif dataVersion >= MCInfdevOldLevel.DATA_VERSION_FLAT18:
            self._createFlat18()
        elif dataVersion >= MCInfdevOldLevel.DATA_VERSION_FLAT15:
            self._createFlat15(dataVersion)
        elif dataVersion >= MCInfdevOldLevel.DATA_VERSION_FLAT13:
            self._createFlat13()
        else:
            self._createAnvil()
        self.Biomes[:] = -1

        self.dirty = True

    @staticmethod
    def _getSectionLightsAnvil(section):
        blockLight = section.get("BlockLight")
        if blockLight is None:
            return None
        skyLight = section.get("SkyLight")
        if skyLight is None:
            return None
        blockLight = unpackNibbleArray(blockLight.value.reshape(16, 16, 8)).swapaxes(0, 2)
        skyLight = unpackNibbleArray(skyLight.value.reshape(16, 16, 8)).swapaxes(0, 2)
        return blockLight, skyLight

    def _loadAnvilBase(self, getSectionBlocks):
        self.Biomes[:] = -1

        levelTag = self.root_tag["Level"]
        minY = self.world.minY
        for sec in levelTag.pop("Sections", []):
            y = sec["Y"].value * 16 - minY
            if y < 0 or y >= self.world.Height:
                continue

            blocksAndData = getSectionBlocks(sec)
            if blocksAndData is not None:
                self.Blocks[..., y:y + 16], self.Data[..., y:y + 16] = blocksAndData

            lights = self._getSectionLightsAnvil(sec)
            if lights is not None:
                self.BlockLight[..., y:y + 16], self.SkyLight[..., y:y + 16] = lights

            addTag = sec.get("Add")
            if addTag is not None:
                addTag.value.shape = (16, 16, 8)
                add = unpackNibbleArray(addTag.value)
                self.Blocks[..., y:y + 16] |= (array(add, dtype="uint16") << 8).swapaxes(0, 2)

        biomesTag = levelTag.pop("Biomes", None)
        if biomesTag is not None:
            self.Biomes[:] = biomesTag.value.reshape(self.Biomes.swapaxes(0, -1).shape).swapaxes(0, -1)

    def _loadAnvil(self):
        # pcm1k TODO - this should convert older blocks if applicable
        gameVersionId = self.world.gameVersionId
        if bool(gameVersionId) and gameVersionId[0] >= MCInfdevOldLevel.DATA_VERSION_FLAT13:
            raise NotImplementedError('Loading pre-1.13 chunks in post-1.13 worlds is currently not supported. Please manually upgrade the world using the ingame "optimize world" button.')

        def getSectionBlocks(section):
            blocks = section.get("Blocks")
            if blocks is None:
                return None
            data = section.get("Data")
            if data is None:
                return None
            blocks = blocks.value.reshape(16, 16, 16).swapaxes(0, 2)
            data = unpackNibbleArray(data.value.reshape(16, 16, 8)).swapaxes(0, 2)
            return blocks, data

        self.Data = zeros((16, 16, self.world.Height), dtype="uint8")
        self.Biomes = zeros((16, 16), dtype="uint8")

        self._loadAnvilBase(getSectionBlocks)

    def _loadFlat13(self, dataVersion):
        def getSectionBlocks(section):
            blockStatesTag = section.get("BlockStates")
            if blockStatesTag is None:
                return None
            paletteTag = section.get("Palette")
            if paletteTag is None:
                return None
            unpackedBlocks = _unpackBlockstates(blockStatesTag.value, len(paletteTag),
                padded=dataVersion >= MCInfdevOldLevel.DATA_VERSION_FLAT16).swapaxes(0, 2)
            paletteTable = _getBlockPaletteTable(paletteTag, self.materials)
            blocksAndData = paletteTable[unpackedBlocks]
            return blocksAndData[..., 0], blocksAndData[..., 1]

        self.Data = zeros((16, 16, self.world.Height), dtype="uint16")
        self.Biomes = zeros((16 // 4, 16 // 4, self.world.Height // 4)
            if dataVersion >= MCInfdevOldLevel.DATA_VERSION_FLAT15 else (16, 16), dtype="uint32")

        self._loadAnvilBase(getSectionBlocks)

    def _loadFlat18(self):
        def getSectionBlocks(section):
            blockStatesTag = section.get("block_states")
            if blockStatesTag is None:
                return None
            paletteTag = blockStatesTag.get("palette")
            if paletteTag is None:
                return None
            paletteTable = _getBlockPaletteTable(paletteTag, self.materials)
            dataTag = blockStatesTag.get("data")
            if dataTag is None:
                unpackedBlocks = zeros((16, 16, 16), dtype="uint16")
            else:
                unpackedBlocks = _unpackBlockstates(dataTag.value, len(paletteTag),
                    padded=True).swapaxes(0, 2)
            blocksAndData = paletteTable[unpackedBlocks]
            return blocksAndData[..., 0], blocksAndData[..., 1]

        def getSectionBiomes(section):
            biomesTag = section.get("biomes")
            if biomesTag is None:
                return None
            paletteTag = biomesTag.get("palette")
            if paletteTag is None:
                return None
            paletteTable = _getBiomePaletteTable(paletteTag, self.world.biomeTypes)
            dataTag = biomesTag.get("data")
            if dataTag is None:
                unpackedBiomes = zeros((16 // 4, 16 // 4, 16 // 4), dtype="uint16")
            else:
                unpackedBiomes = _unpackBlockstates(dataTag.value, len(paletteTag),
                    padded=True, minBits=1, shape=(16 // 4, 16 // 4, 16 // 4)).swapaxes(0, 2)
            return paletteTable[unpackedBiomes]

        self.Data = zeros((16, 16, self.world.Height), dtype="uint16")
        self.Biomes = zeros((16 // 4, 16 // 4, self.world.Height // 4), dtype="uint32")
        self.Biomes[:] = -1

        minY = self.world.minY
        for sec in self.root_tag.pop("sections", []):
            y = sec["Y"].value * 16 - minY
            if y < 0 or y >= self.world.Height:
                continue

            blocksAndData = getSectionBlocks(sec)
            if blocksAndData is not None:
                self.Blocks[..., y:y + 16], self.Data[..., y:y + 16] = blocksAndData

            biomes = getSectionBiomes(sec)
            if biomes is not None:
                self.Biomes[..., y // 4:y // 4 + 16 // 4] = biomes

            lights = self._getSectionLightsAnvil(sec)
            if lights is not None:
                self.BlockLight[..., y:y + 16], self.SkyLight[..., y:y + 16] = lights

    def _load(self, root_tag):
        self.root_tag = root_tag
        dataVersion = root_tag.get("DataVersion")
        if dataVersion is None:
            self._loadAnvil()
        else:
            dataVersion = dataVersion.value
            if dataVersion >= MCInfdevOldLevel.DATA_VERSION_FLAT18:
                self._loadFlat18()
            elif dataVersion >= MCInfdevOldLevel.DATA_VERSION_FLAT13:
                self._loadFlat13(dataVersion)
            else:
                self._loadAnvil()

    def _savedTagDataAnvilBase(self, addSectionBlocks, biomesType):
        sections = nbt.TAG_List()
        append = sections.append
        minY = self.world.minY
        for y in xrange(0, self.world.Height, 16):
            section = nbt.TAG_Compound()

            Blocks = self.Blocks[..., y:y + 16].swapaxes(0, 2)
            Data = self.Data[..., y:y + 16].swapaxes(0, 2)
            BlockLight = self.BlockLight[..., y:y + 16].swapaxes(0, 2)
            SkyLight = self.SkyLight[..., y:y + 16].swapaxes(0, 2)

            if (not Blocks.any() and
                    not BlockLight.any() and
                    (SkyLight == 15).all()):
                continue

            BlockLight = packNibbleArray(BlockLight)
            SkyLight = packNibbleArray(SkyLight)

            addSectionBlocks(section, Blocks, Data)

            section["BlockLight"] = nbt.TAG_Byte_Array(array(BlockLight))
            section["SkyLight"] = nbt.TAG_Byte_Array(array(SkyLight))

            section["Y"] = nbt.TAG_Byte((minY + y) // 16)
            append(section)

        levelTag = self.root_tag["Level"]
        levelTag["Sections"] = sections
        levelTag["Biomes"] = biomesType(self.Biomes.swapaxes(0, -1))
        data = self.root_tag.save(compressed=False)
        del levelTag["Sections"]
        del levelTag["Biomes"]

        return data

    def _savedTagDataAnvil(self):
        def addSectionBlocks(section, blocks, data):
            data = packNibbleArray(data)

            add = blocks >> 8 & 0xF
            if add.any():
                section["Add"] = nbt.TAG_Byte_Array(packNibbleArray(add).astype("uint8"))

            section["Blocks"] = nbt.TAG_Byte_Array(array(blocks, dtype="uint8"))
            section["Data"] = nbt.TAG_Byte_Array(array(data))

        return self._savedTagDataAnvilBase(addSectionBlocks, nbt.TAG_Byte_Array)

    def _savedTagDataFlat13(self, dataVersion):
        def addSectionBlocks(section, blocks, data):
            unpackedBlocks, paletteTag = _createPaletteBlocks(blocks, data, self.materials)
            section["Palette"] = paletteTag
            packedBlocks = _packBlockstates(unpackedBlocks, len(paletteTag),
                padded=dataVersion >= MCInfdevOldLevel.DATA_VERSION_FLAT16)
            section["BlockStates"] = nbt.TAG_Long_Array(packedBlocks)

        return self._savedTagDataAnvilBase(addSectionBlocks, nbt.TAG_Int_Array)

    def _savedTagDataFlat18(self):
        def addSectionBlocks(section, blocks, data):
            section["block_states"] = blockStatesTag = nbt.TAG_Compound()
            unpackedBlocks, paletteTag = _createPaletteBlocks(blocks, data, self.materials)
            blockStatesTag["palette"] = paletteTag
            if len(paletteTag) > 1:
                packedBlocks = _packBlockstates(unpackedBlocks, len(paletteTag),
                    padded=True)
                blockStatesTag["data"] = nbt.TAG_Long_Array(packedBlocks)

        def addSectionBiomes(section, biomes):
            section["biomes"] = biomesTag = nbt.TAG_Compound()
            unpackedBiomes, paletteTag = _createPaletteBiomes(biomes, self.world.biomeTypes)
            biomesTag["palette"] = paletteTag
            if len(paletteTag) > 1:
                packedBiomes = _packBlockstates(unpackedBiomes, len(paletteTag),
                    padded=True, minBits=1)
                biomesTag["data"] = nbt.TAG_Long_Array(packedBiomes)

        sections = nbt.TAG_List()
        append = sections.append
        minY = self.world.minY
        for y in xrange(0, self.world.Height, 16):
            section = nbt.TAG_Compound()

            Blocks = self.Blocks[..., y:y + 16].swapaxes(0, 2)
            Data = self.Data[..., y:y + 16].swapaxes(0, 2)
            BlockLight = self.BlockLight[..., y:y + 16].swapaxes(0, 2)
            SkyLight = self.SkyLight[..., y:y + 16].swapaxes(0, 2)
            Biomes = self.Biomes[..., y // 4:y // 4 + 16 // 4].swapaxes(0, 2)

            BlockLight = packNibbleArray(BlockLight)
            SkyLight = packNibbleArray(SkyLight)

            addSectionBlocks(section, Blocks, Data)
            addSectionBiomes(section, Biomes)

            if BlockLight.any() or (SkyLight != 15).any():
                section["BlockLight"] = nbt.TAG_Byte_Array(array(BlockLight))
                section["SkyLight"] = nbt.TAG_Byte_Array(array(SkyLight))

            section["Y"] = nbt.TAG_Byte((minY + y) // 16)
            append(section)

        self.root_tag["sections"] = sections
        data = self.root_tag.save(compressed=False)
        del self.root_tag["sections"]

        return data

    def savedTagData(self):
        """ does not recalculate any data or light """

        log.debug(u"Saving chunk: {0}".format(self))
        # pcm1k TODO - this should either be removed or be optional
#        sanitizeBlocks(self)

        dataVersion = self.world.dataVersion
        if dataVersion is None:
            data = self._savedTagDataAnvil()
        else:
            # pcm1k TODO - properly convert to newer version if needed
            self.root_tag["DataVersion"] = nbt.TAG_Int(dataVersion)
            if dataVersion >= MCInfdevOldLevel.DATA_VERSION_FLAT18:
                data = self._savedTagDataFlat18()
            elif dataVersion >= MCInfdevOldLevel.DATA_VERSION_FLAT13:
                data = self._savedTagDataFlat13(dataVersion)
            else:
                data = self._savedTagDataAnvil()

        log.debug(u"Saved chunk {0}".format(self))
        return data

    @property
    def Entities(self):
        root_tag = self.root_tag
        dataVersion = root_tag.get("DataVersion")
        if dataVersion is not None:
            dataVersion = dataVersion.value
            if dataVersion >= MCInfdevOldLevel.DATA_VERSION_FLAT18:
                entities = root_tag.get("entities")
#                if entities is None:
#                    root_tag["entities"] = entities = nbt.TAG_List()
                return entities

        levelTag = root_tag["Level"]
        entities = levelTag.get("Entities")
#        if entities is None:
#            levelTag["Entities"] = entities = nbt.TAG_List()
        return entities

    @property
    def TileEntities(self):
        root_tag = self.root_tag
        dataVersion = root_tag.get("DataVersion")
        if dataVersion is not None:
            dataVersion = dataVersion.value
            if dataVersion >= MCInfdevOldLevel.DATA_VERSION_FLAT18:
#                return root_tag["block_entities"]
                tileEntities = root_tag.get("block_entities")
                if tileEntities is None:
                    root_tag["block_entities"] = tileEntities = nbt.TAG_List()
                return tileEntities

        levelTag = root_tag["Level"]
#        return levelTag["TileEntities"]
        tileEntities = levelTag.get("TileEntities")
        if tileEntities is None:
            levelTag["TileEntities"] = tileEntities = nbt.TAG_List()
        return tileEntities

    @property
    def TileTicks(self):
        root_tag = self.root_tag
        dataVersion = root_tag.get("DataVersion")
        if dataVersion is not None:
            dataVersion = dataVersion.value
            if dataVersion >= MCInfdevOldLevel.DATA_VERSION_FLAT18:
#                return root_tag["block_ticks"]
                tileTicks = root_tag.get("block_ticks")
                if tileTicks is None:
                    root_tag["block_ticks"] = tileTicks = nbt.TAG_List()
                return tileTicks

        levelTag = root_tag["Level"]
#        return levelTag["TileTicks"]
        tileTicks = levelTag.get("TileTicks")
        if tileTicks is None:
            levelTag["TileTicks"] = tileTicks = nbt.TAG_List()
        return tileTicks

    @property
    def materials(self):
        return self.world.materials


class AnvilEntityData(BaseChunkData):
    def __init__(self, world, chunkPosition, root_tag=None, create=False):
        super(AnvilEntityData, self).__init__(world, chunkPosition, root_tag=None)

        if create:
            self._create()
        else:
            self._load(root_tag)

    def _create(self):
        cx, cz = self.chunkPosition
        self.root_tag = chunkTag = nbt.TAG_Compound()

        dataVersion = self.world.dataVersion
        if dataVersion is None:
            dataVersion = MCInfdevOldLevel.DATA_VERSION_FLAT17
        chunkTag["DataVersion"] = nbt.TAG_Int(dataVersion)
        chunkTag["Position"] = nbt.TAG_Int_Array(array([cx, cz]))
        chunkTag["Entities"] = nbt.TAG_List()

        self.dirty = True

    def _load(self, root_tag):
        self.root_tag = root_tag

    def savedTagData(self):
        log.debug(u"Saving chunk: {0}".format(self))

        # pcm1k TODO - vanilla seems to leave the entity chunk nonexistent if there are no entities in that chunk
        data = self.root_tag.save(compressed=False)

        log.debug(u"Saved chunk {0}".format(self))
        return data


class AnvilChunk(LightedChunk):
    """ This is a 16x16xH chunk in an (infinite) world.
    The properties Blocks, Data, SkyLight, BlockLight, and Heightmap
    are ndarrays containing the respective blocks in the chunk file.
    Each array is indexed [x,z,y].  The Data, Skylight, and BlockLight
    arrays are automatically unpacked from nibble arrays into byte arrays
    for better handling.
    """

    _defsPlatform = PLATFORM_ALPHA
    _fakeChunkHeightMap = FakeChunk.HeightMap

    def __init__(self, chunkData, entityData=None):
        self.world = chunkData.world
        self.chunkPosition = chunkData.chunkPosition
        self.chunkData = chunkData
        self.entityData = entityData

    def savedTagData(self):
        return self.chunkData.savedTagData()

    def __str__(self):
        return u"AnvilChunk, coords:{0}, world: {1}, D:{2}, L:{3}".format(self.chunkPosition, self.world.displayName,
                                                                          self.dirty, self.needsLighting)

    @property
    def needsLighting(self):
        return self.chunkPosition in self.world.chunksNeedingLighting

    @needsLighting.setter
    def needsLighting(self, value):
        if value:
            self.world.chunksNeedingLighting.add(self.chunkPosition)
        else:
            self.world.chunksNeedingLighting.discard(self.chunkPosition)

    def generateHeightMap(self):
        computeChunkHeightMap(self.materials, self.Blocks, self.HeightMap)

    def addEntity(self, entityTag):

        def doubleize(name):
            # This is needed for compatibility with Indev levels. Those levels use TAG_Float for entity motion and pos
            if name in entityTag:
                m = entityTag[name]
                entityTag[name] = nbt.TAG_List([nbt.TAG_Double(i.value) for i in m])

        doubleize("Motion")
        doubleize("Position")

        self.dirty = True
        return super(AnvilChunk, self).addEntity(entityTag)

    def removeEntitiesInBox(self, box):
        self.dirty = True
        return super(AnvilChunk, self).removeEntitiesInBox(box)

    def removeTileEntitiesInBox(self, box):
        self.dirty = True
        return super(AnvilChunk, self).removeTileEntitiesInBox(box)

    def addTileTick(self, tickTag):
        self.dirty = True
        return super(AnvilChunk, self).addTileTick(tickTag)

    def removeTileTicksInBox(self, box):
        self.dirty = True
        return super(AnvilChunk, self).removeTileTicksInBox(box)

    # --- AnvilChunkData accessors ---

    @property
    def root_tag(self):
        return self.chunkData.root_tag

    @property
    def dirty(self):
        return self.chunkData.dirty or (self.entityData is not None and self.entityData.dirty)

    @dirty.setter
    def dirty(self, val):
        self.chunkData.dirty = val
        if self.entityData is not None:
            self.entityData.dirty = val

    # --- Chunk attributes ---

    @property
    def materials(self):
        return self.world.materials

    @property
    def Blocks(self):
        return self.chunkData.Blocks

    @Blocks.setter
    def Blocks(self, value):
        self.chunkData.Blocks = value

    @property
    def Data(self):
        return self.chunkData.Data

    @property
    def SkyLight(self):
        return self.chunkData.SkyLight

    @property
    def BlockLight(self):
        return self.chunkData.BlockLight

    @property
    def Biomes(self):
        return self.chunkData.Biomes

    @property
    def biomesScale(self):
        return 16 // self.Biomes.shape[0]

    @property
    def HeightMap(self):
        # pcm1k TODO - figure this out
        try:
            return self.root_tag["Level"]["HeightMap"].value.reshape(16, 16)
        except KeyError:
            return self._fakeChunkHeightMap

    @property
    def Entities(self):
        chunkEntities = self.chunkData.Entities
        entityData = self.entityData
        if entityData is not None:
            # pcm1k TODO - even if there is an "entities" directory, entities can still be saved in the main chunk if the chunk is considered to be a "proto chunk"
            entityEntities = entityData.root_tag["Entities"]
            # copy from and clear chunkEntities if it is not empty
            if bool(chunkEntities):
                # pcm1k TODO - we should do this the other way around if the chunk is considered to be a "proto chunk"
                entityEntities.extend(chunkEntities)
                del chunkEntities[:]
                self.dirty = True
            return entityEntities

        return chunkEntities

    @property
    def TileEntities(self):
        return self.chunkData.TileEntities

    @property
    def TileTicks(self):
        return self.chunkData.TileTicks

    @property
    def TerrainPopulated(self):
        try:
            return self.root_tag["Level"]["TerrainPopulated"].value
        except KeyError:
            # no longer relevant for 1.13 and later, I believe
            return True

    @TerrainPopulated.setter
    def TerrainPopulated(self, val):
        """True or False. If False, the game will populate the chunk with
        ores and vegetation on next load"""
        try:
            self.root_tag["Level"]["TerrainPopulated"].value = val
        except KeyError:
            # no longer relevant for 1.13 and later, I believe
            return
        self.dirty = True


base36alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"


def decbase36(s):
    return int(s, 36)


def base36(n):
    global base36alphabet

    n = int(n)
    if 0 == n:
        return '0'
    neg = ""
    if n < 0:
        neg = "-"
        n = -n

    work = []

    while n:
        n, digit = divmod(n, 36)
        work.append(base36alphabet[digit])

    return neg + ''.join(reversed(work))


class ChunkedLevelMixin(MCLevel):
    def blockLightAt(self, x, y, z):
        '''
        Gets the light value of the block at the specified X, Y, Z coordinates

        :param x: The X block coordinate
        :type x: int
        :param y: The Y block coordinate
        :type y: int
        :param z: The Z block coordinate
        :type z: int
        :return: The light value or 0 if the Y coordinate is above the maximum height limit or below 0
        :rtype: int
        '''
        if y < self.minY or y >= self.maxY:
            return 0
        zc = z >> 4
        xc = x >> 4

        xInChunk = x & 0xf
        zInChunk = z & 0xf
        ch = self.getChunk(xc, zc)

        return ch.BlockLight[xInChunk, zInChunk, y - self.minY]

    def setBlockLightAt(self, x, y, z, newLight):
        '''
        Sets the light value of the block at the specified X, Y, Z coordinates

        :param x: The X block coordinate
        :type x: int
        :param y: The Y block coordinate
        :type y: int
        :param z: The Z block coordinate
        :type z: int
        :param newLight: The desired light value
        :type newLight: int
        :return: Returns 0 if the Y coordinate is above the maximum height limit or below 0. Doesn't return anything otherwise
        :rtype: int
        '''
        if y < self.minY or y >= self.maxY:
            return 0
        zc = z >> 4
        xc = x >> 4

        xInChunk = x & 0xf
        zInChunk = z & 0xf

        ch = self.getChunk(xc, zc)
        ch.BlockLight[xInChunk, zInChunk, y - self.minY] = newLight
        ch.chunkChanged(False)

    def blockDataAt(self, x, y, z):
        '''
        Gets the data value of the block at the specified X, Y, Z coordinates

        :param x: The X block coordinate
        :type x: int
        :param y: The Y block coordinate
        :type y: int
        :param z: The Z block coordinate
        :type z: int
        :return: The data value of the block or 0 if the Y coordinate is above the maximum height limit or below 0
        :rtype: int
        '''
        if y < self.minY or y >= self.maxY:
            return 0
        zc = z >> 4
        xc = x >> 4

        xInChunk = x & 0xf
        zInChunk = z & 0xf

        try:
            ch = self.getChunk(xc, zc)
        except ChunkNotPresent:
            return 0

        return ch.Data[xInChunk, zInChunk, y - self.minY]

    def setBlockDataAt(self, x, y, z, newdata):
        '''
        Sets the data value of the block at the specified X, Y, Z coordinates

        :param x: The X block coordinate
        :type x: int
        :param y: The Y block coordinate
        :type y: int
        :param z: The Z block coordinate
        :type z: int
        :param newdata: The desired data value
        :type newData: int
        :return: Returns 0 if the Y coordinate is above the maximum height limit or below 0 or the chunk doesn't exist. Doesn't return anything otherwise
        :rtype: int
        '''
        if y < self.minY or y >= self.maxY:
            return 0
        zc = z >> 4
        xc = x >> 4

        xInChunk = x & 0xf
        zInChunk = z & 0xf

        try:
            ch = self.getChunk(xc, zc)
        except ChunkNotPresent:
            return 0

        ch.Data[xInChunk, zInChunk, y - self.minY] = newdata
        ch.dirty = True
        ch.needsLighting = True

    def blockAt(self, x, y, z):
        """returns 0 for blocks outside the loadable chunks.  automatically loads chunks."""
        if y < self.minY or y >= self.maxY:
            return 0

        zc = z >> 4
        xc = x >> 4
        xInChunk = x & 0xf
        zInChunk = z & 0xf

        try:
            ch = self.getChunk(xc, zc)
        except ChunkNotPresent:
            return 0
        return ch.Blocks[xInChunk, zInChunk, y - self.minY]

    def setBlockAt(self, x, y, z, blockID):
        """returns 0 for blocks outside the loadable chunks.  automatically loads chunks."""
        if y < self.minY or y >= self.maxY:
            return 0

        zc = z >> 4
        xc = x >> 4
        xInChunk = x & 0xf
        zInChunk = z & 0xf

        try:
            ch = self.getChunk(xc, zc)
        except ChunkNotPresent:
            return 0

        ch.Blocks[xInChunk, zInChunk, y - self.minY] = blockID
        ch.dirty = True
        ch.needsLighting = True

    def skylightAt(self, x, y, z):

        if y < self.minY or y >= self.maxY:
            return 0
        zc = z >> 4
        xc = x >> 4

        xInChunk = x & 0xf
        zInChunk = z & 0xf

        ch = self.getChunk(xc, zc)

        return ch.SkyLight[xInChunk, zInChunk, y - self.minY]

    def setSkylightAt(self, x, y, z, lightValue):
        if y < self.minY or y >= self.maxY:
            return 0
        zc = z >> 4
        xc = x >> 4

        xInChunk = x & 0xf
        zInChunk = z & 0xf
        yInChunk = y - self.minY

        ch = self.getChunk(xc, zc)
        skyLight = ch.SkyLight

        oldValue = skyLight[xInChunk, zInChunk, yInChunk]

        ch.chunkChanged(False)
        if oldValue < lightValue:
            skyLight[xInChunk, zInChunk, yInChunk] = lightValue
        return oldValue < lightValue

    createChunk = NotImplemented

    def generateLights(self, dirtyChunkPositions=None):
        return exhaust(self.generateLightsIter(dirtyChunkPositions))

    def generateLightsIter(self, dirtyChunkPositions=None):
        """ dirtyChunks may be an iterable yielding (xPos,zPos) tuples
        if none, generate lights for all chunks that need lighting
        """

        startTime = datetime.now()

        if dirtyChunkPositions is None:
            dirtyChunkPositions = self.chunksNeedingLighting
        else:
            dirtyChunkPositions = (c for c in dirtyChunkPositions if self.containsChunk(*c))

        dirtyChunkPositions = sorted(dirtyChunkPositions)

        maxLightingChunks = getattr(self, 'loadedChunkLimit', 400)

        log.info(u"Asked to light {0} chunks".format(len(dirtyChunkPositions)))
        chunkLists = [dirtyChunkPositions]

        def reverseChunkPosition((cx, cz)):
            return cz, cx

        def splitChunkLists(chunkLists):
            newChunkLists = []
            append = newChunkLists.append
            for l in chunkLists:
                # list is already sorted on x position, so this splits into left and right

                smallX = l[:len(l) / 2]
                bigX = l[len(l) / 2:]

                # sort halves on z position
                smallX = sorted(smallX, key=reverseChunkPosition)
                bigX = sorted(bigX, key=reverseChunkPosition)

                # add quarters to list

                append(smallX[:len(smallX) / 2])
                append(smallX[len(smallX) / 2:])

                append(bigX[:len(bigX) / 2])
                append(bigX[len(bigX) / 2:])

            return newChunkLists

        while len(chunkLists[0]) > maxLightingChunks:
            chunkLists = splitChunkLists(chunkLists)

        if len(chunkLists) > 1:
            log.info(u"Using {0} batches to conserve memory.".format(len(chunkLists)))
        # batchSize = min(len(a) for a in chunkLists)
        estimatedTotals = [len(a) * 32 for a in chunkLists]
        workDone = 0

        for i, dc in enumerate(chunkLists):
            log.info(u"Batch {0}/{1}".format(i, len(chunkLists)))

            dc = sorted(dc)
            workTotal = sum(estimatedTotals)
            t = 0
            for c, t, p in self._generateLightsIter(dc):
                yield c + workDone, t + workTotal - estimatedTotals[i], p

            estimatedTotals[i] = t
            workDone += t

        timeDelta = datetime.now() - startTime

        if len(dirtyChunkPositions):
            log.info(u"Completed in {0}, {1} per chunk".format(timeDelta, dirtyChunkPositions and timeDelta / len(
                dirtyChunkPositions) or 0))

        return

    def _generateLightsIter(self, dirtyChunkPositions):
        la = array(self.materials.lightAbsorption)
        clip(la, 1, 15, la)

        dirtyChunks = set(self.getChunk(*cPos) for cPos in dirtyChunkPositions)

        workDone = 0
        workTotal = len(dirtyChunks) * 29

        progressInfo = (u"Lighting {0} chunks".format(len(dirtyChunks)))
        log.info(progressInfo)

        for i, chunk in enumerate(dirtyChunks):
            chunk.chunkChanged()
            yield i, workTotal, progressInfo
            assert chunk.dirty and chunk.needsLighting

        workDone += len(dirtyChunks)
        workTotal = len(dirtyChunks)

        for ch in list(dirtyChunks):
            # relight all blocks in neighboring chunks in case their light source disappeared.
            cx, cz = ch.chunkPosition
            for dx, dz in itertools.product((-1, 0, 1), (-1, 0, 1)):
                try:
                    ch = self.getChunk(cx + dx, cz + dz)
                except (ChunkNotPresent, ChunkMalformed):
                    continue
                dirtyChunks.add(ch)
                ch.dirty = True

        dirtyChunks = sorted(dirtyChunks, key=lambda x: x.chunkPosition)
        workTotal += len(dirtyChunks) * 28

        for i, chunk in enumerate(dirtyChunks):
            chunk.BlockLight[:] = self.materials.lightEmission[chunk.Blocks]
            chunk.dirty = True

        zeroChunk = ZeroChunk(self.Height)
        zeroChunk.BlockLight[:] = 0
        zeroChunk.SkyLight[:] = 0

        startingDirtyChunks = dirtyChunks

        oldLeftEdge = zeros((1, 16, self.Height), 'uint8')
        oldBottomEdge = zeros((16, 1, self.Height), 'uint8')
        oldChunk = zeros((16, 16, self.Height), 'uint8')
        if self.dimNo in (DIM_NETHER, DIM_END):
            lights = ("BlockLight",)
        else:
            lights = ("BlockLight", "SkyLight")
        log.info(u"Dispersing light...")

        def clipLight(light):
            # light arrays are all uint8 by default, so when results go negative
            # they become large instead.  reinterpret as signed int using view()
            # and then clip to range
            light.view('int8').clip(0, 15, light)

        for j, light in enumerate(lights):
            zerochunkLight = getattr(zeroChunk, light)
            newDirtyChunks = list(startingDirtyChunks)

            work = 0

            for i in xrange(14):
                if len(newDirtyChunks) == 0:
                    workTotal -= len(startingDirtyChunks) * (14 - i)
                    break

                progressInfo = u"{0} Pass {1}: {2} chunks".format(light, i, len(newDirtyChunks))
                log.info(progressInfo)

                # propagate light!
                #                for each of the six cardinal directions, figure a new light value for
                #                adjoining blocks by reducing this chunk's light by light absorption and fall off.
                #                compare this new light value against the old light value and update with the maximum.
                #
                #                we calculate all chunks one step before moving to the next step, to ensure all gaps at chunk edges are filled.
                #                we do an extra cycle because lights sent across edges may lag by one cycle.
                #
                #                xxx this can be optimized by finding the highest and lowest blocks
                #                that changed after one pass, and only calculating changes for that
                #                vertical slice on the next pass. newDirtyChunks would have to be a
                #                list of (cPos, miny, maxy) tuples or a cPos : (miny, maxy) dict

                newDirtyChunks = set(newDirtyChunks)
                newDirtyChunks.discard(zeroChunk)

                dirtyChunks = sorted(newDirtyChunks, key=lambda x: x.chunkPosition)

                newDirtyChunks = list()
                append = newDirtyChunks.append

                for chunk in dirtyChunks:
                    (cx, cz) = chunk.chunkPosition
                    neighboringChunks = {}

                    for dir, dx, dz in ((FaceXDecreasing, -1, 0),
                                        (FaceXIncreasing, 1, 0),
                                        (FaceZDecreasing, 0, -1),
                                        (FaceZIncreasing, 0, 1)):
                        try:
                            neighboringChunks[dir] = self.getChunk(cx + dx, cz + dz)
                        except (ChunkNotPresent, ChunkMalformed):
                            neighboringChunks[dir] = zeroChunk
                        neighboringChunks[dir].dirty = True

                    chunkLa = la[chunk.Blocks]
                    chunkLight = getattr(chunk, light)
                    oldChunk[:] = chunkLight[:]

                    ### Spread light toward -X

                    nc = neighboringChunks[FaceXDecreasing]
                    ncLight = getattr(nc, light)
                    oldLeftEdge[:] = ncLight[15:16, :, :]  # save the old left edge

                    # left edge
                    newlight = (chunkLight[0:1, :, :] - la[nc.Blocks[15:16, :, :]])
                    clipLight(newlight)

                    maximum(ncLight[15:16, :, :], newlight, ncLight[15:16, :, :])

                    # chunk body
                    newlight = (chunkLight[1:16, :, :] - chunkLa[0:15, :, :])
                    clipLight(newlight)

                    maximum(chunkLight[0:15, :, :], newlight, chunkLight[0:15, :, :])

                    # right edge
                    nc = neighboringChunks[FaceXIncreasing]
                    ncLight = getattr(nc, light)

                    newlight = ncLight[0:1, :, :] - chunkLa[15:16, :, :]
                    clipLight(newlight)

                    maximum(chunkLight[15:16, :, :], newlight, chunkLight[15:16, :, :])

                    ### Spread light toward +X

                    # right edge
                    nc = neighboringChunks[FaceXIncreasing]
                    ncLight = getattr(nc, light)

                    newlight = (chunkLight[15:16, :, :] - la[nc.Blocks[0:1, :, :]])
                    clipLight(newlight)

                    maximum(ncLight[0:1, :, :], newlight, ncLight[0:1, :, :])

                    # chunk body
                    newlight = (chunkLight[0:15, :, :] - chunkLa[1:16, :, :])
                    clipLight(newlight)

                    maximum(chunkLight[1:16, :, :], newlight, chunkLight[1:16, :, :])

                    # left edge
                    nc = neighboringChunks[FaceXDecreasing]
                    ncLight = getattr(nc, light)

                    newlight = ncLight[15:16, :, :] - chunkLa[0:1, :, :]
                    clipLight(newlight)

                    maximum(chunkLight[0:1, :, :], newlight, chunkLight[0:1, :, :])

                    zerochunkLight[:] = 0  # zero the zero chunk after each direction
                    # so the lights it absorbed don't affect the next pass

                    # check if the left edge changed and dirty or compress the chunk appropriately
                    if (oldLeftEdge != ncLight[15:16, :, :]).any():
                        # chunk is dirty
                        append(nc)

                    ### Spread light toward -Z

                    # bottom edge
                    nc = neighboringChunks[FaceZDecreasing]
                    ncLight = getattr(nc, light)
                    oldBottomEdge[:] = ncLight[:, 15:16, :]  # save the old bottom edge

                    newlight = (chunkLight[:, 0:1, :] - la[nc.Blocks[:, 15:16, :]])
                    clipLight(newlight)

                    maximum(ncLight[:, 15:16, :], newlight, ncLight[:, 15:16, :])

                    # chunk body
                    newlight = (chunkLight[:, 1:16, :] - chunkLa[:, 0:15, :])
                    clipLight(newlight)

                    maximum(chunkLight[:, 0:15, :], newlight, chunkLight[:, 0:15, :])

                    # top edge
                    nc = neighboringChunks[FaceZIncreasing]
                    ncLight = getattr(nc, light)

                    newlight = ncLight[:, 0:1, :] - chunkLa[:, 15:16, :]
                    clipLight(newlight)

                    maximum(chunkLight[:, 15:16, :], newlight, chunkLight[:, 15:16, :])

                    ### Spread light toward +Z

                    # top edge
                    nc = neighboringChunks[FaceZIncreasing]

                    ncLight = getattr(nc, light)

                    newlight = (chunkLight[:, 15:16, :] - la[nc.Blocks[:, 0:1, :]])
                    clipLight(newlight)

                    maximum(ncLight[:, 0:1, :], newlight, ncLight[:, 0:1, :])

                    # chunk body
                    newlight = (chunkLight[:, 0:15, :] - chunkLa[:, 1:16, :])
                    clipLight(newlight)

                    maximum(chunkLight[:, 1:16, :], newlight, chunkLight[:, 1:16, :])

                    # bottom edge
                    nc = neighboringChunks[FaceZDecreasing]
                    ncLight = getattr(nc, light)

                    newlight = ncLight[:, 15:16, :] - chunkLa[:, 0:1, :]
                    clipLight(newlight)

                    maximum(chunkLight[:, 0:1, :], newlight, chunkLight[:, 0:1, :])

                    zerochunkLight[:] = 0

                    if (oldBottomEdge != ncLight[:, 15:16, :]).any():
                        append(nc)

                    newlight = (chunkLight[:, :, :-1] - chunkLa[:, :, 1:])
                    clipLight(newlight)
                    maximum(chunkLight[:, :, 1:], newlight, chunkLight[:, :, 1:])

                    newlight = (chunkLight[:, :, 1:] - chunkLa[:, :, :-1])
                    clipLight(newlight)
                    maximum(chunkLight[:, :, :-1], newlight, chunkLight[:, :, :-1])

                    if (oldChunk != chunkLight).any():
                        append(chunk)

                    work += 1
                    yield workDone + work, workTotal, progressInfo

                workDone += work
                workTotal -= len(startingDirtyChunks)
                workTotal += work

                work = 0

        for ch in startingDirtyChunks:
            ch.needsLighting = False


def TagProperty(tagName, tagType, default_or_func=None):
    def getter(self):
        if tagName not in self.root_tag["Data"]:
            if hasattr(default_or_func, "__call__"):
                default = default_or_func(self)
            else:
                default = default_or_func

            self.root_tag["Data"][tagName] = tagType(default)
        return self.root_tag["Data"][tagName].value

    def setter(self, val):
        self.root_tag["Data"][tagName] = tagType(value=val)

    return property(getter, setter)


class AnvilWorldFolder(object):
    def __init__(self, filename, regionFolder="region"):
        if not os.path.exists(filename):
            os.mkdir(filename)

        elif not os.path.isdir(filename):
            raise IOError("AnvilWorldFolder: Not a folder: %s" % filename)

        self.filename = filename
        self.regionFolder = regionFolder
        self.regionFiles = {}

    # --- File paths ---

    def getFilePath(self, path):
        path = path.replace("/", os.path.sep)
        return os.path.join(self.filename, path)

    def getFolderPath(self, path, checksExists=True, generation=False):
        # pcm1k TODO - why "##MCEDIT.TEMP##"?
        if checksExists and not os.path.exists(self.filename) and "##MCEDIT.TEMP##" in path and not generation:
            raise IOError("The file does not exist")
        path = self.getFilePath(path)
        if not os.path.exists(path) and "players" not in path:
            os.makedirs(path)

        return path

    # --- Region files ---

    def getRegionFilename(self, rx, rz):
        return os.path.join(self.getFolderPath(self.regionFolder, False), "r.%s.%s.%s" % (rx, rz, "mca"))

    def getRegionFile(self, rx, rz):
        regionFile = self.regionFiles.get((rx, rz))
        if regionFile:
            return regionFile
        regionFile = MCRegionFile(self.getRegionFilename(rx, rz), (rx, rz))
        self.regionFiles[rx, rz] = regionFile
        return regionFile

    def getRegionForChunk(self, cx, cz):
        rx = cx >> 5
        rz = cz >> 5
        return self.getRegionFile(rx, rz)

    def closeRegions(self):
        for rf in self.regionFiles.values():
            rf.close()

        self.regionFiles = {}

    # --- Chunks and chunk listing ---

    @staticmethod
    def tryLoadRegionFile(filepath):
        filename = os.path.basename(filepath)
        bits = filename.split('.')
        if len(bits) < 4 or bits[0] != 'r' or bits[3] != "mca":
            return None

        try:
            rx, rz = map(int, bits[1:3])
        except ValueError:
            return None

        return MCRegionFile(filepath, (rx, rz))

    def findRegionFiles(self):
        regionDir = self.getFolderPath(self.regionFolder, generation=True)

        regionFiles = os.listdir(regionDir)
        for filename in regionFiles:
            yield os.path.join(regionDir, filename)

    def listChunks(self):
        chunks = set()

        for filepath in self.findRegionFiles():
            regionFile = self.tryLoadRegionFile(filepath)
            if regionFile is None:
                continue

            if regionFile.offsets.any():
                rx, rz = regionFile.regionCoords
                self.regionFiles[rx, rz] = regionFile

                for index, offset in enumerate(regionFile.offsets):
                    if offset:
                        cx = index & 0x1f
                        cz = index >> 5

                        cx += rx << 5
                        cz += rz << 5

                        chunks.add((cx, cz))
            else:
                log.info(u"Removing empty region file {0}".format(filepath))
                regionFile.close()
                os.unlink(regionFile.path)

        return chunks

    def containsChunk(self, cx, cz):
        rx = cx >> 5
        rz = cz >> 5
        if not os.path.exists(self.getRegionFilename(rx, rz)):
            return False

        return self.getRegionForChunk(cx, cz).containsChunk(cx, cz)

    def deleteChunk(self, cx, cz):
        r = cx >> 5, cz >> 5
        rf = self.getRegionFile(*r)
        if rf:
            rf.setOffset(cx & 0x1f, cz & 0x1f, 0)
            if (rf.offsets == 0).all():
                rf.close()
                os.unlink(rf.path)
                del self.regionFiles[r]

    def readChunk(self, cx, cz):
        if not self.containsChunk(cx, cz):
            raise ChunkNotPresent((cx, cz))

        try:
            return self.getRegionForChunk(cx, cz).readChunk(cx, cz)
        except ExternalChunk:
            # pcm1k TODO - handle the external chunk thing
            raise

    def saveChunk(self, cx, cz, data):
        regionFile = self.getRegionForChunk(cx, cz)
        try:
            regionFile.saveChunk(cx, cz, data)
        except ChunkTooBig:
            # pcm1k TODO - handle the external chunk thing
            raise

    def copyChunkFrom(self, worldFolder, cx, cz):
        fromRF = worldFolder.getRegionForChunk(cx, cz)
        rf = self.getRegionForChunk(cx, cz)
        rf.copyChunkFrom(fromRF, cx, cz)


class MCInfdevOldLevel(ChunkedLevelMixin, EntityLevel):
    '''
    A class that handles the data that is stored in a Minecraft Java level.

    This class is the type of the 'level' parameter that is passed to a filter's :func:`perform` function
    '''
    playersFolder = None

    def __init__(self, filename=None, create=False, random_seed=None, last_played=None, readonly=False, dat_name='level', dataVersion=None):
        """
        Load an Alpha level from the given filename. It can point to either
        a level.dat or a folder containing one. If create is True, it will
        also create the world using the random_seed and last_played arguments.
        If they are none, a random 64-bit seed will be selected for RandomSeed
        and long(time.time() * 1000) will be used for LastPlayed.

        If you try to create an existing world, its level.dat will be replaced.
        """

        self.dat_name = dat_name

        self.playerTagCache = {}
        self.players = []
        assert not (create and readonly)

        self.lockAcquireFuncs = []
        self.lockLoseFuncs = []
        self.initTime = -1

        if os.path.basename(filename) in ("%s.dat" % dat_name, "%s.dat_old" % dat_name):
            filename = os.path.dirname(filename)

        if not os.path.exists(filename):
            if not create:
                raise IOError('File not found')

            os.mkdir(filename)

        if not os.path.isdir(filename):
            raise IOError('File is not a Minecraft Alpha world')

        self.worldFolder = AnvilWorldFolder(filename)
        self.filename = self.worldFolder.getFilePath("%s.dat" % dat_name)
        self.readonly = readonly
        if not readonly:
            self.acquireSessionLock()
            workFolderPath = self.worldFolder.getFolderPath("##MCEDIT.TEMP##")
            if os.path.exists(workFolderPath):
                # xxxxxxx Opening a world a second time deletes the first world's work folder and crashes when the first
                # world tries to read a modified chunk from the work folder. This mainly happens when importing a world
                # into itself after modifying it.
                shutil.rmtree(workFolderPath, True)

            self.unsavedWorkFolder = AnvilWorldFolder(workFolderPath)

        # maps (cx, cz) pairs to AnvilChunk
        self._loadedChunks = weakref.WeakValueDictionary()

        # maps (cx, cz) pairs to AnvilChunkData
        self._loadedChunkData = {}
        self._loadedEntityData = None
        # used to keep references to recent chunks to prevent them from unloading too early
        self.recentChunks = collections.deque(maxlen=20)

        self.chunksNeedingLighting = set()
        self._allChunks = None
        self.dimensions = {}

        self.loadLevelDat(create, random_seed, last_played, dataVersion=dataVersion)

        assert self.version == self.VERSION_ANVIL, "Pre-Anvil world formats are not supported (for now)"

        dataVersion = self.dataVersion

        def setupVersion():
            if dataVersion is None or dataVersion < self.DATA_VERSION_FLAT17:
                return
            self.worldEntityFolder = AnvilWorldFolder(filename, regionFolder="entities")
            if not readonly:
                self.unsavedEntityFolder = AnvilWorldFolder(workFolderPath, regionFolder="entities")
            self._loadedEntityData = {}
            if dataVersion < self.DATA_VERSION_FLAT18:
                return
            if self.dimNo == DIM_OVERWORLD:
                self.Height = 384
                self.minY = -64
        setupVersion()

        if not readonly:
            if dat_name == 'level':
                playersFolder = self.worldFolder.getFolderPath("playerdata")
                if os.path.exists(playersFolder):
                    self.playersFolder = playersFolder
                    self.oldPlayerFolderFormat = False
                else:
                    # pcm1k TODO - apparently only the "playerdata" folder uses UUIDs, so the below code won't even work for that
                    playersFolder = self.worldFolder.getFolderPath("players")
                    if os.path.exists(playersFolder) and bool(os.listdir(playersFolder)):
                        self.playersFolder = playersFolder
                        self.oldPlayerFolderFormat = True
                self.players = [x[:-4] for x in os.listdir(self.playersFolder) if x.endswith(".dat")]
                for player in self.players:
                    try:
                        UUID(player, version=4)
                    except ValueError:
                        # pcm1k TODO - Why does this need to be 3 times? Also "UnicodeEncode" is not a thing apparently
#                        try:
#                            print "{0} does not seem to be in a valid UUID format".format(player)
#                        except UnicodeEncode:
#                            try:
                        print u"{0} does not seem to be in a valid UUID format".format(player)
#                            except UnicodeError:
#                                print "{0} does not seem to be in a valid UUID format".format(repr(player))
                        self.players.remove(player)
                if "Player" in self.root_tag["Data"]:
                    self.players.append("Player")

                self.preloadDimensions()

    # --- Load, save, create ---

    def _create(self, filename, random_seed, last_played, dataVersion):

        # create a new level
        root_tag = nbt.TAG_Compound()
        root_tag["Data"] = dataTag = nbt.TAG_Compound()
        dataTag["SpawnX"] = nbt.TAG_Int(0)
        dataTag["SpawnY"] = nbt.TAG_Int(2)
        dataTag["SpawnZ"] = nbt.TAG_Int(0)

        if last_played is None:
            last_played = long(time.time() * 1000)
        if random_seed is None:
            random_seed = long(random.random() * 0xffffffffffffffffL) - 0x8000000000000000L

        self.root_tag = root_tag
        dataTag["version"] = nbt.TAG_Int(self.VERSION_ANVIL)

        if dataVersion is not None:
            dataTag["Version"] = versionTag = nbt.TAG_Compound()
            versionTag["Id"] = nbt.TAG_Int(dataVersion)

        self.LastPlayed = long(last_played)
        self.RandomSeed = long(random_seed)
        self.SizeOnDisk = 0
        self.Time = 1
        self.DayTime = 1
        # pcm1k TODO - the filename argument is not used
        self.LevelName = os.path.basename(self.worldFolder.filename)

        # ## if singleplayer:

        self.createPlayer("Player")

    def acquireSessionLock(self):
        lock_file = self.worldFolder.getFilePath("session.lock")
        self.initTime = int(time.time() * 1000)
        with file(lock_file, "wb") as f:
            f.write(struct.pack(">q", self.initTime))
            f.flush()
            os.fsync(f.fileno())

        for function in self.lockAcquireFuncs:
            function()

    def setSessionLockCallback(self, acquire_func, lose_func):
        self.lockAcquireFuncs.append(acquire_func)
        self.lockLoseFuncs.append(lose_func)

    def checkSessionLock(self):
        if self.readonly:
            raise SessionLockLost("World is opened read only.")

        lockfile = self.worldFolder.getFilePath("session.lock")
        try:
            (lock, ) = struct.unpack(">q", file(lockfile, "rb").read())
        except struct.error:
            lock = -1
        if lock != self.initTime:
            for func in self.lockLoseFuncs:
                func()
            raise SessionLockLost("Session lock lost. This world is being accessed from another location.")

    def loadLevelDat(self, create=False, random_seed=None, last_played=None, dataVersion=None):

        dat_name = self.dat_name

        if create:
            self._create(self.filename, random_seed, last_played, dataVersion)
            self.saveInPlace()
        else:
            try:
                self.root_tag = nbt.load(self.filename)
            except Exception as e:
                filename_old = self.worldFolder.getFilePath("%s.dat_old"%dat_name)
                log.info("Error loading {1}.dat, trying {1}.dat_old ({0})".format(e, dat_name))
                try:
                    self.root_tag = nbt.load(filename_old)
                    log.info("%s.dat restored from backup."%dat_name)
                    self.saveInPlace()
                except Exception as e:
                    traceback.print_exc()
                    print repr(e)
                    log.info("Error loading %s.dat_old. Initializing with defaults."%dat_name)
                    self._create(self.filename, random_seed, last_played, dataVersion)

    # pcm1k TODO - put loadedChunkData, worldFolder, and unsavedWorkFolder into their own class?
    @staticmethod
    def _saveChunkData(loadedChunkData, worldFolder, unsavedWorkFolder):
        dirtyChunkCount = 0
        for chunk in loadedChunkData.itervalues():
            cx, cz = chunk.chunkPosition
            if chunk.dirty:
                data = chunk.savedTagData()
                dirtyChunkCount += 1
                worldFolder.saveChunk(cx, cz, data)
                chunk.dirty = False
            yield None

        for cx, cz in unsavedWorkFolder.listChunks():
            if (cx, cz) not in loadedChunkData:
                data = unsavedWorkFolder.readChunk(cx, cz)
                worldFolder.saveChunk(cx, cz, data)
                dirtyChunkCount += 1
            yield None

        unsavedWorkFolder.closeRegions()
        shutil.rmtree(unsavedWorkFolder.filename, True)
        if not os.path.exists(unsavedWorkFolder.filename):
            os.mkdir(unsavedWorkFolder.filename)
        yield dirtyChunkCount

    def saveInPlaceGen(self):
        if self.readonly:
            raise IOError("World is opened read only. (%s)"%self.filename)
        self.saving = True
        self.checkSessionLock()

        for level in self.dimensions.itervalues():
            for _ in MCInfdevOldLevel.saveInPlaceGen(level):
                yield

        for dirtyChunkCount in self._saveChunkData(self._loadedChunkData, self.worldFolder, self.unsavedWorkFolder):
            yield
        if self._loadedEntityData is not None:
            for dirtyAdd in self._saveChunkData(self._loadedEntityData, self.worldEntityFolder, self.unsavedEntityFolder):
                yield
            dirtyChunkCount += dirtyAdd

        for path, tag in self.playerTagCache.iteritems():
            tag.save(path)

        if self.playersFolder is not None:
            for file_ in os.listdir(self.playersFolder):
                if file_.endswith(".dat") and file_[:-4] not in self.players:
                    os.remove(os.path.join(self.playersFolder, file_))

        self.playerTagCache.clear()

        self.root_tag.save(self.filename)
        self.saving = False
        log.info(u"Saved {0} chunks (dim {1})".format(dirtyChunkCount, self.dimNo))

    def unload(self):
        """
        Unload all chunks and close all open filehandles.
        """
        if self.saving:
            raise ChunkAccessDenied
        self.worldFolder.closeRegions()
        if not self.readonly:
            self.unsavedWorkFolder.closeRegions()

        self._allChunks = None
        self.recentChunks.clear()
        self._loadedChunks.clear()
        self._loadedChunkData.clear()

        if self._loadedEntityData is not None:
            self.worldEntityFolder.closeRegions()
            if not self.readonly:
                self.unsavedEntityFolder.closeRegions()
            self._loadedEntityData.clear()

    def close(self):
        """
        Unload all chunks and close all open filehandles. Discard any unsaved data.
        """
        self.unload()
        try:
            self.checkSessionLock()
            shutil.rmtree(self.unsavedWorkFolder.filename, True)
            if self._loadedEntityData is not None:
                shutil.rmtree(self.unsavedEntityFolder.filename, True)
        except SessionLockLost:
            pass

    # --- Resource limits ---

    loadedChunkLimit = 400

    # --- Constants ---

    GAMETYPE_SURVIVAL = 0
    GAMETYPE_CREATIVE = 1

    VERSION_MCR = 19132
    VERSION_ANVIL = 19133

    DATA_VERSION_FLAT13 = 1451
    DATA_VERSION_FLAT15 = 2203
    DATA_VERSION_FLAT16 = 2529
    DATA_VERSION_FLAT17 = 2681
    DATA_VERSION_FLAT18 = 2844

    # --- Instance variables  ---

    isInfinite = True
    parentWorld = None
    dimNo = DIM_OVERWORLD
    Height = 256
    Length = 0
    Width = 0
    _bounds = None
    _gamePlatform = GAME_PLATFORM_JAVA
    _defsPlatform = PLATFORM_ALPHA

    # --- NBT Tag variables ---

    SizeOnDisk = TagProperty('SizeOnDisk', nbt.TAG_Long, 0)
    RandomSeed = TagProperty('RandomSeed', nbt.TAG_Long, 0)
    Time = TagProperty('Time', nbt.TAG_Long, 0)  # Age of the world in ticks. 20 ticks per second; 24000 ticks per day.
    DayTime = TagProperty('DayTime', nbt.TAG_Long, 0)
    LastPlayed = TagProperty('LastPlayed', nbt.TAG_Long, lambda self: long(time.time() * 1000))

    LevelName = TagProperty('LevelName', nbt.TAG_String, lambda self: self.displayName)
    GeneratorName = TagProperty('generatorName', nbt.TAG_String, 'default')

    MapFeatures = TagProperty('MapFeatures', nbt.TAG_Byte, 1)

    GameType = TagProperty('GameType', nbt.TAG_Int, 0)  # 0 for survival, 1 for creative

    version = TagProperty('version', nbt.TAG_Int, VERSION_ANVIL)

    # --- World info ---

    def __str__(self):
        return "MCInfdevOldLevel(\"%s\")" % os.path.basename(self.worldFolder.filename)

    @property
    def displayName(self):
        # shortname = os.path.basename(self.filename)
        # if shortname == "level.dat":
        shortname = os.path.basename(os.path.dirname(self.filename))

        return shortname

    def init_scoreboard(self):
        '''
        Creates a scoreboard for the world

        :return: A scoreboard
        :rtype: pymclevel.nbt.TAG_Compound()
        '''
        dataPath = self.worldFolder.getFolderPath("data")
        if os.path.exists(dataPath):
            scoreboardPath = os.path.join(dataPath, "scoreboard.dat")
            if os.path.exists(scoreboardPath):
                return nbt.load(scoreboardPath)

        root_tag = nbt.TAG_Compound()
        root_tag["data"] = dataTag = nbt.TAG_Compound()
        dataTag["Objectives"] = nbt.TAG_List()
        dataTag["PlayerScores"] = nbt.TAG_List()
        dataTag["Teams"] = nbt.TAG_List()
        dataTag["DisplaySlots"] = nbt.TAG_List()
        self.save_scoreboard(root_tag)
        return root_tag

    def save_scoreboard(self, score):
        '''
        Saves the provided scoreboard

        :param score: The scoreboard
        :type score: pymclevel.nbt.TAG_Compound()
        '''
        scoreboardPath = os.path.join(self.worldFolder.getFolderPath("data"), "scoreboard.dat")
        score.save(scoreboardPath)

    def init_player_data(self):
        player_data = {}
        if self.oldPlayerFolderFormat:
            playersFolder = self.worldFolder.getFolderPath("players")
        else:
            playersFolder = self.worldFolder.getFolderPath("playerdata")
        for p in self.players:
            if p == "Player":
                continue
            player_data_file = os.path.join(playersFolder, p + ".dat")
            player_data[p] = nbt.load(player_data_file)
        player_data["Player"] = self.root_tag["Data"]["Player"]

        #player_data = []
        #for p in [x for x in os.listdir(self.playersFolder) if x.endswith(".dat")]:
                #player_data.append(player.Player(self.playersFolder+"\\"+p))
        return player_data

    def save_player_data(self, player_data):
        if self.oldPlayerFolderFormat:
            playersFolder = self.worldFolder.getFolderPath("players")
        else:
            playersFolder = self.worldFolder.getFolderPath("playerdata")
        for p in player_data.keys():
            if p != "Player":
                player_data[p].save(os.path.join(playersFolder, p + ".dat"))
        # pcm1k TODO - what about "Player"?

    @property
    def bounds(self):
        if self._bounds is None:
            self._bounds = self.getWorldBounds()
        return self._bounds

    def getWorldBounds(self):
        if self.chunkCount == 0:
            return BoundingBox((0, 0, 0), (0, 0, 0))

        allChunks = array(list(self.allChunks))
        mincx = (allChunks[:, 0]).min()
        maxcx = (allChunks[:, 0]).max()
        mincz = (allChunks[:, 1]).min()
        maxcz = (allChunks[:, 1]).max()

        origin = (mincx << 4, self.minY, mincz << 4)
        size = ((maxcx - mincx + 1) << 4, self.Height, (maxcz - mincz + 1) << 4)

        return BoundingBox(origin, size)

    @property
    def size(self):
        return self.bounds.size

    # --- Format detection ---

    @classmethod
    def _isLevel(cls, filename):

        if os.path.exists(os.path.join(filename, "chunks.dat")) or os.path.exists(os.path.join(filename, "db")):
            return False  # exclude Pocket Edition folders

        if not os.path.isdir(filename):
            f = os.path.basename(filename)
            if f not in ("level.dat", "level.dat_old"):
                return False
            filename = os.path.dirname(filename)

        files = os.listdir(filename)
        if "db" in files:
            return False
        if "level.dat" in files or "level.dat_old" in files:
            return True

        return False

    @property
    def dataVersion(self):
        version = self.root_tag["Data"].get("Version")
        if version is None:
            return None
        id_ = version.get("Id")
        if id_ is None:
            return None
        return id_.value

    @property
    def gameVersionNumber(self):
        version = self.root_tag["Data"].get("Version")
        if version is None:
            return VERSION_UNKNOWN
        name = version.get("Name")
        if name is None:
            return VERSION_UNKNOWN
        return name.value

    @property
    def gameVersionId(self):
        dataVersion = self.dataVersion
        if dataVersion is None:
            return None
        return [dataVersion]

    # --- Dimensions ---

    def preloadDimensions(self):
        worldDirs = os.listdir(self.worldFolder.filename)

        for dirname in worldDirs:
            if dirname.startswith("DIM"):
                try:
                    dimNo = int(dirname[3:])
                    log.info("Found dimension {0}".format(dirname))
                    dim = MCAlphaDimension(self, dimNo)
                    self.dimensions[dimNo] = dim
                except Exception as e:
                    log.error(u"Error loading dimension {0}: {1}".format(dirname, e))

    def getDimension(self, dimNo):
        if self.dimNo != DIM_OVERWORLD:
            return self.parentWorld.getDimension(dimNo)

        if dimNo in self.dimensions:
            return self.dimensions[dimNo]
        dim = MCAlphaDimension(self, dimNo, create=True)
        self.dimensions[dimNo] = dim
        return dim

    # --- Region I/O ---

    def preloadChunkPositions(self):
        log.info(u"Scanning for regions...")
        self._allChunks = self.worldFolder.listChunks()
        if not self.readonly:
            self._allChunks.update(self.unsavedWorkFolder.listChunks())
        self._allChunks.update(self._loadedChunkData.iterkeys())

    def getRegionForChunk(self, cx, cz):
        return self.worldFolder.getRegionForChunk(cx, cz)

    # --- Chunk I/O ---

    def dirhash(self, n):
        return self.dirhashes[n % 64]

    def _dirhash(self):
        n = self
        n %= 64
        s = u""
        if n >= 36:
            s += u"1"
            n -= 36
        s += u"0123456789abcdefghijklmnopqrstuvwxyz"[n]

        return s

    dirhashes = [_dirhash(n) for n in xrange(64)]

    def _oldChunkFilename(self, cx, cz):
        return self.worldFolder.getFilePath(
            "%s/%s/c.%s.%s.dat" % (self.dirhash(cx), self.dirhash(cz), base36(cx), base36(cz)))

    def extractChunksInBox(self, box, parentFolder):
        for cx, cz in box.chunkPositions:
            if self.containsChunk(cx, cz):
                self.extractChunk(cx, cz, parentFolder)

    def extractChunk(self, cx, cz, parentFolder):
        if not os.path.exists(parentFolder):
            os.mkdir(parentFolder)

        chunkFilename = self._oldChunkFilename(cx, cz)
        outputFile = os.path.join(parentFolder, os.path.basename(chunkFilename))

        chunk = self.getChunk(cx, cz)

        chunk.root_tag.save(outputFile)

    @property
    def chunkCount(self):
        """Returns the number of chunks in the level. May initiate a costly
        chunk scan."""
        if self._allChunks is None:
            self.preloadChunkPositions()
        return len(self._allChunks)

    @property
    def allChunks(self):
        """Iterates over (xPos, zPos) tuples, one for each chunk in the level.
        May initiate a costly chunk scan."""
        if self._allChunks is None:
            self.preloadChunkPositions()
        return self._allChunks.__iter__()

    def copyChunkFrom(self, world, cx, cz):
        """
        Copy a chunk from world into the same chunk position in self.
        """
#        assert isinstance(world, MCInfdevOldLevel)
        if self.readonly:
            raise IOError("World is opened read only.")
        if world.saving | self.saving:
            raise ChunkAccessDenied
        self.checkSessionLock()

        if not isinstance(world, MCInfdevOldLevel):
            log.debug("Incompatible world. Using block copy.")
            # Incompatible world. Use block copy.
            destChunkBox = BoundingBox((cx << 4, self.minY, cz << 4), (16, self.Height, 16))
            self.removeEntitiesInBox(destChunkBox)
            self.copyBlocksFrom(world, destChunkBox, destChunkBox.origin, create=True)
            return

        destChunk = self._loadedChunks.get((cx, cz))
        sourceChunk = world._loadedChunks.get((cx, cz))

        if sourceChunk:
            if destChunk:
                log.debug("Both chunks loaded. Using block copy.")
                # Both chunks loaded. Use block copy.
                self.removeEntitiesInBox(destChunk.bounds)
                self.copyBlocksFrom(world, destChunk.bounds, destChunk.bounds.origin)
                return
            else:
                log.debug("Source chunk loaded. Saving into work folder.")

                # Only source chunk loaded. Discard destination chunk and save source chunk in its place.
                self._loadedChunkData.pop((cx, cz), None)
                self.unsavedWorkFolder.saveChunk(cx, cz, sourceChunk.chunkData.savedTagData())
                self._loadedEntityData.pop((cx, cz), None)
                self.unsavedEntityFolder.saveChunk(cx, cz, sourceChunk.entityData.savedTagData())
                return
        else:
            if destChunk:
                log.debug("Destination chunk loaded. Using block copy.")
                # Only destination chunk loaded. Use block copy.
                self.removeEntitiesInBox(destChunk.bounds)
                self.copyBlocksFrom(world, destChunk.bounds, destChunk.bounds.origin)
            else:
                log.debug("No chunk loaded. Using world folder.copyChunkFrom")
                # Neither chunk loaded. Copy via world folders.
                def copyChunk(loadedChunkDataProp, worldFolderProp, unsavedWorkFolderProp):
                    loadedChunkData = getattr(self, loadedChunkDataProp)
                    if loadedChunkData is None:
                        return
                    worldLoadedChunkData = getattr(world, loadedChunkDataProp)
                    if worldLoadedChunkData is None:
                        return

                    loadedChunkData.pop((cx, cz), None)

                    # If the source chunk is dirty, write it to the work folder.
                    chunkData = worldLoadedChunkData.pop((cx, cz), None)
                    worldUnsavedWorkFolder = getattr(world, unsavedWorkFolderProp)
                    if chunkData and chunkData.dirty:
                        data = chunkData.savedTagData()
                        worldUnsavedWorkFolder.saveChunk(cx, cz, data)

                    if worldUnsavedWorkFolder.containsChunk(cx, cz):
                        sourceFolder = worldUnsavedWorkFolder
                    else:
                        sourceFolder = getattr(world, worldFolderProp)

                    getattr(self, unsavedWorkFolderProp).copyChunkFrom(sourceFolder, cx, cz)

                copyChunk("_loadedChunkData", "worldFolder", "unsavedWorkFolder")
                copyChunk("_loadedEntityData", "worldEntityFolder", "unsavedEntityFolder")

    def _getChunkBytes(self, cx, cz, worldFolder=None, unsavedWorkFolder=None):
        if worldFolder is None:
            worldFolder = self.worldFolder
        if unsavedWorkFolder is None:
            unsavedWorkFolder = self.unsavedWorkFolder

        if not self.readonly and unsavedWorkFolder.containsChunk(cx, cz):
            return unsavedWorkFolder.readChunk(cx, cz)
        else:
            return worldFolder.readChunk(cx, cz)

    def _getChunkData(self, cx, cz, loadedChunkData=None, worldFolder=None, unsavedWorkFolder=None, dataClass=AnvilChunkData):
        if loadedChunkData is None:
            loadedChunkData = self._loadedChunkData
        if worldFolder is None:
            worldFolder = self.worldFolder
        if unsavedWorkFolder is None:
            unsavedWorkFolder = self.unsavedWorkFolder

        chunkData = loadedChunkData.get((cx, cz))
        if chunkData is not None:
            return chunkData

        if self.saving:
            raise ChunkAccessDenied

        try:
            data = self._getChunkBytes(cx, cz,
                worldFolder=worldFolder,
                unsavedWorkFolder=unsavedWorkFolder)
            root_tag = nbt.load(buf=data)
            chunkData = dataClass(self, (cx, cz), root_tag)
        except (MemoryError, ChunkNotPresent):
            raise
        except Exception as e:
            traceback.print_exc()
            raise ChunkMalformed("Chunk {0} had an error: {1!r}".format((cx, cz), e), sys.exc_info()[2])

        if not self.readonly and unsavedWorkFolder.containsChunk(cx, cz):
            chunkData.dirty = True

        self._storeLoadedChunkData(chunkData,
            loadedChunkData=loadedChunkData,
            unsavedWorkFolder=unsavedWorkFolder)

        return chunkData

    def _storeLoadedChunkData(self, chunkData, loadedChunkData=None, unsavedWorkFolder=None):
        if loadedChunkData is None:
            loadedChunkData = self._loadedChunkData
        if unsavedWorkFolder is None:
            unsavedWorkFolder = self.unsavedWorkFolder

        if len(loadedChunkData) > self.loadedChunkLimit:
            # Try to find a chunk to unload. The chunk must not be in _loadedChunks, which contains only chunks that
            # are in use by another object. If the chunk is dirty, save it to the temporary folder.
            if not self.readonly:
                self.checkSessionLock()
            for (ocx, ocz), oldChunkData in loadedChunkData.iteritems():
                if (ocx, ocz) in self._loadedChunks:
                    continue
                if oldChunkData.dirty and not self.readonly:
                    data = oldChunkData.savedTagData()
                    unsavedWorkFolder.saveChunk(ocx, ocz, data)

                del loadedChunkData[ocx, ocz]
                break

        loadedChunkData[chunkData.chunkPosition] = chunkData

    def getChunk(self, cx, cz):
        '''
        Read the chunk from disk, load it, and then return it

        :param cx: The X coordinate of the Chunk
        :type cx: int
        :param cz: The Z coordinate of the Chunk
        :type cz: int
        :rtype: pymclevel.infiniteworld.AnvilChunk
        '''

        chunk = self._loadedChunks.get((cx, cz))
        if chunk is not None:
            return chunk

        chunkData = self._getChunkData(cx, cz)
        if self._loadedEntityData is not None:
            try:
                entityData = self._getChunkData(cx, cz,
                    loadedChunkData=self._loadedEntityData,
                    worldFolder=self.worldEntityFolder,
                    unsavedWorkFolder=self.unsavedEntityFolder,
                    dataClass=AnvilEntityData)
            except ChunkNotPresent:
                entityData = AnvilEntityData(self, (cx, cz), create=True)
                self._storeLoadedChunkData(entityData,
                    loadedChunkData=self._loadedEntityData,
                    unsavedWorkFolder=self.unsavedEntityFolder)
        else:
            entityData = None
        chunk = AnvilChunk(chunkData, entityData=entityData)

        self._loadedChunks[cx, cz] = chunk
        self.recentChunks.append(chunk)
        return chunk

    def markDirtyChunk(self, cx, cz):
        self.getChunk(cx, cz).chunkChanged()

    def markDirtyBox(self, box):
        for cx, cz in box.chunkPositions:
            self.markDirtyChunk(cx, cz)

    def listDirtyChunks(self):
        for cPos, chunkData in self._loadedChunkData.iteritems():
            if chunkData.dirty:
                yield cPos

    # --- HeightMaps ---

    def heightMapAt(self, x, z):
        zc = z >> 4
        xc = x >> 4
        xInChunk = x & 0xf
        zInChunk = z & 0xf

        ch = self.getChunk(xc, zc)

        heightMap = ch.HeightMap

        return heightMap[zInChunk, xInChunk]  # HeightMap indices are backwards

    # --- Biome manipulation ---
    def biomeAt(self, x, z, y=0):
        '''
        Gets the biome of the block at the specified coordinates

        :param x: The X block coordinate
        :type x: int
        :param z: The Z block coordinate
        :type z: int
        :rtype: int
        '''
        if y < self.minY or y >= self.maxY:
            return -1

        zc = z >> 4
        xc = x >> 4

        ch = self.getChunk(xc, zc)
        biomes = ch.Biomes
        biomesScale = ch.biomesScale

        xInChunk = (x & 0xf) // biomesScale
        zInChunk = (z & 0xf) // biomesScale

        if len(biomes.shape) >= 3:
            yInChunk = (y - self.minY) // biomesScale
            return biomes[xInChunk, zInChunk, yInChunk]
        return biomes[xInChunk, zInChunk]

    def setBiomeAt(self, x, z, biomeID, y=0):
        '''
        Sets the biome data for the Y column at the specified X and Z coordinates

        :param x: The X block coordinate
        :type x: int
        :param z: The Z block coordinate
        :type z: int
        :param biomeID: The wanted biome ID
        :type biomeID: int
        '''
        if y < self.minY or y >= self.maxY:
            return

        zc = z >> 4
        xc = x >> 4

        ch = self.getChunk(xc, zc)
        biomes = ch.Biomes
        biomesScale = ch.biomesScale

        xInChunk = (x & 0xf) // biomesScale
        zInChunk = (z & 0xf) // biomesScale

        if len(biomes.shape) >= 3:
            yInChunk = (y - self.minY) // biomesScale
            biomes[xInChunk, zInChunk, yInChunk] = biomeID
        else:
            biomes[xInChunk, zInChunk] = biomeID
        ch.dirty = True

    # --- Entities and TileEntities ---

    def addEntity(self, entityTag):
        '''
        Adds an Entity to the level and sets its position to the values of the 'Pos' tag

        :param entityTag: The NBT data of the Entity
        :type entityTag: pymclevel.nbt.TAG_Compound
        '''
        assert isinstance(entityTag, nbt.TAG_Compound)
        x, y, z = map(lambda x: int(floor(x)), Entity.pos(entityTag))

        try:
            chunk = self.getChunk(x >> 4, z >> 4)
        except (ChunkNotPresent, ChunkMalformed):
            return None
            # raise Error, can't find a chunk?
        chunk.addEntity(entityTag)
        chunk.dirty = True

    def tileEntityAt(self, x, y, z):
        '''
        Gets the TileEntity at the specified X, Y, and Z block coordinates

        :param x: The X block coordinate
        :type x: int
        :param y: The Y block coordinate
        :type y: int
        :param z: The Z block coordinate
        :type z: int
        :rtype: pymclevel.nbt.TAG_Compound
        '''
        chunk = self.getChunk(x >> 4, z >> 4)
        return chunk.tileEntityAt(x, y, z)

    def addTileEntity(self, tileEntityTag):
        '''
        Adds an TileEntity to the level and sets its position to the values of the X, Y, and Z tags

        :param tileEntityTag: The NBT data of the TileEntity
        :type tileEntityTag: pymclevel.nbt.TAG_Compound
        '''
        assert isinstance(tileEntityTag, nbt.TAG_Compound)
        if 'x' not in tileEntityTag:
            return
        x, y, z = TileEntity.pos(tileEntityTag)

        try:
            chunk = self.getChunk(x >> 4, z >> 4)
        except (ChunkNotPresent, ChunkMalformed):
            return
            # raise Error, can't find a chunk?
        chunk.addTileEntity(tileEntityTag)
        chunk.dirty = True

    def addTileTick(self, tickTag):
        '''
        Adds an TileTick to the level and sets its position to the values of the X, Y, and Z tags

        :param tickTag: The NBT data of the TileTick
        :type tickTag: pymclevel.nbt.TAG_Compound
        '''
        assert isinstance(tickTag, nbt.TAG_Compound)

        if 'x' not in tickTag:
            return
        x, y, z = TileTick.pos(tickTag)
        try:
            chunk = self.getChunk(x >> 4,z >> 4)
        except(ChunkNotPresent, ChunkMalformed):
            return
        chunk.addTileTick(tickTag)
        chunk.dirty = True

    def getEntitiesInBox(self, box):
        '''
        Get all of the Entities in the specified box

        :param box: The box to search for Entities in
        :type box: pymclevel.box.BoundingBox
        :return: A list of all the Entity tags in the box
        :rtype: list
        '''
        entities = []
        for chunk, slices, point in self.getChunkSlices(box):
            entities += chunk.getEntitiesInBox(box)

        return entities

    def getTileEntitiesInBox(self, box):
        '''
        Get all of the TileEntities in the specified box

        :param box: The box to search for TileEntities in
        :type box: pymclevel.box.BoundingBox
        :return: A list of all the TileEntity tags in the box
        :rtype: list
        '''
        tileEntites = []
        for chunk, slices, point in self.getChunkSlices(box):
            tileEntites += chunk.getTileEntitiesInBox(box)

        return tileEntites

    def getTileTicksInBox(self, box):
        '''
        Get all of the TileTicks in the specified box

        :param box: The box to search for TileTicks in
        :type box: pymclevel.box.BoundingBox
        :return: A list of all the TileTick tags in the box
        :rtype: list
        '''
        tileticks = []
        for chunk, slices, point in self.getChunkSlices(box):
            tileticks += chunk.getTileTicksInBox(box)

        return tileticks

    def removeEntitiesInBox(self, box):
        '''
        Removes all of the Entities in the specified box

        :param box: The box to remove all Entities from
        :type box: pymclevel.box.BoundingBox
        :return: The number of Entities removed
        :rtype: int
        '''
        count = 0
        for chunk, slices, point in self.getChunkSlices(box):
            count += chunk.removeEntitiesInBox(box)

        log.info("Removed {0} entities".format(count))
        return count

    def removeTileEntitiesInBox(self, box):
        '''
        Removes all of the TileEntities in the specified box

        :param box: The box to remove all TileEntities from
        :type box: pymclevel.box.BoundingBox
        :return: The number of TileEntities removed
        :rtype: int
        '''
        count = 0
        for chunk, slices, point in self.getChunkSlices(box):
            count += chunk.removeTileEntitiesInBox(box)

        log.info("Removed {0} tile entities".format(count))
        return count

    def removeTileTicksInBox(self, box):
        '''
        Removes all of the TileTicks in the specified box

        :param box: The box to remove all TileTicks from
        :type box: pymclevel.box.BoundingBox
        :return: The number of TileTicks removed
        :rtype: int
        '''
        count = 0
        for chunk, slices, point in self.getChunkSlices(box):
            count += chunk.removeTileTicksInBox(box)

        log.info("Removed {0} tile ticks".format(count))
        return count

    # --- Chunk manipulation ---

    def containsChunk(self, cx, cz):
        '''
        Checks if the specified chunk exists/has been generated

        :param cx: The X coordinate of the chunk
        :type cx: int
        :param cz: The Z coordinate of the chunk
        :type cz: int
        :return: True if the chunk exists/has been generated, False otherwise
        :rtype: bool
        '''
        if self._allChunks is not None:
            return (cx, cz) in self._allChunks
        if (cx, cz) in self._loadedChunkData:
            return True

        return self.worldFolder.containsChunk(cx, cz)

    def containsPoint(self, x, y, z):
        '''
        Checks if the specified X, Y, Z coordinate has been generated

        :param x: The X coordinate
        :type x: int
        :param y: The Y coordinate
        :type y: int
        :param z: The Z coordinate
        :type z: int
        :return: True if the point exists/has been generated, False otherwise
        :rtype: bool
        '''
        # pcm1k TODO - should this be y >= self.maxY instead?
        if y < self.minY or y > self.maxY:
            return False
        return self.containsChunk(x >> 4, z >> 4)

    def createChunk(self, cx, cz):
        '''
        Creates a chunk at the specified chunk coordinates if it doesn't exist already

        :param cx: The X coordinate of the chunk
        :type cx: int
        :param cz: The Z coordinate of the chunk
        :type cz: int
        :raises ValueError: Raise when a chunk is already present/generated at the specified X and Z coordinates
        '''
        if self.containsChunk(cx, cz):
            raise ValueError("{0}:Chunk {1} already present!".format(self, (cx, cz)))
        if self._allChunks is not None:
            self._allChunks.add((cx, cz))

        self._storeLoadedChunkData(AnvilChunkData(self, (cx, cz), create=True))
        if self._loadedEntityData is not None:
            self._storeLoadedChunkData(AnvilEntityData(self, (cx, cz), create=True),
                loadedChunkData=self._loadedEntityData,
                unsavedWorkFolder=self.unsavedEntityFolder)
        self._bounds = None

    def createChunks(self, chunks):
        '''
        Creates multiple chunks specified by a list of chunk X and Z coordinate tuples

        :param chunks: A list of chunk X and Z coordinates in tuple form [(cx, cz), (cx, cz)...]
        :type chunks: list
        :return: A list of the chunk coordinates that were created, doesn't include coordinates of ones already present
        :rtype: list
        '''
        i = 0
        ret = []
        append = ret.append
        for cx, cz in chunks:
            i += 1
            if not self.containsChunk(cx, cz):
                append((cx, cz))
                self.createChunk(cx, cz)
            assert self.containsChunk(cx, cz), "Just created {0} but it didn't take".format((cx, cz))
            if i % 100 == 0:
                log.info(u"Chunk {0}...".format(i))

        log.info("Created {0} chunks.".format(len(ret)))

        return ret

    def createChunksInBox(self, box):
        '''
        Creates all chunks that would be present in the box

        :param box: The box to generate chunks in
        :type box: pymclevel.box.BoundingBox
        :return: A list of the chunk coordinates that were created, doesn't include coordinates of ones already present
        :rtype: list
        '''
        log.info(u"Creating {0} chunks in {1}".format((box.maxcx - box.mincx) * (box.maxcz - box.mincz),
                                                      ((box.mincx, box.mincz), (box.maxcx, box.maxcz))))
        return self.createChunks(box.chunkPositions)

    def deleteChunk(self, cx, cz):
        '''
        Deletes the chunk at the specified chunk coordinates

        :param cx: The X coordinate of the chunk
        :type cx: int
        :param cz: The Z coordinate of the chunk
        :type cz: int
        '''
        self.worldFolder.deleteChunk(cx, cz)
        if self._loadedEntityData is not None:
            self.worldEntityFolder.deleteChunk(cx, cz)
        if self._allChunks is not None:
            self._allChunks.discard((cx, cz))

        self._bounds = None

    def deleteChunksInBox(self, box):
        '''
        Deletes all of the chunks in the specified box

        :param box: The box of chunks to remove
        :type box: pymclevel.box.BoundingBox
        :return: A list of the chunk coordinates  of the chunks that were deleted
        :rtype: list
        '''
        log.info(u"Deleting {0} chunks in {1}".format((box.maxcx - box.mincx) * (box.maxcz - box.mincz),
                                                      ((box.mincx, box.mincz), (box.maxcx, box.maxcz))))
        i = 0
        ret = []
        append = ret.append
        for cx, cz in itertools.product(xrange(box.mincx, box.maxcx), xrange(box.mincz, box.maxcz)):
            i += 1
            if self.containsChunk(cx, cz):
                self.deleteChunk(cx, cz)
                append((cx, cz))

            assert not self.containsChunk(cx, cz), "Just deleted {0} but it didn't take".format((cx, cz))

            if i % 100 == 0:
                log.info(u"Chunk {0}...".format(i))

        return ret

    # --- Player and spawn manipulation ---

    def playerSpawnPosition(self, player=None):
        """
        xxx if player is None then it gets the default spawn position for the world
        if player hasn't used a bed then it gets the default spawn position
        """
        dataTag = self.root_tag["Data"]
        if player is None:
            playerSpawnTag = dataTag
        else:
            playerSpawnTag = self.getPlayerTag(player)

        return [playerSpawnTag.get(i, dataTag[i]).value for i in ("SpawnX", "SpawnY", "SpawnZ")]

    def setPlayerSpawnPosition(self, pos, player=None):
        """ xxx if player is None then it sets the default spawn position for the world """
        if player is None:
            playerSpawnTag = self.root_tag["Data"]
        else:
            playerSpawnTag = self.getPlayerTag(player)
        for name, val in zip(("SpawnX", "SpawnY", "SpawnZ"), pos):
            playerSpawnTag[name] = nbt.TAG_Int(val)

    def getPlayerPath(self, player, dim=0):
        '''
        Gets the file path to the player file

        :param player: The UUID of the player
        :type player: str
        :param dim: The dimension that the player resides in
        :type dim: int
        :return: The file path to the player data file
        :rtype: str
        '''
        assert player != "Player"
        if dim != 0:
            return os.path.join(os.path.dirname(self.level.filename), "DIM%s" % dim, "playerdata", "%s.dat" % player)
        else:
            return os.path.join(self.playersFolder, "%s.dat" % player)

    def getPlayerTag(self, player="Player"):
        '''
        Gets the NBT data for the specified player

        :param player: The UUID of the player
        :type player: str
        :return: The NBT data for the player
        :rtype: pymclevel.nbt.TAG_Compound
        '''
        if player == "Player":
            if player in self.root_tag["Data"]:
                # single-player world
                return self.root_tag["Data"]["Player"]
            raise PlayerNotFound(player)
        else:
            playerFilePath = self.getPlayerPath(player)
            playerTag = self.playerTagCache.get(playerFilePath)
            if playerTag is None:
                if os.path.exists(playerFilePath):
                    playerTag = nbt.load(playerFilePath)
                    self.playerTagCache[playerFilePath] = playerTag
                else:
                    raise PlayerNotFound(player)
            return playerTag

    def getPlayerDimension(self, player="Player"):
        '''
        Gets the dimension that the specified player is currently in

        :param player: The UUID of the player
        :type player: str
        :return: The dimension the player is currently in
        :rtype: int
        '''
        playerTag = self.getPlayerTag(player)
        if "Dimension" not in playerTag:
            return 0
        # pcm1k TODO - "Dimension" is a string in newer versions
        return playerTag["Dimension"].value

    def setPlayerDimension(self, d, player="Player"):
        '''
        Sets the player's current dimension

        :param d: The desired dimension (0 for Overworld, -1 for Nether, 1 for The End)
        :type d: int
        :param player: The UUID of the player
        :type player: str
        '''
        playerTag = self.getPlayerTag(player)
        if "Dimension" not in playerTag:
            playerTag["Dimension"] = nbt.TAG_Int(0)
        playerTag["Dimension"].value = d

    def setPlayerPosition(self, (x, y, z), player="Player"):
        '''
        Sets the specified player's position

        :param x: The desired X coordinate
        :type x: float
        :param y: The desired Y coordinate
        :type y: float
        :param z: The desired Z coordinate
        :type z: float
        :param player: The UUID of the player
        :type player: str
        '''
        posList = nbt.TAG_List([nbt.TAG_Double(p) for p in (x, y - 1.75, z)])
        playerTag = self.getPlayerTag(player)

        playerTag["Pos"] = posList

    def getPlayerPosition(self, player="Player"):
        '''
        Gets the position for the specified player

        :param player: The UUID of the player
        :type player: str
        :return: The X, Y, Z coordinates of the player
        :rtype: tuple
        '''
        playerTag = self.getPlayerTag(player)
        posList = playerTag["Pos"]

        x, y, z = map(lambda x: x.value, posList)
        return x, y + 1.75, z

    def setPlayerOrientation(self, yp, player="Player"):
        '''
        Sets the specified player's orientation

        :param yp: The desired Yaw and Pitch
        :type yp: tuple or list
        :param player: The UUID of the player
        :type player: str
        '''
        self.getPlayerTag(player)["Rotation"] = nbt.TAG_List([nbt.TAG_Float(p) for p in yp])

    def getPlayerOrientation(self, player="Player"):
        '''
        Gets the orientation of the specified player

        :param player: The UUID of the player
        :type player: str
        :return: The orientation of the player in the format: (yaw, pitch)
        :rtype: numpy.array
        '''
        yp = map(lambda x: x.value, self.getPlayerTag(player)["Rotation"])
        y, p = yp
        if p == 0:
            p = 0.000000001
        if p == 180.0:
            p -= 0.000000001
        yp = y, p
        return array(yp)

    def setPlayerAbilities(self, gametype, player="Player"):
        playerTag = self.getPlayerTag(player)

        # Check for the Abilities tag.  It will be missing in worlds from before
        # Beta 1.9 Prerelease 5.
        if 'abilities' not in playerTag:
            playerTag['abilities'] = nbt.TAG_Compound()

        # Assumes creative (1) is the only mode with these abilities set,
        # which is true for now.  Future game modes may not hold this to be
        # true, however.
        if gametype == 1:
            playerTag['abilities']['instabuild'] = nbt.TAG_Byte(1)
            playerTag['abilities']['mayfly'] = nbt.TAG_Byte(1)
            playerTag['abilities']['invulnerable'] = nbt.TAG_Byte(1)
        else:
            playerTag['abilities']['flying'] = nbt.TAG_Byte(0)
            playerTag['abilities']['instabuild'] = nbt.TAG_Byte(0)
            playerTag['abilities']['mayfly'] = nbt.TAG_Byte(0)
            playerTag['abilities']['invulnerable'] = nbt.TAG_Byte(0)

    def setPlayerGameType(self, gametype, player="Player"):
        '''
        Sets the specified player's gametype/gamemode

        :param gametype: The desired Gametype/Gamemode number
        :type gametype: int
        :param player: The UUID of the player
        :type player: str
        '''
        playerTag = self.getPlayerTag(player)
        # This annoyingly works differently between single- and multi-player.
        if player == "Player":
            self.GameType = gametype
            self.setPlayerAbilities(gametype, player)
        else:
            playerTag['playerGameType'] = nbt.TAG_Int(gametype)
            self.setPlayerAbilities(gametype, player)

    def getPlayerGameType(self, player="Player"):
        '''
        Gets the Gamemode of the specified player

        :param player: The UUID of the player
        :type player: str
        :return: The Gamemode number
        :rtype: int
        '''
        if player == "Player":
            return self.GameType
        else:
            playerTag = self.getPlayerTag(player)
            return playerTag["playerGameType"].value

    def createPlayer(self, playerName):
        '''
        ~Deprecated~
        Creates a player with default values

        :param playerName: The name of the player
        :type playerName: str
        '''
        if playerName == "Player":
            playerTag = self.root_tag["Data"].setdefault(playerName, nbt.TAG_Compound())
        else:
            playerTag = nbt.TAG_Compound()

        playerTag['Air'] = nbt.TAG_Short(300)
        playerTag['AttackTime'] = nbt.TAG_Short(0)
        playerTag['DeathTime'] = nbt.TAG_Short(0)
        playerTag['Fire'] = nbt.TAG_Short(-20)
        playerTag['Health'] = nbt.TAG_Short(20)
        playerTag['HurtTime'] = nbt.TAG_Short(0)
        playerTag['Score'] = nbt.TAG_Int(0)
        playerTag['FallDistance'] = nbt.TAG_Float(0)
        playerTag['OnGround'] = nbt.TAG_Byte(0)

        playerTag["Inventory"] = nbt.TAG_List()

        playerTag['Motion'] = nbt.TAG_List([nbt.TAG_Double(0) for i in xrange(3)])
        playerTag['Pos'] = nbt.TAG_List([nbt.TAG_Double([0.5, 2.8, 0.5][i]) for i in xrange(3)])
        playerTag['Rotation'] = nbt.TAG_List([nbt.TAG_Float(0), nbt.TAG_Float(0)])

        if playerName != "Player":
            self.playerTagCache[self.getPlayerPath(playerName)] = playerTag


class MCAlphaDimension(MCInfdevOldLevel):
    def __init__(self, parentWorld, dimNo, create=False):
        filename = parentWorld.worldFolder.getFolderPath("DIM" + str(int(dimNo)))

        self.parentWorld = parentWorld
        self.dimNo = dimNo
        MCInfdevOldLevel.__init__(self, filename, create)
        self.filename = parentWorld.filename
        self.players = self.parentWorld.players
        self.playersFolder = self.parentWorld.playersFolder
        self.playerTagCache = self.parentWorld.playerTagCache

    @property
    def root_tag(self):
        return self.parentWorld.root_tag

    def __str__(self):
        return u"MCAlphaDimension({0}, {1})".format(self.parentWorld, self.dimNo)

    def loadLevelDat(self, create=False, random_seed=None, last_played=None, dataVersion=None):
        pass

    def preloadDimensions(self):
        pass

    def _create(self, *args, **kw):
        pass

    def acquireSessionLock(self):
        pass

    def checkSessionLock(self):
        self.parentWorld.checkSessionLock()

    dimensionNames = {-1: "Nether", 1: "The End"}

    @property
    def displayName(self):
        return u"{0} ({1})".format(self.parentWorld.displayName,
                                   self.dimensionNames.get(self.dimNo, "Dimension %d" % self.dimNo))

    def saveInPlace(self, saveSelf=False):
        """saving the dimension will save the parent world, which will save any
         other dimensions that need saving.  the intent is that all of them can
         stay loaded at once for fast switching """

        if saveSelf:
            MCInfdevOldLevel.saveInPlace(self)
        else:
            self.parentWorld.saveInPlace()
